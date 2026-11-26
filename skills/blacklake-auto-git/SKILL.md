---
name: blacklake-auto-git
description: 通过内网 Mac 上的 Git 气闸（airlock）对公司内网 GitLab 的单个仓库做 Agentic Coding：拉代码、开 Agent 专用分支、推送并自动建 Draft MR、读 MR 评论迭代，以及首次搭建、自检和故障自愈。用户提到 blacklake-auto-git、内网仓库/公司 GitLab、气闸、提 MR、"拉一下最新代码"、"把改动推上去"，或在不在内网的开发机上改公司 GitLab 代码时使用。
license: Proprietary
---

# blacklake-auto-git：经内网 Mac 气闸开发公司 GitLab 仓库

你（Agent）运行在**用户的 Windows 开发机**上，这台机器**不在公司内网**。公司 GitLab 只有一台内网 Mac（走 VPN）能访问。气闸让你只用 git 协议、只碰一个仓库的 Agent 分支。

```
Windows 开发机（你 + Claude Code）           内网 Mac（连公司 VPN）                      公司 GitLab
  本地克隆 ──ssh：仅限 git+只读查询──▶  airlock 用户 → 气闸仓库 repo.git ──校验后转推+建 Draft MR──▶ 单个项目
            ◀────── git fetch ───────    launchd 每 2 分钟从 GitLab 同步   ◀─────────────────────
```

## 适用前提（不满足就在第一步告诉用户"不适用"，不要硬做）

| 前提 | 怎么判断 |
| --- | --- |
| 开发机是 Windows，Claude Code 用 Git Bash 执行命令 | `uname -s` 含 `MINGW`/`MSYS`；Linux/macOS 开发机未测试，可以尝试但要先告诉用户 |
| 有一台能连公司 VPN 的 Mac，和开发机**在同一个网络**（同一个手机热点或同一个局域网），开发机能 ssh 到它 | `bag doctor` 的 `mac.ssh` 一项；跨网络（Mac 在公司、开发机在家）本版本**不支持** |
| 代码托管是 GitLab，用 HTTPS + Project Access Token 访问，一次只接一个项目 | 用户给的克隆地址；GitHub、Gitee、多仓库都不适用 |

只适用于黑湖内部团队。不满足时直说哪一条不满足、为什么，不要尝试端口转发、内网穿透之类的绕行。

## 角色

下文用角色称呼人，不写具体名字。一个人可以同时担任多个角色（最常见的是用户本人全包）。

| 角色 | 做什么 |
| --- | --- |
| **用户** | 和你对话、给你任务的人；开发机的主人 |
| **审批人** | 在 GitLab 网页上审 MR、改分支、点合并的人 |
| **气闸管理员** | 内网 Mac 的主人：运行安装器、输入 GitLab token、改气闸策略 |

搭建时问清楚后两个角色是不是用户本人（`bag learn` 记下来），之后需要谁做事就找谁；不是用户本人时，把要转交的话写好，由用户转发。

## 边界

- 你手里**没有** GitLab 凭据，也**到不了**内网；GitLab token 只在 Mac 上，由气闸管理员亲手输入。
- 你只能推**本项目约定的 Agent 分支前缀**开头的分支（见 `bag status` 的 `prefix=`，下文写作 `<前缀>`）。不能推目标分支或受保护分支、不能 force push、不能删分支、不能推 tag、不能推密钥和大文件。违规推送会被气闸当场拒绝并给出错误码。
- 合并永远由审批人在 GitLab 网页上点。

