"""Bounded, revision-pinned search over complete IFC arrangements.

Search owns a private snapshot. Only accept() can publish, using canonical server-held
operations and a fresh check under the Workspace lock. Model output never grants acceptance.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import threading
import time
import uuid

import ifcopenshell.util.system as system
import numpy as np

from . import context_eval, domains, edits, verify
from .limits import env_float, env_int

MAX_STORED_SCENES = 16
MAX_STORED_PROPOSALS = 24


@dataclass(frozen=True)
class Limits:
    model_calls: int = 6
    trials: int = 12
    seconds: float = 120
    alternatives: int = 3
    radius_m: float = 2.5

    @classmethod
    def from_env(cls):
        return cls(model_calls=env_int('SIGHTLINE_CONTEXT_MODEL_CALLS', 6),
                   trials=env_int('SIGHTLINE_CONTEXT_TRIALS', 12),
                   seconds=env_float('SIGHTLINE_CONTEXT_SECONDS', 120),
                   alternatives=env_int('SIGHTLINE_CONTEXT_ALTERNATIVES', 3),
                   radius_m=env_float('SIGHTLINE_CONTEXT_RADIUS_M', 2.5))

    def __post_init__(self):
        for value, maximum in ((self.model_calls, 6), (self.trials, 12), (self.seconds, 120),
                               (self.alternatives, 3), (self.radius_m, 2.5)):
            if not np.isfinite(value) or not 0 < value <= maximum:
                raise ValueError(f'context limit must be positive and at most {maximum}')


def _tool(name, description, properties, required):
    return dict(type='function', function=dict(name=name, description=description, parameters=dict(
        type='object', properties=properties, required=required, additionalProperties=False)))


TOOLS = [
    _tool('inspect_element', 'Inspect a discovered element, its complete translation run, connections and measured openings.',
          {'element': {'type': 'string'}}, ['element']),
    _tool('inspect_neighbourhood', 'Inspect around a discovered element. For either objective seed, continue the original '
          'clash-centred query using next_offset. Omitted radius uses the configured initial radius. '
          'A larger radius is an explicit wider search (maximum 10 metres).',
          {'element': {'type': 'string'}, 'radius_m': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 10},
           'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}, ['element']),
    _tool('evaluate_proposal', 'Evaluate ONE complete arrangement, one to three independent edit groups. '
          'Move expands the full connected run. Supply SI world delta_m; offset split_m is distance ALONG the run.',
          {'title': {'type': 'string'}, 'operations': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': {
              'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['move', 'offset', 'trim']},
              'element': {'type': 'string'}, 'reason': {'type': 'string'},
              'delta_m': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
              'split_m': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 2, 'maxItems': 2},
              'end': {'type': 'string', 'enum': ['start', 'end']}, 'by_m': {'type': 'number'}},
              'required': ['kind', 'element', 'reason'], 'additionalProperties': False}}}, ['title', 'operations']),
]


class ContextError(ValueError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


# A wider fix copies the open models two or three times (snapshots); past this size it is not offered (docs/uploads.md).
WIDER_MAX_MB = env_int('SIGHTLINE_WIDER_FIX_MAX_MB', 100)


def validate_objective(ws, scene_id, objective):
    """Reject fabricated physical IDs, optional report attribution and models too big to copy, before charging."""
    if not isinstance(objective, dict):
        raise ContextError(422, 'Objective must identify two physical elements.')
    size = getattr(ws, 'sizes', {}).get(scene_id, 0)
    if WIDER_MAX_MB and size > WIDER_MAX_MB << 20:
        raise ContextError(413, f'These models are {size / 1e6:.0f} MB: a wider fix copies them several times, so it is '
                                f'offered up to {WIDER_MAX_MB} MB. Propose fixes works at any size.')
    obj = {k: objective[k] for k in ('element_a', 'element_b', 'report_id', 'clash_id') if objective.get(k) is not None}
    with ws.lock:
        scene = ws.scene(scene_id)
        physical = scene.bounds()
        a, b = obj.get('element_a'), obj.get('element_b')
        if not a or not b or a == b or a not in physical or b not in physical:
            raise ContextError(422, 'Objective must identify two distinct physical elements in this scene.')
        rid, cid = obj.get('report_id'), obj.get('clash_id')
        if bool(rid) != bool(cid):
            raise ContextError(422, 'Report attribution requires both report_id and clash_id.')
        if rid:
            if rid not in ws.reports:
                raise ContextError(404, 'Clash report is no longer loaded.')
            matched = ws.match(rid, scene_id).get(cid)
            if not matched or {matched.get('a'), matched.get('b')} != {a, b}:
                raise ContextError(422, 'Report clash does not identify this objective pair.')
    # The clearance the pair needs, from the requirements as they are now (Workspace.clearance): checked with that.
    clearance = getattr(ws, 'clearance', None)
    if clearance is not None:
        obj['clearance_m'] = clearance(scene_id, a, b)
    return obj


class Inspection:
    def __init__(self, scene, objective, radius):
        self.scene, self.objective = scene, objective
        self.radius = radius
        self.discovered = {objective['element_a'], objective['element_b']}
        boxes = [scene.bounds()[g] for g in self.discovered]
        # The clash zone, rather than the whole extent of a long beam or service run.
        lo, hi = np.maximum(boxes[0][0], boxes[1][0]), np.minimum(boxes[0][1], boxes[1][1])
        self.origin = (lo + hi) / 2
        self.initial_ids = self._near(self.origin, radius)
        self.discovered.update(self.initial_ids)

    def _near(self, point, radius):
        return sorted(g for g, box in self.scene.bounds().items()
                      if np.all(box[0] <= point + radius) and np.all(box[1] >= point - radius))

    def element(self, element):
        gid = element
        if gid not in self.discovered:
            raise ValueError(f'element was not discovered: {gid}')
        scene = self.scene
        info = asdict(scene.element(gid))
        run_members = scene.connected_run(gid)
        constraints = context_eval.element_constraints(scene, gid)
        run_constraints = {g: c for g in run_members if (c := context_eval.element_constraints(scene, g))}
        self.discovered.update(run_members)
        self.discovered.update(info['connected'])
        connections = []
        for p in system.get_ports(scene.entity(gid)):
            other = system.get_connected_port(p)
            owner = system.get_port_element(other) if other is not None else None
            item = dict(port=p.GlobalId, other=owner.GlobalId if owner is not None else None,
                        flow=getattr(p, 'FlowDirection', None), predefined_type=getattr(p, 'PredefinedType', None),
                        system_type=getattr(p, 'SystemType', None))
            frame = scene.placement(p.GlobalId) if p.ObjectPlacement else None
            item['position_m'] = frame[:3, 3].tolist() if frame is not None else None
            item['frame_m'] = frame.tolist() if frame is not None else None
            connections.append(item)
        capabilities = ['move']
        run, unsupported = None, []
        try:
            run = asdict(edits.run_of(scene, gid))
            context_eval.check_offset_profile(scene, gid)
            if edits.fitting_class(scene.entity(gid)) is not None and abs(run['direction'][2]) < 1e-6:
                capabilities.append('offset')
        except (edits.Unsupported, RuntimeError, ValueError) as exc:
            unsupported.append(str(exc))
        try:
            _, start, direction, length = edits.member_axis(scene, scene.entity(gid))
            verts = np.array(edits.meshes(scene, [gid])[0]['verts']).reshape(-1, 3)
            if length >= edits.SLENDER * edits._across(verts - start, direction):
                capabilities.append('trim')
        except (edits.Unsupported, RuntimeError, ValueError) as exc:
            unsupported.append(str(exc))
        if constraints:
            capabilities = []
            unsupported.append('KeepFixed model property prohibits editing this element.')
        elif run_constraints:
            capabilities.remove('move')
            unsupported.append(f'Translation run includes KeepFixed elements: {sorted(run_constraints)}')
        openings = []
        for other in (self.objective['element_a'], self.objective['element_b']):
            if other == gid or 'offset' not in capabilities:
                continue
            try:
                openings.append(dict(obstacle=other, passages=edits.passages(
                    scene, gid, other, context_eval.clearance_of(self.objective))))
            except (edits.Unsupported, RuntimeError, ValueError) as exc:
                openings.append(dict(obstacle=other, unavailable=str(exc)))
        return dict(**info, bounds_m=scene.bounds().get(gid).tolist() if gid in scene.bounds() else None,
                    run=run, run_members=run_members, systems=[dict(global_id=s.GlobalId, name=s.Name)
                    for s in system.get_element_systems(scene.entity(gid))], connections=connections,
                    capabilities=capabilities, unsupported=unsupported, openings=openings,
                    constraints=constraints, run_constraints=run_constraints)

    def page(self, ids, offset=0, limit=20):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('offset must be nonnegative and limit must be 1 to 20')
        self.discovered.update(ids)
        return dict(total=len(ids), elements=[self.element(g) for g in ids[offset:offset + limit]],
                    next_offset=offset + limit if offset + limit < len(ids) else None)

    def neighbourhood(self, element, radius_m=None, offset=0, limit=20):
        if element not in self.discovered:
            raise ValueError(f'element was not discovered: {element}')
        radius_m = self.radius if radius_m is None else radius_m
        if isinstance(radius_m, bool) or not isinstance(radius_m, (int, float)) or not np.isfinite(radius_m) or not 0 < radius_m <= 10:
            raise ValueError('radius_m must be positive and at most 10 metres')
        box = self.scene.bounds().get(element)
        if box is None:
            raise ValueError('element has no measurable bounds')
        point = self.origin if element in (self.objective['element_a'], self.objective['element_b']) else box.mean(axis=0)
        return self.page(self._near(point, radius_m), offset, limit) | dict(center_m=point.tolist(), radius_m=radius_m)


def _identity(evaluated_edits):
    """Compare arrangements, including equivalent seeds in the same translated run."""
    keys = []
    for edit in evaluated_edits:
        kind = edit['kind']
        key = dict(kind=kind, members=sorted(edit['moved']) if kind == 'move' else [edit['element']])
        if kind in ('move', 'offset'):
            key['delta_m'] = [float(v) + 0.0 for v in edit['delta_m']]
        if kind == 'offset':
            key['split_m'] = [float(v) + 0.0 for v in edit['split_m']]
        if kind == 'trim':
            key.update(end=edit['end'], by_m=float(edit['by_m']))
        keys.append(json.dumps(key, sort_keys=True))
    return tuple(sorted(keys))


def _rank(scene, proposal):
    changes = proposal['edits']
    structural = any(scene.stays(g) for e in changes for g in e['moved'])
    # The supported radiused detour has four bend fittings, with optional straight risers.
    fittings = sum(4 for e in changes if e['kind'] == 'offset')
    displacement = sum(float(np.linalg.norm(e.get('delta_m', [e.get('by_m', 0)]))) for e in changes)
    gap = proposal['checks']['geometry']['min_clearance_m']
    return structural, len(proposal['review_conditions']), len(changes), fittings, displacement, -(gap if gap is not None else -1)


def _store(ws, sid, candidates, cancel=None):
    with ws.lock:
        if cancel is not None and cancel.is_set():
            return False
        if not hasattr(ws, '_context_proposals'):
            ws._context_proposals = OrderedDict()
        stores = ws._context_proposals
        for old in list(stores):
            if old not in ws.scenes:
                del stores[old]
        store = stores.setdefault(sid, OrderedDict())
        stores.move_to_end(sid)
        for proposal, operations, discovered in candidates:
            store[proposal['id']] = deepcopy(dict(proposal=proposal, operations=operations, discovered=discovered))
        while len(store) > MAX_STORED_PROPOSALS:
            store.popitem(last=False)
        while len(stores) > MAX_STORED_SCENES:
            stores.popitem(last=False)
        return True


def build(ws, scene_id, objective, emit=lambda e: None, model=None, *, limits=None, cancel=None, clock=time.monotonic):
    limits = limits or Limits.from_env()
    cancel = cancel or threading.Event()
    start = clock()
    objective = validate_objective(ws, scene_id, objective)
    with ws.lock:
        scene = ws.scene(scene_id).snapshot()
    inspection = Inspection(scene, objective, limits.radius_m)
    progress = lambda phase, message: emit(dict(type='context_progress', phase=phase, message=message))
    progress('inspecting', 'Inspecting the objective and local geometry, connections and supported edits.')
    initial = dict(objective=objective, objective_elements=[inspection.element(objective[k]) for k in ('element_a', 'element_b')],
                   neighbourhood=inspection.neighbourhood(objective['element_a']), limits=asdict(limits))
    system = domains.prompt('context', domains.of(ws, scene_id))   # in the voice of the scene's domain
    messages = [dict(role='system', content=system), dict(role='user', content=json.dumps(initial))]
    candidates, seen, blockers = [], set(), set()
    trials = calls = 0
    stop = 'Search completed within its bounds.'
    active = lambda: not cancel.is_set() and clock() - start < limits.seconds
    model = model if model is not None else ws.model
    while active() and calls < limits.model_calls and trials < limits.trials:
        progress('thinking', 'Considering complete arrangements of at most three edit groups.')
        if not active():
            break
        calls += 1
        try:
            reply = model.chat(messages, TOOLS, timeout_s=max(.001, limits.seconds - (clock() - start)))
            if not isinstance(reply, dict):
                raise ValueError('model reply must be a message object')
            tool_calls = reply.get('tool_calls') or []
            if not isinstance(tool_calls, list) or any(not isinstance(call, dict)
                    or not isinstance(call.get('id'), str) or not isinstance(call.get('function'), dict)
                    or not isinstance(call['function'].get('name'), str) for call in tool_calls):
                raise ValueError('malformed model tool calls')
        except Exception as exc:
            stop = f'Model request ended ({type(exc).__name__}); retained earlier passing arrangements.'
            break
        if not active():
            break
        messages.append({k: v for k, v in reply.items() if k in ('content', 'tool_calls')} | dict(role='assistant'))
        if not tool_calls:
            break
        # Inspection calls have a bound too: a single model response cannot create unbounded work.
        for call in tool_calls[:48]:
            if not active():
                break
            fn = call.get('function') or {}
            name = fn.get('name')
            try:
                args = json.loads(fn.get('arguments') or '{}')
                if not isinstance(args, dict):
                    raise ValueError('tool arguments must be an object')
                if name == 'inspect_element':
                    progress('inspecting', f'Inspecting discovered element {args.get("element", "")}.')
                    if not active():
                        break
                    result = inspection.element(**args)
                elif name == 'inspect_neighbourhood':
                    progress('inspecting', 'Expanding the inspected neighbourhood explicitly.')
                    if not active():
                        break
                    result = inspection.neighbourhood(**args)
                elif name == 'evaluate_proposal':
                    if trials >= limits.trials:
                        result = dict(error='Geometry trial budget exhausted.')
                    else:
                        progress('checking', f'Checking complete arrangement {trials + 1} of {limits.trials}.')
                        if not active():
                            break
                        trials += 1
                        ops = args.get('operations')
                        result = context_eval.evaluate_candidate(scene, objective, ops, inspection.discovered)
                        hits = result['checks']['geometry']['hits']
                        found = {h[k] for h in hits for k in ('element', 'other') if h.get(k) in scene.bounds()}
                        inspection.discovered.update(found)
                        blockers.update(found)
                        result['discovered'] = sorted(found)
                        if not result['passed']:
                            progress('blocked', f'Arrangement did not pass; discovered {len(found)} geometry elements for inspection.')
                        elif not cancel.is_set():
                            # The deadline bounds starting work, not retaining a
                            # completed, verified trial. Cancellation still discards it.
                            key = _identity(result['edits'])
                            if key not in seen:
                                seen.add(key)
                                proposal = dict(id=uuid.uuid4().hex, scene_revision=scene.revision, objective=deepcopy(objective),
                                                title=str(args.get('title') or 'Coordinated arrangement')[:200],
                                                **{k: deepcopy(result[k]) for k in ('edits', 'checks', 'review_conditions', 'passed')})
                                candidates.append((proposal, deepcopy(ops), set(inspection.discovered)))
                                candidates.sort(key=lambda c: _rank(scene, c[0]))
                                del candidates[limits.alternatives:]
                        # Meshes belong in the UI result, not in the model's tool history.
                        result = {k: v for k, v in result.items() if k not in ('edits', 'pieces')}
                else:
                    raise ValueError(f'unknown tool: {name}')
            except Exception as exc:
                result = dict(error=f'{type(exc).__name__}: {exc}')
            messages.append(dict(role='tool', tool_call_id=call.get('id', ''), content=json.dumps(result)))
        if len(tool_calls) > 48:
            stop = 'Tool-call budget exhausted; retained passing arrangements.'
            break
    if cancel.is_set():
        candidates = []
        stop = 'Search cancelled.'
    else:
        if not active() or trials >= limits.trials or calls >= limits.model_calls:
            stop = 'Search budget reached; retained passing arrangements.'
        if not _store(ws, scene_id, candidates, cancel=cancel):
            candidates = []
            stop = 'Search cancelled.'
    if not candidates:
        stop += ' No passing arrangement was found in this bounded search; other solutions may exist.'
    return dict(type='context_result', proposals=[c[0] for c in candidates], message=stop,
                seconds=round(clock() - start, 3), trials=trials, model_calls=calls, blockers=sorted(blockers))


def _resolved_pairs(ws, sid, scene, objective, result):
    """Measure whole source groups, including every generated piece, without legacy connection exclusions."""
    sources = {g: e['pieces'] for e in result['edits'] for g in e['moved']}
    seed = dict(element_a=objective['element_a'], element_b=objective['element_b'])
    # The fresh whole-arrangement check measured the seed, including valid butt-trim contact.
    # Rechecking it without the evaluator's validated joint exception would mislabel that fix.
    resolved = [seed] if result['checks']['geometry']['target_resolved'] else []
    seen = {frozenset(seed.values())}
    pairs = []
    if objective.get('report_id') in ws.reports:
        for m in ws.match(objective['report_id'], sid).values():
            a, b = m.get('a'), m.get('b')
            if a and b and (a in sources or b in sources):
                pairs.append((a, b))
    for a, b in pairs:
        key = frozenset((a, b))
        if key in seen or a == b:
            continue
        seen.add(key)
        left, right = sources.get(a, [a]), set(sources.get(b, [b]))
        if any(g not in scene.bounds() for g in [*left, *right]):
            continue
        if all(not any(h.other in right for h in verify.check(scene, [g], context_eval.clearance_of(objective),
                   exclude_connected=False).hits) for g in left):
            resolved.append(dict(element_a=a, element_b=b))
    return resolved


def accept(ws, scene_id, proposal_id, acknowledged_conditions):
    with ws.lock:
        record = getattr(ws, '_context_proposals', {}).get(scene_id, {}).get(proposal_id)
        if record is None:
            raise ContextError(404, 'Proposal expired or unknown. Generate a new wider fix.')
        proposal = record['proposal']
        scene = ws.scene(scene_id)
        if scene.revision != proposal['scene_revision']:
            raise ContextError(409, 'Scene changed since this proposal. Generate a new wider fix.')
        required = {c['id'] for c in proposal['review_conditions']}
        if set(acknowledged_conditions) != required:
            raise ContextError(422, 'Acknowledge every review condition using its exact ID; unknown IDs are not accepted.')
        # All fallible work happens privately, including post-edit report measurements.
        private = scene.snapshot()
        try:
            result = context_eval.commit_candidate(private, proposal['objective'], record['operations'], record['discovered'])
            if {c['id'] for c in result['review_conditions']} - set(acknowledged_conditions):
                raise ValueError('Review conditions changed; generate and review a fresh proposal.')
            resolved = _resolved_pairs(ws, scene_id, private, proposal['objective'], result)
        except Exception as exc:
            raise ContextError(409, f'Fresh proposal checks failed: {exc}') from exc
        changed = list(dict.fromkeys([*(g for ps in result['pieces'] for g in ps),
                                      *(g for e in result['edits'] for g in e.get('moved', []))]))
        words = '; '.join(f"{e.get('kind', 'edit')} {', '.join(e.get('moved', [])[:1])}: {e.get('label') or ''}".strip(': ')
                          for e in result['edits'])
        with ws.journal(scene_id).record(scene, 'wider', 'wider', title='Wider fix', summary=words) as rec:
            scene.__dict__ = private.__dict__.copy()
            rec.changed, rec.files = changed, list(result['files'])
            rec.params = {'proposal': proposal_id, 'operations': record['operations']}
            rec.clashes = [{'id': objective_clash, 'pair': [proposal['objective']['element_a'], proposal['objective']['element_b']]}
                           for objective_clash in [proposal['objective'].get('clash_id')]]
            rec.clashes += [{'id': None, 'pair': [r['element_a'], r['element_b']]} for r in resolved[1:]]
        return dict(files=result['files'], pieces=result['pieces'], edits=result['edits'],
                    resolved_pairs=resolved, checks=result['checks'], changed=changed)
