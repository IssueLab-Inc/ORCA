# The submission text

**Status (Nov 2):** drafts for the owner: the one-liner and what's next. The rest of the form is written at the
freeze (Nov 3); submit Nov 4 before noon ET ([20](architecture/20-decisions-limits-and-roadmap.md), "The hackathon
frame"). The video has its own script: [demo-video.md](demo-video.md).

## Rules for this text

- **The user and the job first, the loop second, features last** (as "it also…"). Past Meta hackathon winners named a
  user and a job in one line ("A&E triage assistant for NHS staff"), and judges weighed coherence over feature count.
- **The opening lines are plain words for any industry:** they describe the problem (two designs that conflict,
  parts designed into the same space) before naming it. "Clash" is the building industry's word for it, and the app's:
  use it after it has been explained, as the video does.
- **Technical names are fine after that** (IFC, STEP, BCF, MCP), unlike the video's plain words.
- **Every number is measured** and measured again on the day (CLAUDE.md, "Numbers people see are measured").

## The one-liner

> ORCA is for the design coordinator, who makes every team's 3D design fit together: where two designs conflict, it
> proposes a fix as a real edit to the model, and proves the fix with geometry before anyone sees it.

Short form, for a tagline field: **When teams' 3D designs collide, ORCA proposes the fix and proves it before anyone
sees it.**

"Design coordinator" is the user [01](architecture/01-product-and-journeys.md) names, and "who makes every team's 3D
design fit together" says the job in words any industry reads: on a building the same person is often the BIM
coordinator; on a machine, the engineer who owns the assembly. "Conflict" is the landing's word ("finds where they
conflict"). Not "design coordination issues": it is vaguer, and it promises more than ORCA fixes (conflicts in space
and room to spare, not missing information or code compliance). The README opens with the same sentence.

## Who it's for

> ORCA is built around the design coordinator, who makes every team's 3D design fit together (on a building, often the
> BIM coordinator; on a machine, the engineer who owns the assembly). It also serves the teams whose designs meet, each
> with its own report and a review of every fix to its design; whoever sets the project's standard, through
> requirements every fix must meet; people who don't read technical drawings, through a picture of what will be built;
> and teams with their own AI agent, through a pairing link. Later: site teams, comparing what was installed with what
> was designed.

One user leads and the others follow, each with what ORCA gives them: a list of job titles with nothing beside them
would blur the one-liner. The table with where each lives: [01](architecture/01-product-and-journeys.md), "Who it is
for".

## What's next

> Today a kept fix ends in an exported IFC or STEP, with a PDF report and BCF issues. Next, none of it built yet:
> connectors, so a kept fix lands in the designer's own tool (open and cloud tools first: Speckle, the BCF API,
> Onshape and Bonsai; then Revit and Inventor); photos, video and laser scans from site, aligned to the model and
> segmented with SAM 3.1, so ORCA checks a fix against what is really there; and sign-in with saved projects.

The README's "What's next" says the same, and the video's last shot carries it as a card under the notch
([demo-video.md](demo-video.md), 2:50). The detail: [20](architecture/20-decisions-limits-and-roadmap.md), "Later".
