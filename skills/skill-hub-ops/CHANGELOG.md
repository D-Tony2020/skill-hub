# Changelog

## 0.2.0 - 2026-11-26

- 接入 Skill 链：入库前要求已对齐的 INTENT.md（skill-intent）和"可分发"的 QA_REPORT.md（skill-qa）；`hub chain` 显示每个 Skill 卡在哪一步、下一步交给谁。
- 可分发化：仓库位置读 `SKILL_HUB_DIR`、hub-starter 记下的 `~/.skill-hub/profile.json`；Hub 地址不再写死 localhost，按 `--registry`、环境变量、profile、CLI 配置的顺序解析，发布脚本打印所用地址；加 config.schema.json；人名改为负责人、发布人角色。
- 新增：`hub new` 脚手架；基建套件维护（`hub suite`，由负责人在网页套件编辑器建版本）；官方镜像同步（`hub upstream`）；回滚与下架；反馈 issue 分诊；巡检清单。
- 发布流程补上"上一版还在审核时不要提交新版（会被顶替）"、扫描结论跟进、安装验证；细节下沉到 references/。
- 导入前必须先过 skill-qa；导入走 `skill/<name>` 分支和 PR；发布脚本拒绝没有有效"可分发"报告的 Skill（`--skip-qa` 须负责人同意）。
- 补齐评测用例（evals.json、trigger-evals.json）。

## 0.1.0 - 2026-11-25

- 首版：导入、升级、发版、发布到 SkillHub、安装、下架、巡检的操作手册。
