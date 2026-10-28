"""Isolated, whole-arrangement geometry and connection checks.

The Workspace lock must surround snapshot/commit when called against a live scene.
Passing means the model constraints checked here passed; engineering adequacy is review-only.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import ifcopenshell.util.system as system
import ifcopenshell.util.element

from . import edits, verify
from .scene import IfcScene, FIXED_CLASSES

TOL = .002
CLEARANCE = .025


def element_constraints(scene: IfcScene, gid: str) -> list[str]:
    """Explicit per-element model constraints; absent properties impose no restriction."""
    properties = ifcopenshell.util.element.get_pset(scene.entity(gid),'Pset_SightlineConstraints') or {}
    return ['KeepFixed'] if properties.get('KeepFixed') is True else []


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def _vector(value, size, name):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f'{name} must have {size} values')
    return [_number(v, name) for v in value]


def _validate(scene, objective, operations, discovered):
    if not isinstance(objective, dict):
        raise ValueError('objective must identify element_a and element_b')
    physical = {p.GlobalId for p in scene.products()}
    for key in ('element_a', 'element_b'):
        if objective.get(key) not in physical:
            raise ValueError(f'{key} must identify a physical element in this scene')
    if objective['element_a'] == objective['element_b']:
        raise ValueError('objective must contain two distinct elements')
    if not isinstance(operations, list) or not 1 <= len(operations) <= 3:
        raise ValueError('a candidate needs one to three edit groups')
    groups, seen = [], set()
    for op in operations:
        if not isinstance(op, dict):
            raise ValueError('each operation must be an object')
        gid, kind = op.get('element'), op.get('kind')
        if not isinstance(gid, str) or gid not in physical:
            raise ValueError(f'unknown or unsupported element: {gid}')
        if discovered is not None and gid not in discovered:
            raise ValueError(f'element was not discovered: {gid}')
        if not isinstance(op.get('reason'), str) or not op['reason'].strip():
            raise ValueError('each edit needs a reason')
        if kind not in ('move', 'offset', 'trim'):
            raise ValueError(f'unsupported operation: {kind}')
        group = scene.connected_run(gid) if kind == 'move' else [gid]
        if discovered is not None and set(group) - discovered:
            raise ValueError(f'connected run contains undiscovered elements: {sorted(set(group) - discovered)}')
        if seen.intersection(group):
            raise ValueError('duplicate or overlapping edit groups')
        if any(g not in physical for g in group):
            raise ValueError('connected run contains an element without supported geometry')
        fixed = [g for g in group if element_constraints(scene,g)]
        if fixed:
            raise ValueError(f'KeepFixed model constraint prohibits editing: {fixed}')
        seen.update(group)
        if kind in ('move', 'offset'):
            delta = np.array(_vector(op.get('delta_m'), 3, 'delta_m'))
            if np.linalg.norm(delta) < 1e-6:
                raise ValueError('delta_m must describe a nonzero edit')
        if kind == 'offset':
            split = _vector(op.get('split_m'), 2, 'split_m')
            if split[0] >= split[1]:
                raise ValueError('split_m must be increasing')
            run = edits.run_of(scene, gid)
            d = np.array(run.direction)
            if abs(d @ edits.UP) > 1e-6 or abs(delta @ d) > 1e-6:
                raise ValueError('offset must be perpendicular to a horizontal run')
            if abs(delta[2]) > 1e-9 and np.linalg.norm(delta[:2]) > 1e-9:
                raise ValueError('compound offsets are unsupported')
            size = run.depth_m if abs(delta[2]) > 1e-9 else run.width_m
            if scene.entity(gid).is_a() not in edits.FITTING_CLASS or edits.bend_radius(size, np.linalg.norm(delta)) is None:
                raise ValueError('offset requires supported radiused fittings; square fallback is not verified')
        if kind == 'trim':
            by = _number(op.get('by_m'), 'by_m')
            if op.get('end') not in ('start', 'end') or by <= 0:
                raise ValueError('trim requires start/end and positive by_m')
            _, start, d, length = edits.member_axis(scene, scene.entity(gid))
            verts = np.array(edits.meshes(scene, [gid])[0]['verts']).reshape(-1, 3)
            if length < edits.SLENDER * edits._across(verts - start, d):
                raise ValueError('trim requires a slender member')
        groups.append(group)
    return groups


def _connections(scene, owners):
    found = {}
    for gid in owners:
        for p in system.get_ports(scene.entity(gid)):
            q = system.get_connected_port(p)
            if q is None:
                continue
            other = system.get_port_element(q)
            if other is None:
                continue
            key = tuple(sorted((p.GlobalId, q.GlobalId)))
            found[key] = (p.GlobalId, q.GlobalId, gid, other.GlobalId)
    return found


def _systems(scene, gid):
    return {s.GlobalId for s in system.get_element_systems(scene.entity(gid))}


def _profile_evidence(scene, gid):
    try:
        item = edits._body(scene.entity(gid))[1]
        dimensions = np.array(edits._profile_size(item.SweptArea)) * scene.unit_scales[scene.index_of(gid)]
        return item.SweptArea.is_a('IfcCircleProfileDef'), dimensions
    except edits.Unsupported:
        return None, None


def _port_endpoint_matches(scene, owner, port):
    """Known straight-run endpoint position, independently of flow or orientation."""
    if port.ObjectPlacement is None:
        return None
    try:
        run = edits.run_of(scene,owner)
    except edits.Unsupported:
        return None
    point = scene.placement(port.GlobalId)[:3,3]
    return any(np.linalg.norm(point-end) <= TOL for end in (run.start,run.end))


def _physical_port_frame(scene, owner, port, circular, dimensions, generated, flow=None):
    """Compare IFC flow axes to actual extrusion endpoints or triangulated fitting caps.

    This does not reuse the offset generator's tangent/reference construction. None
    means the available shape cannot establish the physical frame independently.
    """
    flow = flow or port.FlowDirection
    if port.ObjectPlacement is None or flow not in ('SOURCE','SINK'):
        return None
    matrix = scene.placement(port.GlobalId)
    outward = matrix[:3,2] * (-1 if flow == 'SINK' else 1)
    try:
        run = edits.run_of(scene,owner)
        _,_,item,_,d,px,py = edits._frames(scene,scene.entity(owner))
        position = getattr(item.SweptArea,'Position',None)
        if position is not None and position.RefDirection is not None:
            x,y = position.RefDirection.DirectionRatios
            px = (px*x + py*y) / np.hypot(x,y)
        if np.linalg.norm(matrix[:3,3]-run.start) <= TOL:
            normal = -d
        elif np.linalg.norm(matrix[:3,3]-run.end) <= TOL:
            normal = d
        else:
            # Position failures are rejected separately, never classified as frame defects.
            return None
        return bool(outward @ normal > .999 and (circular or matrix[:3,0] @ px > .999))
    except edits.Unsupported:
        pass
    if dimensions is None:
        return None
    mesh = edits.meshes(scene,[owner])[0]
    vertices = np.array(mesh['verts']).reshape(-1,3)
    triangles = vertices[np.array(mesh['faces']).reshape(-1,3)]
    cap = np.all(np.abs((triangles-matrix[:3,3]) @ outward) < 1e-4,axis=1)
    if not cap.any():
        return False if generated else None
    triangles = triangles[cap]
    normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    lengths = np.linalg.norm(normals,axis=1)
    normals = normals[lengths > 1e-10] / lengths[lengths > 1e-10,None]
    if not len(normals) or not np.all(normals @ outward > .999):
        return False
    if circular:
        return True
    extents = np.ptp(triangles.reshape(-1,3) @ matrix[:3,:2],axis=0)
    return bool(np.allclose(extents,dimensions,atol=.001,rtol=0))


def _unchanged_external_frame_defect(before, after, originals, sources, old, a, b, ep, eq):
    """Narrow baseline exception: an authored external defect, never a new joint.

    Both port poses and flows, the unchanged peer, and the edited source's physical
    endpoint/profile frame must be retained exactly. Known other violations are
    checked separately. This is a disclosed legacy defect, not IFC conformance.
    """
    sa,sb = sources.get(a,a),sources.get(b,b)
    if (sa in originals) == (sb in originals):
        return False
    if sb in originals:
        a,b,sa,sb,ep,eq = b,a,sb,sa,eq,ep
    for p,q,x,y in old.values():
        if y == sa and x == sb:
            p,q,x,y = q,p,y,x
        if x != sa or y != sb or q != eq.GlobalId:
            continue
        bp,bq = before.entity(p),before.entity(q)
        endpoint_evidence = [_port_endpoint_matches(before,sa,bp), _port_endpoint_matches(before,sb,bq),
                             _port_endpoint_matches(after,a,ep), _port_endpoint_matches(after,b,eq)]
        if False in endpoint_evidence:
            return False
        if any(port.ObjectPlacement is None or port.FlowDirection not in ('SOURCE','SINK')
               for port in (bp,bq,ep,eq)):
            return False
        if bp.FlowDirection != ep.FlowDirection or bq.FlowDirection != eq.FlowDirection:
            return False
        mp,mq = before.placement(p),before.placement(q)
        if not (np.allclose(mp,after.placement(ep.GlobalId),atol=1e-8,rtol=0) and
                np.allclose(mq,after.placement(eq.GlobalId),atol=1e-8,rtol=0)):
            return False
        try:
            old_run,new_run = edits.run_of(before,sa),edits.run_of(after,a)
            old_frame,new_frame = edits._frames(before,before.entity(sa)),edits._frames(after,after.entity(a))
        except edits.Unsupported:
            return False
        ends = [(old_run.start,new_run.start),(old_run.end,new_run.end)]
        if not any(np.linalg.norm(mp[:3,3]-start) <= TOL and np.allclose(start,end,atol=1e-8,rtol=0)
                   for start,end in ends):
            return False
        if not all(np.allclose(old_frame[k],new_frame[k],atol=1e-8,rtol=0) for k in (4,5,6)):
            return False
        if old_frame[2].SweptArea.get_info(recursive=True) != new_frame[2].SweptArea.get_info(recursive=True):
            return False
        ca,da = _profile_evidence(before,sa)
        cn,dn = _profile_evidence(after,a)
        cb,db = _profile_evidence(before,sb)
        if da is None or dn is None or ca != cn or not np.allclose(da,dn,atol=1e-8,rtol=0):
            return False
        # The fixed peer's geometry also must be retained, not merely its port pose.
        old_box,new_box = before.bounds().get(sb),after.bounds().get(b)
        if old_box is None or new_box is None or not np.allclose(old_box,new_box,atol=1e-8,rtol=0):
            return False
        return (float(mp[:3,2] @ mq[:3,2]) <= .999 or
                ((ca is False or cb is False) and float(mp[:3,0] @ mq[:3,0]) <= .999) or
                (endpoint_evidence[0] is True and _physical_port_frame(before,sa,bp,ca,da,False) is False) or
                (endpoint_evidence[1] is True and _physical_port_frame(before,sb,bq,cb,db,False) is False))
    return False


def _integrity(before, after, originals, sources, result):
    errors = result['checks']['integrity']['errors']
    review = result['review_conditions']
    allowed = set()
    old = _connections(before, originals)
    new = _connections(after, sources)
    for gid in sources:
        entity = after.entity(gid)
        ports = system.get_ports(entity)
        if len(ports) != 2:
            continue
        try:
            run = edits.run_of(after,gid)
        except edits.Unsupported:
            continue
        if any(p.ObjectPlacement is None for p in ports):
            review.append(dict(id='connection_metadata', message='Connection positions or frames are missing; verify routing continuity.'))
            continue
        points = [after.placement(p.GlobalId)[:3,3] for p in ports]
        ends = [np.array(run.start),np.array(run.end)]
        if not any(all(np.linalg.norm(points[j]-ends[k]) <= TOL for j,k in enumerate(order))
                   for order in ((0,1),(1,0))):
            errors.append(f'connection ports do not align with physical run endpoints: {gid}')
    # Each authored connection must still connect the same source owners. Offsets may transfer
    # a far-end port to a generated last piece, but must preserve the external port itself.
    for p, q, a, b in old.values():
        matches = [(u, v, x, y) for u, v, x, y in new.values()
                   if {sources.get(x, x), sources.get(y, y)} == {a, b}]
        if a not in originals or b not in originals:
            external = p if a not in originals else q
            matches = [edge for edge in matches if external in edge[:2]]
        if not matches:
            errors.append(f'connection removed between {a} and {b}')
    for p, q, a, b in new.values():
        pair = frozenset((a,b))
        ep, eq = after.entity(p), after.entity(q)
        endpoint_evidence = [_port_endpoint_matches(after,a,ep), _port_endpoint_matches(after,b,eq)]
        for owner, valid in zip((a,b),endpoint_evidence):
            if valid is False:
                errors.append(f'connection port does not align with physical run endpoint: {owner}')
        # None falls through to the existing missing-placement / fitting-cap evidence
        # paths below; a supported fitting cap is not a missing straight-run endpoint.
        ca,da = _profile_evidence(before,sources.get(a,a))
        cb,db = _profile_evidence(before,sources.get(b,b))
        orientation_ok, gap = False, None
        if ep.ObjectPlacement is None or eq.ObjectPlacement is None:
            review.append(dict(id='connection_metadata', message='Connection positions or frames are missing; verify routing continuity.'))
        else:
            mp, mq = after.placement(p), after.placement(q)
            gap = float(np.linalg.norm(mp[:3,3] - mq[:3,3]))
            if gap > TOL:
                errors.append(f'connection misaligned between {a} and {b}: {gap:.4f} m')
            if ep.FlowDirection in ('SOURCE','SINK') and eq.FlowDirection in ('SOURCE','SINK'):
                # IFC rigid SOURCE/SINK joints have equal signed effective flow axes.
                orientation_ok = float(mp[:3,2] @ mq[:3,2]) > .999
                if ca is False or cb is False:
                    orientation_ok &= float(mp[:3,0] @ mq[:3,0]) > .999
                physical = [_physical_port_frame(after,a,ep,ca,da,sources.get(a,a)!=a),
                            _physical_port_frame(after,b,eq,cb,db,sources.get(b,b)!=b)]
                if False in physical or not orientation_ok:
                    if _unchanged_external_frame_defect(before,after,originals,sources,old,a,b,ep,eq):
                        message = f'Authored external frame defect remains unchanged between {a} and {b}; these frames are not IFC-conformant and require designer review.'
                        result['checks']['integrity']['warnings'].append(message)
                        review.append(dict(id='legacy_port_frames',message=message))
                        orientation_ok = True  # retained physical contact, not a conformant frame
                    else:
                        errors.append(f'connection frame mismatch between {a} and {b}')
                        orientation_ok = False
                if None in physical or ca is None or cb is None:
                    review.append(dict(id='port_frames',message='Some physical port frames cannot be established from the available profiles; verify connection orientation.'))
            else:
                review.append(dict(id='port_frames',message='Flow direction is undefined or bidirectional; verify effective connection frames.'))
                # Contact can still be established from opposed physical cap normals.
                # This validates touching geometry only, not an unknown flow convention.
                fp = ep.FlowDirection if ep.FlowDirection in ('SOURCE','SINK') else 'SOURCE'
                fq = eq.FlowDirection if eq.FlowDirection in ('SOURCE','SINK') else 'SOURCE'
                outward_p = mp[:3,2] * (-1 if fp == 'SINK' else 1)
                outward_q = mq[:3,2] * (-1 if fq == 'SINK' else 1)
                orientation_ok = (outward_p @ outward_q < -.999 and
                    _physical_port_frame(after,a,ep,ca,da,sources.get(a,a)!=a,fp) is True and
                    _physical_port_frame(after,b,eq,cb,db,sources.get(b,b)!=b,fq) is True)
        # Semantic and profile evidence is independent of port positions and frames:
        # missing spatial metadata must not conceal a known incompatibility.
        flows = (ep.FlowDirection, eq.FlowDirection)
        if all(f in ('SOURCE', 'SINK') for f in flows) and flows[0] == flows[1]:
            errors.append(f'connection flow mismatch between {a} and {b}')
        elif any(f not in ('SOURCE', 'SINK') for f in flows):
            review.append(dict(id='flow_metadata', message='Flow direction is missing or bidirectional; confirm service continuity.'))
        sa, sb = _systems(after,a), _systems(after,b)
        if sa and sb and sa.isdisjoint(sb):
            errors.append(f'connection system mismatch between {a} and {b}')
        if not sa or not sb:
            review.append(dict(id='system_metadata', message='System membership is incomplete; confirm connected services.'))
        for field in ('SystemType', 'PredefinedType'):
            va, vb = getattr(ep, field, None), getattr(eq, field, None)
            if va not in (None, 'NOTDEFINED') and vb not in (None, 'NOTDEFINED') and va != vb:
                errors.append(f'connection {field} mismatch between {a} and {b}')
        try:
            ra, rb = edits.run_of(after,a), edits.run_of(after,b)
            profile_a = edits._body(after.entity(a))[1].SweptArea.is_a()
            profile_b = edits._body(after.entity(b))[1].SweptArea.is_a()
            if (profile_a != profile_b or
                    not np.allclose((ra.depth_m,ra.width_m), (rb.depth_m,rb.width_m), atol=.001, rtol=0)):
                errors.append(f'connection profile mismatch between {a} and {b}')
        except edits.Unsupported:
            # Generated bends are built from the source profile by apply_offset.
            if a not in sources or b not in sources or sources.get(a) != sources.get(b):
                review.append(dict(id='profile_metadata', message='Some joint profiles cannot be verified; confirm fitting compatibility.'))
        if orientation_ok and gap is not None and gap <= TOL and False not in endpoint_evidence:
            allowed.add(pair)
    for gid in originals:
        entity = before.entity(gid)
        if any(entity.is_a(cls) for cls in FIXED_CLASSES):
            review.append(dict(id='structural_review', message='A structural element changes; a structural designer must review adequacy, bearing and connections.'))
        if entity.is_a('IfcDistributionElement'):
            review.append(dict(id='service_review', message='Review service performance, access, maintenance space and supports for the changed route.'))
            if not system.get_ports(entity):
                review.append(dict(id='connection_metadata', message='Service ports are missing; physical continuity needs designer review.'))
            if not _systems(before,gid):
                review.append(dict(id='system_metadata', message='System membership is incomplete; confirm connected services.'))
    result['checks']['integrity']['passed'] = not errors
    return allowed


def _findings(scene, changed, allowed):
    findings, gaps = {}, []
    for gid in sorted(changed):
        touch = {next(iter(pair - {gid})) for pair in allowed if gid in pair and len(pair) == 2}
        v = verify.check(scene, [gid], CLEARANCE, exclude_connected=False, touching=touch)
        if v.min_clearance_m is not None:
            gaps.append(v.min_clearance_m)
        for h in v.hits:
            key = frozenset((gid, h.other))
            hit = dict(element=gid, other=h.other, kind=h.kind, distance_m=h.distance_m)
            if h.location is not None:
                hit['location'] = h.location
            if key not in findings or h.distance_m < findings[key]['distance_m']:
                findings[key] = hit
    return findings, min(gaps) if gaps else None


def _run(scene, objective, operations, discovered):
    result = dict(passed=False, edits=[], checks=dict(
        geometry=dict(passed=False, target_resolved=False, hits=[], existing_conflicts=[], min_clearance_m=None),
        integrity=dict(passed=False, errors=[], warnings=[])), review_conditions=[], files=[], pieces=[])
    try:
        groups = _validate(scene, objective, operations, discovered)
        before = scene.snapshot()
        originals = {g for group in groups for g in group}
        baseline, _ = _findings(before, originals | {objective['element_a'], objective['element_b']}, set())
        sources = {}
        for op, group in zip(operations, groups):
            entry = deepcopy(op)
            entry.update(moved=group, before=edits.meshes(scene,group), label=op['reason'])
            gid = op['element']
            if op['kind'] == 'move':
                scene.translate(group, tuple(op['delta_m']))
                pieces = group
            elif op['kind'] == 'offset':
                run = edits.run_of(scene,gid)
                delta = np.array(op['delta_m'])
                lateral = float(delta @ np.cross(edits.UP,np.array(run.direction)))
                off = edits.apply_offset(scene,gid,*op['split_m'],float(delta[2]),corners='bends',lateral_m=lateral)
                if off.corners != 'bends':
                    raise ValueError('offset requires real fittings')
                pieces = off.pieces
            else:
                edits.apply_trim(scene,gid,op['end'],op['by_m'])
                pieces = [gid]
            sources.update({g: (g if op['kind'] == 'move' else gid) for g in pieces})
            entry.update(pieces=pieces, preview=edits.meshes(scene,pieces))
            result['edits'].append(entry)
            result['pieces'].append(pieces)
        result['files'] = sorted({scene.index_of(g) for g in originals})
        allowed = _integrity(before,scene,originals,sources,result)
        # A slender butt trim may touch its objective partner; penetration is still checked.
        for op in operations:
            if op['kind'] == 'trim' and op['element'] in (objective['element_a'],objective['element_b']):
                allowed.add(frozenset((objective['element_a'],objective['element_b'])))
        final, gap = _findings(scene,set(sources) | {objective['element_a'],objective['element_b']},allowed)
        geometry = result['checks']['geometry']
        target = frozenset((objective['element_a'],objective['element_b']))
        geometry['target_resolved'] = True
        for pair, hit in final.items():
            source_pair = frozenset(sources.get(g,g) for g in pair)
            prior = baseline.get(source_pair)
            is_target = source_pair == target
            if is_target:
                geometry['target_resolved'] = False
            if not is_target and prior and hit['distance_m'] >= prior['distance_m'] - 1e-4:
                geometry['existing_conflicts'].append(hit)
            else:
                geometry['hits'].append(hit)
        geometry.update(passed=not geometry['hits'] and geometry['target_resolved'], min_clearance_m=gap)
        result['review_conditions'] = list({r['id']: r for r in result['review_conditions']}.values())
        if geometry['existing_conflicts']:
            result['review_conditions'].append(dict(id='existing_conflicts',message='Unchanged baseline conflicts remain and require coordination review.'))
        result['passed'] = geometry['passed'] and result['checks']['integrity']['passed']
    except Exception as exc:
        result['checks']['integrity']['errors'].append(f'{type(exc).__name__}: {exc}')
        result['checks']['integrity']['passed'] = False
        result['passed'] = False
    return result


def evaluate_candidate(scene: IfcScene, objective: dict, operations: list[dict], discovered: set[str] | None = None) -> dict:
    """Evaluate a complete arrangement on a private clone; never change the input scene."""
    return _run(scene.snapshot(), objective, operations, discovered)


def commit_candidate(scene: IfcScene, objective: dict, operations: list[dict], discovered: set[str] | None = None) -> dict:
    """Recheck and publish all files together. Caller must hold the Workspace lock."""
    private = scene.snapshot()
    result = _run(private, objective, operations, discovered)
    if not result['passed']:
        raise ValueError(f'candidate failed verification: {result["checks"]}')
    private._edited.update(result['files'])
    private.revision = scene.revision + 1
    # All fallible model work completed before the single state publication.
    scene.__dict__ = private.__dict__.copy()
    return result
