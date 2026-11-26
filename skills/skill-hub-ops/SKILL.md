---
name: skill-hub-ops
description: 运维 Skills 工厂的 Skill Hub：把存量 skill 导入 skill-hub 仓库、改版本、发版、发布到 SkillHub 看板、安装到本机、下架和巡检。用户说"把这个 skill 放进 Hub / 上架 / 发布 / 升级版本 / 装到我电脑 / 下架 / 看看各端版本"，或提到 skill-hub、SkillHub、技能看板、blacklake-skill-hub 时使用。
---

# skill-hub-ops：Skill Hub 的 Agent 运维手册

Skill Hub 由三部分组成，**Git 仓库是唯一事实来源**，其他都是从它派生的：

| 部分 | 作用 | 谁来动 |
| --- | --- | --- |
| skill-hub 仓库（`skills/<name>/`） | 源码、版本、元数据（`hub.yaml`） | Agent 开分支、提 PR；用户合并 |
| GitHub Actions | 校验、生成 Claude 插件市场清单、发版时打 claude.ai 安装包 | 自动 |
| SkillHub 看板（一期 http://localhost:8088） | 浏览、审计、审核上架 | Agent 提交；**用户在网页批准** |

## 0. 找到仓库

依次找：环境变量 `SKILL_HUB_DIR`、`~/skill-hub`。都没有就问用户，不要自己新克隆到别处。
所有命令在仓库根目录执行，需要 Node 20+，先 `git pull` 再 `npm ci`。下文 `hub` = `node tools/hub/cli.mjs`。

## 1. 铁律

1. 只改 `skills/` 下的内容和 `hub.yaml`；`.claude-plugin/marketplace.json` 只能用 `npm run build` 生成。
2. 每个改动走分支 + PR，不直接推 main，不合并 PR，不改 CI 去让检查变绿。
3. 发布前 `npm run validate` 必须 0 错误；警告要逐条看，能修就修，不能修的写进 PR 说明。
4. 已经上架的版本不能改内容：改了就升版本号（`hub bump`）。
5. SkillHub 的审核批准、namespace 创建、管理员密码都是用户的事：不代填密码，不绕过审核。
6. 不把密钥、内网地址、客户数据写进 skill；仓库可能是公开的。

## 2. 导入存量 skill

0. **先质检**：导入前必须用 skill-qa 在完整源码上跑出结论为"可分发"的 QA_REPORT.md（含内容哈希）。没有报告就先交给 skill-qa，不要直接导入。
1. 找到**完整**源码目录（含 `scripts/`、`references/`）。注意：`~/.claude/skills/synced/` 和 Claude 桌面端插件缓存里的是 claude.ai 同步下来的副本，通常**只有 SKILL.md**，不能当源码。
2. 在 skill-hub 仓库新建分支 `skill/<name>`，`hub import <源目录>`：复制到 `skills/<name>/`，状态为 draft，版本取 VERSION / plugin.json / 默认 0.1.0，去掉 `.claude-plugin/`、缓存目录。输出的 `qa:` 一行说明报告是否仍然有效；导入后改过文件就要在仓库副本上重跑 skill-qa。
3. 逐条处理输出：
   - `refers to files that are not in the skill folder`：源码不全，回去找；若属于依赖的另一个 skill，写进 `requires.skills`。
   - `hardcodes an install path`：把 `~/.claude/skills/<name>` 这类写死的路径改成"本 SKILL.md 所在目录"，否则通过插件市场或 SkillHub 安装后会找不到脚本。
4. 在 `hub.yaml` 写依赖：
   ```yaml
   requires:
     skills: [drawio-skill]     # 其他 skill
     commands: [py, draw.io]    # 需要在 PATH 上的命令
     env: [ARCH_DIAGRAMS_ROOT]  # 需要的环境变量
   ```
5. `npm run validate` 和 `npm run qa -- <name>` 通过后提 PR，说明来源、去掉了什么、还有哪些警告，并贴上 QA 报告的结论和门禁表。

## 3. 修改与升级

1. 改代码 → `hub bump <name> patch|minor|major -m "改了什么"`（自动改 VERSION 或 hub.yaml，并在 CHANGELOG 顶部加一条，补全内容）。
2. 要发布时把 `hub.yaml` 的 `status` 设为 `published`。
3. `npm test`、`npm run validate`、`npm run build`，提交并开 PR。
4. 用户合并后，CI 自动创建 GitHub Release `<name>@v<version>`，附 claude.ai 安装包 zip。

## 4. 发布到 SkillHub 看板

前提：本机 SkillHub 在运行，CLI 已登录（`skillhub login --registry http://localhost:8088`，需用户在浏览器点确认），namespace `blacklake` 已由用户建好。

```
npm run publish:local -- --dry-run     # 先让服务端校验
npm run publish:local                  # 提交所有 published 的新版本
```

发布脚本会拒绝没有有效"可分发"报告的 Skill（`report missing / stale`）。正确做法是补跑 skill-qa；`--skip-qa "<理由>"` 只能在负责人亲口同意后用，并把理由告诉负责人。

提交后告诉用户：到 SkillHub 网页的审核队列批准。重复运行会跳过已提交的版本（记录在 `.hub-state.json`）；要重发用 `--skill <name> --force`。

## 5. 安装到本机

| 目标 | 做法 |
| --- | --- |
| 本机 Claude Code（推荐） | `hub install <name>`：装到 `~/.claude/skills/<name>`，写入 `.hub-source.json` 标记；不会覆盖用户手工放的同名目录（除非用户同意后加 `--force`） |
| 通过插件市场 | `claude plugin marketplace add <owner>/skill-hub`，再 `claude plugin install <name>@blacklake-skill-hub` |
| 通过 SkillHub | `skillhub install <name> --agent claude-code --registry http://localhost:8088` |
| claude.ai 账号（含云端会话） | 没有写入 API：把 Release 里的 zip 给用户，请用户在 claude.ai → Customize → Skills 上传 |

装完提醒用户新开一个会话才会加载；`install` 输出的 `missing:` 是缺的依赖，要告诉用户怎么补。

## 6. 下架

1. `hub.yaml` 的 `status` 改为 `archived`，`npm run build`，提 PR（合并后从插件市场消失）。
2. SkillHub 上的下架和删除只能由用户在网页做，告诉用户入口。
3. 已装到本机的副本：用户同意后删除 `~/.claude/skills/<name>`。

## 7. 巡检

`hub status`：列出每个 skill 的仓库版本和本机安装状态（未安装 / 最新 / 过期 / 手工安装），以及缺失的依赖。`hub list` 看全部 skill 和状态。发现过期就 `hub install` 更新；发现"手工安装"先问用户是否交给 Hub 管理。

## 8. 回复规范

每次操作完：一句话说结果；列出 PR 链接、版本号、需要用户做的事（合并 PR、网页批准、上传 zip、新开会话）。命令失败时给出原始报错的关键一行和你的判断，不要假装完成。
