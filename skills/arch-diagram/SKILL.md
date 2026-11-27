---
name: arch-diagram
description: 把讨论结果凝练成可编辑的 draw.io 架构图并多轮迭代维护。用户说"画/更新架构图、系统图、Agent 架构、分层图、流程图、泳道图、模块关系图"，"把刚才的讨论画成图"，"图里加个 X / 把 Y 改成共享 / 删掉 Z"，"这轮改了什么 / 回到上一版"，"导出 PNG"，"放进飞书 / 同步飞书"，或提到 draw.io、.drawio 时使用。不用于数据图表（柱状/饼图）和 UI 原型。
license: Proprietary
---

# arch-diagram：讨论 → 架构图 → 迭代 → 交付

面向产品设计期：把对话里的结论画成**可编辑**的 draw.io 图，随讨论多轮增量修改，交付到飞书。
底层用 drawio-skill（XML 写法、形状库、自动布局、校验），本 skill 负责流程、规范、质量门禁、版本与交付。

## 0. 适用前提与执行环境

**适用前提**（不满足时第一步就告诉用户，不要硬做）：本机装有 Python 3.10+、draw.io 桌面版、依赖 Skill drawio-skill。飞书同步是**可选**功能，另需 lark-cli 和用户本人完成的飞书授权；没有它，画图、迭代、导出照常可用。主要在 Windows 上验证，macOS / Linux 同样可用。
状态位（目录、工具位置、默认飞书文档等）见同目录 `config.schema.json`；新机器第一次用、或任何命令报「找不到」时，先跑 `diagram.py doctor` 看各项定位结果。

**路径一律从本 skill 所在目录推导**，不假定装在哪一级（用户级、项目级 `.claude/skills/`、SkillHub 安装位置都可能）：

- `$AD` = 本 SKILL.md 所在目录（加载 skill 时给出的 base directory）。
- `$DS` = drawio-skill 目录。脚本自动查找：环境变量 `DRAWIO_SKILL_DIR` → 与本 skill 同级的 `drawio-skill` → 项目级 → 用户级；`doctor` 会打印找到的位置。由它自己的安装方式管理，不要改它。
- Python：Windows 用 `py -3`（PATH 上的 `python` 可能是旧版本），macOS / Linux 用 `python3`。下文统一写 `py -3`，按系统替换。

每次调用都是新 shell，变量不保留——每条命令都带上前缀，例如：

- PowerShell：`$AD="<本 skill 目录>"; py -3 "$AD\scripts\diagram.py" list`
- Bash：`AD="<本 skill 目录>"; py -3 "$AD/scripts/diagram.py" list`（macOS / Linux 换成 `python3`）

下文命令统一写成 `diagram.py <子命令>`，实际执行时按上面的前缀补全；`$DS\...` 的路径取 `doctor` 打印的 drawio-skill 位置。

| 项 | 位置 |
| --- | --- |
| 图档 | `<文档目录>/arch-diagrams/<slug>/`（预设；环境变量 `ARCH_DIAGRAMS_ROOT` 可改） |
| draw.io CLI | 脚本自动定位（Windows 默认 `%LOCALAPPDATA%\Programs\draw.io\draw.io.exe`）；找不到时设 `DRAWIO_CLI` |

**分客户端说明**（只在对应客户端适用）：

- Claude Code（本机直接运行）：用 Bash 或 PowerShell 工具执行上面的命令，Read 工具可直接看 PNG。
- 云端会话连接本机（Claude App + Desktop Commander 等本机执行工具）：命令必须在**本机**执行——draw.io 和 Python 在本机；云端虚拟机里的 shell 调不到它们。若云端的 skill 目录里只有这份说明，`$AD` 取本机上的安装目录：依次看本机项目级、用户级 skills 目录下名为 arch-diagram 的文件夹，以含 `scripts/diagram.py` 的那个为准。本机文件用本机读写工具（如 Desktop Commander 的 `read_file` / `write_file` / `edit_block`，`read_file` 打开 PNG 即可看图）。本机不可达时（工具报设备未连接）：告诉用户打开桌面端，不要在云端假装完成。
- Windows PowerShell 5.1：不要把 `diagram.py` 的输出再接管道（`| Select-Object` 等），会把中文转成乱码；直接运行即可。

## 1. 核心规则（违反任何一条都算失败）

