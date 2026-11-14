#!/usr/bin/env python3
"""magpie_crew.py — Magpie 路由组查询、派工检查与改组的辅助脚本。

只读命令: status, groups, show, picker, models, judge
调用模型: ask <model>（纯文本）、run <model>（Claude Code CLI，能读写文件）
改路由组: group add|set|rm|restore|pick|copy|template|auto|rule (rm 需要 --yes)
配置:     config [set key value]
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
    # Claude 桌面端给模型起的内部 id（mythos-magpie-<n>）；顺序与模型列表里的
    # routing group 顺序一致。为空时说明还没校准。
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
        raise RuntimeError(f"连不上 magpie ({BASE_URL}): {exc.reason}") from exc


def run_cli(args: list[str], timeout: int = 40) -> str:
    if not os.path.exists(MAGPIE_BIN):
        raise RuntimeError(f"找不到 magpie CLI: {MAGPIE_BIN}")
    try:
        proc = subprocess.run([MAGPIE_BIN, *args], capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"magpie {' '.join(args)} 超时") from exc
    out = (proc.stdout or "").rstrip("\n")
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or f"magpie 退出码 {proc.returncode}")
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
    """模型列表里的 routing group 条目，保持顺序（桌面端内部 id 也按这个顺序）。"""
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
            # 自定义组：/v1/models 可能还没有它，按名字兜底
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
        print("没有查到路由组。先运行 magpie status 确认网关在跑。")
        return
    header = ("组", "路由", "上下文", "思考档位", "派工模型")
    rows = []
    for g in groups:
        levels = "/".join(g["levels"]) if g["levels"] else "—"
        rows.append((
            g["id"], g["routing"], fmt_ctx(g["context"]), levels,
            g["app_model"] or g["picker_model"]
            or ("（picker 里没有）" if not g["in_picker"] else "—"),
        ))
    widths = [max(disp_width(r[i]) for r in [header, *rows]) for i in range(5)]
    print("  ".join(pad(h, widths[i]) for i, h in enumerate(header)))
    print("  ".join("-" * widths[i] for i in range(5)))
    for g, row in zip(groups, rows):
        print("  ".join(pad(v, widths[i]) for i, v in enumerate(row)))
        if g["members"]:
            print("    └ " + " · ".join(g["members"]))
    ready = sum(1 for g in groups if g["in_picker"])
    print(f"\n共 {len(groups)} 组，其中 {ready} 组在 Claude Code 的模型列表里可直接派工；"
          f"magpie 共 {data['models_count']} 个模型。")
    if any(g["app_model"] for g in groups):
        print("带 mythos- 的是本机 Claude 桌面端的内部模型 id，"
              "直接给 start_session / set_session_model 用。")


def print_status(data: dict, cfg: dict) -> None:
    groups = data["groups"]
    ready = sum(1 for g in groups if g["in_picker"])
    print(f"magpie   {data['magpie']}  ·  {data['models_count']} 个模型，可用")
    print(f"CLI      {MAGPIE_BIN}  ·  {'OK' if os.path.exists(MAGPIE_BIN) else '缺失'}")
    print(f"路由组   {len(groups)} 组，其中 {ready} 组可直接派工")
    print(f"picker   {data['picker_count']} 个可选模型（~/.claude/settings.json）")
    print(f"judge    {cfg['judge_model']} / effort={cfg['judge_effort']}")
    print(f"config   {CONFIG_PATH}")
    mapped = sum(1 for g in groups if g["app_model"])
    print(f"app 模型 {mapped}/{len(groups)} 组已映射（Claude 桌面端内部 id）")
    options, _ = read_picker()
    order_now = [strip_suffix(o["model"]) for o in picker_groups(options)]
    saved = cfg.get("app_model_order") or []
    if saved and saved != order_now:
        print("提示     模型列表顺序变了，app 映射可能过期；重新跑 app-models 校准")
    missing = [g["id"] for g in groups if not g["in_picker"]]
    if missing:
        print("提示     这些组不在 picker 里，派工前先确认：" + ", ".join(missing))


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
        print("读不到 ~/.claude/settings.json 的 modelPicker。")
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
        print("\n派工信息：")
        print(f"  picker 模型   {g['picker_model'] or '（没有，需要同步）'}")
        print(f"  app 模型      {g['app_model'] or '（未校准）'}")
        print(f"  上下文        {fmt_ctx(g['context'])}")
        print(f"  思考档位      {', '.join(g['levels']) or '—'}")
        print(f"  输入模态      {', '.join(g['modalities']) or '—'}")
    return 0


def cmd_app_models(argv: list[str]) -> int:
    cfg = load_config()
    options, _ = read_picker()
    pgs = picker_groups(options)
    order = [strip_suffix(o["model"]) for o in pgs]
    if argv and argv[0] == "set":
        if len(argv) < 2:
            print("用法：app-models set <id1,id2,...>", file=sys.stderr)
            return 2
        ids = [x.strip().replace("mythos-magpie-", "")
               for x in argv[1].split(",") if x.strip()]
        if len(ids) != len(order):
            print(f"id 数量 {len(ids)} 和模型列表里的 routing group 数量 "
                  f"{len(order)} 对不上，没有保存。", file=sys.stderr)
            return 2
        cfg["app_model_ids"] = ids
        cfg["app_model_order"] = order
        save_config(cfg)
        print(f"已保存 {len(ids)} 个 app 模型 id。")
    ids = cfg.get("app_model_ids") or []
    if not ids:
        print("还没校准 Claude 桌面端的内部模型 id。\n"
              "校准方法：对一个空闲会话调用 set_session_model，传一个不存在的模型，"
              "错误信息会按模型列表顺序列出 mythos-magpie-*；把它们逗号分隔传给 "
              "`app-models set`。")
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
        print("缺少 --task", file=sys.stderr)
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
        "你是多模型派工裁判，只输出 JSON，不要解释。\n"
        f"任务：{task}\n"
        f"当前主管模型：{args.current_model or '未知'}\n"
        "候选路由组（JSON）：\n"
        + json.dumps(candidates, ensure_ascii=False)
        + "\n判断两件事："
        "1) 当前主管模型是否足以胜任这个任务（信息不足时倾向 stay）；"
        "2) 若不足，选一个候选组当新主管；"
        "3) 不管 verdict 是 stay 还是 switch，都给出最多 4 个子任务的拆分，"
        "每个子任务给出 group 和 effort（必须是该组 efforts 里有的档位）。\n"
        "输出字段：verdict（stay|switch）、supervisor_group（组 id 或 null）、"
        "confidence（0-1）、reasons（中文一句话）、"
        "split（[{subtask, group, effort}]）。"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出一个 JSON 对象。"},
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
        print(f"裁判调用失败：{exc}", file=sys.stderr)
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
    """直接调用一个模型（路由组 id 或具体模型 id），只返回文本。"""
    prompt = (args.prompt or "").strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("缺少 --prompt（或从 stdin 传入提示词）", file=sys.stderr)
        return 2
    parts = [prompt]
    for path in args.file or []:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"读不到文件 {path}: {exc}", file=sys.stderr)
            return 2
        if len(text) > 200_000:
            print(f"文件太大（>200KB），先摘要或分段：{path}", file=sys.stderr)
            return 2
        parts.append(f"\n\n--- 文件：{path} ---\n{text}")
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
        print(f"模型调用失败：{exc}", file=sys.stderr)
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
    """让 claude CLI 走 magpie：补上 base url 和 token，不打印任何凭证。"""
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
    """用 Claude Code CLI 跑一个直连模型：能读写文件、跑命令。"""
    prompt = (args.prompt or "").strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("缺少 --prompt（或从 stdin 传入提示词）", file=sys.stderr)
        return 2
    cli = os.environ.get("CLAUDE_CLI") or shutil.which("claude")
    if not cli:
        print("找不到 claude CLI；可用 CLAUDE_CLI=/path/to/claude 指定", file=sys.stderr)
        return 2
    cwd = os.path.abspath(os.path.expanduser(args.cwd or os.getcwd()))
    if not os.path.isdir(cwd):
        print(f"工作目录不存在：{cwd}", file=sys.stderr)
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
        print(f"超时（{args.timeout}s），CLI 已终止", file=sys.stderr)
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
        print("用法：group add|set|show|rm|restore|pick|copy|template|auto|rule ...",
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
                print(f"不认识的字段 {key!r}；可用：" + ", ".join(sorted(GROUP_KEYS)),
                      file=sys.stderr)
                return 2
    if action == "rm" and not yes:
        print("删除路由组需要用户明确确认；确认后加 --yes。", file=sys.stderr)
        return 2
    if action == "show":
        cmd = [MAGPIE_BIN, "group", "show", *rest]
    else:
        cmd = [MAGPIE_BIN, "group", action, *rest]
    if dry:
        print("将执行：" + " ".join(shlex.quote(x) for x in cmd))
        return 0
    try:
        out = run_cli(cmd[1:], timeout=60)
    except RuntimeError as exc:
        print(f"改组失败：{exc}", file=sys.stderr)
        return 1
    if out:
        print(out)
    target = rest[0] if rest else ""
    if target:
        print(f"\n验证：python3 {os.path.abspath(__file__)} show {target}")
    print("提醒：改组后跑一次 groups，确认新组已出现在 picker；"
          "没出现就重启 magpie（或让用户重新选一次模型）。")
    return 0


def cmd_config(argv: list[str]) -> int:
    cfg = load_config()
    if not argv:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    if argv[0] == "set" and len(argv) == 3:
        key, value = argv[1], argv[2]
        if key not in DEFAULT_CONFIG:
            print(f"未知配置项 {key}；可用：" + ", ".join(DEFAULT_CONFIG), file=sys.stderr)
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
    print("用法：config | config set <key> <value>", file=sys.stderr)
    return 2


# ---------------------------------------------------------------- entry

def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "group":
        return cmd_group(sys.argv[2:])

    parser = argparse.ArgumentParser(description="Magpie 路由组派工助手")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="检查 magpie 网关、CLI、picker 与裁判配置")

    p_groups = sub.add_parser("groups", help="列出所有路由组及其派工信息")
    p_groups.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="查看一个路由组")
    p_show.add_argument("id")

    p_picker = sub.add_parser("picker", help="列出 Claude Code 模型列表里的模型")
    p_picker.add_argument("--grep")

    p_models = sub.add_parser("models", help="列出 magpie 的模型")
    p_models.add_argument("--groups-only", action="store_true")
    p_models.add_argument("--grep")

    p_app = sub.add_parser("app-models", help="查看/校准 Claude 桌面端内部模型 id")
    p_app.add_argument("args", nargs="*")

    p_judge = sub.add_parser("judge", help="让裁判模型判断主管是否合适、如何拆任务")
    p_judge.add_argument("--task", required=True)
    p_judge.add_argument("--current-model")
    p_judge.add_argument("--model", help="覆盖裁判模型")

    p_ask = sub.add_parser("ask", help="直接调用任意模型（路由组或具体模型 id），只返回文本")
    p_ask.add_argument("model", help="如 auto/gmodel 或 gemini-2/gemini-3.1-pro")
    p_ask.add_argument("--prompt")
    p_ask.add_argument("--system")
    p_ask.add_argument("--file", action="append", default=[], help="附带文本文件，可重复")
    p_ask.add_argument("--max-tokens", type=int, default=2000)
    p_ask.add_argument("--temperature", type=float, default=0.6)
    p_ask.add_argument("--effort", help="reasoning_effort；不支持时会自动去掉重试")
    p_ask.add_argument("--timeout", type=int, default=180)
    p_ask.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="用 Claude Code CLI 跑直连模型（能读写文件、跑命令）")
    p_run.add_argument("model", help="如 gemini-2/gemini-3.1-pro")
    p_run.add_argument("--prompt")
    p_run.add_argument("--cwd", help="工作目录，默认当前目录")
    p_run.add_argument("--permission-mode", default="acceptEdits",
                       choices=["default", "acceptEdits", "plan", "bypassPermissions"])
    p_run.add_argument("--max-turns", type=int, default=40)
    p_run.add_argument("--timeout", type=int, default=900)
    p_run.add_argument("--json", dest="output_json", action="store_true",
                       help="输出 CLI 的 JSON 结果")
    p_run.add_argument("--dry-run", action="store_true")

    sub.add_parser("config", help="查看或修改本技能配置").add_argument(
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
