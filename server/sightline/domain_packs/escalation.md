
## A second try

You are taking a second, longer look at this clash. A first designer (Muse Spark) has already tried; what it read,
what it proposed and exactly why each idea failed the geometry check are below, with a wider view of what stands
around the clash. Every idea you propose is tried on the real model and checked the same way; nothing reaches a
person unless it passes.

- Do not repeat an idea that failed. Use why it failed: what it hit, where, and by how much.
- When the first try did find fixes, beat them: a plain geometry fix (move, offset, route) where it found only a
  resize or an opening, more clearance, or a smaller change. Its fixes stay on offer either way.
- Look further than the two elements: the room may be beside or above a neighbour, through an opening in another
  element, or made by moving a service that is in the way.
- Structure and anything marked "stays" is never moved. Only services may move to make room.

You may also propose a **combined** fix: up to three elements change together in one check, for example the pipe
beside the duct moves 150 mm and the duct takes the room it leaves. Each step is a move, an offset or a route, on its
own element: "A", "B" or the GlobalId of a service listed around the clash. One step must change A or B.

    {"title": "Move the return-air main 200 mm north and offset the duct up through the opening",
     "kind": "combined",
     "steps": [{"kind": "move", "move": "<GlobalId>", "delta_m": [0, 0.2, 0]},
               {"kind": "offset", "move": "A", "split_m": [2.6, 4.4], "dz_m": 0.4}],
     "rationale": "one sentence", "also_needs": "e.g. the return-air main's hangers moved, or none"}

Prefer one element over a combined fix when one is enough: every element changed is more work on site.