1. **清单先行**：先把讨论整理成清单 `<slug>.spec.json`（节点、关系、分组、待定项），再画图。清单格式见 `$AD\references\iteration.md`。
2. **id 即清单键**：图中每个节点的 cell id = 清单里的节点键；`check` 按 id 核对，不按文字。
3. **每轮先读后改、先消化人工改动**：改图前先 `diagram.py inspect <slug>`。用户在 draw.io 里的手改（含压缩格式保存）和团队成员在飞书画板上的改动都是**人工改动**：先如实合回，再分析意图，最后才做本轮新修改。规则见 `$AD\references\human-edits.md`。
4. **迭代时只做局部修改**：未变化的节点坐标不动；用 Edit 对 .drawio 局部替换，不整份重写（新建图除外）。重排版只在用户要求时做。
5. **坐标以图为准**：加拐点、挪位置时用 `inspect` 输出的坐标（图坐标），不要用预览 PNG 的像素坐标——两者有缩放和偏移。
6. **两道门禁**：`check` 退出码 0（结构校验 + 清单一致性），**并且**你亲眼看过预览 PNG。结构校验看不出连线压字、叠线——渲染图乱成一团它也可能报 0 分。
7. **用规范样式**：节点 / 连线写样式代号 `style="@agent"`（代号表见 `$AD\references\style-guide.md`），自己定的端口、对齐等键照常写全、接在代号后面：`style="@sync;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"`。脚本读图前会把代号原样展开成规范样式串；不自创颜色。
8. **人工改动优先**：人工改动 > 你之前的方案 > 你的推断。清单里带 `by` 的元素（人工决定过的）不改它的文字、位置、样式和连接，除非用户本轮明确要求；清单顶层 `decisions`（从人工改动提炼的术语、范围、布局规则）每轮遵守；新需求与它们冲突时说明冲突、让用户定。

## 2. 新建一张图

1. 从对话提取：节点（英文语义 id + 中文标签 + kind）、关系（谁→谁 + 动词标签 + type）、分组、待定项。
   抽象层级或关键关系有歧义时，先用 3–6 行列出清单请用户确认；清晰时直接做。
   讨论里没明说、由你推断出来的节点或关系，标成待定（`"status": "tbd"`），让用户确认。
2. **同一条消息里同时发出**：`diagram.py new <slug> --title "图标题"`（slug 用英文小写短横线，如 `kitting-agent`）；本会话第一次画图时，再加上读 `$AD\references\iteration.md`（清单格式）、`$AD\references\style-guide.md`、`$DS\references\xml-authoring.md`（首次必读）。
3. 选画法（见第 5 节），然后**在同一条消息里先写清单、再写图**：`<slug>.spec.json`（覆盖 new 生成的空清单），`<slug>.drawio`（保留 new 生成的 `title` 节点）。
   每个文件一次写完；Desktop Commander 提示「≤30 行分块」时忽略。
4. `diagram.py round <slug> -m "初版"`：首轮自动判断要不要图例（按页：≥3 种 kind、有待定项或特殊连线才加，之后每轮刷新），检查通过后导出 PNG 和 SVG，预览图就是交付的 PNG → 打开预览检查 → 有问题局部修复后再 `round`（自动修复最多 2 轮，之后把问题告诉用户）。

## 3. 迭代修改

按 `$AD\references\iteration.md` 第 2 节：`inspect` →（有人工改动时）合回 + 分析意图 + 更新清单的 `by` / `intent` / `decisions` → 改清单 + 局部改图（两个文件的修改**放在同一条消息里同时发出**；同一个文件的多处修改按顺序发，不要并行）→ `round -m "本轮改动"` → 看预览。
- `check` 报「清单外元素 / 图中多出关系 / 标签不一致」且来自「自 rNN 以来的变化」→ 是人工改动，**并入清单**、标 `by`，不要删。
- 「这轮改了什么」→ `diagram.py diff <slug>`；评审要高亮图 → `diagram.py export <slug> --highlight`。
- 「回到第 N 版」→ `diagram.py restore <slug> rNN`。

## 4. 交付

| 交付物 | 命令 | 用途 |
| --- | --- | --- |
| `<slug>.png` / `<slug>.drawio.svg` | `round` 已自动导出（多页时第 N 页为 `<slug>.pN.png`；`<slug>.preview.png` 与 `<slug>.png` 是同一张图） | 文档展示 / 可再编辑的矢量图 |
| 飞书画板（原生、可编辑） | `diagram.py sync <slug>` | **交付到飞书文档**：每页一块画板，形状 / 文字 / 连线走向与 draw.io 一致 |
| `<slug>.drawio` | — | 手动导入飞书画板（sync 不可用时的退路） |
| `<slug>.changes.png` | `diagram.py export <slug> --highlight` | 评审时标出本轮变化 |
| `<slug>.pdf` | `diagram.py export <slug> --pdf` | 全部页面合成一份 |
| `<slug>.mmd` | `diagram.py mermaid <slug>` | 降级方案：.drawio 导入效果不可接受时才用 |

