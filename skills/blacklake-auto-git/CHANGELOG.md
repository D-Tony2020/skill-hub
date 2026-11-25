# Changelog

## 1.1.1 - 2026-11-25

- 从 SkillHub 安装的副本没有 VERSION 文件时，bag.sh 改读 SKILL.md 的 metadata.version，不再误判为 0.0.0；install_local.sh 只复制存在的文件

## 1.1.0 — 2026-11-25
- SKILL.md 写明源码仓库（D-Tony2020/skill-hub，`skills/blacklake-auto-git`，main），以及修改、反馈和 PR 的流程。
- 新增 `bag update`：从源码仓库快进 `~/skill-hub` 并重装。会提示是否需要重开会话，以及是否需要升级 Mac 端；本地有改动或分叉时拒绝执行。
- `install_local.sh` 会写入 `SOURCE` 来源记录（仓库、分支、提交号、安装时间），`bag version` 会显示这些信息。
- Skill 版本与 Mac 端（airlock）版本拆开：只改 Windows 端时不再要求重装 Mac 端。
- `bag update` 默认不会降级。源码分支上的版本较低时（例如当前安装的是未合并 PR 分支上的版本）会返回 `E_SRC_DOWNGRADE`；确需降级时加 `--allow-downgrade`。
- 修复：从 CRLF 检出读取 airlock 版本号时会带上 `\r`。

## 1.0.0 — 2026-11-25
- 首个版本：内网 Mac Git 气闸（受限 SSH 闸门、推送策略校验、转推 GitLab、自动建 Draft MR、定时同步、状态/MR/评论查询）。
- Windows 侧 `bag.sh`：配对（主机指纹固定）、按指纹自动重新发现 Mac、克隆、开分支、推送、MR 与评论查询、分层 doctor、经验回写。
- 自包含 Mac 安装器（幂等升级、令牌轮换、追加密钥、卸载）。
- 四层测试：模拟端到端、Agent CLI、真实 sshd 安全边界、安装器系统模拟；14 条 Agent 行为评测。
