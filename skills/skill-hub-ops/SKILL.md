---
name: skill-hub-ops
description: 运维团队的 Skill Hub（skill-hub 源码仓库 + SkillHub 看板）：新建 Skill 骨架、把存量 Skill 导入仓库、升版本、发版、提交到 SkillHub 并跟进扫描与审批、维护基建套件、同步官方镜像、回滚、下架、处理使用者反馈的 issue、巡检各端版本。用户说"把这个 skill 放进 Hub / 上架 / 发布 / 发新版 / 升级版本 / 回滚 / 下架 / 套件更新一下 / 同步一下官方 skill-creator / 看看 Hub 上的 issue / 看看各个 skill 走到哪一步了"，或提到 skill-hub 仓库、SkillHub、技能看板、blacklake-skill-hub 时使用。不用于质检（用 skill-qa）、对齐目标（用 skill-intent）、新人接入（用 hub-starter），也不用于使用者自己安装某个 Skill（用 skillhub-cli）。
license: Proprietary
---

# skill-hub-ops：Skill Hub 的 Agent 运维手册

Skill Hub 由三部分组成，**Git 仓库是唯一事实来源**，其他都从它派生：

| 部分 | 作用 | 谁来动 |
| --- | --- | --- |
| skill-hub 源码仓库（`skills/<name>/`） | 源码、版本、元数据（`hub.yaml`）、目标卡、质检报告 | Agent 开分支、提 PR；负责人合并 |
| GitHub Actions | 校验、生成 Claude 插件市场清单、发版时打 claude.ai 安装包 | 自动 |
| SkillHub 看板（团队空间，默认 `blacklake`） | 浏览、扫描、审核上架、套件 | Agent 提交；**负责人在网页批准** |

## 在 Skill 链里的位置

```
hub-starter 接入 → skill-creator / session-distiller 生产 → skill-intent 意图对齐 → skill-qa 质检
  → 【skill-hub-ops 入库与发布】 → skillhub-cli 安装与升级 → skill-feedback 反馈 → 【skill-hub-ops 分诊】→ 回到生产
```

本 Skill 只在两处接手：**有了"已对齐"的 INTENT.md 和"可分发"的 QA_REPORT.md 之后入库发布**，以及**收到反馈之后分诊**。前面的步骤缺了，交回对应的 Skill，不在这里补做。

## 适用前提

- 有 skill-hub 源码仓库的本地克隆和 GitHub 写权限（至少能推分支、开 PR）；Node 20+、git。
- 提交到 SkillHub 的那一步，需要能访问团队 Hub、CLI 已登录，并且由**发布人**（负责人或他指定的人）执行。
- 本 Skill 只服务这一套 Skill Hub（目标卡里 `bound_to: skill-hub`），不是通用的仓库运维工具。

## 源码、更新与反馈

- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/skill-hub-ops/`，分支 `main`。改动经 PR 合并，不改已安装的副本。
- 更新：从 SkillHub 安装的用 `skillhub upgrade @blacklake/skill-hub-ops --registry <Hub 地址> --check`；从仓库装的 `git pull` 后 `node tools/hub/cli.mjs install skill-hub-ops --force`。
- 反馈：用 skill-feedback，或在仓库提 issue，标题以 `[skill-hub-ops]` 开头。

## 0. 找到仓库和 Hub

- **仓库**：依次看环境变量 `SKILL_HUB_DIR`、`~/.skill-hub/profile.json` 的 `repo_dir`（hub-starter 记下的）、`~/skill-hub`。都没有就问用户，不要自己新克隆到别处。所有命令在仓库根目录执行，先 `git pull` 再 `npm ci`。下文 `hub` = `node tools/hub/cli.mjs`。
- **Hub 地址**：`--registry`、`SKILLHUB_REGISTRY`、`~/.skill-hub/profile.json`、`~/.skillhub/config.json`，都没有时发布脚本用 `http://localhost:8088`（一期发布人就在 Hub 所在的电脑上）。脚本开头会打印用的是哪个地址，核对一下。
- 本 Skill 的状态位见 [config.schema.json](config.schema.json)。

