# Changelog

## 2.0.0 - 2026-11-26

可分发化（产品侧设计 loop 第 1 轮）：换一个黑湖同事、换一个项目装上就能用。**不兼容变更**见第一条。

- **分支前缀改为开放槽位，没有默认值**。不再内置 `deans-cc/`：`bag init` 给出建议值 `suggested_prefix=`（取自 Git 邮箱/用户名），首次搭建时由用户确认或自定义；`bag bundle` 必须带 `--prefix`（不能等于目标分支）；Mac 安装器没拿到前缀会提示输入并校验格式；气闸配置的前缀为空时拒绝一切推送（`E_POLICY_PREFIX`）。已搭建的环境不受影响（前缀已写在 Mac 配置里，`bag start` 会从 Mac 同步）
- 正文、参考文档、脚本提示里的人名全部换成角色：用户、审批人、气闸管理员，搭建时问清分工并 `bag learn` 记录
- 写明适用前提：Windows + Git Bash、开发机与内网 Mac 同网（热点或局域网）、GitLab HTTPS 单项目、一期仅黑湖内部。跨网络等不满足的情况第一步就告知不适用
- 新增 `config.schema.json`：列出全部状态位（固定/预设/实例/角色）和环境前提，说明怎么推断、问谁、存在哪
- 更新渠道跟安装来源走：从 SkillHub 安装的副本（无 SOURCE 记录）执行 `bag update` 返回 `E_SRC_HUB` 并提示 `skillhub upgrade`，不绕过 SkillHub 审核；`--from-source` 可显式切到源码安装
- 新增 `qa-exceptions.json`（3 条 SkillHub 扫描告警的例外理由，负责人已确认）、`evals/trigger-evals.json`（7 条该触发、6 条不该触发），行为评测新增"前缀由用户决定""跨网络不适用"两条
- 新增测试：前缀必填、空前缀拒推、SkillHub 安装的更新渠道

## 1.1.2 - 2026-11-25

- 安全修复：`serve-bundle` 和 `bundle` 给 Mac 的安装命令先用 `shasum -a 256 -c` 核对安装器，一致才 `sudo bash`。此前经热点明文 HTTP 下载后直接以 root 执行，同网段可篡改（SkillHub 安全扫描 CRITICAL）

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
