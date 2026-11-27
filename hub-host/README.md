# hub-host：SkillHub 主机运维文件

一期 SkillHub 跑在负责人的 Windows 主机上（Docker Desktop + WSL2）。这个目录是主机上 `skillhub\` 运维目录的**版本控制副本**，不含任何密钥。

| 文件 | 作用 |
| --- | --- |
| `RUNBOOK.md` | 主机运维手册（地址已替换成占位符；主机上的那份写着真实地址，由 `set-address.ps1` 维护） |
| `ops\*.ps1` | 启停、巡检、通知、备份、恢复、换地址、防火墙、计划任务 |
| `compose.local.yml`、`custom\` | 在官方 `compose.release.yml` 上叠加：中文默认、日志轮转 |
| `notify.env.example` | 飞书通知配置模板 |

**不在这里、也永远不进 git：** `.env.release`（全部配置和密钥）、`notify.env`、`ADMIN_PASSWORD.txt`、`MEMBER_ACCOUNTS.txt`、`backups\`、`logs\`。官方 `compose.release.yml` 与 `.env.release.example` 从上游 [iflytek/skillhub](https://github.com/iflytek/skillhub) 对应版本（当前 v0.2.28）取。

## 部署到一台新主机

1. 装 Docker Desktop（勾上“登录时启动”）和 PowerShell 7（`pwsh`）。
2. 建目录（例如 `C:\...\skillhub`），放入上游 `compose.release.yml`、`.env.release.example`，以及本目录全部文件。
3. 复制 `.env.release.example` 为 `.env.release`，按上游文档填写；`SKILLHUB_PUBLIC_BASE_URL` 用 `pwsh ops\set-address.ps1` 设置。
4. `pwsh ops\hub.ps1 up`，`pwsh ops\install-tasks.ps1`（注册巡检和备份计划任务），以管理员运行 `pwsh ops\open-lan.ps1 -NetworkName <网络名>`。
5. 复制 `notify.env.example` 为 `notify.env` 填飞书 webhook，`pwsh ops\notify.ps1 -Test`。
6. `pwsh ops\health.ps1` 返回 ok 即完成。

## 改动流程

主机上的脚本以本目录为准：改脚本先提 PR，合并后复制到主机 `skillhub\ops\`。只有 `RUNBOOK.md` 的地址行在主机上就地维护。
