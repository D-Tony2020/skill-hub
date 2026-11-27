# SkillHub 运行手册（一期：本机 + 局域网）

## 1. 地址与账号

| 项 | 值 |
| --- | --- |
| 局域网地址（给其他设备） | http://<局域网IP>:8088 |
| 本机地址 | http://localhost:8088 |
| 管理员 | `admin`，密码见 `ADMIN_PASSWORD.txt` |
| 普通账号 | 见 `MEMBER_ACCOUNTS.txt`（member01，blacklake 空间 MEMBER） |
| 审核队列 | `/dashboard/reviews`（只有管理员能看） |
| 团队空间 | `blacklake`（黑湖） |
| 版本 | SkillHub v0.2.28；postgres、redis 按 digest 固定 |

只有 8088 对局域网开放，而且只在**专用网络**上开放（防火墙规则“SkillHub web (TCP 8088, private networks)”）。8080、5432、6379 只绑本机。当前热点已设为专用网络；连到别的网络时，要在 Windows 设置里把那个网络设成“专用”，局域网才能访问。

### 自助注册的风险（Dean 2026-11-26 决定保持开放）

- **风险**：任何能连上同一热点或局域网的人，都能在 `/register` 自助注册。注册后自动得到一个自己当 OWNER 的个人空间（形如 `personal-xxxxxxxx`）。按 SkillHub 文档，团队空间的 OWNER 可以审批自己的提交，所以这个人可能不经过 skill-hub 仓库和管理员审批，就在 Hub 上发布公开 skill。这一点是按文档推断，没有实测。
- **发现**：健康巡检每 30 分钟检查一次，出现以下情况就写进 `logs\health-alerts.log`，每项只报一次：新账号、新空间、`global` 和 `blacklake` 以外空间里出现已发布或待审的版本。已知清单在 `logs\known-accounts.txt`。
- **处置**（管理员登录网页操作）：
  1. 不认识的账号：管理后台 → 用户管理，停用该账号。
  2. 已发布的可疑 skill：打开该 skill 详情页 → 更多 → 归档（下架）；必要时删除。
  3. 安装过它的机器：`skillhub remove <coordinate>`，并检查它是否运行过脚本。
  4. 要彻底关闭：管理后台 → 系统配置 → 本地登录，关掉“自助注册”（目前保持开放）。
  5. 在 `logs\` 里留下处理记录。

## 2. 启停

所有操作都用 `ops\hub.ps1`，它会自动带上 `compose.release.yml` 和 `compose.local.yml`（中文默认、日志轮转）。不要只用 `-f compose.release.yml` 启动。

```
pwsh ops\hub.ps1 status          # 容器状态
pwsh ops\hub.ps1 up              # 启动并等到全部健康
pwsh ops\hub.ps1 restart         # 重建容器（改了 .env.release 后用）
pwsh ops\hub.ps1 logs server     # 看日志
pwsh ops\hub.ps1 down            # 停止（数据保留；永远不要加 -v）
```

开机后：Docker Desktop 随 Windows 登录自动启动，容器策略是 `unless-stopped`，Hub 会自己起来（已验证：重启 Docker 后约 45 秒全部健康）。

## 3. 换了网络、IP 变了

手机热点会重新分配 IP。健康检查会报 “public address … is no longer on this machine”。处理：

1. 运行 `pwsh ops\set-address.ps1`。它会找出承载默认路由的 Wi-Fi 网卡及其 IPv4（跳过代理虚拟网卡 Meta 和 WSL 网卡），把 `.env.release` 的 `SKILLHUB_PUBLIC_BASE_URL` 以及本手册、`MEMBER_ACCOUNTS.txt` 里的地址改成新地址，重建 web 和 server，再验证本机地址、新地址和登录验证链接。记录写在 `logs\address.log`。也可以手动指定：`pwsh ops\set-address.ps1 -Ip <地址>`。
2. 脚本提示网络是“公用”时，以管理员运行 `pwsh ops\open-lan.ps1 -NetworkName '<网络名>'`（会弹 UAC），把这个网络设为“专用”。8088 的防火墙规则只对专用网络生效。
3. 其他设备上改用新地址；用旧地址登录过 CLI 的，要对新地址重新 `skillhub login --registry http://<新IP>:8088`（CLI 按地址分别保存登录凭证）。

记录：2026-11-27 从当前热点（<旧IP>）换到新热点，地址改为 <局域网IP>，网络本来就是专用。

## 4. 备份与恢复

