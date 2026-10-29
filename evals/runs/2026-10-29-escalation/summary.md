# E0: a second try on Muse Wonder

21 cases, one Muse Spark proposal each; 6 with no verified fix; 2 fixed only with a resize or an opening. 19 min, Muse Wonder $2.01.

## The sweep

| Case | Spark's first try | Tried | s |
|---|---|---|---|
| cell C1 air/seg2 x cv/rail/north | offset: Local offset of pipe A down 150 mm under rail | 3 | 59.8 |
| cell C1 air/seg2 x cv/rail/south | offset: Offset pipe down 150 mm under the side rail | 3 | 87.7 |
| cell C2 ct/h2 x fence/post/W5 | offset: Offset tray up over post top | 3 | 16.6 |
| cell C3 fence/rail/S5-SE x fence/post/SE | trim: Trim top rail end to post face | 1 | 9.3 |
| cell C4 r1/reach x fence/post/N3 | no fix | 7 | 127.0 |
| cell C4 r1/reach x fence/post/N4 | no fix | 8 | 108.0 |
| cell C4 r1/reach x fence/plate/N3 | no fix | 8 | 131.3 |
| cell C4 r1/reach x fence/plate/N4 | no fix | 7 | 229.5 |
| cell C4 r1/reach x fence/panel/N2-N3 | error: HTTPStatusError: Server error '500 Internal Server Error' for url 'https://api.m | | |
| cell C4 r1/reach x fence/panel/N4-N5 | move: Move guard N4-N5 north 350 mm, keep level | 10 | 122.4 |
| cell C4 r1/reach x fence/curtain/N/a | move: Move light curtain emitter radially out of restricted space | 2 | 20.4 |
| cell C4 r1/reach x fence/curtain/N/b | move: Move receiver 350 mm in +Y to clear zone | 2 | 24.3 |
| cell C5 hmi x ep301/space | no fix | 9 | 80.9 |
| cell C6 air/pl302/seg3 x bldg/column/C3 | route: Reroute pipe north past column | 3 | 56.1 |
| cell C6 air/pl302/seg3 x bldg/column/C4 | route: Detour pipe north past column C4 | 2 | 24.2 |
| cell C7 air/main x bldg/wall/west | penetration: Cored Ø130 mm opening for air main through west wall | 4 | 53.4 |
| cell C8 elec/c302 x gland/ep301-top | penetration: Glanded opening for C-302 conduit through EP-301 top gland plate | 4 | 63.8 |
| northbank #042 duct | offset: Offset duct up 400 mm through girder opening | 3 | 44.1 |
| northbank #057 tray | offset: Offset tray up 250 mm through girder opening | 2 | 46.8 |
| northbank #061 cold water | offset: Offset main up 280 mm through girder opening | 2 | 27.6 |
| northbank B1 pad footing x lift pit wall | no fix | 10 | 96.0 |

## No fix after the sweep: three arms, two rounds each

| Case | Spark again | Spark + brief | Wonder + brief | Wonder s / $ |
|---|---|---|---|---|
| cell C4 r1/reach x fence/post/N3 | no fix | no fix | move: Move post N3 north-west 300 mm and lift 180 mm clear of slab | 113.1 / 0.26 |
| cell C4 r1/reach x fence/post/N4 | no fix | move: Move post N4 north 400 mm onto 150 mm plinth | move: Move post N4 north 400 mm and lift 120 mm clear of its slab embedment | 111.5 / 0.19 |
| cell C4 r1/reach x fence/plate/N3 | no fix | move: Shift N3 base north 1250 mm beyond slab edge | move: Relocate N3 base plate 500 mm north, lifted 200 mm clear of slab | 143.0 / 0.35 |
| cell C4 r1/reach x fence/plate/N4 | no fix | move: Move N4 base 350 mm north onto plinth clear of restricted volume | move: Move N4 base plate 500 mm north and raise it 150 mm | 116.5 / 0.30 |
| cell C5 hmi x ep301/space | no fix | no fix | no fix | 124.3 / 0.33 |
| northbank B1 pad footing x lift pit wall | no fix | no fix | move: Shift pad footing 1.30 m west clear of pit and ground beam | 44.9 / 0.12 |
- spark_again: 0 of 6 verified
- spark_brief: 3 of 6 verified
- wonder_brief: 5 of 6 verified

## Fixed only with a resize or an opening: Wonder looking for a better fix

| Case | Spark | Wonder | Plain fix found |
|---|---|---|---|
| cell C7 air/main x bldg/wall/west | penetration: Cored Ø130 mm opening for air main through west wall | no fix:  | no |
| cell C8 elec/c302 x gland/ep301-top | penetration: Glanded opening for C-302 conduit through EP-301 top gland plate | no fix:  | no |

Advice and failures per arm: results.json.