`$SKILL` = 本文件所在目录。所有操作都通过 `bash "$SKILL/scripts/bag.sh" <命令>` 完成（路径里的 `\` 换成 `/`）。下文写作 `bag`。
每条命令最后一行固定是 `RESULT ok ...` 或 `RESULT fail code=<错误码> ...`。**以最后一行为准**，错误码查 [references/troubleshooting.md](references/troubleshooting.md)。

## 硬性规则（任何情况下都不违反）

1. 不向任何人索要、接收或保存 GitLab token，也不拿它去连 GitLab。有人发过来就提醒对方：这个 token 已经泄露，要在 GitLab 撤销；如果它正是气闸在用的那个，撤销后请气闸管理员建新 token，在 Mac 上运行 `sudo bash blacklake-airlock-installer.sh --rotate-token` 输入新值（token 只在 Mac 安装器里输入）。
2. 不尝试从开发机直连 GitLab 或内网任何地址，不尝试用 ssh 在 Mac 上拿 shell、开端口转发或访问其它路径。气闸拒绝的事不绕过，只按错误码处理。
3. 不推目标分支或受保护分支，不改写已推送的历史（不 rebase 已推分支、不 force），不删远端分支。和目标分支同步用 `git merge origin/<目标分支>`。
4. 不把 MR 标记为就绪（`--ready`）、不要求合并，除非用户明确说了。
5. 不提交密钥、token、`.env`、构建产物和大文件。
6. 需要别人在 Mac 上操作时，给出**可直接复制粘贴的一行命令**和一句原因，做完后由你复查（`bag doctor`），不让对方自己判断结果。
7. 分支前缀、目标分支这类**项目约定**不自己拍板：先推断一个建议值，问用户确认后才写入。

## 配置项

本 Skill 的可配置项和来源见 [config.schema.json](config.schema.json)。只有两类值要问用户，并且在首次搭建时**一条消息问完**：

| 配置项 | 怎么来 | 存在哪 |
| --- | --- | --- |
| GitLab 项目 HTTPS 克隆地址 | 问用户（项目页 → Clone → Clone with HTTPS） | 开发机 `~/.blacklake-auto-git/state.env`、Mac 气闸配置 |
| Agent 分支前缀 | **开放槽位，没有默认值**。用 `bag init` 输出的 `suggested_prefix=` 作建议（取自 git 邮箱或用户名，如 `zhangsan-cc/`），请用户确认或改 | 同上；Mac 端为准，气闸据此拒绝其它分支 |
| 目标分支 | 默认 `main`，请用户确认（有的项目是 `master`/`develop`） | 同上 |
| 后两个角色是谁 | 问用户 | `bag learn` |

改配置：前缀或目标分支要变时，重新 `bag bundle --prefix ... --target ...` 并请气闸管理员重跑安装器（升级模式，token 不用重输）；不要只改开发机一侧。

## 源码仓库与更新

- **唯一源码**：<https://github.com/D-Tony2020/skill-hub>（私有仓库，黑湖成员的 GitHub 账号可访问），目录 `skills/blacklake-auto-git/`，分支 `main`。改 Skill 只改这里，经 PR 合并；不要直接改已安装的副本，它会在下次更新时被覆盖。
- **更新渠道跟着安装来源走**：
  - 从团队 SkillHub 安装的（副本里没有 `SOURCE` 文件）：用 `skillhub upgrade blacklake-auto-git` 更新，新版本要先过 SkillHub 审核。`bag update` 会返回 `E_SRC_HUB` 并提示这条命令。
  - 从源码克隆安装的（有 `SOURCE` 文件）：`bag update` 拉取 `main` 并重装（克隆默认在 `~/skill-hub`，`BAG_SRC` 可改）。结果中 `already_latest` 表示已是最新；`restart_session=yes` 表示新版本从**下一个会话**生效，告诉用户；`mac_upgrade_needed=yes` 按 [references/iteration.md](references/iteration.md)「升级 Mac 端」处理；`E_SRC_DOWNGRADE` 说明已装的比 main 新（多半来自未合并的 PR 分支），保持现状即可。
  - 以插件方式安装的：提示用户用 `/plugin` 更新（`E_SRC_PLUGIN`）。
- `bag version` 显示 Skill 版本、附带的 Mac 端版本和来源记录。
- **反馈与修改**：Skill 本身的缺陷写进 `~/.blacklake-auto-git/skill-feedback.md`，任务结束时告诉用户；也可以在源码仓库提 Issue。用户要求你直接修时，在源码克隆里新建分支，修改 `skills/blacklake-auto-git/` 并补测试（`bash skills/blacklake-auto-git/tests/run_all.sh`），升版本号、写 CHANGELOG，推送后开 PR，由仓库维护者合并。

## 每个会话开始

1. `cat ~/.blacklake-auto-git/learnings.md 2>/dev/null` 读这台机器积累的环境经验（之前踩过的坑、用户偏好、角色分工）。然后运行 `bag update`。它很快，失败（包括 `E_SRC_HUB`）也不影响后续工作：记一笔，继续往下做。
2. `bag doctor`：
   - `RESULT ok` → 进入日常开发。
   - `E_NOT_PAIRED` 且 `~/.blacklake-auto-git/` 不存在或没有 state.env → 还没搭建，先对照「适用前提」，再走「首次搭建」。
   - 其它错误码 → 按 troubleshooting.md 处理后再跑一次 `bag doctor`，直到 ok 或确定需要别人配合。
3. `doctor` 的 `versions` 一行出现 `MISMATCH`（Mac 端 airlock 版本和 Skill 附带的版本不一致）时，按 [references/iteration.md](references/iteration.md)「升级 Mac 端」处理（不阻塞日常开发，但要告诉用户）。

## 日常开发流程

1. `bag sync`：让气闸先从 GitLab 刷新，再 fetch 到本地。输出里有 `upstream_refresh_failed=` 时说明 Mac 暂时连不上 GitLab，代码是气闸最后一次快照，可以继续开发，但要告诉用户。
2. `bag start <主题>`：从最新的 `origin/<目标分支>` 开分支 `<前缀><主题>`（主题自动转成小写短横线；工作区不干净会拒绝）。继续改同一个 MR 时，切回原分支即可（`git switch <前缀>xxx`）。前缀还没配置时返回 `E_NOT_CONFIGURED`，回到「首次搭建」第 1 步确认前缀。
3. 在本地克隆里改代码、装依赖（走公网）、构建、跑测试。克隆目录见 `bag status` 的 `repo=`。
4. 小步提交，提交信息写清楚改了什么、为什么。
5. `bag push --title "<MR 标题>" --desc "<改了什么；为什么；怎么测的>"`：
   - 成功：`RESULT ok push branch=... mr=<链接>`。首次推送会建 Draft MR；后续推送自动更新同一个 MR（标题、描述只在首次生效，不会覆盖审批人的修改）。
   - 失败：看 `AIRLOCK REASON` / `AIRLOCK HINT` 和错误码，修好后重推。常见：`E_POLICY_SECRET`（删掉密钥并改写**尚未推送**的本地提交）、`E_UPSTREAM_DIVERGED`（有人在网页上改过分支：`bag sync` → `git pull --no-rebase origin <分支>` → 再推）、`E_POLICY_FORCE`（不要 amend/rebase 已推送提交，改为追加新提交）、`E_POLICY_PREFIX`（分支名不带约定前缀：`git branch -m <前缀><主题>` 再推）。
6. 把 MR 链接和改动摘要发给用户。

### 处理 Review 意见

- 用户说"看下评论"或你要确认进展时：`bag notes`（JSON，含每条评论的作者、内容、文件、行号、是否已解决）、`bag mr`（状态、是否 Draft、流水线、冲突）。
- 逐条处理未解决的评论 → 提交 → `bag push` → 回复用户：哪条评论改了什么、哪条没改及原因。你无法在 GitLab 上回复或解决评论，这由审批人完成。
- `bag mr` 显示 `has_conflicts: true` 或目标分支前进太多：`bag sync` → `git merge origin/<目标分支>` → 解决冲突 → 测试 → `bag push`。

### MR 合并之后

`bag mr` 显示 `state: merged` → `bag sync`（远端源分支已自动删除）→ 下个任务重新 `bag start`。本地旧分支可 `git branch -d` 清理。

## 首次搭建（需要气闸管理员配合约 10 分钟）

按 [references/setup-runbook.md](references/setup-runbook.md) 执行，要点：

1. 先对照「适用前提」。都满足后运行 `bag init`，拿到 `suggested_prefix=`。然后**一条消息**问用户：GitLab 项目的 HTTPS 克隆地址；Agent 分支前缀用建议值还是自定义；目标分支是不是 `main`；审批人和气闸管理员是不是他本人。用户确认后再继续，不要替他决定前缀。
2. `bag bundle --gitlab-url <地址> --prefix <前缀> --target <目标分支>`，生成 Mac 安装器（单个自包含 .sh 文件）。不带 `--prefix` 会被拒绝（`E_USAGE`），这是有意的。
3. 把安装器给到 Mac：优先 `bag serve-bundle`（**后台运行**，把它打印的 `curl ...` 那一行**原样**交给气闸管理员在 Mac 终端执行；这一行会先核对 sha256，不要删掉核对部分）；不行就用微信/AirDrop/U 盘拷过去。
4. 告诉气闸管理员在 Mac 上：连好公司 VPN → 在 GitLab 建 Project Access Token（runbook 有逐步说明）→ 执行安装命令（直传用 serve-bundle 给的那一行；手动传用 `bag bundle` 打印的 "On the Mac run" 那一行，都先核对 sha256 再 `sudo bash`）→ 粘贴 token → 把最后打印的 `BAG-PAIR ...` 那一整行发回来。
5. `bag pair "<BAG-PAIR 行>"` → `bag doctor` → `bag clone`。
6. 记录环境：`bag learn "首次搭建完成：Mac=<host>，GitLab=<地址>，前缀=<前缀>，目标=<目标分支>，审批人=<本人/他人>，气闸管理员=<本人/他人>，<任何特别情况>"`。
7. 问用户是否做一次冒烟推送（会在 GitLab 建一个可以直接关掉的 Draft MR）。

## 遇到新情况：感知 → 诊断 → 修复 → 回写

环境会变（热点换 IP、Mac 休眠、VPN 断开、token 过期、GitLab 证书或地址变化、macOS 升级重置配置……）。处理原则：

1. **感知**：任何命令失败，先看最后一行错误码；不确定时跑 `bag doctor`（逐层检查：本机工具 → 配对 → Mac 可达 → Mac 到 GitLab → token → 本地仓库），只处理**第一个失败项**。
2. **已知错误码**：照 troubleshooting.md 的步骤修。能自己修的自己修（例如 Mac 换 IP 时 `doctor` 会按主机指纹在同网段里重新找到 Mac）；要别人做的，给一行命令，等对方做完再 `bag doctor` 复查。
3. **未知情况**（`E_UNKNOWN`、`E_PUSH_UNKNOWN` 或新的现象）：
   - 收集证据：失败命令的完整输出、`bag doctor`、`bag log 50`（Mac 侧事件日志）。
   - 列出最多 3 个假设，先验证成本最低的；每次只改一个变量。
   - 修复不得触碰「硬性规则」。需要放宽气闸策略（例如提高大小上限、允许某类文件）时，只能请气闸管理员在 Mac 上改 `/usr/local/blacklake-airlock/airlock.conf.json`，并说明风险。
4. **回写**（必须做）：
   - 环境事实和解决办法：`bag learn "<现象> -> <原因> -> <解决>"`，下个会话开头会读到。
   - 如果是本 Skill 的缺陷或缺少预案：追加到 `~/.blacklake-auto-git/skill-feedback.md`（现象、根因、修复、建议怎么改 Skill），任务结束时告诉用户，用于 Skill 迭代（见 iteration.md）。

## 命令速查

| 命令 | 作用 |
| --- | --- |
| `bag doctor` | 分层自检，失败项带 `code=` 和 `fix=` |
| `bag sync` | 气闸从 GitLab 刷新 + 本地 fetch，显示领先/落后 |
| `bag start <主题>` | 从 `origin/<目标分支>` 开 `<前缀><主题>` |
| `bag push [--title T] [--desc D] [--ready]` | 推送当前分支 → 校验 → GitLab（首推建 Draft MR） |
| `bag mr [分支]` / `bag notes [分支]` | MR 状态 / Review 评论（JSON） |
| `bag status` / `bag log [n]` / `bag version` | 配置与健康 / Mac 侧事件 / 双端版本 |
| `bag init` / `bundle` / `serve-bundle` / `pair` / `clone` | 首次搭建 |
| `bag learn "<...>"` | 记录环境经验 |
| `bag update [--from-source]` | 从源码仓库更新本 Skill（SkillHub 安装的改用 `skillhub upgrade`） |

## 参考文档

- [references/setup-runbook.md](references/setup-runbook.md)：首次搭建逐步说明（含转交给气闸管理员的原话模板、GitLab token 创建步骤）
- [references/troubleshooting.md](references/troubleshooting.md)：错误码 → 原因 → 处理；环境变化应对表
- [references/architecture.md](references/architecture.md)：架构、安全边界与威胁模型、文件位置
- [references/iteration.md](references/iteration.md)：测试体系、评测、版本与升级、反馈闭环
