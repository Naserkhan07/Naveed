# Polarion: what Naveed knows, and how you teach it more

This is the pack for Siemens Polarion ALM — work items, their workflow, and how to
change one without breaking it. It has two halves: knowledge that ships in the
box (`naveed/skills/polarion.py`), and **routines you record yourself** on your
own instance (the part that makes it yours).

> **What "training" means here — read this first.**
>
> **Naveed does not fine-tune a model, and nothing you teach it changes the model's
> weights.** Training here is *record once, distil into a routine, replay with
> parameters*:
>
> 1. you demonstrate the task once, while Naveed watches and records the events;
> 2. the recording is distilled into a parameterised routine — literally JSON on
>    disk under `~/.naveed/skills/learned/`;
> 3. replaying it is deterministic: no model call, no guessing, the same steps
>    every time, with your values substituted in.
>
> Consequences worth knowing up front: a routine is only as good as the one
> demonstration it came from; it replays steps, it does not generalise; and it
> does not get "smarter" the more you use it. What it does get is *more recipes*,
> each one exact and inspectable — you can open the JSON and read every step.
> `--export-training` writes a JSONL dataset of taught tasks, which is there in
> case you ever want to fine-tune something outside this app. Naveed itself never
> trains a model, and never will by accident.

---

## 1. Knowledge that ships in the box

Eleven facts and eight shortcuts, injected into the planner's prompt **only while
Polarion is the app in front** (and trimmed to fit a budget — see §6). The
load-bearing ones:

* A work item has a project-qualified id (`PROJ-1234`), a Type, Title,
  Description, Status, and usually Resolution, Severity, Priority, Assignee and
  custom fields.
* Typing an id into the search box and pressing Enter opens it directly — faster
  than finding it in a table.
* In the modern Web UI, fields are edited **in place** (click, change, save); the
  Description is a rich-text editor, not a textarea. In the classic UI the work
  item is a form with one Edit and one Save for everything.
* **The Status dropdown only offers the transitions the workflow allows from the
  current state.** If the status you want is not in the list, it cannot be set by
  hand either. Naveed is told to *report* that, not hunt for another route.
* **Approved / released work items can be locked**; their fields stay read-only
  until the approval is retracted. A field that refuses typing is locked, not
  broken — expect an honest "it did not keep the new value", and check the
  workflow state.
* Custom fields are project-specific and labelled differently in every
  installation. Naveed looks for one instead of assuming it exists.
* Comments live in the Comments section at the bottom, saved with their own Post
  button.
* Search takes Lucene-style queries (`type:defect AND status:open`).
* Bulk edits: row checkboxes plus the bulk action — with the selection count
  confirmed first.

## 2. The API fast path (optional)

If you give Naveed a base URL and a token, it stops clicking and uses the REST API
for the things an API is better at: reading a work item, searching, and (only with
explicit permission) patching fields.

```ini
# ~/.naveed/config.env   (as an environment variable, prefix every key with NAVEED_)
SKILLS_POLARION_BASE_URL=https://alm.example.com
SKILLS_POLARION_TOKEN=<personal access token>
SKILLS_POLARION_PROJECT=PROJ           # default for bare ids like 1042
SKILLS_ALLOW_API=true                  # reading (on by default)
SKILLS_ALLOW_API_WRITES=false          # leave this off until you mean it
```

Rules that are enforced, not documented-and-hoped:

* **No configuration, no API tools.** With no base URL, the tools are simply not
  offered to the model, and the pack says to drive the UI instead.
* **Reads need `ALLOW_API`; writes need `ALLOW_API_WRITES`.** A read-only setup
  still gets `polarion_get_work_item` and `polarion_search` and does not get
  `polarion_update_work_item`.
* **A writing tool goes through the safety guard and asks for confirmation**,
  every time, in the same way a `edit_field` would. An unconfirmed write is
  refused by name ("you did not confirm it").
* **A qualified id names its own project.** `OPS-7` goes to project `OPS` even if
  `SKILLS_POLARION_PROJECT` says something else; the default applies only to bare
  ids like `1042`. (This precedence used to be backwards, which addressed the
  wrong project — the one failure an ALM tool must never have.)
* **Errors are sentences, not tracebacks**: `401`/`403` name the token, `404`
  names the endpoint that was missed, an unreachable server names the server.
* **A missing comments endpoint is not guessed.** If your server has no comments
  route configured, the tool is not advertised and Naveed is told to post the
  comment in the UI. If yours does, map it:

  ```ini
  # JSON, or the shorter key:value form
  SKILLS_POLARION_ENDPOINTS={"comments": "/polarion/rest/v1/projects/{project}/workitems/{id}/comments"}
  SKILLS_POLARION_ENDPOINTS=comments:/polarion/rest/v1/projects/{project}/workitems/{id}/comments
  ```

  **Not guessed, and not half-applied either**: a malformed value used to become
  the endpoint `{"comments": "/polarion…` and 404 forever. The config loader now
  understands JSON for these mappings (and the tests load a real config file to
  prove the documented line works).

