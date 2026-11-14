---
name: magpie-dispatch
description: Multi-model dispatch through Magpie. Inspect available routing groups and models, let the supervisor (the current session's model) split the task, and assign work to sessions by capability and thinking effort; models outside routing groups are usable too (Gemini etc. via crew ask for text, crew run for CLI work). The supervisor reviews deliverables and sends defective work back. Can also edit routing groups. Use when the user says "dispatch", "multi-model", "assign this to models", "supervisor review", "edit routing group", or "what models are available".
---

# Magpie multi-model dispatch

The supervisor is **the model of the current session**. It inspects groups, splits the task, dispatches, reviews, and sends work back. Sub-tasks should run in new sessions; the supervisor does not write their code, but must inspect the actual artifacts during review.

**Two kinds of targets, three dispatch methods, all directly usable:**

- **Routing group** (`auto/...`, `group/...`) → desktop sub-session: reads/writes files, runs commands, appears in the sidebar. Best for implementation, research, review.
- **Direct model** (a concrete model id such as `gemini-2/...`, `codex/...`, `trae-cn/...`):
  - `crew ask`: one-shot plain text, no file access. Best for copy, summaries, translation, second opinions.
  - `crew run`: runs through the Claude Code CLI and can read/write files and run commands. Best when a non-group model needs to do real work.
- Direct models **do not need a routing group in Magpie first**; if `crew models` lists it, it is usable.

**Quota is never checked.** Magpie switches to a usable account automatically. Only query which routing groups exist, which models are available, and which thinking levels they support.

## Hard rule: identify the deliverable type first

- Code, documents, analysis, review → text models in routing groups.
- **Posters, covers, illustrations, logos, image edits, videos, voice-over, music → media generation. Never let a text model substitute an HTML/CSS/SVG screenshot.** Follow the user's global media rules: image generation through Codex CLI first, then gpt-image or Dreamina on failure. Image models inside Magpie (e.g. `gemini-image`, `MiniMax-Image`) are only a fallback.
- When dispatching a media task to a session, the brief must say "call the image generation tool; do not substitute a web page or SVG" and give an exact output path. The supervisor must **look at the resulting image** and check for wrong characters, garbled text, or truncation; do not trust the session's report alone.
- Before accepting any task, ask: is the user asking for an image or a video? If so, go straight to the media workflow, not a front-end group.

Script: `~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py` (referred to below as `crew`; invoke it as `python3` plus the full path). Read-only commands change nothing.

## 1. Every round: inspect targets

```bash
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py status
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py groups
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py models --grep <keyword>
```

- `groups`: routing groups; these can back a session.
- `models`: every model Magpie can call directly, including direct models that are in no routing group. `--groups-only` shows groups only; `--grep gemini` filters by name.
- A direct model is usable as soon as it appears in `models`; no group required.

In the `groups` table:

- **Group**: `auto/...` is an auto-discovered routing group; a custom group is `group/<id>`.
- **Dispatch model**: pass this as the session `model` argument. The Claude desktop app uses internal ids (`mythos-magpie-...`); without calibration it shows the `auto/...` picker id.
- **Context / thinking levels**: use these to judge whether the group fits the task.
- Member rows: which vendor models the group may actually use.

Add `--json` for structured data. Inspect one group with `crew show <group-id>`. Check a group's id in the model menu with `crew picker --grep <keyword>`.

**If the dispatch model is `auto/...` rather than `mythos-...`:** the local app ids are not calibrated. Call `mcp__ccd_session_mgmt__set_session_model` on an idle session with a deliberately nonexistent model; the error lists every `mythos-magpie-*` in model-list order. Pass the numeric parts, comma-separated and in order, to `crew app-models set 7607648695,2663368781,...`. After that `crew groups` maps them automatically. `status` warns when the model list order changes; recalibrate once.

Also read the current session's model and effort: `mcp__ccd_session_mgmt__get_session {"session_id": "self"}`.

**Desktop sub-session limitation:** `start_session` / `set_session_model` accept only `mythos-magpie-...`. Passing `gemini-2/...` or `auto/...` is **silently ignored** (it falls back to the current model). This is a whitelist in the desktop session API, not a Magpie limitation. Use `crew ask` (text) or `crew run` (CLI, with file access) for direct models. Do not infer that a desktop sub-session supports an id just because `crew picker` lists it.

## 2. Is the supervisor good enough? (optional judge)

For complex tasks, work spanning several modules, or when the user asks "should we use a stronger supervisor", ask the judge model. **Do not call it for every small task**; it is an extra model request:

```bash
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py judge \
  --task "one or two sentences on the task, its size, and the hard part" \
  --current-model "<self.model>"
```

Returns JSON: `verdict` (stay/switch), `supervisor_group`, `split` (recommended breakdown). The judge returns group ids; resolve them to app model ids with `groups` before dispatching.
The judge defaults to `auto/glm-5.3-flash`; change it with `crew config set judge_model auto/...`.

- `stay`: the current session stays supervisor.
- `switch`: the current session **cannot change its own model** (the tool refuses). Open a **new supervisor session** (below), put the full handoff in the brief, then stop working here and tell the user "supervisor handed to group X; continuing there".
- If no new session can start: tell the user which group to pick in the model menu and wait.

## 3. Split the task, choose targets and effort

Use `references/routing-playbook.md` to classify the task. First decide whether the deliverable is code/text or media: media tasks go straight to the media workflow, never to a text group. Rules for text tasks:

- 2–4 sub-tasks, independent, each with a verifiable deliverable.
- For each sub-task state: **target (group or direct model) + method (session / API / CLI) + thinking level + whether it writes files + acceptance criteria**.
- File writes or commands → a routing-group session, or `crew run` for a direct model. `crew ask` is text only; the supervisor writes its output to disk.
- One writer per file set; review/acceptance tasks go to read-only sessions.
- The effort level must be supported by the target (see the `groups` thinking-level column); otherwise use the nearest level.
- Do not send everything to a flagship: mechanical work to flash groups, hard problems to a flagship at xhigh.
- Models outside routing groups (Gemini, for example) are addressed by model id directly; no group needed. Confirm it with `models --grep` first.

## 4. Dispatch

### Routing group → open a sub-session

State in one message who is dispatched, to do what, in which group, at which effort level. Then call:

```
mcp__ccd_session__start_session
  initiation: "user_asked"
  context: "fresh"
  model: "<dispatch model from the groups table: mythos-magpie-... or picker id>"
  effort: "high"            # minimal|low|medium|high|xhigh|max
  name: "<short name>"
  title: "<sub-task title>"
  use_worktree: true        # own worktree for code; false is fine for read-only review
  prompt: "<self-contained brief>"
  background: "<project context, constraints, verification commands, report format, >=80 chars>"
```

- At most 4 sessions per batch.
- The brief must be self-contained: goal, files involved, constraints, definition of done, how to verify, report format (what was done / files changed / verification results / unfinished / risks).
- Do not let sub-sessions commit or push by default, unless the user asks or the task needs a branch.
- **Recommended dispatch order**: start with prompt "Stand by: do nothing until I send the full brief", `model` = the app model from `groups`, `effort` = the chosen level → check `model`/`effort` with `get_session` → if wrong, fix with `set_session_model` to the target `mythos-magpie-...` → then send the full brief with `mcp__ccd_session_mgmt__send_message`. This prevents half the work being done on the wrong model.
- Measured locally: `start_session` **silently ignores** Magpie's `auto/...`; always verify. `effort` applies normally.
- If `start_session` rejects the model outright: the error lists valid ids; map them with `crew app-models` to a mythos id; if that still fails, ask the user to pick manually.

To change an existing session's effort: `mcp__ccd_session_mgmt__set_session_effort` (refused for the current session itself, by design).

### Direct model → `crew ask` (no session)

```bash
# Basic: a routing-group id or a concrete model id both work
crew ask gemini-2/gemini-3.1-pro --prompt "Write 3 launch taglines, max 40 characters each"
crew ask auto/glm-5.3-flash --prompt "Rewrite the paragraph below in a more conversational tone"
# Attach source files (repeatable); contents are appended to the prompt
crew ask gemini-2/gemini-3.1-pro --prompt "Write copy from the brief" --file brief.md --file notes.txt
# Set effort, cap length, request JSON metadata
crew ask gemini-2/gemini-3.1-pro --prompt "..." --effort high --max-tokens 1200 --json
```

- Returns plain text on stdout; the prompt may also come from stdin.
- One request, no tools, no file access. Multi-turn work or file edits must use a session or `crew run`.
- The supervisor writes the result to disk and reviews it per section 5; "it was a strong model" is not a reason to pass it.
- For batches, run them one by one and check each response for emptiness or errors (nonzero exit code).
- A direct model neither needs to nor should appear in `groups`; if `crew models` lists it, it works.

### Direct model → `crew run` (Claude Code CLI, with tools)

```bash
crew run gemini-2/gemini-3.1-pro --cwd <project-dir> \
  --prompt "Implement the feature from the brief and run the tests" --max-turns 40 --timeout 900
# Print the command without running it
crew run gemini-2/gemini-3.1-pro --cwd <dir> --prompt "..." --dry-run
# Raw result, including usage
crew run gemini-2/gemini-3.1-pro --cwd <dir> --prompt "..." --json
```

- This is `claude -p --model <id>`; the CLI reads/writes files and runs commands itself. It **does not appear in the desktop sidebar**; its result returns synchronously to the supervisor.
- Defaults to `--permission-mode acceptEdits`. If Bash or another action needs approval, tell the user, or use `--permission-mode bypassPermissions` with their consent (risky; only inside that project).
- Blocking: give long tasks a large `--timeout`, or start them with Bash `run_in_background` instead of waiting in the same turn.
- One clear brief per run. The CLI sends no side-session notification; the supervisor must read the files, inspect the diff, and run the tests.
- If the first run in a directory hangs, ask the user to `cd` there and run `claude` once to accept the folder, or use `bypassPermissions` temporarily.

## 5. Review (mandatory)

- Wait for side-session notifications; **do not poll**.
- Do not trust the report: read which files changed, inspect the diff, run tests/builds. For a session in its own worktree, inspect its branch (`git log` / `git diff <base>...<branch>`).
- Review `crew ask` output too: read it in full, check facts, typos, and invented details; rerun with a better prompt or another model instead of passing it.
- Review `crew run` like a sub-session: read the changed files, inspect the diff, run the tests. Its "done" is not evidence.
- Pass → summarize the delivery. Fail → **send it back**:
  - Use SendMessage to that session with concrete defects: file:line, failing output, expected behavior; ask for a fix and another report.
  - If the session has ended, open a "rework" session in the same group with the original brief plus the defect list.
  - At most 2 rounds; if it still fails, take over as supervisor or let the user decide.
- Merging branches, pushing, and publishing always require the user's approval first.

## 6. Edit routing groups

When the user says "edit the routing group / create a group / switch this group to X", use the script directly; no need to open the Magpie UI. Run `--dry-run` first, then execute after the user confirms.

```bash
# Create
crew group add quick-jobs models=qoder/qfmodel,qoder-cn/qfmodel,zcode/GLM-5.3-Flash routing=smart stays=off
# Replace / append / remove members
crew group set auto/hy3 models=workbuddy/hy3,workbuddy-ai/hy3 routing=order
crew group set auto/gmodel models+=trae-cn/glm-5.3-max levels=low,medium,high,xhigh,max
crew group set auto/hy3 models-=workbuddy-ai/hy3
# Pin to one member / copy / template / delete / restore
crew group pick auto/hy3 workbuddy/hy3
crew group copy auto/gmodel writing
crew group template smart main
crew group rm writing --yes
crew group restore auto-mmodel   # restore a deleted auto group
```

After any change:

1. Confirm with `crew groups`.
2. Confirm the dispatch model is `mythos-...`; changing groups may reorder the model list, so recalibrate `app-models` if `status` warns.
3. Confirm the new group appears in Claude Code's model list with `crew picker --grep <new-group>`; it needs a dispatch model before it can be used.
4. If it is missing, tell the user: restart Magpie to resync the model list, or select the model again in the menu, then dispatch. Never force-dispatch a group that is not in the picker.

First use: run `status` + `groups`, explain the group list and the default judge model, then ask one question: whether to adjust routing groups. Do not change anything unless the user asks.

## Output habits

- Before dispatch: a small table (sub-task / target: group or model / method: session, API, or CLI / effort / deliverable / write scope).
- After review: pass or send back, with evidence (command + result). Never just say "done".
- Never report quota, accounts, or key details to the user.
