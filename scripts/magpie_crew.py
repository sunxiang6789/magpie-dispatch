#!/usr/bin/env python3
"""magpie_crew.py — inspect Magpie routing groups, dispatch checks, and group edits.

Read-only commands: status, groups, show, picker, models, judge
Model calls:        ask <model> (plain text), run <model> (Claude Code CLI, file access)
Group edits:        group add|set|rm|restore|pick|copy|template|auto|rule (rm needs --yes)
Config:             config [set key value]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
MAGPIE_ENV = os.path.expanduser("~/AI/API/magpie.env")
DEFAULT_BIN = "/Applications/magpie.app/Contents/MacOS/magpie"

DEFAULT_CONFIG = {
    "judge_model": "auto/glm-5.3-flash",
    "judge_effort": "high",
    "max_dispatch": 4,
    # Internal model ids used by the Claude desktop app (mythos-magpie-<n>);
    # their order matches the routing groups in the model list. Empty = not calibrated.
    "app_model_ids": [],
    "app_model_order": [],
}

ROUTINGS = {
    "smart", "order", "rotate", "usage", "pace", "weight",
    "free", "fast", "cheap", "drain", "expiring", "manual",
}

GROUP_KEYS = {
    "name", "note", "models", "models+", "models-", "routing", "stays",
    "context", "compact", "levels", "family", "id", "effort", "classifier",
    "intent-sure", "pick", "fast", "ultra", "weight", "listed",
}


# ---------------------------------------------------------------- helpers

def load_env(path: str) -> dict:
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


ENV = load_env(MAGPIE_ENV)
BASE_URL = (os.environ.get("MAGPIE_BASE_URL") or ENV.get("MAGPIE_BASE_URL")
            or "http://127.0.0.1:3425/v1").rstrip("/")
API_KEY = os.environ.get("MAGPIE_API_KEY") or ENV.get("MAGPIE_API_KEY") or "placeholder"
MAGPIE_BIN = os.environ.get("MAGPIE_BIN") or DEFAULT_BIN


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def http_json(method: str, path: str, payload: dict | None = None,
              timeout: int = 120) -> dict:
    url = path if path.startswith("http") else BASE_URL + path
    data = None
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach magpie ({BASE_URL}): {exc.reason}") from exc


def run_cli(args: list[str], timeout: int = 40) -> str:
    if not os.path.exists(MAGPIE_BIN):
        raise RuntimeError(f"magpie CLI not found: {MAGPIE_BIN}")
    try:
        proc = subprocess.run([MAGPIE_BIN, *args], capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"magpie {' '.join(args)} timed out") from exc
    out = (proc.stdout or "").rstrip("\n")
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or f"magpie exited with {proc.returncode}")
    return out


def fetch_models() -> list[dict]:
    data = http_json("GET", "/models", timeout=40)
    return data.get("data") or []


def read_picker() -> tuple[list[dict], str]:
    try:
        with open(CLAUDE_SETTINGS, encoding="utf-8") as fh:
            settings = json.load(fh)
    except (OSError, ValueError):
        return [], ""
    options = (settings.get("modelPicker") or {}).get("options") or []
    caps = ((settings.get("env") or {}).get("CLAUDE_CODE_MODEL_CAPABILITIES") or "")
    return options, caps


def parse_caps(caps: str) -> dict:
    out = {}
    for part in caps.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        model, flags = part.split("=", 1)
        out[model.strip().lower()] = [f.strip() for f in flags.split(",") if f.strip()]
    return out


def strip_suffix(model: str) -> str:
    return re.sub(r"\[[^\]]*\]$", "", model)


def picker_groups(options: list[dict]) -> list[dict]:
    """Routing-group entries in the model list, in order (desktop ids follow this order)."""
    return [o for o in options
            if "routing group" in (o.get("label") or "").lower()
            or "routing group" in (o.get("description") or "").lower()]


def app_model_for(gid: str, picker_model: str | None, cfg: dict) -> str | None:
    ids = cfg.get("app_model_ids") or []
    order = cfg.get("app_model_order") or []
    if not ids or not order or gid not in order:
        return None
    idx = order.index(gid)
    if idx >= len(ids):
        return None
    base = str(ids[idx])
    if picker_model and picker_model.endswith("[1m]"):
        return f"mythos-magpie-{base}[1m]"
    return f"mythos-magpie-{base}"


def picker_for(gid: str, options: list[dict]) -> dict | None:
    wanted = {gid.lower(), strip_suffix(gid).lower()}
    if not gid.startswith("group/"):
        wanted.add(("group/" + gid).lower())
    for opt in options:
        model = (opt.get("model") or "").lower()
        if model in wanted or strip_suffix(model) in wanted:
            return opt
    return None


LINE_RE = re.compile(
    r"^\s{2,}(?P<name>\S.*?)\s{2,}"
    r"(?P<id>[A-Za-z0-9][\w./+\-]*)\s{2,}"
    r"(?P<routing>[a-z]+)\s{2,}(?P<members>.+?)\s*$"
)


def parse_groups(text: str) -> list[dict]:
    groups = []
    for line in text.splitlines():
        if line.lstrip().startswith(("removed:", "(", "usage:", "  (")):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        routing = m.group("routing")
        if routing not in ROUTINGS:
            continue
        name = m.group("name").strip()
        found = bool(re.search(r"\s+found$", name))
        name = re.sub(r"\s+found$", "", name)
        members = [x.strip() for x in m.group("members").split(" · ") if x.strip()]
        groups.append({
            "id": m.group("id").strip(),
            "name": name,
            "found": found,
            "routing": routing,
            "members": members,
        })
    return groups


def build_groups() -> dict:
    cli_text = run_cli(["groups"])
    entries = parse_groups(cli_text)
    try:
        models = fetch_models()
    except RuntimeError:
        models = []
    model_map = {m.get("id"): m for m in models}
    options, caps_text = read_picker()
    caps = parse_caps(caps_text)
    cfg = load_config()

    groups = []
    for entry in entries:
        gid = entry["id"]
        mi = model_map.get(gid) or model_map.get(strip_suffix(gid))
        if mi is None and not gid.startswith("group/"):
            mi = model_map.get("group/" + gid)
        if mi is None:
            # Custom group: /v1/models may not list it yet; fall back to the name
            for cand in models:
                label = (cand.get("magpie_label") or "")
                if label.endswith("routing group") and cand.get("display_name") == entry["name"]:
                    mi = cand
                    break
        picker = picker_for(gid, options)
        picker_model = (picker or {}).get("model")
        cap_flags = []
        if picker_model:
            cap_flags = caps.get(strip_suffix(picker_model).lower(), [])
        groups.append({
            **entry,
            "context": (mi or {}).get("context_length"),
            "levels": (mi or {}).get("reasoning_levels") or [],
            "modalities": ((mi or {}).get("modalities") or {}).get("input") or [],
            "tool_call": (mi or {}).get("tool_call"),
            "picker_model": picker_model,
            "app_model": app_model_for(gid, picker_model, cfg),
            "in_picker": picker is not None,
            "claude_efforts": cap_flags,
        })
    return {
        "groups": groups,
        "models_count": len(models),
        "picker_count": len(options),
        "magpie": BASE_URL,
    }


# ---------------------------------------------------------------- display

def disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in str(text))


def pad(text: object, width: int) -> str:
    text = str(text)
    return text + " " * max(0, width - disp_width(text))


def fmt_ctx(n) -> str:
    if not n:
        return "?"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


def print_groups(data: dict) -> None:
    groups = data["groups"]
    if not groups:
        print("No routing groups found. Run `magpie status` to confirm the gateway is up.")
        return
    header = ("group", "routing", "context", "effort", "dispatch model")
    rows = []
    for g in groups:
        levels = "/".join(g["levels"]) if g["levels"] else "—"
        rows.append((
            g["id"], g["routing"], fmt_ctx(g["context"]), levels,
            g["app_model"] or g["picker_model"]
            or ("(not in picker)" if not g["in_picker"] else "—"),
        ))
    widths = [max(disp_width(r[i]) for r in [header, *rows]) for i in range(5)]
    print("  ".join(pad(h, widths[i]) for i, h in enumerate(header)))
    print("  ".join("-" * widths[i] for i in range(5)))
    for g, row in zip(groups, rows):
        print("  ".join(pad(v, widths[i]) for i, v in enumerate(row)))
        if g["members"]:
            print("    └ " + " · ".join(g["members"]))
    ready = sum(1 for g in groups if g["in_picker"])
    print(f"\n{len(groups)} groups; {ready} are in Claude Code's model list and can be dispatched;"
          f" magpie has {data['models_count']} models.")
    if any(g["app_model"] for g in groups):
        print("The mythos- ids are the local Claude desktop internal model ids;"
              " pass them to start_session / set_session_model.")


def print_status(data: dict, cfg: dict) -> None:
    groups = data["groups"]
    ready = sum(1 for g in groups if g["in_picker"])
    print(f"magpie   {data['magpie']}  ·  {data['models_count']} models available")
    print(f"CLI      {MAGPIE_BIN}  ·  {'OK' if os.path.exists(MAGPIE_BIN) else 'missing'}")
    print(f"groups   {len(groups)} total, {ready} ready to dispatch")
    print(f"picker   {data['picker_count']} selectable models (~/.claude/settings.json)")
    print(f"judge    {cfg['judge_model']} / effort={cfg['judge_effort']}")
    print(f"config   {CONFIG_PATH}")
    mapped = sum(1 for g in groups if g["app_model"])
    print(f"app ids  {mapped}/{len(groups)} groups mapped (Claude desktop internal ids)")
    options, _ = read_picker()
    order_now = [strip_suffix(o["model"]) for o in picker_groups(options)]
    saved = cfg.get("app_model_order") or []
    if saved and saved != order_now:
        print("warning  the model list order changed; app mapping may be stale; re-run app-models")
    missing = [g["id"] for g in groups if not g["in_picker"]]
    if missing:
        print("warning  these groups are not in the picker; check before dispatching: "
              + ", ".join(missing))


# ---------------------------------------------------------------- commands

def cmd_status(args) -> int:
    data = build_groups()
    print_status(data, load_config())
    return 0


def cmd_groups(args) -> int:
    data = build_groups()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_groups(data)
    return 0


def cmd_picker(args) -> int:
    options, _ = read_picker()
    if not options:
        print("Could not read modelPicker from ~/.claude/settings.json.")
        return 1
    needle = (args.grep or "").lower()
    for opt in options:
        model = opt.get("model") or ""
        if needle and needle not in model.lower() and needle not in (opt.get("label") or "").lower():
            continue
        print(f"{model}  |  {opt.get('label')}  |  {opt.get('description') or ''}")
    return 0


def cmd_show(args) -> int:
    print(run_cli(["group", "show", args.id]))
    data = build_groups()
    g = next((x for x in data["groups"] if x["id"] == args.id), None)
    if g:
        print("\nDispatch info:")
        print(f"  picker model  {g['picker_model'] or '(missing; needs sync)'}")
        print(f"  app model     {g['app_model'] or '(not calibrated)'}")
        print(f"  context       {fmt_ctx(g['context'])}")
        print(f"  effort        {', '.join(g['levels']) or '—'}")
        print(f"  input         {', '.join(g['modalities']) or '—'}")
    return 0


def cmd_app_models(argv: list[str]) -> int:
    cfg = load_config()
    options, _ = read_picker()
    pgs = picker_groups(options)
    order = [strip_suffix(o["model"]) for o in pgs]
    if argv and argv[0] == "set":
        if len(argv) < 2:
            print("usage: app-models set <id1,id2,...>", file=sys.stderr)
            return 2
        ids = [x.strip().replace("mythos-magpie-", "")
               for x in argv[1].split(",") if x.strip()]
        if len(ids) != len(order):
            print(f"got {len(ids)} ids but the model list has {len(order)} routing groups; "
                  f"nothing saved.", file=sys.stderr)
            return 2
        cfg["app_model_ids"] = ids
        cfg["app_model_order"] = order
        save_config(cfg)
        print(f"Saved {len(ids)} app model ids.")
    ids = cfg.get("app_model_ids") or []
    if not ids:
        print("Claude desktop internal model ids are not calibrated yet.\n"
              "To calibrate: call set_session_model on an idle session with a nonexistent "
              "model; the error lists every mythos-magpie-* in model-list order. Pass the "
              "numeric parts, comma-separated, to `app-models set`.")
        return 0
    for i, gid in enumerate(order):
        base = ids[i] if i < len(ids) else "—"
        has_1m = pgs[i]["model"].endswith("[1m]") if i < len(pgs) else False
        suffix = " (+[1m])" if has_1m else ""
        print(f"{gid:<28} mythos-magpie-{base}{suffix}")
    return 0


def cmd_models(args) -> int:
    models = fetch_models()
    needle = (args.grep or "").lower()
    for m in models:
        mid = m.get("id") or ""
        label = m.get("magpie_label") or ""
        if args.groups_only and "routing group" not in label:
            continue
        if needle and needle not in mid.lower() and needle not in label.lower():
            continue
        print(f"{mid}  |  {m.get('display_name')}  |  ctx={fmt_ctx(m.get('context_length'))}"
              f"  |  {'/'.join(m.get('reasoning_levels') or []) or '—'}")
    return 0


def cmd_judge(args) -> int:
    cfg = load_config()
    task = args.task.strip()
    if not task:
        print("missing --task", file=sys.stderr)
        return 2
    model = args.model or cfg["judge_model"]
    data = build_groups()
    candidates = []
    for g in data["groups"]:
        if not g["in_picker"]:
            continue
        candidates.append({
            "group": g["id"],
            "name": g["name"],
            "members": g["members"][:4],
            "context": g["context"],
            "efforts": g["levels"],
            "input": g["modalities"],
        })
    prompt = (
        "You are a multi-model dispatch judge. Output JSON only, no explanation.\n"
        f"Task: {task}\n"
        f"Current supervisor model: {args.current_model or 'unknown'}\n"
        "Candidate routing groups (JSON):\n"
        + json.dumps(candidates, ensure_ascii=False)
        + "\nDecide three things:"
        "1) whether the current supervisor can handle this task (lean stay when information is thin);"
        "2) if not, pick one candidate group as the new supervisor;"
        "3) regardless of stay or switch, propose a split of at most 4 sub-tasks,"
        "each with a group and an effort level (must be one of that group's efforts).\n"
        "Output fields: verdict (stay|switch), supervisor_group (group id or null),"
        "confidence (0-1), reasons (one sentence),"
        "split ([{subtask, group, effort}])."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Output a single JSON object."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 900,
    }
    if cfg.get("judge_effort"):
        payload["reasoning_effort"] = cfg["judge_effort"]
    try:
        try:
            resp = http_json("POST", "/chat/completions", payload, timeout=150)
        except RuntimeError as exc:
            if "HTTP 400" not in str(exc):
                raise
            payload.pop("reasoning_effort", None)
            resp = http_json("POST", "/chat/completions", payload, timeout=150)
    except RuntimeError as exc:
        print(f"judge call failed: {exc}", file=sys.stderr)
        return 1

    content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    match = re.search(r"\{.*\}", content, re.S)
    verdict: dict
    if match:
        try:
            verdict = json.loads(match.group(0))
        except ValueError:
            verdict = {"verdict": "unknown", "raw": content}
    else:
        verdict = {"verdict": "unknown", "raw": content}
    verdict.setdefault("_judge_model", model)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0


def cmd_ask(args) -> int:
    """Call one model directly (group id or concrete model id); return text only."""
    prompt = (args.prompt or "").strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("missing --prompt (or pipe the prompt via stdin)", file=sys.stderr)
        return 2
    parts = [prompt]
    for path in args.file or []:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"cannot read file {path}: {exc}", file=sys.stderr)
            return 2
        if len(text) > 200_000:
            print(f"file too large (>200KB); summarize or split it first: {path}", file=sys.stderr)
            return 2
        parts.append(f"\n\n--- file: {path} ---\n{text}")
    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": "\n".join(parts)})
    payload = {
        "model": args.model,
        "messages": messages,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    if args.effort:
        payload["reasoning_effort"] = args.effort
    try:
        try:
            resp = http_json("POST", "/chat/completions", payload, timeout=args.timeout)
        except RuntimeError as exc:
            if "HTTP 400" not in str(exc) or "reasoning_effort" not in payload:
                raise
            payload.pop("reasoning_effort", None)
            resp = http_json("POST", "/chat/completions", payload, timeout=args.timeout)
    except RuntimeError as exc:
        print(f"model call failed: {exc}", file=sys.stderr)
        return 1
    content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if args.json:
        print(json.dumps({"model": resp.get("model") or args.model,
                          "usage": resp.get("usage"), "text": content},
                         ensure_ascii=False, indent=2))
    else:
        print(content)
    return 0


def claude_cli_env() -> dict:
    """Point the claude CLI at magpie: fill in the base URL and token; never print them."""
    env = dict(os.environ)
    try:
        with open(CLAUDE_SETTINGS, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return env
    ecfg = cfg.get("env") or {}
    if ecfg.get("ANTHROPIC_BASE_URL"):
        env.setdefault("ANTHROPIC_BASE_URL", ecfg["ANTHROPIC_BASE_URL"])
    token = env.get("ANTHROPIC_API_KEY") or ecfg.get("ANTHROPIC_AUTH_TOKEN")
    if token:
        env["ANTHROPIC_API_KEY"] = token
    return env


def cmd_run(args) -> int:
    """Run a direct model through the Claude Code CLI: file access and commands."""
    prompt = (args.prompt or "").strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("missing --prompt (or pipe the prompt via stdin)", file=sys.stderr)
        return 2
    cli = os.environ.get("CLAUDE_CLI") or shutil.which("claude")
    if not cli:
        print("claude CLI not found; set CLAUDE_CLI=/path/to/claude", file=sys.stderr)
        return 2
    cwd = os.path.abspath(os.path.expanduser(args.cwd or os.getcwd()))
    if not os.path.isdir(cwd):
        print(f"working directory does not exist: {cwd}", file=sys.stderr)
        return 2
    cmd = [cli, "-p", prompt, "--model", args.model,
           "--permission-mode", args.permission_mode]
    if args.max_turns:
        cmd += ["--max-turns", str(args.max_turns)]
    if args.output_json:
        cmd += ["--output-format", "json"]
    if args.dry_run:
        print(shlex.join(cmd))
        return 0
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=claude_cli_env(),
                              capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f"timed out after {args.timeout}s; CLI terminated", file=sys.stderr)
        return 124
    out = (proc.stdout or "").rstrip()
    if out:
        print(out)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if err:
            print(err[-2000:], file=sys.stderr)
    return proc.returncode


def cmd_group(argv: list[str]) -> int:
    if not argv:
        print("usage: group add|set|show|rm|restore|pick|copy|template|auto|rule ...",
              file=sys.stderr)
        return 2
    action, rest = argv[0], argv[1:]
    dry = "--dry-run" in rest
    rest = [x for x in rest if x != "--dry-run"]
    yes = "--yes" in rest
    rest = [x for x in rest if x != "--yes"]

    if action in ("add", "set"):
        for token in rest[1:]:
            if "=" not in token:
                continue
            key = token.split("=", 1)[0]
            if key not in GROUP_KEYS:
                print(f"unknown field {key!r}; available: " + ", ".join(sorted(GROUP_KEYS)),
                      file=sys.stderr)
                return 2
    if action == "rm" and not yes:
        print("Deleting a routing group requires explicit confirmation; add --yes once confirmed.",
              file=sys.stderr)
        return 2
    if action == "show":
        cmd = [MAGPIE_BIN, "group", "show", *rest]
    else:
        cmd = [MAGPIE_BIN, "group", action, *rest]
    if dry:
        print("would run: " + " ".join(shlex.quote(x) for x in cmd))
        return 0
    try:
        out = run_cli(cmd[1:], timeout=60)
    except RuntimeError as exc:
        print(f"group edit failed: {exc}", file=sys.stderr)
        return 1
    if out:
        print(out)
    target = rest[0] if rest else ""
    if target:
        print(f"\nverify: python3 {os.path.abspath(__file__)} show {target}")
    print("Note: after editing, run groups and confirm the new group appears in the picker; "
          "if not, restart magpie (or have the user select the model again).")
    return 0


def cmd_config(argv: list[str]) -> int:
    cfg = load_config()
    if not argv:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    if argv[0] == "set" and len(argv) == 3:
        key, value = argv[1], argv[2]
        if key not in DEFAULT_CONFIG:
            print(f"unknown config key {key}; available: " + ", ".join(DEFAULT_CONFIG), file=sys.stderr)
            return 2
        default = DEFAULT_CONFIG[key]
        if isinstance(default, bool):
            cfg[key] = value.lower() in ("1", "true", "yes", "on")
        elif isinstance(default, int):
            cfg[key] = int(value)
        else:
            cfg[key] = value
        save_config(cfg)
        print(f"{key} = {cfg[key]}")
        return 0
    print("usage: config | config set <key> <value>", file=sys.stderr)
    return 2


# ---------------------------------------------------------------- entry

def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "group":
        return cmd_group(sys.argv[2:])

    parser = argparse.ArgumentParser(description="Magpie routing-group dispatch helper")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="check the magpie gateway, CLI, picker, and judge config")

    p_groups = sub.add_parser("groups", help="list routing groups and dispatch info")
    p_groups.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="show one routing group")
    p_show.add_argument("id")

    p_picker = sub.add_parser("picker", help="list models in Claude Code's model list")
    p_picker.add_argument("--grep")

    p_models = sub.add_parser("models", help="list magpie models")
    p_models.add_argument("--groups-only", action="store_true")
    p_models.add_argument("--grep")

    p_app = sub.add_parser("app-models", help="show/calibrate Claude desktop internal model ids")
    p_app.add_argument("args", nargs="*")

    p_judge = sub.add_parser("judge", help="ask the judge whether the supervisor fits and how to split")
    p_judge.add_argument("--task", required=True)
    p_judge.add_argument("--current-model")
    p_judge.add_argument("--model", help="override the judge model")

    p_ask = sub.add_parser("ask", help="call any model directly (group or concrete id), text only")
    p_ask.add_argument("model", help="e.g. auto/gmodel or gemini-2/gemini-3.1-pro")
    p_ask.add_argument("--prompt")
    p_ask.add_argument("--system")
    p_ask.add_argument("--file", action="append", default=[], help="attach a text file; repeatable")
    p_ask.add_argument("--max-tokens", type=int, default=2000)
    p_ask.add_argument("--temperature", type=float, default=0.6)
    p_ask.add_argument("--effort", help="reasoning_effort; retried without it if unsupported")
    p_ask.add_argument("--timeout", type=int, default=180)
    p_ask.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="run a direct model via Claude Code CLI (files and commands)")
    p_run.add_argument("model", help="e.g. gemini-2/gemini-3.1-pro")
    p_run.add_argument("--prompt")
    p_run.add_argument("--cwd", help="working directory; defaults to the current directory")
    p_run.add_argument("--permission-mode", default="acceptEdits",
                       choices=["default", "acceptEdits", "plan", "bypassPermissions"])
    p_run.add_argument("--max-turns", type=int, default=40)
    p_run.add_argument("--timeout", type=int, default=900)
    p_run.add_argument("--json", dest="output_json", action="store_true",
                       help="print the CLI's JSON result")
    p_run.add_argument("--dry-run", action="store_true")

    sub.add_parser("config", help="show or edit this skill's config").add_argument(
        "config_args", nargs="*")

    args = parser.parse_args()
    if args.command == "config":
        return cmd_config(args.config_args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "groups":
        return cmd_groups(args)
    if args.command == "show":
        return cmd_show(args)
    if args.command == "picker":
        return cmd_picker(args)
    if args.command == "models":
        return cmd_models(args)
    if args.command == "app-models":
        return cmd_app_models(args.args)
    if args.command == "judge":
        return cmd_judge(args)
    if args.command == "ask":
        return cmd_ask(args)
    if args.command == "run":
        return cmd_run(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
