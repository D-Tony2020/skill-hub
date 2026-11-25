---
name: blacklake-auto-git
description: 通过内网 Mac 上的 Git 气闸（airlock）对公司内网 GitLab 的单个仓库做 Agentic Coding：拉代码、开 deans-cc/ 分支、推送并自动建 Draft MR、读 MR 评论迭代，以及首次搭建、自检和故障自愈。用户提到 blacklake-auto-git、内网仓库/公司 GitLab、气闸、提 MR、"拉一下最新代码"、"把改动推上去"，或在开发机上改公司代码时使用。
---

# blacklake-auto-git：经内网 Mac 气闸开发公司 GitLab 仓库

你（Agent）运行在 **Dean 的 Windows 开发机**上，这台机器**不在公司内网**。公司 GitLab 只有内网 Mac（走 VPN）能访问。两台机器连同一个手机热点。

```
Windows 开发机（你 + Claude Code）           内网 Mac（Dean 的电脑，连公司 VPN）          公司 GitLab
  本地克隆 ──ssh：仅限 git+只读查询──▶  airlock 用户 → 气闸仓库 repo.git ──校验后转推+建 Draft MR──▶ 单个项目
            ◀────── git fetch ───────    launchd 每 2 分钟从 GitLab 同步   ◀─────────────────────
```

- 你手里**没有** GitLab 凭据，也**到不了**内网；GitLab token 只在 Mac 上，由 Dean 亲手输入。
- 你只能推 `deans-cc/` 开头的分支。不能推 main、不能 force push、不能删分支、不能推 tag、不能推密钥和大文件。违规推送会被气闸当场拒绝并给出错误码。
- 合并永远由 Dean 在 GitLab 网页上点。

