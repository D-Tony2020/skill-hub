---
name: session-distiller
description: 从过去的 Agent 会话（Claude Code 本机会话记录，以 session 为单位）里挖出值得长期复用的资产，包括工程管线、组件、方法论、人与 Agent 的交互流程和工具、规则以及"规则+代码"。依据用户的长期目标画像打分，把资产划分为项目、行业、基座三层，和已有 skill 去重，经用户逐条确认后固化成可在 Skill Hub 拼装的 skill 或记忆文件草稿。用户说"复盘/盘点/沉淀/提炼最近的会话或项目""把做过的东西沉淀成 skill""哪些经验值得固化""从历史 session 里提取可复用的东西""做个资产盘点"，或在一个项目收尾时想把可复用部分提到项目之外，都应使用本 skill，即使没有明确说 skill。
---

# session-distiller：从历史会话提炼可复用资产

用户在很多会话里用 Agent 完成一个个项目。有价值的东西常常埋在某个项目里：一段反复写的脚本、一次踩坑后定下的规则、一套和客户对需求的方法、某类业务场景下和 Agent 配合的固定套路。本 skill 的工作，是把这些东西从会话里找出来，按用户的长期目标判断值不值得留，分清它属于项目、行业还是基座，再把值得留的固化成不同层级的 skill 或记忆文件，供 Skill Hub 拼装：基座被行业复用，行业组合成项目方案。

分工：**脚本负责确定性的部分，你负责判断。** 找会话、压缩成摘要、脱敏、编号、校验、排序、记账、生成骨架，这些都由 `sd` 完成，结果可复现。哪些模式值得固化、怎么抽象、属于哪种形态，由你在阅读摘要后判断。

