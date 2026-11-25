# 首次搭建 Runbook

目标：Windows 开发机上的 Agent 能通过内网 Mac 的气闸读写 GitLab 单仓库。Dean 只需在 Mac 上做 4 件事：连 VPN、建 token、运行安装器、把一行配对信息发回。

## 0. 前置条件（Agent 自查）

| 项 | 检查 | 不满足时 |
| --- | --- | --- |
| Git for Windows（含 Git Bash、ssh、ssh-keygen、ssh-keyscan） | `git --version && ssh -V` | 让 Dean 安装 Git for Windows（默认选项即可），装完重开 Claude Code |
| 两台机器在同一网络 | 无法自查，问 Dean | 都连同一个手机热点或同一 Wi-Fi |
| Mac 能访问 GitLab | 无法自查 | Dean 在 Mac 浏览器能打开 GitLab 项目页即可 |

## 1. 收集参数（问 Dean，一次问完）

> 我需要两样东西来生成 Mac 端安装器：
> 1. GitLab 项目的 HTTPS 克隆地址：打开项目页 → 右上角 "Clone" → 复制 "Clone with HTTPS"（形如 `https://gitlab.xxx.com/组/项目.git`）。
> 2. 确认一下：Agent 分支用 `deans-cc/` 开头、合并目标是 `main`，对吗？

如果 Dean 只能给 SSH 地址（`git@...`），把它改写成 `https://<同一主机>/<同一路径>.git` 并请他确认能在浏览器打开 `https://<主机>`。

## 2. 生成安装器

```bash
bag init
bag bundle --gitlab-url "https://gitlab.xxx.com/组/项目.git"   # 可选 --prefix deans-cc/ --target main
```

输出安装器路径和 sha256。安装器是**单个自包含 bash 文件**（安装逻辑 + airlock.py 源码 + Agent 公钥），Dean 可以打开审阅。

## 3. 传到 Mac（任选其一）

**A. 热点直传（推荐）**：后台运行 `bag serve-bundle`（默认端口 8765，只服务一次，路径带随机串）。它会打印若干行 `curl -fsSLo blacklake-airlock-installer.sh http://<IP>:8765/<随机串> && echo "<sha256>  blacklake-airlock-installer.sh" | shasum -a 256 -c - && sudo bash blacklake-airlock-installer.sh`：先核对 sha256，下载内容被改过就不会执行。把**和热点同网段**的那一行发给 Dean（手机热点常见网段：iPhone `172.20.10.x`，安卓 `192.168.43.x` 等）。Windows 防火墙弹窗时请 Dean 选"允许（专用网络）"。

**B. 手动**：把安装器文件通过微信文件传输助手 / AirDrop（经手机）/ U 盘给 Dean，放到 Mac 的「下载」目录。

手动传的，让 Dean 在 Mac 上执行 `bag bundle` 打印的 "On the Mac run" 那一行（先 `cd ~/Downloads`）：它先核对 sha256，一致才 sudo 执行。热点直传那一行已内置核对。**任何方式都不要让 Dean 跳过核对直接 `sudo bash`。**

## 4. Dean 在 Mac 上操作（发给他的原话模板）

> 请在 **Mac** 上按顺序做：
> 1. 连上公司 VPN，确认浏览器能打开 GitLab 项目页。
> 2. 在 GitLab 项目里建一个令牌：项目页左侧 **设置 (Settings) → 访问令牌 (Access Tokens)** → 添加新令牌：名称 `blacklake-airlock`，角色 **Developer**，范围勾选 **read_api** 和 **write_repository**，过期时间按公司规定（建议 90 天）。点创建后**复制令牌**（只显示一次）。
>    - 如果项目里没有"访问令牌"菜单（管理员关闭了项目令牌），改用个人令牌：右上角头像 → 偏好设置 → 访问令牌，范围同上。
> 3. 打开「终端」，执行：`cd ~/Downloads && sudo bash blacklake-airlock-installer.sh`，输入 Mac 开机密码。
> 4. 提示 `GitLab token:` 时粘贴刚才的令牌（输入不会显示），回车。问是否保持唤醒时建议输入 `y`。
> 5. 最后会打印一行以 `BAG-PAIR` 开头的文字，把这一整行发给我。
>
> 令牌只保存在这台 Mac 上一个专用账户里，不会发给我。

安装器可能出现的情况及应对：

| 安装器输出 | 处理 |
| --- | --- |
| `Command Line Tools ... missing` | 弹出系统安装窗口，Dean 点"安装"，完成后重跑同一命令 |
| `Could not enable Remote Login automatically` | Dean 打开 系统设置 → 通用 → 共享 → 打开「远程登录」，然后 `sudo bash blacklake-airlock-installer.sh --check`，把新的 BAG-PAIR 行发回 |
| `first sync failed ... E_GITLAB_DNS / UNREACHABLE` | Mac 的 VPN 没连上或断了；连好后 `--check` |
| `first sync failed ... E_GITLAB_AUTH / FORBIDDEN` | 令牌错误或权限不够；`sudo bash blacklake-airlock-installer.sh --rotate-token` 重新粘贴 |
| `first sync failed ... E_GITLAB_TLS` | 公司自签证书；见 troubleshooting.md `E_GITLAB_TLS` |
| `ip=unknown` | 无所谓，配对会通过主机名或扫描网段找到 Mac |

## 5. 配对与克隆

```bash
bag pair "BAG-PAIR v=1.0.0 host=xxx.local ip=172.20.10.3 fp=SHA256:... user=airlock"
bag doctor          # 期望 RESULT ok
bag clone           # 默认 ~/blacklake/<项目名>，也可 bag clone <目录>
```

`pair` 会核对 Mac 的 SSH 主机指纹（防止连到别的机器），把它固定在 `~/.blacklake-auto-git/known_hosts`。之后 Mac 的 IP 变了也能凭指纹重新找到。

## 6. 收尾

- `bag learn "首次搭建完成：Mac=<host>，GitLab=<地址>，令牌到期 <日期>"`（到期日从 `bag status` 的 `token.expires_at` 读）。
- 问 Dean 是否做冒烟推送：`bag start airlock-smoke-test` → 加一个无害提交（例如空的 `.airlock-smoke` 文件）→ `bag push --title "airlock 冒烟测试（可直接关闭）"`。成功后请 Dean 在 GitLab 关闭该 MR 并删除分支。
- 告诉 Dean：日常只需要 Mac 开着、连着 VPN 和同一网络。

## 卸载 / 重来

- Mac：`sudo bash blacklake-airlock-installer.sh --uninstall`（删除 airlock 用户、气闸仓库、令牌、sshd 策略、定时任务）。随后 Dean 应在 GitLab 撤销令牌。
- Windows：删除 `~/.blacklake-auto-git/`（密钥、配对、经验记录）和本地克隆目录。