## 1. 铁律

1. 只改 `skills/` 下的内容；`.claude-plugin/marketplace.json` 只能用 `npm run build` 生成。
2. 每个改动走分支 + PR，不直接推 main，不合并 PR，不改 CI 让检查变绿。
3. 发布前 `npm run validate` 必须 0 错误；警告逐条看，能修就修，不能修的写进 PR 说明。
4. 已经提交到 SkillHub 的版本不能改内容：改了就升版本号（`hub bump`）。
5. SkillHub 的审核批准、例外放行、套件版本、空间和账号都是负责人的事：不代填密码，不绕过审核，不自批例外。
6. 不把密钥、内网地址、客户数据写进 Skill；仓库可能是公开的。

## 2. 看链路：每个 Skill 走到哪一步了

`hub chain` 每个 Skill 一行：目标卡（INTENT.md）、质检报告、仓库状态、是否在基建套件里，以及**下一步该交给谁**。用户问"现在什么情况"时先跑它，按 `next` 一列回答。`hub suite` 看基建套件，`hub status` 看本机安装。

## 3. 新建与导入

- **从零新建**：`hub new <name> --owner <负责人账号>`，生成 draft 骨架（SKILL.md 带「源码、更新与反馈」一节、hub.yaml、CHANGELOG、evals 占位、空白 INTENT.md）。然后按顺序交给 skill-intent 填目标卡、skill-creator 写正文和评测、skill-qa 质检。
- **导入存量 Skill**：前提是用户手里的**完整**源码已经有已对齐的 INTENT.md 和"可分发"的 QA_REPORT.md；没有就先交给 skill-intent / skill-qa。然后新建分支 `skill/<name>`，`hub import <源目录>`，逐条处理输出（缺文件、写死安装路径、依赖），细节见 [references/import.md](references/import.md)。导入后改过任何文件，就要在仓库副本上重跑 skill-qa。

## 4. 修改与升级

1. 改代码 → `hub bump <name> patch|minor|major -m "改了什么"`（改 VERSION 或 hub.yaml，并在 CHANGELOG 顶部加一条）。改了一句话目标或分发范围的，先重跑 skill-intent。
2. 重跑 skill-qa 出新报告（报告带内容哈希，改了文件旧报告就失效）。
3. 要发布时 `hub.yaml` 的 `status` 设为 `published`；`npm test`、`npm run validate`、`npm run build`，提交并开 PR，正文贴质检结论。
4. 合并后 CI 自动创建 GitHub Release `<name>@v<version>`，附 claude.ai 安装包 zip。

## 5. 提交到 SkillHub 并跟进到上架

由发布人执行，步骤和踩过的坑见 [references/publish.md](references/publish.md)。要点：

1. **先确认上一版已审完**。同一个 Skill 上一版还在审核队列里时，提交新版会把它顶替掉；先请负责人在网页上审完或驳回上一版。
2. `npm run publish:local -- --skill <name> --dry-run`，再去掉 `--dry-run` 正式提交。脚本会拒绝没有有效"可分发"报告的 Skill；`--skip-qa "<理由>"` 只能在负责人书面同意后用。
3. **提交成功不等于扫描通过**。等扫描结束，到 `<Hub 地址>/dashboard/reviews` 看每条扫描结论；BLOCKED 一律先修再发新版，必要行为的告警要写理由交负责人确认。
4. 负责人批准后，在一个全新的项目目录里 `skillhub install @blacklake/<name> --registry <Hub 地址> --scope project --agent claude-code` 装一次（`--dir` 不能和 `--scope`、`--agent` 同用），确认 SKILL.md 和 `.skillhub/metadata.json` 都在，再新开会话确认它能被触发。

## 6. 基建套件（`@blacklake/infra`）

新人靠 hub-starter 一条命令装齐基建，装的就是这个套件。成员和版本定义在仓库里 hub-starter 目录下的 `infra-suite.json`（`hub suite` 会读它），流程见 [references/suite-and-mirror.md](references/suite-and-mirror.md)：

