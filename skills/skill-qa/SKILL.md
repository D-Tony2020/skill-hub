---
name: skill-qa
description: 检查一个 Skill 是否达到"可分发"级别，在导入 Skill Hub 之前跑。它会跑结构门禁、安全扫描（与 SkillHub 同款）、评测和评分表，给出"可分发 / 需修改 / 暂缓 / 不收录"的结论，并在 Skill 目录里写一份带内容哈希的 QA_REPORT.md。只有结论是"可分发"、且哈希与当前内容一致，hub import 才会接收。用户说"检查这个 skill 能不能上 Hub""上传前审一下""给这个 skill 做质检/验收""这个 skill 可以分发吗""导入前先过一遍规范"，或提到 skill-qa、可分发规范、验收门禁时使用。不用于从零写新 Skill（用 skill-creator），也不用于导入、发布或安装（用 skill-hub-ops）。
license: Proprietary
---

# skill-qa：可分发 Skill 的质检关

任何进入 Skill Hub 的 Skill 都必须先过这一关。检查在**用户手里的完整源码**上做，因为仓库和云端拿到的经常是残缺副本：claude.ai 同步下来的通常只有 SKILL.md。

本 Skill 的规范依据是《可分发 Skill 规范》：<https://claude.ai/artifact/BTAVqYxACPxLa7KQCk5Cwk>。门禁编号（G1–G14、S1–S4、R1）与规范一一对应。

## 源码、更新与反馈

- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/skill-qa/`，分支 `main`。只在仓库里改，经 PR 合并，不改已安装的副本。
- 更新：从 SkillHub 安装的用 `skillhub upgrade skill-qa`；从仓库装的在仓库里 `git pull` 后 `hub install skill-qa --force`。
- 反馈：误判、漏判、门禁不合理，在仓库提 issue 或 PR，附上 QA_REPORT.md 和被检查 Skill 的名字。规范的改动走同一个仓库。

## 执行环境

- 下文 `QA` 指 `node <本 SKILL.md 所在目录>/scripts/qa.mjs`。路径从本文件所在目录算，不要写死安装位置。需要 Node 18+，没有其他依赖。
- 安全扫描器（推荐）：`pip install cisco-ai-skill-scanner`，命令 `skill-scanner`。它和 SkillHub 服务端用的是同一个扫描器，本地先扫，上传时就不会意外。装不了就在 review.json 里写明原因，最终由上传时的服务端扫描兜底。
- 评测：用 Anthropic 官方的 skill-creator（任务评测做有无 Skill 的对照，触发评测用它的 `run_eval.py`，每条跑 3 次）。没有 skill-creator 时，G6/G7 没有结论，结果最多是"暂缓"。
- 工作文件（review.json 等）放在 `~/.skill-qa/work/`。不要放进被检查的 Skill 目录，否则会被打包。客户名脱敏词放在 `~/.skill-qa/redact.txt`，一行一个。

## 流程

先在用户面前列出这 9 步，再逐步做。每一步的结果要给证据（命令输出、文件行号），不凭印象下结论。

1. **定位完整源码**。问清目录。如果 SKILL.md 提到 `scripts/`、`references/` 但目录里没有，或者路径在 `~/.claude/skills/synced/`、插件缓存下，就停下来，请用户提供完整源码，不要拿残缺副本继续检查。
2. **静态门禁**：`QA check <目录>`，逐条看"未通过"和"待确认"。修法见 [references/fixes.md](references/fixes.md)。修改用户的文件之前先说明改什么，用户同意了再改。改完重跑。
3. **评测用例**。没有 `evals/evals.json`（任务用例 ≥ 3 条）和 `evals/trigger-evals.json`（不该触发 ≥ 3 条，要用"近似但不该用"的说法），就和用户一起写，格式见 [references/evals.md](references/evals.md)。用例要用户确认，因为它定义了这个 Skill 应该做到什么。
4. **跑评测**：按 [references/evals.md](references/evals.md) 用 skill-creator 跑任务评测（含不装 Skill 的基线）和触发评测，记下通过数。
5. **安装冒烟**：把打包副本装进一个全新目录（按 SkillHub 的形态：没有 tests/、evals/、hub.yaml，也没有无扩展名的文件），在这个副本上跑一条任务评测。G9 提示"无扩展名文件被读取"时，必须在去掉这些文件的副本上跑，确认有回退。
6. **安全扫描**：`QA scan <目录>`。每条 MEDIUM 及以上的告警逐条处置：
   - 真问题：修掉，重扫。
   - 必要行为或扫描器误报：按 [references/exceptions.md](references/exceptions.md) 起草一条例外，写清理由，**交给负责人（Dean）确认**。他确认后才写进 `qa-exceptions.json`，`approved_by` 填他的名字。Agent 不能自己批准例外。
7. **评分表**：按 [references/rubric.md](references/rubric.md) 给 5 项各打 0–2 分，每项写依据（引用 SKILL.md 的原文或行号）。
8. **出报告**：`QA review-template <目录> > ~/.skill-qa/work/<name>-review.json`，填好后 `QA report <目录> --review ~/.skill-qa/work/<name>-review.json`。脚本会重跑静态门禁和扫描、算结论，把 `QA_REPORT.md` 写进 Skill 目录。结论由脚本算，不由 Agent 写。
9. **回复用户**：结论、每个没通过的阻断项和修法、下一步。结论是"可分发"时，下一步交给 skill-hub-ops：`hub import <目录>`，提 PR 时附上 QA_REPORT.md。

## 结论的含义

| 结论 | SkillHub 分级 | 条件 | 下一步 |
| --- | --- | --- | --- |
| 可分发 | include | 所有阻断项通过 | 导入，提 PR |
| 需修改 | adapt | 有阻断项未通过 | 修完重跑 |
| 暂缓 | hold | 有阻断项还没结论（多半是评测没跑） | 补齐重跑 |
| 不收录 | reject | 评分"安全"为 0，或判定不该进 Hub（与已有 Skill 重复、没有实际用途） | 由 Dean 决定 |

## 铁律

1. 报告里有内容哈希。出报告之后改了任何文件（hub.yaml 和报告本身除外），报告就失效，必须重跑。`QA status <目录>` 可以查。
2. 不靠删文件、删用例、改阈值、改测试来过关。例如 SkillHub 会去掉无扩展名文件，那就让脚本有回退，不能把读取它的检查删掉。
3. 密钥、评测、评分表永远不能豁免。能豁免的只有 G3、G12–G14、S1、S2 和扫描告警，而且每条都要负责人确认。
4. 评测数字必须来自真的跑过的结果。没跑就留空，结论会是"暂缓"，如实告诉用户。
5. 检查别人的 Skill 时只改用户同意修改的地方。默认只读，修改先问。
