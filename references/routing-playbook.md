# 路由与思考档位手册

以 `crew groups` 和 `crew models` 的实时结果为准；下面的组名和模型名只是当前这台机器的例子。

派工目标有两类：**路由组**（开子会话，能读写文件）和**直连模型**（`crew ask`，只出文本，不需要先建组）。

## 怎么选派工目标

**先定方式：** 要改文件、跑命令、多轮调试 → 路由组会话（要出现在侧栏、能被打回）或直连模型 `crew run`（CLI，不在侧栏）；只要一段文本（文案、摘要、翻译、评审意见）→ `crew ask`。

选路由组时看四个字段：

1. **成员**：这组背后有哪些厂商/模型。成员里有 2–3 家旗舰的，适合难题；只有 flash 的，适合杂活。
2. **上下文**：1M 适合整仓库/长文档；192k 的组别塞超大材料。
3. **思考档位**：没有 xhigh/max 的组，难题别硬派；档位越全越灵活。
4. **输入模态**：要读截图/设计稿，必须选带 `image` 的组。

直连模型看三个字段：`crew models` 里的 `ctx`、`reasoning_levels`、名字里的 `thinking`。没有路由组、也没在 magpie 里配置路由的模型，只要出现在 `models` 里就能 `crew ask` 直接调用。

## 任务类型 → 组特征 → 档位

| 任务 | 组特征 | 思考档位 |
| --- | --- | --- |
| 海报、封面、插画、Logo、图片编辑 | **不是文本组**：Codex CLI 生图（默认）→ 失败再 gpt-image / 即梦；magpie 图像模型作备选 | — |
| 视频、配音、音乐 | 即梦（视频/音频）或用户指定的媒体工具 | — |
| 架构设计、疑难 bug、安全审查、关键决策 | 旗舰推理组（成员含多家顶级模型） | xhigh / max |
| 多文件功能实现、重构 | 强的通用组 | high |
| 前端/视觉/截图/设计稿还原 | 带 image 输入的强组 | high |
| 整仓库或长文档扫描、资料整理 | 1M 上下文组 | medium / high |
| 机械改动：重命名、格式化、样板代码、批量替换 | flash 组 | minimal / low |
| 独立审查、交叉验证 | 与实现方**不同厂商**的组 | high / xhigh |
| 文案、文档、总结 | 路由组（Kimi / GLM 系），或直连 Gemini / GPT 系 | medium / high |
| 数据分析、长表格 | 长上下文 + 强推理组 | high |

直连模型举例（是否可用以 `crew models` 为准）：`gemini-2/gemini-3.1-pro`、`gemini-2/gemini-3.8-flash`、`codex/gpt-6.1-sol`、`trae-cn/kimi-k3.1-pro`、`qoder-cn/gmodel`。它们不在任何路由组里，也不需要建组。

当前机器上的典型分组（会变，只作参考）：

- 旗舰：`auto/kmodel_latest`（Kimi K3.1 Pro）、`auto/gmodel`（GLM-5.3）、`auto/deepseek-v4-pro`、`auto/qmodel_latest`（Qwen4-Max）。
- 通用：`auto/glm-5.2`、`auto/mimo-v2.6-pro`、`auto/qmodel_38max`。
- 快：`auto/qfmodel`、`auto/glm-5.3-flash`、`auto/deepseek-v4.1-flash`、`auto/minimax-m3.1-flash`。
- 长上下文小模型/特殊：`auto/mercury-3`、`auto/minimax-m3`、`auto/hy4free`、`auto/hy3`。

## 媒体任务（海报/封面/插画/视频/配音）

这些不是路由组的活，不要派给文本模型写 HTML 再截图。默认顺序：

1. **生图**：Codex CLI 的图片生成工具（用户全局规则里的完整命令），参考图用 `-i`，输出到目标目录；失败或超时才走 gpt-image 技能（内置浏览器）或即梦。
2. **视频/音频**：即梦（Dreamina）优先，失败再换别的。
3. magpie 的图像模型（`gemini-2/gemini-image`、`minimax-code/MiniMax-Image`、`agens-free/agnes-image-*`）只作备选，不默认。

派给子会话做媒体任务时，brief 要写死：

- 必须调用生图工具，**禁止**用 HTML/CSS/SVG 渲染截图顶替；
- 输出路径、比例、尺寸；
- 中文文案逐字给全，要求“不能有错字、缺笔、乱码、英文替代”；
- 生完自己读图检查一遍。

主管验收：用 Read 读成图，检查中文文案、构图、是否有仿冒 logo/二维码/真人肖像。对不上就打回重生成，不要拿“渲染出来了”当通过。

## 直连模型（crew ask / crew run）

不在路由组里的模型有两种用法：

**`crew ask` — 纯文本，一次性。** 适合文案、润色、翻译、摘要、资料整理、挑错、第二意见。

```bash
crew models --grep gemini                  # 先确认模型在列表里
crew ask gemini-2/gemini-3.1-pro --prompt "写 3 条开业文案" --max-tokens 600
crew ask codex/gpt-6.1-sol --prompt "评审下面的实现" --file app.js --effort high
```

**`crew run` — 走 Claude Code CLI，能读写文件、跑命令。** 适合实现、重构、调试这类真动手的活。

```bash
crew run gemini-2/gemini-3.1-pro --cwd <项目目录> --prompt "按 brief 实现并跑测试" \
  --max-turns 40 --timeout 900
```

- `run` 默认 `acceptEdits`；需要跑命令时权限可能被拦，先看 CLI 输出，别默认开 `bypassPermissions`。
- `run` 是同步阻塞的，长任务放到后台或给大 timeout；它不在桌面端侧栏里，主管自己验收。
- `ask` 没有工具，素材用 `--file` 传，产出由主管写盘。
- 同一个提示词可以换模型对比，取更好的那份；但不要把多份结果不加判断地混在一起。
- 模型 id 带 `[1m]` 后缀时，`ask` / `run` 里也照写；不确定就先 `--json` 看返回的 `model`。

## 档位规则

- `none` / `minimal`：纯机械、不需要判断。
- `low`：简单的单文件修改、查资料。
- `medium`：常规实现、有明确规格。
- `high`：多文件、需要调试、需要权衡。
- `xhigh`：架构、难题、最终验收。
- `max`：关键任务且这组支持；不要默认拉满。

组不支持某档位时取最近的，别假设它一定接受。

## 拆分与并行

- 一批最多 4 个会话；2–3 个通常最好。
- 子任务必须能独立验收；有依赖的串行做，不要同时开工。
- 同一文件集只安排一个写入者；审查/验收会话只读。
- 实现和审查尽量不同厂商，避免同源盲点。
- 长任务先给一个 5 分钟能出结果的小任务试水，再放开大任务。

## 常见错误

- 所有任务都派旗舰：慢、贵、还容易互相踩文件。
- 把"实现"和"验收"交给同一个会话：等于自己批自己。
- 主管边写边验同一个文件：视角丢失，也违反单写入者。
- 只看子会话的汇报就通过：必须跑测试、看 diff。
- 把不在 picker 里的组硬塞给 `start_session`：先 `crew picker --grep` 确认。
- 把 `gemini-2/...` 这类直连模型 id 传给 `start_session`：会被静默忽略、退回当前模型；直连模型用 `crew ask` 或 `crew run`。
- 直连模型的文本不读就放行：它不会自己跑测试，事实和错字都得主管核。
- 用 `crew run` 时不验收：CLI 的 done 只是它自己的话，文件、diff、测试都要主管自己看。