1. 基建 Skill 发了新版、加入或退出套件 → 改 infra-suite.json 的成员版本、升 `metadata.version`；它随 hub-starter 发布，所以 hub-starter 同时升一个 patch，`entrySkill` 跟着改。
2. `hub suite --check` 必须通过（每个 `blacklake` 成员都在仓库里、已发布、版本一致、带 `infra` 标签）。
3. 所有成员在 SkillHub 上都是已发布状态后，`hub suite` 打印成员清单；SkillHub CLI 还不能发布套件，**由负责人在网页的套件编辑器里按这份清单建新版本**。

## 7. 官方镜像（skill-creator）

镜像的规则是"原样复制、固定 commit、只追加来源说明"，见 [references/suite-and-mirror.md](references/suite-and-mirror.md)。巡检时（建议每月）比较上游最新 commit 和 `hub.yaml` 的 `upstream.commit`；有更新就克隆上游，`hub upstream skill-creator --from <克隆>/skills/skill-creator --commit <sha>`，`hub bump skill-creator minor`，重跑 skill-qa，开 PR。不在镜像里改上游的内容；要改就提给上游，或者另做一个我们自己的 Skill。

## 8. 安装到本机

| 目标 | 做法 |
| --- | --- |
| 从 SkillHub（推荐给使用者） | 交给 skillhub-cli：`skillhub install @blacklake/<name> --registry <Hub 地址> --scope user --agent claude-code` |
| 从仓库（作者自测、未发布的版本） | `hub install <name>`：装到 `~/.claude/skills/<name>`，写入 `.hub-source.json`；不覆盖手工放的同名目录（用户同意后才 `--force`） |
| 通过插件市场 | `claude plugin marketplace add D-Tony2020/skill-hub`，再 `claude plugin install <name>@blacklake-skill-hub` |
| claude.ai 账号（含云端会话） | 没有写入 API：把 Release 里的 zip 给用户，请用户在 claude.ai → Customize → Skills 上传 |

装完提醒用户新开一个会话才会加载；`install` 输出的 `missing:` 是缺的依赖，要告诉用户怎么补。

## 9. 回滚与下架

已发布的版本不能改，所以回滚靠"往前修"，见 [references/rollback-retire.md](references/rollback-retire.md)：

- **单个使用者先恢复工作**：`skillhub install @blacklake/<name> --version <上一个好版本> --registry <Hub 地址>`，修好后再升级。
- **修复**：仓库里 `git revert` 出问题的提交（或修掉），`hub bump <name> patch`，质检、发布。套件里的成员版本同步改。
- **严重问题（安全、数据损坏）**：请负责人在网页上把出问题的版本下架，并在项目里通知已安装的人。
- **下架整个 Skill**：`hub.yaml` 的 `status` 改为 `archived`，从 infra-suite.json 去掉（如在其中），`npm run build`，提 PR；SkillHub 上的下架由负责人在网页做。本机副本在用户同意后删除。

## 10. 处理反馈

使用者通过 skill-feedback 提的 issue，标题形如 `[<skill>] <现象>`。分诊步骤见 [references/feedback-triage.md](references/feedback-triage.md)：复现 → 判断是 Skill 的问题还是环境问题 → 把复现用的那句话补进这个 Skill 的 evals（不触发、误触发的补进 trigger-evals）→ 交给 `hub.yaml` 的 owner 或用 skill-creator 修 → 升 patch、质检、发布 → 告诉用户怎么升级。是否在 GitHub 上回复 issue，由用户决定。

## 11. 巡检

按顺序跑，有问题就按对应小节处理：

1. `hub chain`：卡在某一步的 Skill。
2. `hub suite --check`：套件和仓库不一致。
3. `npm run qa`：已发布但没有有效质检报告的 Skill。
4. `hub status`：本机安装落后。
5. 上游镜像：比较 `upstream.commit` 和上游最新提交。
6. 仓库里未处理的反馈 issue。

## 12. 回复规范

每次操作完：一句话说结果；列出 PR 链接、版本号、扫描结论、需要用户或负责人做的事（合并 PR、网页审批、建套件版本、上传 zip、新开会话）。命令失败时给出原始报错的关键一行和你的判断，不要假装完成。
