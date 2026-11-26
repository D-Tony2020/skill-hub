# Changelog

## 0.1.0 - 2026-11-26

- 首版：接入团队 Skill Hub 的 6 步流程（推断后一次问完、装官方 CLI、设备码登录、一次装齐基建套件 `@blacklake/infra`、作者补 Git 与源码仓库、自检）。
- `scripts/starter.mjs`（不跑命令、不联网）：`doctor` 解读 Agent 采集的只读体检输出、`plan` 打印安装命令（套件优先，逐个安装回退）、`profile` 记录 Hub 地址与角色。
- 套件成员唯一事实来源 `assets/infra-suite.json`；Hub 地址不写死，按 CLI 同样的优先级推断，推断不到就问，绝不落到公网默认地址。