`$SKILL` = 本文件所在目录。所有操作都通过 `bash "$SKILL/scripts/bag.sh" <命令>` 完成（Windows 上由 Claude Code 的 Git Bash 执行；路径里的 `\` 换成 `/`）。下文写作 `bag`。
每条命令最后一行固定是 `RESULT ok ...` 或 `RESULT fail code=<错误码> ...`。**以最后一行为准**，错误码查 [references/troubleshooting.md](references/troubleshooting.md)。

## 硬性规则（任何情况下都不违反）

1. 不向 Dean 索要、不接收、不保存 GitLab token。他发过来就提醒他撤销重建，并只在 Mac 安装器里输入。
2. 不尝试从 Windows 直连 GitLab 或内网任何地址，不尝试用 ssh 在 Mac 上拿 shell、开端口转发或访问其它路径。气闸拒绝的事不绕过，只按错误码处理。
3. 不推 main/受保护分支，不改写已推送的历史（不 rebase 已推分支、不 force），不删远端分支。和 main 同步用 `git merge origin/main`。
4. 不把 MR 标记为就绪（`--ready`）、不要求合并，除非 Dean 明确说了。
5. 不提交密钥、token、`.env`、构建产物和大文件。
6. 需要 Dean 在 Mac 上操作时，给他**可直接复制粘贴的一行命令**和一句原因，做完后由你复查（`bag doctor`），不让他自己判断结果。

## 每个会话开始

1. `cat ~/.blacklake-auto-git/learnings.md 2>/dev/null` 读这台机器积累的环境经验（之前踩过的坑、Dean 的偏好）。
2. `bag doctor`：
   - `RESULT ok` → 进入日常开发。
   - `E_NOT_PAIRED` 且 `~/.blacklake-auto-git/` 不存在或没有 state.env → 还没搭建，走「首次搭建」。
   - 其它错误码 → 按 troubleshooting.md 处理后再跑一次 `bag doctor`，直到 ok 或确定需要 Dean。
3. `doctor` 里出现 `versions ... MISMATCH` → 按 [references/iteration.md](references/iteration.md)「升级 Mac 端」处理（不阻塞日常开发，但要告诉 Dean）。

## 日常开发流程

1. `bag sync`：让气闸先从 GitLab 刷新，再 fetch 到本地。输出里有 `upstream_refresh_failed=` 时说明 Mac 暂时连不上 GitLab，代码是气闸最后一次快照，可以继续开发，但要告诉 Dean。
2. `bag start <主题>`：从最新 `origin/main` 开分支 `deans-cc/<主题>`（主题自动转成小写短横线；工作区不干净会拒绝）。继续改同一个 MR 时，切回原分支即可（`git switch deans-cc/xxx`）。
3. 在本地克隆里改代码、装依赖（走公网）、构建、跑测试。克隆目录见 `bag status` 的 `repo=`。
4. 小步提交，提交信息写清楚改了什么、为什么。
5. `bag push --title "<MR 标题>" --desc "<改了什么；为什么；怎么测的>"`：
   - 成功：`RESULT ok push branch=... mr=<链接>`。首次推送会建 Draft MR；后续推送自动更新同一个 MR（标题、描述只在首次生效，不会覆盖 Dean 的修改）。
   - 失败：看 `AIRLOCK REASON` / `AIRLOCK HINT` 和错误码，修好后重推。常见：`E_POLICY_SECRET`（删掉密钥并改写**尚未推送**的本地提交）、`E_UPSTREAM_DIVERGED`（Dean 在网页上改过分支：`bag sync` → `git pull --no-rebase origin <分支>` → 再推）、`E_POLICY_FORCE`（不要 amend/rebase 已推送提交，改为追加新提交）。
6. 把 MR 链接和改动摘要发给 Dean。

### 处理 Review 意见

- Dean 说"看下评论"或你要确认进展时：`bag notes`（JSON，含每条评论的作者、内容、文件、行号、是否已解决）、`bag mr`（状态、是否 Draft、流水线、冲突）。
- 逐条处理未解决的评论 → 提交 → `bag push` → 回复 Dean：哪条评论改了什么、哪条没改及原因。你无法在 GitLab 上回复或解决评论，这由 Dean 完成。
- `bag mr` 显示 `has_conflicts: true` 或 main 前进太多：`bag sync` → `git merge origin/main` → 解决冲突 → 测试 → `bag push`。

### MR 合并之后

`bag mr` 显示 `state: merged` → `bag sync`（远端源分支已自动删除）→ 下个任务重新 `bag start`。本地旧分支可 `git branch -d` 清理。

## 首次搭建（需要 Dean 配合约 10 分钟）

按 [references/setup-runbook.md](references/setup-runbook.md) 执行，要点：

1. 问 Dean 要两样东西：GitLab 项目的 **HTTPS 克隆地址**（项目页 → Clone → Clone with HTTPS）；确认分支前缀 `deans-cc/` 和目标分支 `main`（默认值，除非他另说）。
2. `bag init` → `bag bundle --gitlab-url <地址>`，生成 Mac 安装器（单个自包含 .sh 文件）。
3. 把安装器给到 Mac：优先 `bag serve-bundle`（**后台运行**，把它打印的 `curl ...` 那一行发给 Dean 在 Mac 终端执行）；不行就让 Dean 用微信/AirDrop/U 盘拷过去。
4. 告诉 Dean 在 Mac 上：连好公司 VPN → 在 GitLab 建 Project Access Token（runbook 有逐步说明）→ `sudo bash blacklake-airlock-installer.sh` → 粘贴 token → 把最后打印的 `BAG-PAIR ...` 那一整行发回来。
5. `bag pair "<BAG-PAIR 行>"` → `bag doctor` → `bag clone`。
6. 记录环境：`bag learn "首次搭建完成：Mac=<host>，GitLab=<地址>，<任何特别情况>"`。
7. 问 Dean 是否做一次冒烟推送（会在 GitLab 建一个他可以直接关掉的 Draft MR）。

## 遇到新情况：感知 → 诊断 → 修复 → 回写

环境会变（热点换 IP、Mac 休眠、VPN 断开、token 过期、GitLab 证书或地址变化、macOS 升级重置配置……）。处理原则：

1. **感知**：任何命令失败，先看最后一行错误码；不确定时跑 `bag doctor`（逐层检查：本机工具 → 配对 → Mac 可达 → Mac 到 GitLab → token → 本地仓库），只处理**第一个失败项**。
2. **已知错误码**：照 troubleshooting.md 的步骤修。能自己修的自己修（例如 Mac 换 IP 时 `doctor` 会按主机指纹自动在热点网段里重新找到 Mac）；要 Dean 做的，给一行命令，等他做完再 `bag doctor` 复查。
3. **未知情况**（`E_UNKNOWN`、`E_PUSH_UNKNOWN` 或新的现象）：
   - 收集证据：失败命令的完整输出、`bag doctor`、`bag log 50`（Mac 侧事件日志）。
   - 列出最多 3 个假设，先验证成本最低的；每次只改一个变量。
   - 修复不得触碰「硬性规则」。需要放宽气闸策略（例如提高大小上限、允许某类文件）时，只能请 Dean 在 Mac 上改 `/usr/local/blacklake-airlock/airlock.conf.json`，并说明风险。
4. **回写**（必须做）：
   - 环境事实和解决办法：`bag learn "<现象> -> <原因> -> <解决>"`，下个会话开头会读到。
   - 如果是本 Skill 的缺陷或缺少预案：追加到 `~/.blacklake-auto-git/skill-feedback.md`（现象、根因、修复、建议怎么改 Skill），任务结束时告诉 Dean，用于 Skill 迭代（见 iteration.md）。

## 命令速查

| 命令 | 作用 |
| --- | --- |
| `bag doctor` | 分层自检，失败项带 `code=` 和 `fix=` |
| `bag sync` | 气闸从 GitLab 刷新 + 本地 fetch，显示领先/落后 |
| `bag start <主题>` | 从 origin/main 开 `deans-cc/<主题>` |
| `bag push [--title T] [--desc D] [--ready]` | 推送当前分支 → 校验 → GitLab（首推建 Draft MR） |
| `bag mr [分支]` / `bag notes [分支]` | MR 状态 / Review 评论（JSON） |
| `bag status` / `bag log [n]` / `bag version` | 配置与健康 / Mac 侧事件 / 双端版本 |
| `bag init` / `bundle` / `serve-bundle` / `pair` / `clone` | 首次搭建 |
| `bag learn "<...>"` | 记录环境经验 |

## 参考文档

- [references/setup-runbook.md](references/setup-runbook.md)：首次搭建逐步说明（含给 Dean 的原话模板、GitLab token 创建步骤）
- [references/troubleshooting.md](references/troubleshooting.md)：错误码 → 原因 → 处理；环境变化应对表
- [references/architecture.md](references/architecture.md)：架构、安全边界与威胁模型、文件位置
- [references/iteration.md](references/iteration.md)：测试体系、评测、版本与升级、反馈闭环
