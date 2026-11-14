---
name: magpie-dispatch
description: 用 Magpie 做多模型派工。先查本机可用的路由组和模型，主管（当前会话的模型）拆任务，按能力和思考档位分派给不同路由组的会话；不在路由组的模型也能直接用（Gemini 等：crew ask 出文本，crew run 走 CLI 动手改文件）；最后主管验收、有问题的打回重做；也能直接改路由组。用户说"派工/派活/多模型协作/用 magpie 分配/主管验收/改路由组/看看有哪些模型能用"时使用。
---

# Magpie 多模型派工

主管就是**当前会话的模型**。主管负责：查组 → 拆任务 → 派工 → 验收 → 打回。子任务尽量新开会话，主管不替它们写代码，但验收时必须亲自看产物。

**派工目标有两种，三种派法，都能直接用：**

- **路由组**（`auto/...`、`group/...`）→ 桌面端子会话：能读写文件、跑命令，出现在侧栏，适合实现、调研、审查。
- **直连模型**（`gemini-2/...`、`codex/...`、`trae-cn/...` 等具体模型 id）：
  - `crew ask`：一次性纯文本，不碰文件，适合文案、摘要、翻译、第二意见。
  - `crew run`：用 Claude Code CLI 跑，能读写文件、跑命令，适合让非路由组模型真正干活。
- 直连模型**不需要先在 magpie 里建路由组**；只要 `crew models` 查得到就能用。

**不查额度。** Magpie 会自动切换能用的账号，只查有哪些路由组、哪些模型可用、支持哪些思考档位。

## 硬规则：先看产出是什么类型

- 代码、文档、分析、审查 → 路由组的文本模型。
- **海报、封面、插画、Logo、图片编辑、视频、配音、音乐 → 媒体生成，绝不能让文本模型用 HTML/CSS/SVG 截图顶替。** 默认顺序按用户全局规则：Codex CLI 生图 → 失败再走 gpt-image / 即梦；magpie 里的图像模型（如 `gemini-image`、`MiniMax-Image`）只作备选。
- 派会话做媒体任务时，brief 必须写“调用生图工具，不要用网页/SVG 代替”，并给死输出路径；主管验收必须**用视觉读图**，检查中文有没有错字、乱码、截断，不能只看子会话汇报。
- 主管接活前先自问一句：用户要的是不是一张图/一段视频？如果是，直接走媒体流程，不要绕到前端组。

脚本：`~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py`（下文简写为 `crew`；实际执行时用 `python3` 加完整路径）。只读命令不会改任何东西。

## 1. 每轮开工：查目标

```bash
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py status
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py groups
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py models --grep <关键字>
```

- `groups`：路由组，能开会话。
- `models`：magpie 里能直接调用的全部模型，包含不在任何路由组里的直连模型；`--groups-only` 只看组，`--grep gemini` 按名字过滤。
- 直连模型只要出现在 `models` 里就能用，不需要先路由进组。

`groups` 表格里：

- **组**：`auto/...` 是 magpie 自动发现的路由组；自定义组是 `group/<id>`。
- **派工模型**：直接作为会话的 `model` 参数。本机 Claude 桌面端用的是内部 id（`mythos-magpie-...`）；没校准时会显示 `auto/...` 的 picker id。
- **上下文 / 思考档位**：判断这组适不适合任务。
- 成员行：这一组背后实际会用到哪些厂商模型。

需要结构化数据时加 `--json`。看单个组：`crew show <组id>`。确认某个组在模型菜单里的 id：`crew picker --grep <关键字>`。

**如果派工模型是 `auto/...` 而不是 `mythos-...`：** 说明本机 app id 还没校准。做法是：对一个空闲会话调用 `mcp__ccd_session_mgmt__set_session_model`，故意传一个不存在的模型，错误信息会按模型列表顺序列出全部 `mythos-magpie-*`；把数字部分按顺序逗号分隔传给 `crew app-models set 7607648695,2663368781,...`。之后 `crew groups` 会自动按顺序映射。模型列表顺序变了 `status` 会警告，重新校准一次即可。

同时取当前会话的模型和档位：`mcp__ccd_session_mgmt__get_session {"session_id": "self"}`。

**桌面端子会话的限制：** `start_session` / `set_session_model` 只认 `mythos-magpie-...`；传 `gemini-2/...` 或 `auto/...` 都会被**静默忽略**（实测退回当前模型）。这是桌面端会话接口的白名单，不是 magpie 的限制。直连模型改用 `crew ask`（纯文本）或 `crew run`（CLI，能读写文件）；不要因为 `crew picker` 里有这个 id 就推断桌面端子会话也能用。