## 3. Editing a work item

This is `docs/EDITING.md` applied to Polarion, and the pack's guidance is specific:

* `read_field` first, then `edit_field` with `operation="replace"` for a surgical
  change. `set` is for when the whole value must go.
* To add to a Description, use `append` — never `set`, which deletes the original.
* The Description is rich text: a targeted edit keeps the user's formatting, a
  full replacement loses it. The safe path also happens to be the polite one.
* `edit_field` verifies its work by reading the field back, and says so when the
  field refused the change.

## 4. Teaching it *your* Polarion

The shipped facts get Naveed oriented. Your instance has its own project, its own
statuses, its own custom fields, its own idea of what "create a release note" means.
That is what recording is for.

```bash
# 1. watch me do it once (Ctrl+Alt+T starts and stops the recording)
python3 -m naveed --teach release-my-item --teach-seconds 45 \
    --describe "verify a fix and move the item to Verified"

# you do the task by hand, in Polarion, while Naveed records events
```

What happens to the recording:

* every click, keystroke, chord and typed value is recorded as an event;
* the events are **distilled**: consecutive typing folds into one step, a
  double-click folds into a double-click (not two clicks), and—if OCR is
  available—a click is anchored to the label nearest to it, so the routine still
  finds its field when the window moves;
* **values that look like data become parameters** automatically:
  `PROJ-1042` → `{work_item_id}`, `me@example.com` → `{email}`,
  `2026-01-31` → `{date}`. Short fixed words that carry meaning ("Verified") stay
  literal, because turning those into parameters would change the task;
* the result is written to `~/.naveed/skills/learned/release-my-item.json`.

Then it replays, with no model in the loop:

```bash
python3 -m naveed --recipes                      # what do I know how to do?
python3 -m naveed --run-recipe release-my-item \
    --arg work_item_id=PROJ-1042 --dry-run       # show the steps, change nothing
python3 -m naveed --run-recipe release-my-item --arg work_item_id=PROJ-1042
```

Details that make replay trustworthy:

* a missing argument becomes a **question**, not a guess;
* an unknown routine name becomes a question too ("I do not know a routine called …");
* a routine that calls another routine is expanded, up to three levels deep;
* **each replayed step still goes through the safety guard**, including the
  confirmation for writes. A recorded routine is shorthand, not a permission —
  otherwise recording would be a way to launder an action past the guard;
* routines live in a plain JSON directory, so they can be copied to another
  machine, edited by hand, or deleted.

## 5. Where the pieces live

| Path | What it is |
| --- | --- |
| `naveed/skills/polarion.py` | the shipped pack: facts, shortcuts, recipes, REST tools |
| `naveed/skills/recorder.py` | event capture, `distill_recipe`, `suggest_parameters` |
| `naveed/skills/base.py` | `Skill`, `Recipe`, `SkillStore`, prompt rendering, matching |
| `~/.naveed/skills/learned/*.json` | your routines — read them, they are meant to be readable |
| `naveed/skills/polarion_training.jsonl` | only if you asked for `--export-training` |

## 6. How the knowledge reaches the model

It does not get dumped in. On the first step of a task, and whenever the app in
front changes to something that matches a pack, a block is injected:

```
=== YOU ARE WORKING IN POLARION ALM (it is the app in front) ===
FACTS:      … trimmed first when space runs short
SHORTCUTS   hotkeys, so the model reaches for a hotkey instead of a menu
WATCH OUT   the traps: workflow-locked statuses, locked fields, rich-text loss
EDITING THIS APP   read_field → edit_field, and which operation to prefer
DIRECT TOOLS       only the ones that are configured right now
KNOWN ROUTINES     your recorded routines, by name, with their argument names
```

The ordering is the point, and it was a bug once: the FACTS section alone used to
fill the budget and silently push the shortcuts and routines off the end, which is
exactly the half that makes Naveed *competent* in Polarion rather than merely
informed about it. Now facts are capped at a share of the budget, each section has
a ceiling, and anything that is cut says so (`…(more notes omitted)`). If you want
more room, raise it:

```ini
SKILLS_MAX_CONTEXT_CHARS=5000   # characters of pack knowledge per prompt
SKILLS_INJECT=true              # set false to plan without any pack knowledge
```

Nothing from a pack is injected when the app in front does not match it — a
Polarion tip in a text editor is just noise the model has to read past.
