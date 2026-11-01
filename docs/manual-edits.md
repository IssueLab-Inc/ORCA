# Manual edits and the edit log: design

Owner request, Nov 1: edit model objects by hand (or by asking Muse) and keep a record of every edit, so the reports,
Muse and agents know what changed, not only the geometry. It is new work, written for ORCA during the event.

## Owner decisions (Nov 1)

1. The whole basic toolset, the edit log and Muse on both, before the freeze.
2. A hand edit that creates a clash can be kept, behind an explicit **Keep with N clashes**. It is never called
   verified, and the clash joins the clash list (the kept checks run again).
3. The coordination requirements bind hand edits as they bind fixes. ORCA's own hard rules (never cut a transfer
   girder, a column, glazing) **warn** instead of block, and the warning is kept in the log with who must review it.
4. "Cut" means split an object into pieces, and optionally take a section out of it.
5. A person's own "keep it", typed or spoken, keeps an edit Muse checked; so does the Keep button. Muse never keeps on
   its own. MCP agents get `apply_edit` beside `apply_fix`.
6. Accept Muse's fix, then adjust it by hand: the log ties the hand edit to that clash and that fix, and the report
   shows both, in order.

## The edit log (`server/sightline/journal.py`)

Every kept edit is one entry, whoever made it:

| Source | Kept by |
|---|---|
| `fix` | an accepted option (`plans.apply`, from the page) |
| `plan` | an accepted plan of several fixes |
| `agent` | an MCP agent (`apply_fix`, `apply_plan`, `apply_edit`) |
| `wider` | an accepted wider fix (`context_planner.accept`) |
| `you` | a hand edit with the Edit tool |
| `muse` | a hand edit Muse checked and the person said to keep, in chat or by voice |

An entry holds what it changed, made and removed (with each element's class and name, so a removed one still has a
name), the files, the revision, the clashes it is for (`clashes`: the clash id when the page or agent knows it, and
the pair), the entries it **follows**, what its check found, its warnings, and its state (kept or undone).

**Follows.** The log keeps a lineage: which entries changed or made each element. A hand edit on an element an
earlier entry changed or made follows that entry and carries its clashes. Editing the middle piece an offset made (a
GlobalId the fix created) finds the fix and its clash with no clash selected. `made_from(gid)` walks the other way:
an element and everything made from it, so a clash can be measured again after its fix split the element.

**How it records.** `Journal.record(scene, source, kind)` wraps the code that keeps an edit. Every keep already makes
one IfcOpenShell transaction per file it changes (`edits.kept_files`); when the block ends, the new transactions on
each file (by identity, empty ones dropped), the boxes that changed (they are replaced when they change, never edited
in place) and the elements made or removed become the entry. Nothing is recorded when the block raises or changes
nothing. A wider fix replaces the scene's state with a private copy: its entry keeps the state before and after.

**Undo and redo.** Undo takes the newest kept entry only ("Undo to here" repeats it). Each file's history must end in
exactly that entry's transactions; otherwise an edit was kept outside the log since, and undo refuses. It rolls them
back, takes them off the file's redo list (a trial since would otherwise come back with them), puts the boxes and the
edited files back, and moves the revision forward (caches are keyed on it). Redo commits the same transactions again.
A wider fix is undone by putting its state back. Measured on the run fixture: an offset undone and redone in place,
its eight new pieces gone and back, the revision 1 → 2 → 3.

**Two traps found on the way.**
- A trial move (`IfcScene.translate` there and back) outside a transaction left the file's history pointing at
  placements it had replaced: the next undo raised `UndoSystemError`. Trial moves now run inside `edits.scratch`, a
  transaction that is always undone (`agent._try_move`, `Workspace.verify_move`).
- `file.redo()` cannot be used: every trial ends its transaction and undoes it, which leaves the trial on the file's
  redo list. The log holds its own transactions and commits them itself. Each file keeps 1,024 transactions
  (`scene.HISTORY_SIZE`; IfcOpenShell's default of 64 would drop old kept edits as trials come and go).

## On the page

- **The Edits panel** (`web/src/EditPanel.tsx`, a tab in the right side bar beside Clash, Plan and Chat): the log,
  newest first. Each row says who kept it, when, its clashes, "after E1" when it follows a fix, what its check found and
  any warning with its reviewer; a click frames it. Undo, Redo, Undo to here, and the log as CSV. It comes into its bar,
  behind the tab in front, the first time something is kept.
- **Ctrl+Z** undoes the newest kept edit, **Ctrl+Shift+Z** or **Ctrl+Y** redoes it (not while typing). A fix undone
  leaves its clash open again.
- **Removed elements** (undo of what a fix made, a delete) leave the viewer's batches in place (`patch.removeElements`).

## Icons

The edit tools' icons (`web/src/editIcons.tsx`) act out what each tool does: they play once on hover or focus and loop
gently while their tool is on. Motion follows the brand's rules (`docs/brand-assets.md`): checking plays only while a
check really runs, Keep settles once only after the server kept the edit. Under reduced motion they hold still.