## 2. 判断主管够不够（可选裁判）

复杂任务、跨多个模块、或用户问"要不要换个更强的主管"时，让裁判模型判断。**不要每个小任务都调**，它是一次额外的模型请求：

```bash
python3 ~/.claude/skills/magpie-dispatch/scripts/magpie_crew.py judge \
  --task "一两句话说明任务、规模、难点" \
  --current-model "<self.model>"
```

返回 JSON：`verdict`（stay/switch）、`supervisor_group`、`split`（推荐拆法）。裁判给的是组 id，派工前用 `groups` 换成 app 模型 id。
裁判模型默认 `auto/glm-5.3-flash`，可用 `crew config set judge_model auto/...` 改。

- `stay`：继续由当前会话当主管。
- `switch`：当前会话**不能改自己的模型**（工具会拒绝）。正确做法是**新开一个主管会话**（见下），把完整交接写进 brief，然后本会话停止动手，只告诉用户"主管已交给 X 组，在那边继续"。
- 新会话也起不来：告诉用户在模型菜单里选哪个组，等用户选好再继续。

## 3. 拆任务、选组、选档位

按 `references/routing-playbook.md` 判断任务类型。先看产出是代码/文档还是媒体：媒体任务按上面的硬规则直接走生图/生视频，不派文本组。文本任务的硬规则：

- 2–4 个子任务，彼此独立、各有可验证的产出。
- 每个子任务写明：**目标（路由组或直连模型）+ 方式（会话 / API / CLI）+ 思考档位 + 写不写文件 + 验收标准**。
- 要读写文件、跑命令 → 路由组会话，或直连模型 `crew run`；`crew ask` 只做纯文本，结果由主管落盘。
- 同一个文件集只派一个写入者；审查/验收类任务派只读会话。
- 档位必须是该组支持的（看 `groups` 的思考档位列）；不支持的取最近档位。
- 不要什么都用旗舰组：机械活给 flash 组，难题才上旗舰 + xhigh。
- 路由组之外的模型（例如 Gemini）直接写模型 id，不用先建组；先 `models --grep` 确认它在列表里。

## 4. 派工

### 路由组 → 开子会话

用一条消息说明派了谁、干什么、哪个组、什么档位，然后对新会话调用：

```
mcp__ccd_session__start_session
  initiation: "user_asked"
  context: "fresh"
  model: "<groups 表里的派工模型：mythos-magpie-... 或 picker id>"
  effort: "high"            # minimal|low|medium|high|xhigh|max
  name: "<短名>"
  title: "<子任务名>"
  use_worktree: true        # 写代码用独立 worktree；只读审查可用 false
  prompt: "<自包含 brief>"
  background: "<项目背景、约束、验收命令、回报格式，≥80 字>"
```

- 每批最多 4 个会话。
- brief 必须自包含：目标、涉及文件、约束、怎么算完成、怎么验证、回报格式（做了什么/改了哪些文件/验证结果/未完成/风险）。
- 默认不让子会话 commit 或 push，除非用户要求或任务本身就要分支。
- **稳妥派工顺序（推荐）**：`start_session` 的 prompt 先只写“待命：不要动手，等我发完整 brief”，`model` 传 groups 表里的 app 模型、`effort` 传档位 → `get_session` 核对 `model`/`effort` → 不对就用 `set_session_model` 改成目标 `mythos-magpie-...` → 再用 `mcp__ccd_session_mgmt__send_message` 发完整 brief。这样不会让它在错误模型上先干一半。
- 本机实测：`start_session` 传 magpie 的 `auto/...` 会被**静默忽略**，必须核对；`effort` 会正常生效。
- 如果 `start_session` 直接拒绝这个 model：错误会列出可用 id；用 `crew app-models` 对照改成 mythos id；还不行就请用户手动选。

已存在的会话要改档位：`mcp__ccd_session_mgmt__set_session_effort`（对当前会话本身会被拒绝，这是设计如此）。

### 直连模型 → `crew ask`（不开会话）

```bash
# 基本用法：路由组 id 或具体模型 id 都行
crew ask gemini-2/gemini-3.1-pro --prompt "写 3 条开业朋友圈文案，每条 40 字以内"
crew ask auto/glm-5.3-flash --prompt "把下面这段改成更口语的表达"
# 带素材文件（可重复）；文件内容会附在提示词后面
crew ask gemini-2/gemini-3.1-pro --prompt "按 brief 写文案" --file brief.md --file 素材.txt
# 指定思考档位、限制长度、要 JSON 元数据
crew ask gemini-2/gemini-3.1-pro --prompt "..." --effort high --max-tokens 1200 --json
```

