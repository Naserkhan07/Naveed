# Safety

Naveed drives your real mouse and keyboard on your real desktop. The guard in
`naveed/control/safety.py` sits between *decided* and *performed*: nothing reaches
your machine without passing it, and no other module may call the OS directly.

```python
verdict = safety.inspect(action, raw_text)
if verdict.blocked:            → tell the user why, skip the action, never confirmable
elif verdict.needs_confirmation: → ask (spoken + panel), wait, deny on timeout
else:                          → perform it
```

The shape of this guard, and the credential rule in particular, is ported from
[jarmen423/voice-computer-use-agent](https://github.com/jarmen423/voice-computer-use-agent)
(`voiceuse/safety.py`).

## Three risk levels

| Level | Meaning | What happens |
|---|---|---|
| `SAFE` | Reading, opening, navigating, typing ordinary text | Runs immediately. |
| `DESTRUCTIVE` | Hard to undo: delete, overwrite, close without saving, purchase, send, shutdown, sign out | Confirmation required, `12s` to answer, **denies on timeout**. |
| `FORBIDDEN` | Unrecoverable or catastrophic | Refused. Never runs, and cannot be confirmed into running. |

## Hard blocks (refused, full stop)

Matched case-insensitively against the action's text, command, URL and label:

```
rm -rf /            rm -rf /*            mkfs.                dd of=/dev/
:(){:|:&};:         fork bomb patterns   format C:            diskpart
reg delete HKLM     shutdown -h now (as a shell command)       > /dev/sda
```

A refusal is reported to the user with the reason ("that would wipe the disk"),
spoken aloud, and recorded in the safety history. The agent is told to stop rather
than retry a different spelling.

## Secrets are never typed

The rule that matters most in practice. Naveed refuses to type:

* a password / passphrase / PIN / 2FA or one-time code / CVV / card number /
  access token / private key — when it can see the *value*, or when the surrounding
  request says that is what it is;
* anything into a field labelled as a credential field when the value is a
  secret-shaped string.

It does **not** refuse to work in a sign-in window in general. That distinction
was a real bug: an early version refused all typing whenever the window looked
like a login screen, which broke the much more common case of "type my email
address, then let me type the password" and failed its own tests. The corrected
rule is:

* refuse when → the value looks like a secret (a long random token, a
  `sk-…`-style key, a card number), **or** the raw request / note / field label
  contains explicit password intent, **or** a bare 4–8 digit value is being typed
  into a field that is *labelled* as a credential field;
* allow otherwise — including typing an email or username into a login form.

The refusal is phrased so a human can act on it:

```
I will not type secrets — please type this one yourself.
```

## Confirmation

When a `DESTRUCTIVE` action needs approval, Naveed:

1. pauses the task (`TaskStatus.WAITING`);
2. says it out loud and shows it on the panel with **Allow / Deny**;
3. waits up to 12 seconds;
4. **denies** if nobody answers, and tells the model the action was declined so it
   can plan something else instead of retrying.

Every verdict lands in `safety.history` (the last 200), which the panel's log and
`--check` can display. That history is also how the agent learns not to repeat a
blocked action.

## Editing, tools and recorded routines

Three newer ways to change things are held to the same rule as everything else —
none of them is a path around the guard:

* **`edit_field` is a write.** `read_field`, `find` and `select_all` are `SAFE`;
  `edit_field` (and `paste`, `clear`, `save`, `undo`) are writes, and every action
  kind that writes text is listed in `WRITE_KINDS`. The secret rule is applied to
  the exact string about to be typed or pasted, so a long random value cannot ride
  into a field as an "edit".
* **A knowledge pack's tool that writes needs confirmation.** `skill_tool` calls
  go through the guard with the tool's own `writes` flag: reading a Polarion work
  item is `SAFE`, changing one is `DESTRUCTIVE` and asks first. A tool name the
  guard does not recognise is assumed to write, never the other way round.
  (An amusing bug this caught: destructive-keyword matching used to scan the
  action's *kind*, and `skill_tool` contains `kill` — so every pack call asked for
  confirmation. The scan now covers params, note, context and raw request only.)
* **A replayed routine is checked step by step.** `recipe` expands into the
  actions it was taught, and each one is inspected and confirmed exactly as if the
  model had proposed it. Otherwise recording a demonstration would be a way to
  launder an action past the guard.
* **An unconfirmed write is refused by name** — "you did not confirm it" — rather
  than performed quietly or retried until the user clicks yes.

## The browser front end

`python -m naveed --serve` (and the panel's *Show mascot* in reverse) exposes the
same bot over HTTP. It is **the same code path**: a task submitted to
`POST /api/task` goes to the same `AgentBridge`, the same planner and the same
`SafetyGuard` as a task typed into the panel, so every rule above applies
unchanged. Nothing about the web layer can perform an action the desktop UI could
not.

What the API can and cannot do:

| Endpoint | Reach |
|---|---|
| `POST /api/task`, `/api/answer`, `/api/cancel` | Queue, answer and stop tasks — i.e. exactly what clicking the mascot does, with the guard still in the way. |
| `POST /api/recipe` | Run a *taught* routine. Recipes are recorded keystrokes, and they still go through `SafetyGuard.inspect`; a recorded step that deletes something is confirmed just like a model's step. |
| `GET /api/screen` | The newest capture — the same frame the model was shown, on the same machine. Nothing is uploaded by this endpoint. |
| `POST /api/overlay`, `/api/quit` | Start the mascot, stop the server. |
| — | There is no endpoint that reads your files, runs a shell or types your secrets. `shell` stays off unless `SAFETY_ALLOW_SHELL=true`, wherever the task came from. |

Who can reach it is part of the safety story, and it is deliberately narrow:

* the default bind is `127.0.0.1` — loopback, so the page is not on your network;
* `--host 0.0.0.0` requires the token printed at startup on every request,
  compared with `hmac.compare_digest`;
* `--no-token` is for a container port or a tunnel that authenticates upstream, and
  it says what it is doing in `--check` and at startup;
* secrets are refused when *typing* them (above), so a page that someone else
  loaded still cannot be used to type your password into a field.

If you would rather not have the surface at all, `python -m naveed --no-serve`
starts the mascot and never opens a socket.

## Shell actions

Shell execution is **off by default** (`SAFETY_ALLOW_SHELL=false`) and off in the
planner's instructions — the model is told never to emit shell commands. When the
setting is enabled, commands still pass the hard-block table and the allowlist.
`--allow-shell` switches it on for one run.

## Budgets and loop protection

| Limit | Default | Behaviour on hitting it |
|---|---|---|
| `AGENT_MAX_STEPS` | 18 | Stop, report what was achieved, ask for guidance. |
| `AGENT_MAX_TASK_SECONDS` | 240 | Stop, same. |
| `no_change_streak` | 3 | The screen did not change after three consecutive actions → stop and tell the user instead of clicking forever. |

The planner is also instructed never to repeat an action that produced no change.

## Dry run

`--dry-run`, or the panel's checkbox, makes `InputController` a no-op: Naveed
plans, prints exactly what it *would* click and type, and performs nothing. Useful
with an unfamiliar model before letting it near your desktop.

## What Naveed deliberately does not do

* No background shell, no service installation, no autostart unless you ask.
* No network calls except the model endpoint you configured — plus, only if you
  set it up yourself, the Polarion REST API at the base URL you gave it (see
  [POLARION.md](POLARION.md)). With no base URL configured, no such call is made
  or even offered.
* No screen content is stored anywhere you did not configure (and the default
  `~/.naveed/screenshots` prunes itself to the newest 100 frames).
* No typing into password fields, even with confirmation.
