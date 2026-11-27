# Changelog

## 0.1.0 - 2026-11-26

- 首版：使用者把 Skill 的问题送回源码仓库。定位安装副本与版本、区分 Skill 问题与环境问题、按模板写最小复现、脱敏、用户确认后生成预填 issue 链接。
- `scripts/feedback.mjs`：locate（SkillHub / 源码仓库 / claude.ai 同步 / 手工四种来源）、scrub（密钥、内网地址、邮箱、个人目录、客户名）、url（预填链接，未脱敏拒绝生成）。
- 安全问题不发公开 issue；镜像和内置 Skill 先回到本仓库，由维护者决定是否转上游。
