---
name: skill-qa
description: 检查一个 Skill 是否达到"可分发"级别，在导入 Skill Hub 之前跑。它默认只做静态分析：结构门禁、安全扫描（与 SkillHub 同款）和评分表，评测是可选项；给出"可分发 / 需修改 / 暂缓 / 不收录"的结论，并在 Skill 目录里写一份带内容哈希的 QA_REPORT.md。只有结论是"可分发"、且哈希与当前内容一致，hub import 才会接收。用户说"检查这个 skill 能不能上 Hub""上传前审一下""给这个 skill 做质检/验收""这个 skill 可以分发吗""导入前先过一遍规范"，或提到 skill-qa、可分发规范、验收门禁时使用。不用于从零写新 Skill（用 skill-creator），也不用于导入、发布或安装（用 skill-hub-ops）。
license: Proprietary
---

# skill-qa：可分发 Skill 的质检关

任何进入 Skill Hub 的 Skill 都必须先过这一关。检查在**用户手里的完整源码**上做，因为仓库和云端拿到的经常是残缺副本：claude.ai 同步下来的通常只有 SKILL.md。

本 Skill 的规范依据是《可分发 Skill 规范》：<https://claude.ai/artifact/BTAVqYxACPxLa7KQCk5Cwk>。门禁编号（G1–G16、S1–S4、R1）与规范一一对应。

"可分发"的意思是：换一个黑湖同事、换一个项目装上就能用，而不只是作者自己能用。所以除了结构和安全，还要查两件事：**G15 个人化耦合**（作者姓名、个人路径、个人分支前缀、邮箱写死在 Skill 里），**G16 配置清单**（凡是因人因项目而异的值，都要做成状态位，写进 `config.schema.json`，由 Skill 在首次使用时推断并请用户确认）。

## 源码、更新与反馈

- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/skill-qa/`，分支 `main`。只在仓库里改，经 PR 合并，不改已安装的副本。
- 更新：从 SkillHub 安装的用 `skillhub upgrade skill-qa`；从仓库装的在仓库里 `git pull` 后 `hub install skill-qa --force`。
- 反馈：误判、漏判、门禁不合理，在仓库提 issue 或 PR，附上 QA_REPORT.md 和被检查 Skill 的名字。规范的改动走同一个仓库。

## 执行环境

- 下文 `QA` 指 `node <本 SKILL.md 所在目录>/scripts/qa.mjs`。路径从本文件所在目录算，不要写死安装位置。需要 Node 18+，没有其他依赖。
- 安全扫描器（推荐）：`pip install cisco-ai-skill-scanner`，命令 `skill-scanner`。它和 SkillHub 服务端用的是同一个扫描器，本地先扫，上传时就不会意外。装不了就在 review.json 里写明原因，最终由上传时的服务端扫描兜底。
- 评测（可选）：默认不跑，结论只看静态分析。用户明确要求、或者负责人要求时，才用 Anthropic 官方的 skill-creator 跑任务评测和触发评测（G6/G7），结果写进报告供参考，不影响结论。跑法和已知的坑见 [references/evals.md](references/evals.md)。
- 工作文件（review.json 等）放在 `~/.skill-qa/work/`。不要放进被检查的 Skill 目录，否则会被打包。客户名脱敏词放在 `~/.skill-qa/redact.txt`，一行一个。
- G15 用的作者身份词：自动读 `git config user.name`/`user.email`、系统用户名、hub.yaml 的 owner；补充的写进 `~/.skill-qa/identity.txt` 或环境变量 `SKILL_QA_IDENTITY`（逗号分隔）。检查**别人的** Skill 时，先问作者叫什么、常用的分支前缀和账号，写进 identity.txt 再跑，否则只能查出路径、前缀和邮箱。本 Skill 自己的配置项见 [config.schema.json](config.schema.json)。

## 流程

先在用户面前列出这 8 步，再逐步做。每一步的结果要给证据（命令输出、文件行号），不凭印象下结论。

1. **定位完整源码**。问清目录。如果 SKILL.md 提到 `scripts/`、`references/` 但目录里没有，或者路径在 `~/.claude/skills/synced/`、插件缓存下，就停下来，请用户提供完整源码，不要拿残缺副本继续检查。
2. **静态门禁**：`QA check <目录>`，逐条看"未通过"和"待确认"。修法见 [references/fixes.md](references/fixes.md)。修改用户的文件之前先说明改什么，用户同意了再改。改完重跑。
3. **可分发化改造**（G15/G16 没过时）：按 [references/config-schema.md](references/config-schema.md) 盘点耦合点，把每个值归到固定、预设、实例、角色四层，人名改成角色，个人值改成状态位，写 `config.schema.json` 和首次引导。命名类的值（分支前缀、目录名、账号）是**开放槽位**：不带默认值，运行时推断一个建议值，问用户确认，可自定义。环境前提（操作系统、网络拓扑、依赖的外部系统）写进 SKILL.md 开头的「适用前提」，不满足时第一步就告诉用户不适用。改动先给用户看清单，同意后再改；这一步通常要升主版本号。
4. **打包副本检查**（G9）：脚本会检查打包副本是否自包含。提示"无扩展名文件被读取"时（SkillHub 打包会去掉这类文件），读代码确认缺了它也有回退，确认后在 review.json 写 `evals.smoke.ok=true` 并在 note 里写依据。
5. **安全扫描**：`QA scan <目录>`。每条 MEDIUM 及以上的告警逐条处置：
   - 真问题：修掉，重扫。
   - 必要行为或扫描器误报：按 [references/exceptions.md](references/exceptions.md) 起草一条例外，写清理由，**交给负责人确认**。负责人确认后才写进 `qa-exceptions.json`，`approved_by` 填负责人的名字。Agent 不能自己批准例外。
6. **评分表**：按 [references/rubric.md](references/rubric.md) 给 5 项各打 0–2 分，每项写依据（引用 SKILL.md 的原文或行号）。
7. **出报告**：`QA review-template <目录> > ~/.skill-qa/work/<name>-review.json`，填好后 `QA report <目录> --review ~/.skill-qa/work/<name>-review.json`。脚本会重跑静态门禁和扫描、算结论，把 `QA_REPORT.md` 写进 Skill 目录。结论由脚本算，不由 Agent 写。
8. **回复用户并提交**：结论、每个没通过的阻断项和修法、下一步。结论是"可分发"时，按「提交到 Skill Hub」做。

## 提交到 Skill Hub

所有 Skill 的源码统一放在 skill-hub 仓库，经 PR 进入，合并后再发布到 SkillHub。成员不直接用 skillhub CLI 上传。

1. 没有仓库权限时，请仓库负责人在 GitHub 上把你加为协作者。
2. 克隆仓库，新建分支 `skill/<name>`，用 skill-hub-ops 导入：`node tools/hub/cli.mjs import <目录>`。导入会复制 QA_REPORT.md，并打印报告是否仍然有效。
3. 在仓库里再跑一次 `QA status skills/<name>`。如果因为导入调整了文件，报告会失效，需要在仓库副本上重跑第 7 步。
4. 推送分支，开 PR，正文贴上报告的结论和门禁表。CI 会复核报告是否有效、静态门禁是否通过。
5. 合并后由负责人发布：`npm run publish:local -- --skill <name>`。没有有效"可分发"报告的 Skill 发布脚本会拒绝。再由负责人在 SkillHub 网页审批。

## 结论的含义

| 结论 | SkillHub 分级 | 条件 | 下一步 |
| --- | --- | --- | --- |
| 可分发 | include | 所有阻断项通过 | 导入，提 PR |
| 需修改 | adapt | 有阻断项未通过 | 修完重跑 |
| 暂缓 | hold | 有阻断项还没结论（多半是评分表、依赖确认或扫描处置没填） | 补齐重跑 |
| 不收录 | reject | 评分"安全"为 0，或判定不该进 Hub（与已有 Skill 重复、没有实际用途） | 由负责人决定 |

## 铁律

1. 报告里有内容哈希。出报告之后改了任何文件（hub.yaml 和报告本身除外），报告就失效，必须重跑。`QA status <目录>` 可以查。
2. 不靠删文件、删用例、改阈值、改测试来过关。例如 SkillHub 会去掉无扩展名文件，那就让脚本有回退，不能把读取它的检查删掉。
3. 密钥、评分表、配置清单永远不能豁免。能豁免的只有 G3、G12–G15、S1、S2 和扫描告警，而且每条都要负责人确认。G15 只在"必须写死"时豁免，例如源码仓库归属写明的账号。
4. 评测是可选的；跑了就如实写，数字必须来自真的跑过的结果，没跑就留空，不要编。
5. 检查别人的 Skill 时只改用户同意修改的地方。默认只读，修改先问。
