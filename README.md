# magpie-dispatch

用 [Magpie](https://magpie.im/) 做多模型派工的 Claude Code 技能：主管（当前会话的模型）查组、拆任务、按能力和思考档位派工，最后验收、打回重做。

支持三种派法：

| 目标 | 方式 | 能做什么 |
| --- | --- | --- |
| Magpie 路由组 | 桌面端子会话 | 读写文件、跑命令，出现在侧栏，可打回 |
| 任意 Magpie 模型 | `crew ask` | 一次性纯文本（文案、摘要、翻译、第二意见） |
| 任意 Magpie 模型 | `crew run` | 走 Claude Code CLI，读写文件、跑命令 |

不在路由组里的模型（例如 `gemini-2/gemini-3.1-pro`、`codex/gpt-6.1-sol`）也能直接用，不需要先在 Magpie 里建组。

## 依赖

- macOS（脚本默认读取 `/Applications/magpie.app` 的 CLI，可用环境变量 `MAGPIE_BIN` 改）
- 已安装并运行 Magpie，网关默认 `http://127.0.0.1:3425/v1`
- Python 3.9+（只用标准库）
- Claude Code 桌面端（派子会话）或 `claude` CLI（`crew run`）
- 凭据放在 `~/AI/API/magpie.env`（`MAGPIE_BASE_URL`、`MAGPIE_API_KEY`），或用同名环境变量

## 安装

```bash
git clone https://github.com/sunxiang6789/magpie-dispatch.git ~/.claude/skills/magpie-dispatch
```

首次使用先校准桌面端模型 id（技能会自动提示）：

```bash
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py status
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py groups
```

如果 `groups` 里的「派工模型」显示 `auto/...` 而不是 `mythos-magpie-...`，按 [SKILL.md](SKILL.md) 里的校准步骤做一次。

## 常用命令

```bash
CREW=~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py

python3 $CREW status                 # 网关、CLI、picker、裁判配置
python3 $CREW groups                 # 路由组 + 派工 id + 档位
python3 $CREW models --grep gemini   # 所有可用模型（含不在路由组的）
python3 $CREW judge --task "任务描述" --current-model "<self.model>"

python3 $CREW ask gemini-2/gemini-3.1-pro --prompt "写 3 条文案"
python3 $CREW run gemini-2/gemini-3.1-pro --cwd ./project --prompt "实现并跑测试"

python3 $CREW group set auto/hy3 models=workbuddy/hy3,workbuddy-ai/hy3 routing=order
```

## 配置

复制示例配置后按本机情况修改：

```bash
cp config.example.json config.json
```

`config.json` 是本机校准结果，已在 `.gitignore` 里；不要提交。

主要字段：

- `judge_model` / `judge_effort`：裁判模型和档位
- `max_dispatch`：一批最多几个会话
- `app_model_ids` / `app_model_order`：桌面端内部模型 id 与路由组顺序的映射

## 注意

- 不查询额度：Magpie 会自动切换可用账号。
- 桌面端 `start_session` 只接受 `mythos-magpie-...`；直接传 `auto/...` 或 `gemini-2/...` 会被静默忽略。直连模型请用 `crew ask` / `crew run`。
- `crew run` 默认 `--permission-mode acceptEdits`；需要更强的权限时显式加参数，风险自负。
- 仓库不包含任何密钥；凭证只从本机环境变量或 `~/AI/API/magpie.env` 读取。