「放进飞书 / 同步飞书」→ 先 `round` 通过，再 `diagram.py sync <slug>`（首次加 `--doc <飞书文档链接>`，之后记住；新图默认进同一文档）。
- 首次在文档末尾新建画板，之后**只覆盖本工具建的那块画板**；输出的「🖼 飞书预览」**必须打开看一眼**，并把文档链接给用户。
- 返回 3 =「画板被人在飞书里改过」：这是团队的人工改动，要合回 draw.io、按 human-edits 规则分析意图后再发布（自动合回随 v2.2 上线；现在先告诉用户，对照输出里的「飞书里现在的样子」预览图把改动手动合回 draw.io，或请用户说明改了什么）。**不要自行加 `--force`**：覆盖会丢掉他们的改动，只在用户明确要求时用。
- 「⚠ 文字在飞书里排不下，字号 12→11」：已自动处理；想保持原字号就按提示把 draw.io 里的框加高后再同步。
- 返回 2 且提示未安装 lark-cli / 需要授权：按 `$AD\references\feishu-sync.md` 引导用户，不要让用户把密钥贴进对话。

## 5. 画法路由

| 图的类型 | 画法 |
| --- | --- |
| 系统 / Agent 架构，≤15 节点 | 手工布局：左→右（用户、触点在左，外部系统在右），规范见 style-guide 第 4 节 |
| 分层架构（接入层 / 应用层 / 数据层…） | `group` 容器自上而下堆叠，子节点 parent=容器（style-guide 第 5 节） |
| 业务流程 / 跨角色泳道 | `lane` 容器 + `step`/`decision`/`terminal`；判断分支连线标「是 / 否」；画完运行 `py -3 "$DS\scripts\edgeports.py" <file> -o <file>` 错开端口；参考 `$DS\references\diagram-types.md` 的 Cross-Functional Flowchart 一节 |
| 时序（Agent 之间的调用顺序） | 参考 `$DS\references\diagram-types.md` 的 Sequence Diagram 一节 |
| 超过 15 个节点 | 先写清单，再按清单生成 autolayout 的 graph JSON（节点 id = 清单键，style 用 style-guide），运行 `py -3 "$DS\scripts\autolayout.py" graph.json -o auto.drawio --tune`，然后 `diagram.py adopt <slug> auto.drawio` 套用规范（容器改名、统一样式、保留自动走线）。格式见 `$DS\references\autolayout.md`。自动布局会有少量斜线，只对最影响阅读的 1–2 条手动加拐点 |
| 已有截图 / 白板照片转可编辑 | 读 `$DS\references\derasterize.md` |
| 一张图放不下（总览 + 子系统细节） | 同一文件加页面（新增 `<diagram name="...">`），清单节点写 `page` |

## 6. 回复规范

- 每轮：一句话说明改了什么（可直接用 `round` 输出的变化摘要）+ 预览图 + 文件路径；不复述整张图。
  Claude App：用 `device_stage_files` 把 `<slug>.png` 取到云端再发送；图档目录还不是已连接文件夹时，先用 `device_request_folder_access` 申请图档根目录（`doctor` 打印的位置，用户点一次同意），用户拒绝就只给路径。Claude Code：给路径。
- 有人工改动时，回复第一段先交代：**谁 · 改了什么 · 我理解的意图（把握度）**，把握度低的合并成一个问题问用户；再说本轮的新修改。
- 命令输出里有「draw.io 正开着这张图」的提醒时，原样转告用户。
- 图中文字用中文，技术名词保留英文（Agent、API、ERP/MES）。

## 7. 源码、更新与反馈

- **源码**：<https://github.com/D-Tony2020/skill-hub> 的 `skills/arch-diagram/`，分支 `main`。改 Skill 只改这里，经 PR 合并；不要直接改已安装的副本，下次更新会被覆盖。目标与范围见 `references/intent.md`，版本记录见 `CHANGELOG.md`。
- **更新**：从 SkillHub 安装的用 `skillhub upgrade`；从源码安装的拉取 `main` 后重新安装。更新从下一个会话生效。
- **反馈**：Skill 本身的缺陷（脚本报错、规则不合理、飞书转换失真）在源码仓库提 Issue，附 `diagram.py doctor` 输出和出问题的 `.drawio`（去掉敏感内容）；用户要求直接修时，在源码克隆里建分支、改 `skills/arch-diagram/` 并补测试（`py -3 -m unittest discover -s tests`），升版本、写 CHANGELOG 后开 PR。
