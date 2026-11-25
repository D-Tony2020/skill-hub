# 故障处理与环境变化预案

规则：先看命令最后一行的 `code=`；不确定就 `bag doctor`，只处理第一个失败项；修完必须再跑 `bag doctor` 验证；新经验用 `bag learn` 记录。

「谁来做」：**A** = Agent 自己做；**D** = 需要 Dean（给他一行可复制的命令）。

## 一、Windows 本机

| 错误码 | 含义 | 处理 |
| --- | --- | --- |
| `E_LOCAL_NO_GIT` / `E_LOCAL_NO_SSH` | 缺 git / ssh | D：安装 Git for Windows；A：确认 Claude Code 用的是 Git Bash（`which ssh` 应为 `/usr/bin/ssh`）。不要用 `C:\Windows\System32\OpenSSH`，它对密钥文件权限要求不同 |
| ssh 报 `UNPROTECTED PRIVATE KEY FILE` / `bad permissions` | 用了 Windows 自带 OpenSSH，或密钥被移到了有 ACL 的位置 | A：确认 `which ssh` 是 `/usr/bin/ssh`（Git Bash）；仍报错则在 PowerShell 执行 `icacls "$env:USERPROFILE\.blacklake-auto-git\id_ed25519" /inheritance:r /grant:r "$env:USERNAME:R"` |
| bash 报 `$'\r': command not found` | 脚本被检出成 CRLF（core.autocrlf） | A：重新安装 Skill（仓库带 `.gitattributes` 强制 LF）；临时：`sed -i 's/\r$//' "$SKILL"/scripts/*.sh` |
| `E_LOCAL_NO_KEY` | 无 Agent 密钥 | A：`bag init`；新密钥需要 Mac 授权 → 见 `E_SSH_AUTH` |
| `E_NOT_PAIRED` | 还没配对 | A：走 setup-runbook；若之前配过但 `~/.blacklake-auto-git/state.env` 丢了，请 Dean 在 Mac 上 `sudo bash blacklake-airlock-installer.sh --check` 拿新的 BAG-PAIR 行 |
| `E_REPO_MISSING` | 未克隆或目录被删 | A：`bag clone [目录]` |
| `E_DIRTY` | 工作区有未提交改动 | A：提交或 `git stash`，再重试 |
| `E_USAGE` | 命令用法错 | A：`bag help` |

### Skill 自更新（`bag update`）

| 错误码 | 含义 | 处理 |
| --- | --- | --- |
| `E_SRC_CLONE` / `E_SRC_FETCH` | 拉不到 skill-hub 仓库（网络问题，或 Git 没有 Dean 的 GitHub 登录） | A：不影响日常工作，继续用当前版本。D：在 Git Bash 里交互执行一次 `git clone https://github.com/D-Tony2020/skill-hub ~/skill-hub` 或 `git -C ~/skill-hub fetch`，完成 GitHub 登录 |
| `E_SRC_DIRTY` | `~/skill-hub/skills/blacklake-auto-git` 下有本地改动 | A：如果是你为修 Skill 做的改动，提交到分支并开 PR；不需要的改动，确认后用 `git -C ~/skill-hub checkout -- skills/blacklake-auto-git` 丢弃 |
| `E_SRC_DIVERGED` | 本地 main 有未推送的提交 | A：把这些提交移到新分支并开 PR，然后 `git -C ~/skill-hub reset --hard origin/main`（先确认这些提交已备份到分支） |
| `E_SRC_PLUGIN` | 以插件方式安装 | D：执行 `/plugin marketplace update blacklake-skill-hub`，再 `/plugin update blacklake-auto-git` |
| `E_SRC_LAYOUT` / `E_SRC_INSTALL` | 仓库里的目录结构变了，或安装脚本失败 | A：读输出原文，`git -C ~/skill-hub log -5 -- skills/` 看最近的改动；处理不了就告诉 Dean |

## 二、Windows ↔ Mac（SSH）

