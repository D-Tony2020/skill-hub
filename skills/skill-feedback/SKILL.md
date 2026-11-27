---
name: skill-feedback
description: 用某个 Skill 时遇到问题，帮用户把它整理成一条能直接处理的反馈，送回这个 Skill 的源码仓库：先找到装的是哪个版本、从哪装的、源码在哪，判断是 Skill 的问题还是本机环境的问题，写出脱敏后的 issue 草稿（现象、期望、最小复现、环境），给用户看过后生成一键提交链接。用户说"这个 skill 有 bug / 不好用 / 帮我反馈一下""skill 该用的时候没用上""它不该出来的时候冒出来了""给 XX skill 提个建议""这个 skill 的文档看不懂"时使用，也用于使用者对 Hub 上任何 Skill 的问题回报。不用于修复 Skill 本身（作者用 skill-creator 改、用 skill-hub-ops 发版），也不用于排查与 Skill 无关的报错。
license: Proprietary
---

# skill-feedback：把使用中的问题送回源头

一个 Skill 装到几十个人手里，作者只在自己电脑上见过它。问题能不能修好，取决于反馈到作者手里时是不是**可处理的**：知道是哪个版本、能复现、没有夹带客户信息。这个 Skill 让使用者花一分钟，交出一条作者拿到就能动手的反馈。

## 源码、更新与反馈

- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/skill-feedback/`，分支 `main`。改动经 PR 合并。
- 更新：从 SkillHub 安装的用 `skillhub upgrade @blacklake/skill-feedback --registry <Hub 地址> --check`；从仓库装的 `git pull` 后 `node tools/hub/cli.mjs install skill-feedback --force`。
- 反馈：对本 Skill 本身的意见，同样用本 Skill，目标仓库就是上面这个。

## 执行环境

- 下文 `FB` 指 `node <本 SKILL.md 所在目录>/scripts/feedback.mjs`，Node 18+，没有其他依赖，不联网，不发送任何东西。
- `FB locate <skill>`：找到本机装着的副本，报告安装来源（SkillHub、源码仓库、claude.ai 同步、手工）、版本、SKILL.md 里写的源码仓库。
- `FB scrub <草稿>`：查密钥、令牌、内网地址、邮箱、个人目录和客户名（读 `~/.skill-qa/redact.txt`）；`--fix` 把能自动替换的替换掉。还有命中时退出码为 1。
- `FB url --repo <owner/repo> --title <标题> --body-file <草稿>`：生成预填好的 GitHub「新建 issue」链接，由用户自己打开、提交。草稿没脱敏干净时拒绝生成。
- issue 正文模板：[assets/issue.template.md](assets/issue.template.md)。本 Skill 的状态位见 [config.schema.json](config.schema.json)。

## 流程

先告诉用户你会做这 5 步。

### 1. 弄清是哪个 Skill、哪个版本

`FB locate <skill>`。记下版本、安装来源、源码仓库。

- 装了多份（比如用户级和项目级各一份，或者一份是 claude.ai 同步的）：先确认出问题时用的是哪一份。
- 版本落后于 Hub 上的最新版：先按 locate 给出的方式查一下有没有新版（`skillhub upgrade <坐标> --check`）。新版已经修了的，告诉用户升级即可，不再反馈。
- SKILL.md 没写源码仓库：这个 Skill 不是按 Hub 规范发布的。告诉用户找它的作者，或者给 Hub 管理员反馈"缺少源码仓库信息"。

### 2. 区分 Skill 的问题和环境的问题

先看这个 Skill 自己的「适用前提」和 troubleshooting（如有）。不满足前提（系统不对、没装依赖、网络不通）的，是环境问题：帮用户按 Skill 的说明解决，不提 issue。只有这些情况算 Skill 的问题：

| 类型 | 例子 |
| --- | --- |
| bug | 按说明操作，脚本报错或结果不对 |
| 不触发 | 用户说的话明明是它该管的，Agent 却没用它 |
| 误触发 | 它出现在不该出现的场合 |
| 文档看不懂 | 步骤缺失、术语不解释、和实际行为不一致 |
| 功能建议 | 现在能用，但有更好的做法 |

**安全问题**（Skill 会泄露凭据、执行危险操作、能被利用）不要发公开 issue。告诉用户直接私下联系 Hub 负责人，只描述到对方能定位为止。

### 3. 写草稿

照模板写到工作目录（例如 `~/.skill-feedback/<skill>-<日期>.md`，不要写进 Skill 的目录）。要点：

- **最小复现**：一两句对 Agent 说的话加上看到的结果，能让作者在自己电脑上重现。用户原话里的客户名、项目名换成"某客户""某项目"。
- **实际 vs 期望**：报错只摘关键几行，不贴整段日志。
- 不触发、误触发的，写出用户的原话（脱敏后），这正是作者要加进触发评测的用例。

### 4. 脱敏，给用户看

`FB scrub <草稿> --fix`，再看一遍剩下的命中，改到 `clean` 为止。然后把标题和正文完整给用户看。草稿会出现在公开或团队可见的地方，用户点头之前不提交。

### 5. 提交

- 默认：`FB url --repo <源码仓库> --title "[<skill>] <现象>" --body-file <草稿> --label skill:<skill>`，把链接给用户，请他用自己的 GitHub 账号打开并提交。链接太长时，给出新建 issue 的地址和草稿文件，请用户粘贴。
- 用户明确说"你直接帮我提"，而当前环境有 GitHub 工具和权限时，可以代为创建，正文末尾注明由 Agent 代提。
- Skill 是官方镜像（例如 skill-creator）或 SkillHub 内置（例如 skillhub-cli）：先提到我们自己的源码仓库，由维护者判断是否转给上游；不要直接往外部项目发。

提交后告诉用户：issue 链接（或待用户提交的链接）、有没有临时绕法、修好以后怎么升级（第 1 步记下的更新方式）。

## 铁律

1. 不发送用户没看过的内容；不在用户不知情时代表他发言。
2. 草稿里不出现客户名、密钥、内网地址、个人目录；脱敏没过不生成链接。
3. 环境问题就地解决，不往 Skill 仓库提；已在新版修复的，引导升级，不重复反馈。
4. 不修改已安装的 Skill 副本来"临时修好"；需要改的是源码，交给作者。
