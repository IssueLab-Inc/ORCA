# The submission text

**Status (Nov 2):** drafts for the owner: the one-liner and what's next. The rest of the form is written at the
freeze (Nov 3); submit Nov 4 before noon ET ([20](architecture/20-decisions-limits-and-roadmap.md), "The hackathon
frame"). The video has its own script: [demo-video.md](demo-video.md).

## Rules for this text

- **The user and the job first, the loop second, features last** (as "it also…"). Past Meta hackathon winners named a
  user and a job in one line ("A&E triage assistant for NHS staff"), and judges weighed coherence over feature count.
- **Technical names are fine here** (IFC, STEP, BCF, MCP), unlike the video's plain words.
- **Every number is measured** and measured again on the day (CLAUDE.md, "Numbers people see are measured").

## The one-liner

> ORCA is for the design coordinator who runs a project's clash meetings: it proposes fixes to the clashes between the
> teams' 3D models as real edits to those models, and proves each one with geometry before anyone sees it.

Short form, for a tagline field: **Clash fixes for design coordinators, each proven by geometry before anyone sees it.**

"Design coordinator" is the user [01](architecture/01-product-and-journeys.md) names and the job
[21](architecture/21-glossary-and-naming.md) calls design coordination; on a building the same person is often called
the BIM coordinator. The README opens with the same sentence.

## What's next

> Today a kept fix ends in an exported IFC or STEP, with a PDF report and BCF issues. Next, none of it built yet:
> connectors, so a kept fix lands in the designer's own tool (open and cloud tools first: Speckle, the BCF API,
> Onshape and Bonsai; then Revit and Inventor); photos, video and laser scans from site, aligned to the model and
> segmented with SAM 3.1, so ORCA checks a fix against what is really there; and sign-in with saved projects.

The README's "What's next" says the same, and the video's last shot proposes it as one line
([demo-video.md](demo-video.md), 2:50). The detail: [20](architecture/20-decisions-limits-and-roadmap.md), "Later".