| 错误码 | 含义 | 处理 |
| --- | --- | --- |
| `E_MAC_UNREACHABLE` | 按主机名、上次 IP、扫描本机所在 /24 网段都没找到 Mac | D：确认 ①Mac 开机未休眠（合盖会休眠）②两台机器连同一个热点/Wi-Fi ③Mac 远程登录开着（`sudo bash blacklake-airlock-installer.sh --check` 显示 `sshd listening`）。做完 A：`bag doctor`。若 Mac 在另一个网段（如开发机连了别的 Wi-Fi），请 Dean 发 `--check` 的新 BAG-PAIR 行，A：`bag pair` |
| `E_HOSTKEY_MISMATCH` | 地址上的机器指纹不对 | **停止**。可能连到了别的设备或被中间人。D：确认 Mac 是否重装系统/换机；是的话用 `--check` 的新 BAG-PAIR 行重新 `bag pair`。不要手动删 known_hosts 绕过 |
| `E_SSH_AUTH` | 找到 Mac，但拒绝 Agent 密钥 | D：在 Mac 执行 `sudo bash blacklake-airlock-installer.sh --add-key "<bag doctor 输出里给出的公钥>"`（用 doctor 打印的那一行）。常见原因：Windows 重装或删了 `~/.blacklake-auto-git`、Mac 重装了气闸 |
| `doctor` 显示 `airlock moved: now at x.x.x.x` | 热点给 Mac 换了 IP，已按指纹自动找回 | A：无需处理，可 `bag learn` 记录 |
| 扫描很慢（>30 秒） | 本机有多个网卡（VPN、虚拟机网卡），扫了多个网段 | A：可忽略；或请 Dean 发新 BAG-PAIR 行直接 `bag pair` |

## 三、Mac ↔ GitLab（来自 `doctor` 的 `mac.gitlab` 或推送失败）

| 错误码 | 含义 | 处理 |
| --- | --- | --- |
| `E_GITLAB_DNS` | Mac 解析不了 GitLab 域名 | D：Mac 的公司 VPN 断了，重新连接。A：之后 `bag doctor` |
| `E_GITLAB_UNREACHABLE` | 连不上 GitLab（超时/拒绝） | 同上；若 Dean 在 Mac 浏览器能打开 GitLab 而气闸不行：VPN 客户端可能是"代理型"（只代理浏览器）。D：在 Mac 上查 VPN 客户端的本地代理地址，A：请 Dean 执行 `sudo /usr/bin/python3 -c "import json;p='/usr/local/blacklake-airlock/airlock.conf.json';c=json.load(open(p));c['http_proxy']='http://127.0.0.1:<端口>';json.dump(c,open(p,'w'),indent=1)"` |
| `E_GITLAB_TLS` | 证书校验失败（公司自签 CA） | 首选：D 把公司根证书（.pem/.crt，IT 提供或从浏览器导出）放到 `/usr/local/blacklake-airlock/corp-ca.pem`，再把 `ca_file` 设为该路径（命令同上，改键名和值）。次选（需 Dean 明确同意，有中间人风险）：`ssl_verify` 设为 `false` |
| `E_GITLAB_AUTH` / `E_TOKEN_MISSING` | 令牌无效、过期或被撤销 | D：在 GitLab 新建令牌（setup-runbook 第 4 步），在 Mac 执行 `sudo bash blacklake-airlock-installer.sh --rotate-token` |
| `W_TOKEN_EXPIRING` | 7 天内过期 | A：提醒 Dean 提前轮换（同上）。不阻塞工作 |
| `E_GITLAB_FORBIDDEN` | 令牌权限不够 | D：令牌需 `write_repository`（推送）+ `read_api`（查 MR），角色至少 Developer；重建后 `--rotate-token` |
| `E_GITLAB_PROTECTED` | GitLab 侧推送规则/分支保护拒绝 | A：读 `AIRLOCK DETAIL` 原文；常见是提交信息格式或分支命名规则。按规则改（提交信息可在**未推送**前 amend），改不了的告诉 Dean |
| `E_GITLAB_NOT_FOUND` | 项目地址不对或令牌看不到项目 | D：确认项目地址（是否迁移/改名）。地址变了：A 重新 `bag bundle --gitlab-url <新地址>`，D 重跑安装器（保留令牌和用户），A `bag doctor` |
| `E_GITLAB_SERVER` / `E_GITLAB_API_5xx` | GitLab 自身故障 | A：稍后重试；持续超过 30 分钟告诉 Dean |
| `W_LAST_SYNC_FAILED:<code>` | 后台同步最近一次失败 | 按 `<code>` 处理；在修复前代码可能是旧快照 |
| `E_TARGET_MISSING` / `E_REPO_MISSING`（Mac 侧） | 气闸仓库没有 main 或不存在 | 通常是首次同步失败导致。先解决 GitLab 连接，再 A：`ssh` 不可用时让 D 执行 `--check`；`bag sync` 会触发同步 |

## 四、推送策略拒绝（`AIRLOCK REJECT`）

