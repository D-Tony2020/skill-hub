# 架构与安全模型

## 组件

| 位置 | 组件 | 说明 |
| --- | --- | --- |
| Windows 开发机 | Claude Code + 本 Skill | Agent 运行处，能访问 Anthropic 和公网包源 |
| | `scripts/bag.sh` | Agent 唯一的操作入口；只会 ssh 到 `bag-airlock` |
| | `~/.blacklake-auto-git/` | `id_ed25519`（Agent 专用密钥）、`ssh_config`、`known_hosts`（固定 Mac 指纹，HostKeyAlias 与 IP 解耦）、`state.env`、`learnings.md`、`skill-feedback.md`、`history.log`、`bundle/` |
| | 本地克隆（默认 `~/blacklake/<项目>`） | `origin = bag-airlock:repo.git`，`core.sshCommand` 指向上面的 ssh_config |
| 内网 Mac | macOS 用户 `airlock` | 隐藏、随机密码、SSH 仅公钥；只属于 `com.apple.access_ssh` 允许组 |
| | `/etc/ssh/sshd_config.d/100-blacklake-airlock.conf` | `Match User airlock`：`ForceCommand airlock.py gate`、无 TTY、无任何转发、无密码 |
| | `~airlock/.ssh/authorized_keys` | `restrict,command="... airlock.py gate"`（与 ForceCommand 双保险） |
| | `/usr/local/blacklake-airlock/`（root 所有） | `airlock.py`、`hooks/pre-receive`、`airlock.conf.json`；airlock 用户不可写 |
| | `/Users/airlock/airlock-data/`（700） | `repo.git`（气闸裸仓库）、`gitlab-token`（600）、`state.json`、`airlock.log`（JSON lines） |
| | `/Library/LaunchDaemons/com.blacklake.airlock.sync.plist` | 以 airlock 身份每 120 秒 `airlock.py sync` |
| 公司 GitLab | 单个项目 + 项目令牌 | `read_api` + `write_repository`，Developer 角色 |

## 数据流

1. **读**：launchd / `bag sync` → `airlock.py sync`：`git fetch --prune <GitLab> +refs/heads/*:refs/heads/*`（令牌经 `GIT_CONFIG_*` 环境变量注入为 HTTP 头，不出现在命令行或 URL）→ Agent `git fetch` 气闸。
2. **写**：Agent `git push` → sshd → `gate`（只放行 `git-receive-pack 'repo.git'`）→ `pre-receive`：
   1. 校验每个 ref：仅 `refs/heads/<前缀>*`；非 main/受保护分支；名称合法；默认禁止删除和非快进；新增对象总大小、单文件大小；新增提交的 diff 做密钥扫描（含气闸自身令牌的精确匹配）。
   2. 持锁后逐个转推到 GitLab；若 GitLab 上分支不存在，附带 push options 建 MR（`merge_request.create/target/title/description/remove_source_branch`，标题加 `Draft:` 前缀；GitLab 11.10+ 支持，push options 不能含换行）。
   3. GitLab 返回的 MR 链接解析后回显 `AIRLOCK OK branch=... mr=...`；失败则 `AIRLOCK REJECT code=...` 并拒绝本次推送，气闸与 GitLab 保持一致。
3. **查询**：`gate` 放行 `status`、`sync`、`mr <分支>`、`notes <分支>`、`log [n]`、`version`、`help`，结果为 JSON（`status --kv` 为扁平键值，供 shell 解析）。

## 为什么这样设计（对比过的方案）

| 方案 | 结论 |
| --- | --- |
| Mac 上的容器/VM 里跑 Claude Code + Remote Control | Mac 访问不了 Anthropic，不可行；且容器默认继承 Mac 的 VPN 路由，能访问整个内网 |
| 开发机 SSH 进 Mac 上的沙盒，远程执行 | 沙盒同样能访问内网，需额外出口防火墙；远程执行体验差；隔离反而弱 |
| 代码镜像到开发机，人工把补丁搬回内网 | 安全但失去 Agentic Coding 的闭环价值 |
| **Git 气闸（本方案）** | 隔离由协议保证：Agent 只能说 git 和几条只读命令，能改的范围 = 一个仓库的 `<前缀>*` 分支（前缀在搭建时与用户约定）；凭据不出 Mac；工作量最小、可测试 |

## 威胁模型

| 威胁 | 控制 |
| --- | --- |
| Agent（或被提示注入的 Agent）试图访问内网 | Windows 无内网路由；SSH 用户被 ForceCommand 锁定，无 shell/TTY/端口转发/sftp/scp；只服务一个仓库路径（真实 sshd 测试覆盖） |
| Agent 篡改主干或他人分支 | 前缀白名单 + 受保护分支黑名单 + GitLab 侧目标分支保护（建议审批人确认）；合并只能人工 |
| Agent 改写/删除历史 | 默认禁止非快进和删除 |
| 凭据泄露 | 令牌只在 Mac，600 权限，只能由 airlock 用户读取；不经 argv/URL；所有输出做令牌脱敏；推送内容若含该令牌会被拦截 |
| 推送内容在 Mac 上被执行 | 钩子是 root 所有的固定代码，不执行仓库内任何文件，不读取仓库内配置；`receive.fsckObjects=true` |
| 连到假冒的 Mac | 主机指纹在配对时固定（StrictHostKeyChecking yes + HostKeyAlias）；IP 变化时按指纹重新发现，指纹不符直接停止 |
| 气闸管理员的 Mac 账户被经 SSH 暴力破解 | 远程登录仅允许 `com.apple.access_ssh` 组（安装器只加入 airlock）；airlock 仅公钥 |
| 同一网络内其它设备 | 只能看到 22 端口；无密钥无法登录 |
| 大文件/二进制拖垮 | 推送总量、单文件上限 |

**未覆盖（已知边界）**：Agent 写进代码的逻辑本身的安全性依赖审批人的 Code Review；构建依赖来自公网（供应链风险同普通开发）；代码会发送给 Anthropic（公司已允许）。

## 可配置项（`/usr/local/blacklake-airlock/airlock.conf.json`，气闸管理员用 sudo 修改）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `gitlab_repo_url` | 安装时填写 | 项目 HTTPS 地址 |
| `target_branch` | `main` | MR 目标分支 |
| `branch_prefix` | 无（必填，搭建时与用户约定，如 `zhangsan-cc/`；为空时拒绝所有推送） | Agent 分支前缀 |
| `protected_branches` | `main, master, develop, release/*` | 永不允许写 |
| `mr_draft` | `true` | 新 MR 为 Draft（`--ready` 可覆盖单次） |
| `remove_source_branch` | `true` | 合并后删除源分支 |
| `allow_force` / `allow_delete` | `false` | 非快进 / 删除分支 |
| `max_push_mb` / `max_file_mb` | 50 / 20 | 大小上限 |
| `secret_scan` | `block` | `block` / `warn` / `off` |
| `ssl_verify` / `ca_file` | `true` / 空 | 自签证书处理 |
| `http_proxy` | 空 | 代理型 VPN 客户端 |
| `gitlab_api_base` / `project_path` | 空 | 特殊部署（API 与 Git 地址不同）时覆盖 |
