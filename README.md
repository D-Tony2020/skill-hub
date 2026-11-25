# skill-hub

Skills 工厂的 skill 仓库：所有自定义 Claude Skill 的唯一事实来源，同时将作为 Claude Code 插件市场分发。

方案文档：Skill Hub 看板系统技术方案（路线 A：GitOps 轻量看板）。

## 目录规范

```
skills/<skill-name>/
├── SKILL.md        # 只写官方 frontmatter（name、description 等），不加自定义字段
├── scripts/        # 可执行脚本（不要放在顶层 bin/）
├── references/     # 按需加载的参考资料
├── evals/          # 评测用例
└── hub.yaml        # Hub 元数据：状态、版本、渠道、负责人、标签（由 hub-cli 维护）
```

`plugins/` 与 `.claude-plugin/marketplace.json` 由 CI 根据 `hub.yaml` 生成，不要手写。

## 分支

- `main`：开发中，所有改动通过 PR 合入
- `stable`：已上架版本，由 CI 在校验与评测通过后快进
