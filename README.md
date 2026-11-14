# magpie-dispatch

A Claude Code skill for multi-model dispatch through [Magpie](https://magpie.im/). The supervisor (the model in the current session) inspects routing groups, splits the task, assigns work by capability and thinking effort, then reviews the result and sends defective work back.

Three ways to dispatch:

| Target | Method | What it can do |
| --- | --- | --- |
| Magpie routing group | Desktop sub-session | Read/write files, run commands, visible in the sidebar, can be sent back for rework |
| Any Magpie model | `crew ask` | One-shot plain text (copy, summaries, translation, second opinions) |
| Any Magpie model | `crew run` | Claude Code CLI: reads/writes files and runs commands |

Models that are not in a routing group (for example `gemini-2/gemini-3.1-pro` or `codex/gpt-6.1-sol`) work directly. No need to create a group first.

## Requirements

- macOS (the script defaults to the CLI at `/Applications/magpie.app`; override with `MAGPIE_BIN`)
- Magpie installed and running; gateway defaults to `http://127.0.0.1:3425/v1`
- Python 3.9+ (standard library only)
- Claude Code desktop app (for sub-sessions) or the `claude` CLI (for `crew run`)
- Credentials in `~/AI/API/magpie.env` (`MAGPIE_BASE_URL`, `MAGPIE_API_KEY`) or the same environment variables

## Install

For an agent-driven, step-by-step setup (Magpie download, providers, gateway check, then this skill), see [INSTALL.md](INSTALL.md).

```bash
git clone https://github.com/sunxiang6789/magpie-dispatch.git ~/.claude/skills/magpie-dispatch
```

Calibrate the desktop model ids once after installing (the skill prompts you when needed):

```bash
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py status
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py groups
```

If the "dispatch model" column shows `auto/...` instead of `mythos-magpie-...`, follow the calibration steps in [SKILL.md](SKILL.md).

## Common commands

```bash
CREW=~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py

python3 $CREW status                 # gateway, CLI, picker, judge config
python3 $CREW groups                 # routing groups + dispatch ids + effort levels
python3 $CREW models --grep gemini   # every available model, grouped or not
python3 $CREW judge --task "task description" --current-model "<self.model>"

python3 $CREW ask gemini-2/gemini-3.1-pro --prompt "Write 3 taglines"
python3 $CREW run gemini-2/gemini-3.1-pro --cwd ./project --prompt "Implement and test"

python3 $CREW group set auto/hy3 models=workbuddy/hy3,workbuddy-ai/hy3 routing=order
```

## Configuration

Copy the example and adjust it for your machine:

```bash
cp config.example.json config.json
```

`config.json` holds local calibration data and is listed in `.gitignore`. Do not commit it.

Main fields:

- `judge_model` / `judge_effort`: judge model and effort level
- `max_dispatch`: maximum number of sessions per batch
- `app_model_ids` / `app_model_order`: mapping between desktop internal model ids and routing group order

## Notes

- Quota is never checked: Magpie switches to a usable account automatically.
- The desktop `start_session` API only accepts `mythos-magpie-...`. Passing `auto/...` or `gemini-2/...` is silently ignored. Use `crew ask` or `crew run` for direct models.
- `crew run` defaults to `--permission-mode acceptEdits`. Grant more only explicitly, and at your own risk.
- The repository contains no keys. Credentials are read from local environment variables or `~/AI/API/magpie.env`.
