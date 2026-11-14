# Install guide (for AI agents)

This document is written for an automated agent that has shell access to a macOS machine. Follow the steps in order. **Stop and ask the user** at any step marked USER ACTION; do not guess credentials, do not click through sign-in flows, and never print tokens.

Goal: install Magpie, verify its local gateway, then optionally install the `magpie-dispatch` skill for Claude Code.

---

## 0. Preflight

Run:

```bash
sw_vers -productVersion          # must be 12.0 or newer
python3 --version                # must be 3.9 or newer
command -v git && command -v curl
```

If macOS is older than 12, stop and tell the user. Magpie is a macOS app.

Check whether Magpie is already installed:

```bash
ls -d /Applications/magpie.app 2>/dev/null && /Applications/magpie.app/Contents/MacOS/magpie --version
```

If the app exists, skip to step 2.

---

## 1. Install Magpie — USER ACTION

Magpie is distributed as a signed macOS app from its official site.

**USER ACTION:** ask the user to:

1. Open <https://magpie.im/> in a browser.
2. Download the macOS build from the download button on that page.
3. Open the downloaded file and drag **magpie** into `/Applications`.
4. Launch it once and finish its onboarding.

Do not invent a direct `.dmg` URL; if the site layout changes, use the download control on the homepage. Do not use third-party mirrors.

Verify after the user confirms:

```bash
ls -d /Applications/magpie.app
/Applications/magpie.app/Contents/MacOS/magpie --help | head -5
```

Expected: the app exists and the CLI prints its command list.

---

## 2. Connect model providers — USER ACTION

Magpie needs at least one provider/account before it can serve models.

**USER ACTION:** in the Magpie app, sign in to the providers the user wants (the app walks through this). This step requires the user's accounts and must not be automated.

Verify from the shell:

```bash
curl -s --max-time 10 http://127.0.0.1:3425/v1/models | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',[])), 'models')"
```

Expected: `N models` with N > 0. If the connection is refused, the app is not running or its gateway is off; ask the user to open Magpie.

List the routing groups Magpie exposes:

```bash
/Applications/magpie.app/Contents/MacOS/magpie groups
```

Expected: a table of `auto/...` groups (or custom `group/...` groups).

---

## 3. Install this skill (optional)

The skill is optional. Magpie works with any client on its own; install this only if the user wants supervisor-based dispatch inside Claude Code.

```bash
git clone https://github.com/sunxiang6789/magpie-dispatch.git ~/.claude/skills/magpie-dispatch
```

Create the local config from the example:

```bash
cd ~/.claude/skills/magpie-dispatch
cp config.example.json config.json
```

`config.json` is machine-local and gitignored. Never commit it.

---

## 4. Credentials

The script reads, in order, environment variables then `~/AI/API/magpie.env`:

- `MAGPIE_BASE_URL` (default `http://127.0.0.1:3425/v1`)
- `MAGPIE_API_KEY` (a local gateway normally accepts the placeholder; if the user's setup requires a real key, ask them to copy it from Magpie's gateway settings)

Create the file without echoing secrets:

```bash
mkdir -p ~/AI/API
printf 'MAGPIE_BASE_URL=http://127.0.0.1:3425/v1\nMAGPIE_API_KEY=placeholder\n' > ~/AI/API/magpie.env
chmod 600 ~/AI/API/magpie.env
```

If the user supplies a real key, append it with a text editor; never put it in a command that prints to the terminal, and never write it into the repository.

---

## 5. Calibrate Claude desktop model ids

The Claude desktop app exposes routing groups under internal ids (`mythos-magpie-<n>`). The skill needs the mapping.

```bash
CREW=~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py
python3 "$CREW" status
```

If the output says `app ids 0/18 groups mapped`, calibrate:

1. In an idle Claude Code session, call `mcp__ccd_session_mgmt__set_session_model` with a deliberately nonexistent model id.
2. The error lists every `mythos-magpie-*` id in model-list order.
3. Pass the numeric parts, comma-separated, to:

```bash
python3 "$CREW" app-models set 7607648695,2663368781,...
```

4. Re-run `status`; it should report `18/18` (or your group count) mapped.

If the model-list order changes later, `status` prints a warning; recalibrate once.

---

## 6. Smoke test

```bash
CREW=~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py

python3 "$CREW" groups
python3 "$CREW" models --grep gemini
python3 "$CREW" ask gemini-2/gemini-3.1-pro --prompt "Reply with exactly: ok" --max-tokens 10
```

Expected:

- `groups` prints the group table with dispatch ids.
- `models` lists matching models (including ones in no routing group).
- `ask` prints `ok`.

Optional, only if the `claude` CLI is installed:

```bash
python3 "$CREW" run gemini-2/gemini-3.1-pro --cwd /tmp --prompt "Create hello.txt containing: ok" --dry-run
```

Remove `--dry-run` to execute. `crew run` uses `claude -p --model <id>` and defaults to `acceptEdits`; do not switch to `bypassPermissions` without the user's consent.

---

## 7. Troubleshooting

| Symptom | Check | Fix |
| --- | --- | --- |
| `cannot reach magpie` | `curl http://127.0.0.1:3425/v1/models` | Open Magpie; enable its gateway |
| `magpie CLI not found` | `ls /Applications/magpie.app` | Install Magpie, or set `MAGPIE_BIN` |
| `0 models` | Provider signed in? | USER ACTION: finish provider sign-in in the app |
| `app ids 0/N mapped` | Step 5 | Recalibrate |
| `crew run` hangs | First run in this directory | Ask the user to run `claude` there once and accept the folder, or use `bypassPermissions` with consent |
| HTTP 429 `model_downgraded` | Account quota for that model | Pick another model/group; do not retry in a loop |
| HTTP 400 `unknown model` | Model id spelling | `crew models --grep <name>` and use the exact id |

---

## 8. Rules for the agent

- Never print, log, or commit `ANTHROPIC_AUTH_TOKEN`, `MAGPIE_API_KEY`, or any provider credential.
- Do not create, modify, or delete routing groups without the user's explicit request; use `--dry-run` first.
- `crew run` and sub-sessions can edit files. Give them a self-contained brief and verify the result by reading files, diffs, and test output.
- If a step needs a GUI, a sign-in, or a payment, stop and hand it to the user.
