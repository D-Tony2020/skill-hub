---
name: skill-intent
description: 在质检和上架之前，先和 Skill 的生产者对齐这个 Skill 到底要做什么：起草一张目标卡（给谁用、解决什么、在哪些说法下触发、不做什么、成功标准、分发范围），查 Hub 和仓库里有没有重复的 Skill，把发散的目标收敛成一个，然后给出"已对齐 / 需澄清 / 驳回"的结论，写成 Skill 根目录的 INTENT.md，供 skill-qa 分诊和写评测用。用户说"这个 skill 想给团队用，先对齐一下目标""帮我理一下这个 skill 该做什么""这个想法值不值得做成 skill""上 Hub 前先过意图""Hub 里有没有和它重复的"，或者准备把一个 Skill 交给 skill-qa、而它还没有 INTENT.md 时使用。不用于检查结构和安全（用 skill-qa），也不用于动手写 Skill（用 skill-creator）。
license: Proprietary
---

# skill-intent：上架前先对齐目标

质检能判断一个 Skill "做得对不对"，判断不了它"做的是不是对的事"。目标没想清楚的 Skill，质检过了也没人用：描述写的是 A、正文做的是 B；一个 Skill 塞了三件事；Hub 里早就有一个一样的；或者它只是作者某天的一次性操作。这些问题越晚发现越贵，所以放在质检之前，由这个 Skill 先拦一道。

它的产出是一张**目标卡**（`INTENT.md`），后面每一步都以它为准：skill-qa 按其中的分发范围决定用哪套门禁，评测用例从它的触发说法和成功标准推出来，Hub 上的描述第一句也从它来。

## 源码、更新与反馈

- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/skill-intent/`，分支 `main`。改动经 PR 合并，不改已安装的副本。
- 更新：从 SkillHub 安装的用 `skillhub upgrade @blacklake/skill-intent --registry <Hub 地址> --check`；从仓库装的在仓库里 `git pull` 后 `node tools/hub/cli.mjs install skill-intent --force`。
- 反馈：用 skill-feedback，或在仓库提 issue，标题以 `[skill-intent]` 开头。判定规则的改动走同一个仓库。

## 执行环境

- 下文 `IT` 指 `node <本 SKILL.md 所在目录>/scripts/intent.mjs`，Node 18+，没有其他依赖。路径从本文件所在目录算。
- `IT init <Skill 目录>` 按 [assets/INTENT.template.md](assets/INTENT.template.md) 生成空白目标卡（已有就不覆盖）；`IT check <Skill 目录>` 校验字段和必填小节；`IT show <Skill 目录> --json` 输出结论，skill-qa 和仓库工具读的就是它。
- 判定规则（分发范围、收敛、驳回条件）在 [references/rules.md](references/rules.md)，第 4 步前读一遍。
- 本 Skill 的状态位见 [config.schema.json](config.schema.json)。

## 流程

先在用户面前列出这 6 步，再逐步做。

### 1. 找到 Skill 和它的生产者

- 已经写好的 Skill：问清目录。读 SKILL.md（描述和正文）、evals、README、CHANGELOG。
- 还只是想法：也可以先对齐，对齐后再交给 skill-creator 写，这样最省返工。
- 弄清**生产者**是谁：通常就是用户；如果用户在替别人检查，目标卡里的问题要由那位生产者回答，Agent 不替他编答案。

### 2. 先自己起草，不要先发问卷

`IT init <目录>`，然后根据已有材料把能填的都填上：一句话目标、给谁用、触发说法、不做什么、成功标准、输入输出、环境前提。每一项标出依据（"来自描述第 1 句""来自 evals 第 2 条""推断"）。推断不了的留空，留到第 4 步问。

同时找矛盾：描述和正文说的不是一件事；描述里的触发词正文根本不处理；正文做了描述没提的事。矛盾要原文引用出来。

### 3. 查重

- Hub：`skillhub search "<两三个核心词>" --registry <Hub 地址> --json`（没装 CLI 或没登录就跳过并说明）。
- 仓库：有源码仓库时 `node tools/hub/cli.mjs list`，再按名字和描述看有没有做同一件事的。
- 有相似的，列出它们和本 Skill 的差别。差别说不出来，就是重复（见 rules.md 的驳回条件）。

### 4. 一次问完，然后收敛

把第 2 步留空的、有矛盾的、和查重结果放在**一条消息**里问生产者，最多 5 个问题，每个问题附上你的推断，让他确认或改。必问的是分发范围：只自己用、团队用、全公司用，还是客户现场用；以及它是否只服务某一个平台（例如只用于运维这个 Hub 本身）。

收到回答后收敛：

- **一个 Skill 只做一件事**。目标里有两件以上能各自独立触发的事，建议拆开，并写明各自的一句话目标。
- **触发说法和不做什么各至少 3 条**。不该触发的要选"近似但不该用"的说法，并写明应该交给哪个 Skill。
- **成功标准要能逐条核对**，它们会直接变成评测的 expectations。"好用""高质量"不算。

### 5. 下结论

按 [references/rules.md](references/rules.md) 判定：

| 结论 | `verdict` | 什么时候 | 下一步 |
| --- | --- | --- | --- |
| 已对齐 | `aligned` | 目标单一、范围明确、成功标准可核对、和已有 Skill 不重复 | 交给 skill-qa |
| 需澄清 | `needs-clarification` | 还有问题生产者没回答，或回答本身互相矛盾 | 把问题清单交给生产者，答完重跑本 Skill |
| 驳回 | `rejected` | 命中驳回条件（重复、一次性、不需要 Skill、范围一期不收、不正当） | 说明理由和替代做法，交还生产者 |

结论由规则决定，不由谁的身份决定，也不为了让流程往下走而放宽。驳回不是否定这个人的工作，要给出能走的路：改进已有的那个 Skill、留作个人 Skill、拆小以后再来。

### 6. 写入并交接

1. 把目标卡给生产者看，确认后写入 `<Skill 目录>/INTENT.md`。它不进发布包，但会随源码进仓库，留作这个 Skill 为什么存在的记录。
2. `IT check <目录>` 必须通过。
3. 回复用户：结论、一句话目标、分发范围、需要生产者做的事。结论是"已对齐"时，告诉用户下一步说"这个 Skill 能上 Hub 吗"，交给 skill-qa；skill-qa 会读 INTENT.md 决定门禁，并用其中的触发说法和成功标准写评测。

## 什么时候要重新对齐

改了一句话目标、分发范围、或要新增一类触发场景时，重跑本 Skill 并更新 INTENT.md 的日期。只是修 bug、改措辞，不需要。

## 铁律

1. 问题要由生产者回答。Agent 可以推断、可以建议，不能替生产者确认他的意图。
2. 不因为 Skill 已经写完、写得很长、或作者资历深就降低判定标准；也不因为想法粗糙就驳回，粗糙的给"需澄清"。
3. 目标卡里不写客户名、密钥、内网地址；要举例时用"某客户""示例地址"。
4. 对齐只管"做什么"。结构、安全、可分发化的问题记在目标卡的「未决问题」里转给 skill-qa，不在这里下结论。
