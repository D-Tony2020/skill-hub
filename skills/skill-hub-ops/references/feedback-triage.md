# 处理反馈（issue 分诊）

使用者用 skill-feedback 提交的 issue，标题形如 `[<skill>] <现象>`，正文有类型、环境（版本、安装来源）、期望、实际、复现步骤。

## 步骤

1. **列出待处理的**：仓库里标题以 `[` 开头或带 `skill:<name>` 标签、还开着的 issue。
2. **核对版本**：issue 里的版本比仓库当前版本旧，先看 CHANGELOG 有没有修过；修过就请用户升级，给出升级命令。
3. **复现**：按复现步骤在自己的环境里跑一遍（装 issue 里写的那个版本）。复现不了就请提交人补信息，不要猜。
4. **分类**：
   - 环境问题（不满足 Skill 的适用前提）：补进那个 Skill 的 troubleshooting 或「适用前提」，让下一个人自己能看懂；不算 Skill 的 bug。
   - 不触发 / 误触发：把用户原话（已脱敏）加进 `evals/trigger-evals.json`，然后用 skill-creator 优化描述。
   - bug / 文档问题：把复现用的那句话写成 `evals/evals.json` 的一条用例（期望写成可核对的结果），再修。
   - 功能建议：改了一句话目标或范围的，先回 skill-intent 更新目标卡。
5. **修**：交给 `hub.yaml` 的 owner，或在用户同意下自己用 skill-creator 修；之后 `hub bump <name> patch`、skill-qa、PR、发布，和普通升级一样。
6. **回告**：告诉用户修在哪个版本、怎么升级。要不要在 GitHub 上回复或关闭 issue，问用户。

## 安全类反馈

不在公开 issue 里讨论细节。确认后按 rollback-retire.md 的「严重问题」处理。