- 返回纯文本到 stdout；提示词也可以用 stdin 传入。
- 一次请求、无工具、无文件读写：需要多轮或改文件的任务必须改用会话。
- 主管负责把结果写盘，并按第 5 节验收；不要拿"调的是强模型"当通过理由。
- 批量调用时逐个跑，每次检查返回是否为空或报错（失败退出码非 0）。
- 直连模型不需要也不应该出现在 `groups` 里；只要 `crew models` 能查到就能用。

### 直连模型 → `crew run`（Claude Code CLI，能动手）

```bash
crew run gemini-2/gemini-3.1-pro --cwd <项目目录> \
  --prompt "按 brief 实现功能并跑测试" --max-turns 40 --timeout 900
# 只预演命令，不执行
crew run gemini-2/gemini-3.1-pro --cwd <目录> --prompt "..." --dry-run
# 要原始结果（含用量）时
crew run gemini-2/gemini-3.1-pro --cwd <目录> --prompt "..." --json
```

- 本质是 `claude -p --model <id>`，CLI 会自己读写文件、跑命令；**不出现在桌面端侧栏**，结果同步返回给主管。
- 默认 `--permission-mode acceptEdits`；Bash 等操作需要用户授权时，明确告诉用户，或经用户同意改用 `--permission-mode bypassPermissions`（有风险，只在该项目内用）。
- 同步阻塞：长任务给足 `--timeout`，或用 Bash 的 `run_in_background` 起，别在同一轮里干等。
- 一次只给一个明确 brief；CLI 不会回传 side-session 通知，主管要自己读文件、看 diff、跑测试验收。
- 目录第一次跑若卡住，让用户在终端里 `cd` 进去跑一次 `claude` 并同意；或临时用 `bypassPermissions`。

## 5. 验收（必须做）

- 等 side-sessions 通知，**不要轮询**。
- 不采信汇报本身：读改了哪些文件、看 diff、跑测试/构建；独立 worktree 的会话看它的分支（`git log` / `git diff <base>...<branch>`）。
- `crew ask` 的产出同样验收：读全文，核对事实、错字、是否越权编造；不合格就改提示词重跑或换模型，不能直接放行。
- `crew run` 按子会话的标准验收：读它改的文件、看 diff、跑测试；它只说 done 不算数。
- 通过 → 汇总交付；未通过 → **打回重做**：
  - 用 SendMessage 给那个 session 发具体缺陷：文件:行、失败输出、期望行为，要求修完再回报。
  - 会话已结束就同组新开一个"返工"会话，附原 brief + 缺陷清单。
  - 最多 2 轮；还不过就主管接手，或把选择交给用户。
- 合并分支、推送、发布必须先问用户。

## 6. 改路由组

用户说"改路由组 / 新建组 / 把这个组换成 X"时，直接用脚本改，不用打开 magpie 界面。先 `--dry-run` 预演，用户确认后执行。

```bash
# 新建
crew group add 快速杂活 models=qoder/qfmodel,qoder-cn/qfmodel,zcode/GLM-5.3-Flash routing=smart stays=off
# 改组：整组替换 / 追加 / 删除成员
crew group set auto/hy3 models=workbuddy/hy3,workbuddy-ai/hy3 routing=order
crew group set auto/gmodel models+=trae-cn/glm-5.3-max levels=low,medium,high,xhigh,max
crew group set auto/hy3 models-=workbuddy-ai/hy3
# 固定到某个成员 / 复制 / 模板 / 删除 / 恢复
crew group pick auto/hy3 workbuddy/hy3
crew group copy auto/gmodel 写作组
crew group template smart 主力
crew group rm 写作组 --yes
crew group restore auto-mmodel   # 恢复被删掉的自动组
```

改完必须：

1. `crew groups` 确认改动；
2. 确认 `派工模型` 是 `mythos-...`；改组可能改变模型列表顺序，看到 `status` 警告就重新校准 `app-models`；
3. `crew picker --grep <新组>` 确认它已经在 Claude Code 的模型列表里，有 `派工模型` 才能派工；
4. 没出现时告诉用户：重启 magpie（让模型列表重新同步），或在模型菜单里重新选一次，再派工。不要拿一个不在 picker 里的组硬派。

首次使用：跑一次 `status` + `groups`，把组清单和裁判默认模型说清楚，然后问用户一句：要不要调整路由组。用户没要求就不改组。

## 输出习惯

- 派工前：一张小表（子任务 / 目标：组或模型 / 方式：会话、API 或 CLI / 档位 / 产出 / 写入范围）。
- 验收后：通过或打回，附证据（命令 + 结果），不要只写"已完成"。
- 不向用户汇报额度、账号、密钥细节。