| 错误码 | 处理（A） |
| --- | --- |
| `E_POLICY_PREFIX` | 分支改名：`git branch -m deans-cc/<主题>`，再推 |
| `E_POLICY_PROTECTED` | 你在推 main 或受保护分支：`git switch -c deans-cc/<主题>`（带着提交），再推 |
| `E_POLICY_REF` | 不能推 tag 等非分支引用 |
| `E_POLICY_FORCE` | 你改写了已推送的历史（amend/rebase）。恢复：`git reset --hard origin/<分支>` 前先 `git branch backup/<x>` 备份，再用新提交重做改动；或开新分支新 MR |
| `E_POLICY_DELETE` | 不删远端分支，合并后 GitLab 会自动删 |
| `E_POLICY_SECRET` | 疑似密钥。若是真密钥：从**所有**未推送提交中删除（`git reset --soft origin/main` 后重新提交，或交互式改写本地未推送提交），并提醒 Dean 该密钥可能需要轮换。若是测试假数据：改成明显的占位符（如 `AKIA_EXAMPLE`）。确属误报且必须提交：请 Dean 决定是否把 `secret_scan` 改为 `warn` |
| `E_POLICY_SIZE` / `E_POLICY_FILE_SIZE` | 移除大文件/构建产物，加 `.gitignore`；确需大文件请 Dean 评估（Git LFS 暂不支持，二期） |
| `E_POLICY_NAME` | 分支名只用小写字母、数字、`-`、`/`、`.` |
| `E_UPSTREAM_DIVERGED` | GitLab 上该分支被改过（Dean 网页编辑/应用建议）：`bag sync` → `git pull --no-rebase origin <分支>` → 解决冲突 → 再推 |

## 五、其它

| 现象 | 处理 |
| --- | --- |
| `E_PUSH_UNKNOWN` / `E_UNKNOWN` | 走 SKILL.md「未知情况」流程：收集 `bag doctor`、`bag log 50`、完整输出 → 假设 → 验证 → `bag learn` → `skill-feedback.md` |
| `versions ... MISMATCH` | 见 iteration.md「升级 Mac 端」 |
| 仓库含 submodule 指向内网地址 | 气闸只放行一个仓库，子模块拉不到。告诉 Dean，属于二期扩展（多仓库气闸） |
| 仓库使用 Git LFS | 气闸不转发 LFS 对象。告诉 Dean，二期扩展 |
| 构建需要内网私有包源（Nexus 等） | 当前不支持（约定依赖走公网），告诉 Dean |
| MR 没自动创建（推送成功但 `mr=unknown`） | `bag mr` 查一次；若确实没有，GitLab 可能关闭了 push options。告诉 Dean 在网页手动建 MR，并 `bag learn` 记录 |

## 环境变化应对表（主动预案）

| 变化 | 你会看到 | 预案 |
| --- | --- | --- |
| 热点重连，Mac 换 IP | 命令短暂变慢，`airlock moved` | 自动按指纹重新发现，无需处理 |
| 换了网络（公司/家里 Wi-Fi） | `E_MAC_UNREACHABLE` | 两台机器必须同网段；请 Dean 两边连同一网络，或发新 BAG-PAIR 行 |
| Mac 休眠/合盖 | `E_MAC_UNREACHABLE` | 请 Dean 唤醒；建议安装时选保持唤醒（`pmset -c sleep 0`），合盖仍会休眠 |
| Mac VPN 断开 | push 被拒 `E_GITLAB_DNS/UNREACHABLE`；sync 带 `upstream_refresh_failed` | 本地开发可继续；推送前请 Dean 重连 VPN |
| 令牌到期 | `W_TOKEN_EXPIRING` → `E_GITLAB_AUTH` | 提前提醒轮换 |
| macOS 大版本升级 | 可能重置 sshd 配置或远程登录 → `E_MAC_UNREACHABLE` / `E_SSH_AUTH` | 请 Dean 重跑安装器（幂等，保留令牌和仓库） |
| Windows 重装 / 换开发机 | `E_LOCAL_NO_KEY` 或 `E_NOT_PAIRED` | `bag init` → Dean `--add-key "<新公钥>"` → 请 Dean 发 `--check` 的 BAG-PAIR 行 → `bag pair` |
| Dean 换了一台内网 Mac | `E_HOSTKEY_MISMATCH` 或找不到 | 在新 Mac 走完整安装，`bag pair` 新行 |
| GitLab 地址/项目迁移 | `E_GITLAB_NOT_FOUND` | 重新 bundle + Dean 重跑安装器 |
| 主分支改名（如 main→master） | `start` 报找不到 origin/main | 重新 `bag bundle --target <新名>`，Dean 重跑安装器；`bag pair` 后 PREFIX/TARGET 会从 Mac 同步 |
| 新增分支前缀需求 | — | 同上，`--prefix` |