- 自动：计划任务 `SkillHub-Backup` 每天 03:00 运行（电脑关着就开机后补跑），保留最近 14 份。
- 手动：`pwsh ops\backup.ps1`
- 内容：`backups\<时间>\` 里有 `db.dump`（pg_dump）、`storage.tgz`（技能包存储卷）、`.env.release` 和 compose 文件、`SHA256SUMS`。**含密钥，只留在这台电脑上。**
- 演练（不影响正式 Hub）：`pwsh ops\restore.ps1 -Backup backups\<时间>`。它在 28088 端口起一套临时实例，恢复、用 CLI 匿名装一个 skill 验证，然后删掉。2026-11-26 演练通过。
- 正式恢复（会覆盖现有数据，先自动再备份一次）：`pwsh ops\restore.ps1 -Backup backups\<时间> -Production -IUnderstandThisReplacesLiveData`
- 日志：`logs\backup.log`、`logs\restore.log`

## 5. 健康检查

- 自动：计划任务 `SkillHub-Health` 每 30 分钟一次，登录后 5 分钟也跑一次。
- 手动：`pwsh ops\health.ps1`
- 检查：5 个容器都健康、本机和局域网地址返回 200、搜索接口正常、没有卡在扫描超过 1 小时或扫描失败的版本、公开地址仍属于本机、最近备份不超过 36 小时、C 盘剩余 ≥ 20 GB。
- 结果：`logs\health.log`；有问题另写 `logs\health-alerts.log`。
- 通知（2026-11-27 起）：`ops\notify.ps1` 在状态变化时推送 Windows 弹窗和飞书（问题、恢复各一条；问题持续每 6 小时再提醒一次）。飞书 webhook 写在 `notify.env`（模板 `notify.env.example`，不进 git、不进备份），配好后 `pwsh ops\notify.ps1 -Test` 验证。记录在 `logs\notify.log`，当前状态在 `logs\notify-state.json`。
- 自愈：巡检发现 Docker 引擎没跑，会先启动 Docker Desktop 并 `compose up`，再检查（Docker Desktop 的“登录时启动”实测是关着的）。

## 6. 发布与审核（摘要）

1. skill 先过 skill-qa（结论“可分发”），经 PR 合并进 skill-hub 仓库。
2. 本机：`cd ~/skill-hub && git pull && npm run publish:local -- --skill <name> --registry http://localhost:8088`
3. 等扫描结束，到 `/dashboard/reviews` 看扫描结论。BLOCKED 的不批准：真问题修掉发新版本；必要行为由负责人书面确认例外后再批。
4. 同一个 skill 上一版还在待审时再提交，会把上一版顶出队列。
5. 限流：每个用户每 60 秒 10 次（dry-run 和发布各算一次）。

## 7. 升级 SkillHub

1. `pwsh ops\backup.ps1`，并用 `restore.ps1` 演练这份备份。
2. 看上游 release notes，改 `.env.release` 的 `SKILLHUB_VERSION=vX.Y.Z`。
3. `pwsh ops\hub.ps1 pull`，然后 `pwsh ops\hub.ps1 restart`，跑 `pwsh ops\health.ps1`。
4. 验证：登录、搜索、安装一个 skill。
5. 回退：`SKILLHUB_VERSION` 改回旧版本 restart；数据库迁移不兼容时用升级前的备份 `-Production` 恢复。

## 8. 常见故障

| 现象 | 处理 |
| --- | --- |
| 打不开页面 | `pwsh ops\health.ps1`；Docker Desktop 没开就打开它；`pwsh ops\hub.ps1 up` |
| 其他设备打不开、本机能开 | IP 变了（见第 3 节）；网络是“公用”；防火墙规则被删（以管理员运行 `ops\open-lan.ps1 -NetworkName <网络名>`） |
| 登录验证链接或下载地址指向 localhost / 旧 IP | `SKILLHUB_PUBLIC_BASE_URL` 没改或没 restart |
| 界面变成英文 | 没用 `ops\hub.ps1` 启动，`compose.local.yml` 没生效 |
| 上传后一直“扫描中” | `pwsh ops\hub.ps1 logs skill-scanner`；扫描失败不等于通过 |
| CLI 报 not logged in | `skillhub login --registry <地址>`，按地址分别保存 token |
| CLI 报 Rate limit exceeded | 等 60 秒再试 |

## 9. 本机文件

| 文件 | 用途 |
| --- | --- |
| `.env.release` | 全部配置和密钥（不外传） |
| `compose.release.yml` | 官方编排（不改） |
| `compose.local.yml` | 本地补充：中文默认、日志轮转 |
| `custom\90-default-zh.sh` | 中文默认脚本 |
| `ops\*.ps1` | 启停、备份、恢复、巡检、通知、计划任务、防火墙 |
| `backups\`、`logs\` | 备份和日志 |
| `e2e-log.md` | 验收记录 |
