---
name: hub-starter
description: 把一个人接入团队的 Skill Hub（SkillHub）：装好 SkillHub CLI、用设备码登录、一次装齐基建套件（写 Skill、意图对齐、质检、上架、安装、反馈的全套工具），按角色补齐作者要的仓库和 Git 配置，最后自检。用户说"帮我接入 Skill Hub""我是新来的，怎么用 Hub""装一下基建 Skill""配置 skillhub""Hub 连不上 / 登录过期了""换了电脑重新接入"，或第一次提到团队 Skill Hub、技能看板时使用。它是 Skill Hub 生命周期的第 0 步；已接入后要找或装某个具体 Skill，用 skillhub-cli；要发布或运维 Hub，用 skill-hub-ops。
license: Proprietary
---

# hub-starter：接入 Skill Hub

第二个、第三个……第 N 个人进来时，只需要对 Agent 说一句"帮我接入 Skill Hub"。这个 Skill 让 Agent 把从零到"全套工具可用"的路一次走完，并且每一步都可以重复执行：已经做过的会被检查出来、跳过，不会重装或覆盖。

## 适用前提

- Agent 能在用户电脑上跑命令（Claude Code、Cowork 桌面端等）。claude.ai 网页和云端会话不读本机的 Skill 目录，那边见「claude.ai 与云端会话」一节。
- 用户能访问团队的 Hub（同一局域网或 Hub 管理员给的地址），并有 Hub 账号，或 Hub 开放了自助注册。
- Node.js 18 或更高版本（SkillHub CLI 需要）。

不满足时第一步就告诉用户缺什么、找谁，不要绕行（例如不要改用公网上别的 Hub）。

## 第一次怎么拿到本 Skill

本 Skill 自己也在 Hub 上，所以新人第一次通常这样说："读 `<Hub 地址>/registry/skill.md` 连接 SkillHub，然后安装 `@blacklake/hub-starter`，按它帮我接入"。`/registry/skill.md` 是 SkillHub 自带的接入指南，负责装官方 CLI 和连上这个 Hub；之后由本 Skill 接手。已经通过其他方式（插件市场、zip）装上本 Skill 的，直接从第 1 步开始，第 4 步装套件时会再装一份到用户目录，提醒用户卸掉先前那份，以免同一个 Skill 被加载两次。

## 源码、更新与反馈

- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/hub-starter/`，分支 `main`。改动经 PR 合并，不改已安装的副本。
- 更新：`skillhub upgrade @blacklake/hub-starter --registry <Hub 地址> --check`，看过计划再升级；整套基建用 `skillhub suite upgrade @blacklake/infra --check`。
- 反馈：用 skill-feedback（"这个 skill 有问题，帮我反馈"），或直接在仓库提 issue，标题以 `[hub-starter]` 开头。

## 执行环境

- 下文 `ST` 指 `node <本 SKILL.md 所在目录>/scripts/starter.mjs`。路径从本文件所在目录算，不要写死安装位置。
- 脚本自己不跑命令、不联网。`ST doctor` 解读体检结果：它列出几条只读命令（`skillhub version`、`skillhub whoami`、`skillhub list`、作者还有 `git --version`），Agent 照 `next` 原样执行、把输出存进 `~/.skill-hub/evidence/`，再跑一次 `ST doctor` 得到结论。`ST plan` 只打印安装命令，不执行。`ST profile set` 是唯一的写操作，写 `~/.skill-hub/profile.json`，只在用户确认之后调用。
- 基建套件的成员和版本在 [assets/infra-suite.json](assets/infra-suite.json)。不要凭记忆列成员。
- 本 Skill 的状态位见 [config.schema.json](config.schema.json)。

## 流程

先在用户面前列出这 6 步，再逐步做。每一步说结果，失败时给原始报错的关键一行。

### 1. 推断，然后一次问完

先跑 `ST doctor`（没有 Hub 地址时它会报缺），从输出里拿到能推断的值，再**用一条消息**问用户：

| 要问的 | 怎么推断 | 说明 |
| --- | --- | --- |
| Hub 地址 | `SKILLHUB_REGISTRY`、`~/.skillhub/config.json`、`~/.skill-hub/profile.json` | 推断不到就问；地址由 Hub 管理员提供。不要猜，也不要用 CLI 的公网默认地址 |
| 角色 | 无 | 作者（写 Skill、上架）/ 使用者（只装来用）/ 管理员（维护 Hub、审批）。一个人可以兼多个，按最大的那个装 |
| Agent | 当前所在的 Agent，通常是 `claude-code` | 只有用户同时用多个 Agent 时才问 |

用户确认后：`ST profile set registry=<地址> role=<角色> agent=<agent>`。

### 2. SkillHub CLI

看 doctor 的 `cli` 一行：

- `pass`：跳过。
- `skillhub 不在 PATH 上`：告诉用户要全局安装官方 CLI，然后 `npm install --global @astron-team/skillhub`，再 `skillhub version` 确认输出是 `SkillHub CLI <版本>`。
- `warn`（有一个叫 skillhub 的命令但不像官方 CLI）：**不要覆盖**。按 skillhub-cli 的规则查清它从哪个包装的，把路径和来源告诉用户，由用户决定。

### 3. 登录

doctor 的 `login` 为 `fail` 时：

1. 用户还没有 Hub 账号：请用户在浏览器打开 Hub 地址自助注册；Hub 不开放注册时，请 Hub 管理员开账号。
2. 后台运行 `skillhub login --registry <Hub 地址>`。它会打印一个网址和一个设备码，把这两样转给用户，请用户在浏览器里用**自己的账号**确认。命令在用户确认后自己结束。
3. `skillhub whoami --registry <Hub 地址>` 确认登录身份。

密码和令牌只由用户在浏览器或自己的终端里输入。Agent 不索要、不接收、不把它们写进任何文件或命令行。

### 4. 装齐基建套件

`ST plan` 打印两组命令：

1. **首选**：`skillhub suite install @blacklake/infra ...`，一次装齐、版本一致，以后用 `skillhub suite upgrade` 整体升级。
2. **回退**：服务端还没有这个套件（报 `suite` 不存在或服务端不支持套件）时，按角色逐个 `skillhub install`。使用者只装用得到的几个。

执行前告诉用户要装哪几个、装到哪（默认用户级 `~/.claude/skills/`）。命令带 `--json`，装完看输出里的 `ok`。遇到"本地有改动""来源冲突""指纹不符"就停下来报告，不加 `--force`，除非用户看过原因后明确同意。

### 5. 作者和管理员的补充配置

只在角色是作者或管理员时做：

- **Git 与 GitHub 账号**：`git --version`；`git config user.name`、`user.email` 已设置。作者通过 PR 向源码仓库提交 Skill，需要 GitHub 账号；没有仓库写权限时，请仓库负责人把他加为协作者（这一步由人在 GitHub 上做）。
- **源码仓库**：问用户放在哪个目录（建议 `~/skill-hub`），`git clone https://github.com/D-Tony2020/skill-hub.git <目录>`，然后 `ST profile set repo_dir=<目录> repo_url=https://github.com/D-Tony2020/skill-hub`。已经有克隆的，直接记下目录，不要再克隆一份。
- **质检用的身份词和客户名脱敏词**：告诉用户 skill-qa 会读 `~/.skill-qa/identity.txt`（作者姓名、常用分支前缀、账号，用来查有没有写死在 Skill 里）和 `~/.skill-qa/redact.txt`（客户名，一行一个）。脱敏词由用户自己维护，Agent 不替用户收集客户名。

### 6. 自检与下一步

按 doctor 的 `next` 重新采一遍体检输出，再跑一次 `ST doctor`，全部 `ok` 或只剩用户知情的 `warn` 才算完成。然后告诉用户：

- **新开一个会话**，新装的 Skill 才会加载（已经在跑的会话看不到它们）。
- 接下来想做什么，直接这样说：

| 想做的事 | 这样说 | 用到的 Skill |
| --- | --- | --- |
| 找现成的 Skill | "Hub 里有没有做 XX 的 Skill" | skillhub-cli |
| 写一个新 Skill | "帮我做一个 XX 的 Skill" | skill-creator |
| 从过去的会话里提炼 Skill | "看看我最近的会话里有什么值得做成 Skill" | session-distiller（如已安装） |
| 上架前对齐目标 | "这个 Skill 想给团队用，先对齐一下目标" | skill-intent |
| 质检 | "这个 Skill 能上 Hub 吗" | skill-qa |
| 入库、发布、下架、巡检 | "把它放进 Hub" | skill-hub-ops |
| 反馈问题 | "这个 Skill 有 bug，帮我反馈" | skill-feedback |

## claude.ai 与云端会话

claude.ai 网页、Cowork 云端会话、Claude Code 云端会话不读用户电脑上的 `~/.claude/skills/`。要在那里用基建 Skill：到源码仓库的 Releases 页面下载 `<skill>-<版本>.zip`，在 claude.ai → Customize → Skills 上传。上传要用户本人操作，Agent 只给出要下载哪几个文件。

## 回复规范

完成时回复：Hub 地址和登录身份、装了哪些 Skill（名称和版本）、哪些步骤跳过了及原因、用户还要做的事（新开会话、等协作者权限、上传 zip）。任何一步失败都如实说，不说"已接入"。