`$SKILL` = 本文件所在目录。所有命令写作 `sd <命令>`，实际执行 `bash "$SKILL/scripts/sd" <命令>`（Windows 上由 Git Bash 执行，路径里的 `\` 换成 `/`；没有 bash 时用 `python "$SKILL/scripts/sd.py" <命令>`）。每条命令最后一行固定是 `RESULT ok ...` 或 `RESULT fail code=<错误码> ...`，**以最后一行为准**。错误码见 [references/troubleshooting.md](references/troubleshooting.md)。

## 原则

1. **证据先行。** 每个候选都要指向具体会话的具体轮次（`T3`、`T7`）。没有证据的"感觉有用"不进清单。`sd validate` 会核对证据是否真实存在。
2. **画像是标尺。** 契合度以 `~/.session-distiller/profile.md` 为准，不以你自己的偏好为准。画像缺失或还有 TODO 时，先和用户补全，因为没有标尺的打分没有意义。
3. **分层，抽象到项目之外。** 每个候选都要标明层级：项目资产（只对这个客户成立，留在项目里）、行业资产（制造业通用）、基座（跨行业）。一个项目产出往往横跨几层，要拆开，并用 `builds_on` 连起来，而不是做成一个大而全的 skill。拿不准时往低一层归。
4. **用户拍板。** 你只提出候选和建议，采纳、合并或拒绝由用户决定。被拒绝的候选会记在账本里，没有新证据时不要再提。
5. **不泄密。** 摘要已经自动脱敏（密钥、token、手机号、身份证、邮箱，以及 `redact.txt` 里的客户名等）。写进候选和 skill 草稿的内容同样不能带客户真实信息。发现漏网的敏感词，就加进 `redact.txt` 并重跑 digest。
6. **只读会话。** 不修改、不删除任何会话记录。

## 第一次使用

1. `sd doctor`。看到 `not_initialized` 就运行 `sd init`，它会在 `~/.session-distiller/` 下生成 `config.json`、`profile.md` 和 `redact.txt`。这个目录属于用户，skill 升级不会碰它。
2. **画像**：`assets/profiles/` 里有预置画像（例如 `blacklake-fde`，即黑湖科技 FDE 的画像），用 `sd init --profile <名字>` 套用，已有画像时加 `--force` 覆盖。没有合适的预置画像，就读 `profile.md` 模板，结合你已知的用户信息（CLAUDE.md、记忆、当前对话）先替用户起草，再请用户确认。重点是长期目标、沉淀重点、高价值领域和"不要提炼的东西"。画像想跟着用户换机器，就把它作为预置画像提交到源码仓库。
3. **补全脱敏词**：问用户有哪些客户名、内部域名或人名需要遮盖，写进 `redact.txt`，每行一个。
4. 默认数据源是 `~/.claude/projects`（Claude Code 本机会话）。要处理别处的会话，比如从其他机器拷来的 `.jsonl` 目录，就在 `config.json` 的 `sources` 里加一项 `{"type": "claude-code", "path": "<目录>"}`。`skill_hub` 指向 skill-hub 源码克隆，默认 `~/skill-hub`。

## 一次提炼的流程

### 1. 定范围

`sd scan` 默认列出尚未处理的会话，按时间从新到旧排列，并过滤掉人类轮次少于 2 的会话。常用参数：

- `--since 30d` 或 `--since 2026-10-01`：按时间窗口筛选。
- `--project <cwd 片段>`：只看某个项目。
- `--session <id 前缀>`：点名某几个会话，可以重复写。
- `--all`：包括已经处理过的会话。
- `--limit N`：只取最新的 N 个。

把扫描结果的概要告诉用户（多少个会话、涉及哪些项目），确认范围后再继续。用户没有指定时，默认取最新的 20 个未处理会话。

### 2. 生成摘要

`sd digest <同样的筛选参数>` 会新建 `~/.session-distiller/runs/<run-id>/`，里面有：

- `digests/<session>.md`：每个会话一份压缩摘要，内容包括用户原话、动作清单、报错、最终回复和信号区（工具、命令、写过的代码文件、用户纠正过 Agent 的轮次 ⚑）。轮次编号 `T<n>` 是证据引用的锚点。
- `overview.md`：会话总表和**跨会话信号**。在多个会话里反复出现的命令、技能或 MCP，是复用度最强的证据。如果有「Security」一节，说明原始会话记录里存有明文凭据。摘要里已经遮盖，但原始文件里还在。要在回复里提醒用户作废或更换这些凭据，这比提炼本身更紧急。
- `catalog.md`：用户已有的 skill 和账本里以前的候选，用来去重。
- `index.json`：机器读的索引，供 validate 和 report 使用。

### 3. 阅读并提取

先读 `profile.md`、`overview.md`、`catalog.md`，再逐个读摘要。每个会话按 [references/rubric.md](references/rubric.md) 的"六问"做笔记：目标是什么、产出了什么、哪里返工或被纠正、用到哪些领域知识、用户是怎么和 Agent 配合的、去掉项目细节后还剩什么以及属于哪一层。两类地方要重点看：一是用户纠正 Agent 的轮次（⚑），那往往就是一条值得固化的规则；二是用户的配合方式，比如先给样例、在哪里停下来确认、要求先出什么中间物，这套方式在下一个业务场景大概率会沿用。

**会话多时并行处理。** 摘要总量超过约 15 万字符，或会话超过 8 个时，把摘要分批交给子代理并行阅读。每个子代理拿到 `profile.md`、`rubric.md` 和它负责的摘要路径，按 rubric 里的"会话笔记格式"返回笔记。跨会话的归并由你自己做，不要交给子代理，因为只有看到全部笔记才能判断复用度。

**需要原始代码时**：`sd files <session>` 列出该会话写过的文件，并标出文件是否还在磁盘上；`sd extract <session> <路径片段> --out <目录>` 会从会话记录里回放出文件最终内容，并自动脱敏。文件仍在磁盘上时，加 `--prefer-disk` 读磁盘上的版本。

### 4. 归并成候选

把各会话笔记里相似的东西合并成候选。同一模式在越多的会话里出现，复用度越高。每个候选判断以下几件事：

- **层级 layer**：`foundation` 基座、`industry` 行业资产、`project` 项目资产，判断标准见 rubric。项目资产也要列出来，因为用户想看到划分结果，但它们固定为 C 档，不会被固化。
- **形态 kind**：`rule`（行为规则、检查清单）、`rule+code`（规则加可执行脚本，首选形态）、`methodology`（方法论、框架）、`workflow`（跨工具的多步流程）、`interaction`（某类业务场景下人与 Agent 的协作方式及其工具）、`component`（可复用的代码模块）。
- **拼装关系 builds_on**：它建立在哪些已有 skill 或同批候选之上。
- **打分**：fit、reuse、leverage、maturity 四项，各 0–5 分，标准见 rubric。
- **去重 dedupe**：对照 `catalog.md`，判断是全新（`new`）、并入已有 skill（`merge`），还是已经有了（`duplicate`）。
- **落地方式 packaging.form**：独立 skill（`skill`）、记忆文件（`memory`，写进 CLAUDE.md 或记忆库的短规则），或者给已有 skill 补一份参考资料（`reference`）。

把结果写入 `runs/<run-id>/candidates.json`，格式见 [references/candidate-schema.md](references/candidate-schema.md)。宁缺毋滥：通常一次 20 个会话能提出 3–8 个像样的候选。凑数的候选会浪费用户的审核时间。没有值得固化的东西也是正常结果：写 `{"candidates": [], "none_reason": "..."}`，照常 validate、report、close，并向用户说明原因。

### 5. 校验、出报告、请用户决定

1. `sd validate`：修到没有 ERROR 为止。WARN 要看一眼，例如复用度打了高分但证据只来自一个会话。
2. `sd report`：生成 `report.md`，按 A/B/C 三档和优先级排序。
3. 给用户看报告。不要整份贴出，先讲 A 档，每条一两句，再附上报告路径。请用户逐条给出决定：采纳、合并到某个 skill、拒绝（附理由）或暂缓。
4. 每条决定用 `sd decide <run> <id> accept|merge|reject|defer --reason "..." [--target <skill>]` 记账。拒绝的理由要写清楚，下次提炼时能用来避免重复推荐。

### 6. 固化

对每个采纳的候选：

1. `sd scaffold <run> <id>` 在 skill-hub 克隆的 `skills/<id>/` 下生成草稿，包括 SKILL.md、`hub.yaml`（`status: draft`）、CHANGELOG、`references/evidence.md`（引用的会话片段）和 evals 占位。没有 skill-hub 克隆时，草稿生成在 `~/.session-distiller/drafts/`。
2. 按 Claude 官方 skill-creator 的流程把草稿补全：写清步骤和背后的原因，用 `sd extract` 取回原始代码放进 `scripts/` 并整理成通用版本，再从 `evidence.md` 里挑真实请求写评测用例。
3. 在 skill-hub 里运行 `npm run validate`。
4. **提交前先问用户。** 默认做法是新建分支 `skill/<id>`、提交、推送并开 Draft PR，不合并、不改 `status: published`，这两步由用户决定。用户明确说过可以直接提交时，就按他说的办。

对 `merge` 和 `reference` 的候选，在目标 skill 的源码里加内容并升小版本号，同样走 PR。对 `memory` 的候选，`sd scaffold` 会在 `~/.session-distiller/memory-drafts/` 生成记忆格式的草稿，拿给用户看，由用户决定放进哪个 CLAUDE.md 或记忆库。

### 7. 收尾

`sd close <run>` 把这次的会话标记为已处理。会话之后又有新内容（文件变大）时，会以 `changed` 状态重新出现。`sd status` 可以随时查看账本：处理过多少会话，以及各候选的状态。

## 源码、更新与反馈

- **唯一源码**：<https://github.com/D-Tony2020/skill-hub>（私有仓库），目录 `skills/session-distiller/`，分支 `main`。改 skill 只改源码仓库并走 PR，不要改已安装的副本，它会在下次更新时被覆盖。
- **安装**：插件市场用 `claude plugin marketplace add D-Tony2020/skill-hub`，然后 `claude plugin install session-distiller@blacklake-skill-hub`。也可以手动装：克隆仓库后运行 `python skills/session-distiller/scripts/install_local.py`。claude.ai 账号到仓库 Releases 下载 zip 上传。
- **自更新**：`sd update` 会拉取 `main` 并重新安装，输出含 `restart_session=yes` 表示新版本从下一个会话起生效。`sd version` 显示当前版本和来源提交。插件安装的副本改用 `/plugin update session-distiller`。
- **反馈**：skill 本身的问题记进 `~/.session-distiller/skill-feedback.md`，或在 skill-hub 提 issue，标题以 `[session-distiller]` 开头。用户要求你直接修时，在 skill-hub 克隆里新建分支，修改 `skills/session-distiller/` 并跑测试（`python -m unittest discover -s skills/session-distiller/tests`），升版本号、写 CHANGELOG，然后开 PR。

## 参考

- [references/rubric.md](references/rubric.md)：五问、打分标准、会话笔记格式、好坏候选的例子。**提取前必读。**
- [references/candidate-schema.md](references/candidate-schema.md)：`candidates.json` 字段说明和示例。
- [references/troubleshooting.md](references/troubleshooting.md)：错误码、数据源和隐私问题。
