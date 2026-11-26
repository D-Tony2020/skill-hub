# Changelog

## Unreleased

- 修复：`tests/qa.test.mjs` 在 Windows 上加载失败（动态导入传了 `C:\...` 绝对路径，改为 file:// URL）。CI 跑在 Linux 上所以之前没暴露

## 0.2.0 - 2026-11-26

- 新增 G15 个人化耦合：查作者姓名（git、系统用户名、hub.yaml owner、identity.txt）、个人目录路径、个人分支前缀（形如 `<名字>-cc/`）、写死的邮箱；跳过网址、示例名、占位符、CHANGELOG 和 tests/evals。可登记例外
- 新增 G16 配置清单：有 `config.schema.json` 就按四层（固定/预设/实例/角色）校验：实例层不能带默认值、敏感项要写存储位置且不在 Skill 目录、要问用户就要写首次引导；没有清单但有状态位迹象（环境变量、首次配置步骤、G15 命中）时要 Agent 确认 `stateless_confirmed`。不可豁免
- 流程增加第 4 步"可分发化改造"和「提交到 Skill Hub」：统一经 skill-hub 仓库 PR 进入，成员不直接用 CLI 上传
- 配套：`references/config-schema.md`（规则与格式）、本 Skill 自己的 `config.schema.json`、12 条单元测试、5 条行为评测、12 条触发评测
- 仓库工具：`publish:local` 拒绝没有有效"可分发"报告的 Skill（`--skip-qa "<理由>"` 须负责人同意）；`hub import` 打印报告状态；新增 `npm run qa`，CI 先以提示方式复核；QA_REPORT.md 与 qa-exceptions.json 不进发布包
- 文案里的人名改为"负责人"

## 0.1.0 - 2026-11-26

- 首版（草稿）：静态门禁 G1–G14、S1–S3、R1；本地跑 Cisco skill-scanner（与 SkillHub 同款）并逐条处置；评分表与 skill-creator 评测结果由 Agent 填 review.json；脚本计算结论并写带内容哈希的 QA_REPORT.md；已登记例外机制。
- 可分发化门禁（G15 个人化耦合、G16 配置清单）待第 1 轮设计拍板后加入。
