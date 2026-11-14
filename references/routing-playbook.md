# Routing and thinking-effort playbook

Use the live output of `crew groups` and `crew models` as the source of truth. Group and model names below are examples from this machine only.

There are two kinds of targets: **routing groups** (open a sub-session; file access) and **direct models** (`crew ask` for text, `crew run` for tools; no group needed).

## Choosing a dispatch target

**Pick the method first:** file edits, commands, multi-round debugging → a routing-group session (visible in the sidebar, can be sent back) or a direct model via `crew run` (CLI, not in the sidebar). A single piece of text (copy, summary, translation, review notes) → `crew ask`.

For routing groups, look at four fields:

1. **Members**: which vendors/models back the group. Two or three flagship members suit hard problems; flash-only groups suit routine work.
2. **Context**: 1M is good for whole repositories and long documents; do not stuff huge material into a 192k group.
3. **Thinking levels**: do not force a hard problem onto a group without xhigh/max; more levels means more flexibility.
4. **Input modalities**: to read screenshots or design files, pick a group with `image`.

For direct models, look at three fields in `crew models`: `ctx`, `reasoning_levels`, and `thinking` in the name. A model with no routing group and no route configured in Magpie is usable via `crew ask` as long as it appears in `models`.

## Task type → group traits → effort

| Task | Group traits | Thinking level |
| --- | --- | --- |
| Posters, covers, illustrations, logos, image edits | **Not a text group**: Codex CLI image generation (default) → gpt-image / Dreamina on failure; Magpie image models as fallback | — |
| Video, voice-over, music | Dreamina (video/audio) or the user's chosen media tool | — |
| Architecture, hard bugs, security review, key decisions | Flagship reasoning group (several top models as members) | xhigh / max |
| Multi-file implementation, refactoring | Strong general group | high |
| Front-end/visual work, screenshot or design reproduction | Strong group with image input | high |
| Whole-repo or long-document scan, research organization | 1M-context group | medium / high |
| Mechanical work: renames, formatting, boilerplate, bulk replacement | Flash group | minimal / low |
| Independent review, cross-checking | A group from a **different vendor** than the implementer | high / xhigh |
| Copy, documentation, summaries | Routing group (Kimi / GLM family) or a direct Gemini / GPT model | medium / high |
| Data analysis, long tables | Long-context group with strong reasoning | high |

Direct-model examples (check `crew models` for availability): `gemini-2/gemini-3.1-pro`, `gemini-2/gemini-3.8-flash`, `codex/gpt-6.1-sol`, `trae-cn/kimi-k3.1-pro`, `qoder-cn/gmodel`. They are in no routing group and need none.

Typical groups on this machine (they change; reference only):

- Flagship: `auto/kmodel_latest` (Kimi K3.1 Pro), `auto/gmodel` (GLM-5.3), `auto/deepseek-v4-pro`, `auto/qmodel_latest` (Qwen4-Max).
- General: `auto/glm-5.2`, `auto/mimo-v2.6-pro`, `auto/qmodel_38max`.
- Fast: `auto/qfmodel`, `auto/glm-5.3-flash`, `auto/deepseek-v4.1-flash`, `auto/minimax-m3.1-flash`.
- Long-context small models / special: `auto/mercury-3`, `auto/minimax-m3`, `auto/hy4free`, `auto/hy3`.

## Media tasks (posters/covers/illustrations/video/voice-over)

These are not routing-group work. Never hand them to a text model to render HTML and screenshot it. Default order:

1. **Images**: the Codex CLI image-generation tool (the exact command is in the user's global rules), reference images via `-i`, output to the target directory; only on failure/timeout fall back to the gpt-image skill (built-in browser) or Dreamina.
2. **Video/audio**: Dreamina first; try something else on failure.
3. Magpie image models (`gemini-2/gemini-image`, `minimax-code/MiniMax-Image`, `agens-free/agnes-image-*`) are fallback only, never the default.

When dispatching a media task to a sub-session, the brief must state:

- Call the image-generation tool; **never** substitute an HTML/CSS/SVG screenshot;
- Output path, aspect ratio, size;
- The exact text to render, character by character, with "no typos, missing strokes, garbled characters, or English substitutions";
- Read the generated image back and check it yourself.

Supervisor review: use Read to look at the image; check the text, composition, and whether it invents logos, QR codes, or real-person portraits. If it does not match, send it back for regeneration. "It rendered" is not a pass.

## Direct models (crew ask / crew run)

Models outside routing groups have two uses:

**`crew ask` — plain text, one-shot.** Good for copy, editing, translation, summaries, research organization, finding defects, second opinions.

```bash
crew models --grep gemini                  # confirm the model is listed
crew ask gemini-2/gemini-3.1-pro --prompt "Write 3 launch taglines" --max-tokens 600
crew ask codex/gpt-6.1-sol --prompt "Review the implementation below" --file app.js --effort high
```

**`crew run` — through the Claude Code CLI; reads/writes files and runs commands.** Good for implementation, refactoring, and debugging.

```bash
crew run gemini-2/gemini-3.1-pro --cwd <project-dir> --prompt "Implement the brief and run the tests" \
  --max-turns 40 --timeout 900
```

- `run` defaults to `acceptEdits`; command execution may be blocked, so read the CLI output instead of defaulting to `bypassPermissions`.
- `run` blocks until done: run long tasks in the background or give a large timeout. It is not in the desktop sidebar, so the supervisor reviews it directly.
- `ask` has no tools; pass source material with `--file` and write its output to disk yourself.
- Run the same prompt through several models and keep the better result, but do not merge multiple answers without judgment.
- If a model id carries a `[1m]` suffix, keep it in `ask` / `run` too; when unsure, run with `--json` and check the returned `model`.

## Effort rules

- `none` / `minimal`: purely mechanical, no judgment.
- `low`: simple single-file edits, lookups.
- `medium`: routine implementation with a clear spec.
- `high`: multiple files, debugging, trade-offs.
- `xhigh`: architecture, hard problems, final review.
- `max`: critical work and the group supports it; do not max out by default.

If a group does not support a level, use the nearest one; do not assume it accepts it.

## Splitting and parallelism

- At most 4 sessions per batch; 2–3 is usually best.
- Every sub-task must be independently reviewable; dependent tasks run in sequence, not at the same time.
- One writer per file set; review/acceptance sessions are read-only.
- Use different vendors for implementation and review when possible, to avoid shared blind spots.
- For long tasks, start with a small task that produces a result in about 5 minutes before opening up the big one.

## Common mistakes

- Sending everything to a flagship: slow, expensive, and they step on each other's files.
- Giving implementation and acceptance to the same session: it grades its own work.
- The supervisor writing and reviewing the same file: loses perspective and breaks the one-writer rule.
- Passing a sub-session's report without reading it: run the tests and inspect the diff.
- Forcing a group that is not in the picker into `start_session`: confirm with `crew picker --grep` first.
- Passing a direct model id such as `gemini-2/...` to `start_session`: it is silently ignored and falls back to the current model. Use `crew ask` or `crew run`.
- Passing direct-model text without reading it: it does not run tests; the supervisor must check facts and typos.
- Skipping review for `crew run`: the CLI's "done" is just its own claim; inspect files, diff, and tests yourself.
