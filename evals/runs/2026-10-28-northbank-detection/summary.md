# Sightline detection vs Navisworks, Northbank

Sightline's default tests (hard, 1 mm) on 1961 elements in 4 models: **633 clashes in 6.3 s** (from opening the models: element boxes, triangle tree, all tests).

| Test | Elements A | Elements B | Pairs checked | Clashes | Touching | Meant to meet | Seconds |
|---|---|---|---|---|---|---|---|
| Architecture vs MEP | 658 | 844 | 312 | 0 | 0 | 0 | 0.366 |
| Architecture vs Site | 658 | 229 | 145 | 0 | 0 | 0 | 0.165 |
| Architecture vs Structure | 658 | 230 | 188 | 0 | 0 | 0 | 0.038 |
| MEP vs Site | 844 | 229 | 48 | 0 | 0 | 0 | 0.022 |
| MEP vs Structure | 844 | 230 | 33 | 3 | 0 | 0 | 0.027 |
| Site vs Structure | 229 | 230 | 53 | 0 | 0 | 0 | 0.021 |
| Architecture (within) | 658 | 658 | 1637 | 12 | 6 | 0 | 0.13 |
| MEP (within) | 844 | 844 | 647 | 0 | 10 | 1 joined by ports | 0.103 |
| Site (within) | 229 | 229 | 472 | 169 | 0 | 0 | 0.232 |
| Structure (within) | 230 | 230 | 691 | 449 | 0 | 0 | 0.172 |
| Duplicates (all models) | 1961 | 1961 | 4226 | 0 | 0 | 0 | 0.038 |

## Answer key

| | Sightline | Test | In Navisworks' sample |
|---|---|---|---|
| #042 | -300.0 mm | MEP vs Structure | yes |
| #057 | -100.0 mm | MEP vs Structure | yes |
| #061 | -76.8 mm | MEP vs Structure | no |

## The 317 sampled Navisworks results

Of the 117 that are physical, on two elements and overlap deeper than 1 mm in Navisworks and Sightline and are not meant to meet, Sightline reports **117**.

| Outcome | Results |
|---|---|
| not physical (never reported) | 129 |
| found | 117 |
| touch at 1 mm (Navisworks) | 46 |
| one element on both sides | 24 |
| meant to meet: joined by ports | 1 |

## Counts per pair of disciplines

Navisworks' stored results include ports, spaces and sub-objects of one element, and one element pair can give several results; Sightline reports each physical element pair once. Context, not a score.

Navisworks stored 7668 results; 3100 of them are in tests of a space, port or opening, which Sightline never reports. The rest, by pair of disciplines (still including touches, one element's own parts and repeated pairs):

| Disciplines | Navisworks stored | Sightline |
|---|---|---|
| Architecture / Architecture | 522 | 12 |
| Architecture / Structure | 99 | 0 |
| MEP / MEP | 829 | 0 |
| MEP / Structure | 6 | 3 |
| Site / Site | 1642 | 169 |
| Structure / Structure | 1470 | 449 |
