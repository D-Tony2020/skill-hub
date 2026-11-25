# candidates.json 格式

文件位置：`~/.session-distiller/runs/<run-id>/candidates.json`。写完运行 `sd validate`。

```json
{
  "run": "20261125-101500",
  "candidates": [
    {
      "id": "purchase-doc-normalizer",
      "title": "采购单据标准化",
      "kind": "rule+code",
      "summary": "把各家 ERP 导出的采购单 Excel 清洗成统一字段：字段映射用 YAML 配置，脚本做单位换算、供应商编码映射和必填校验，输出标准 CSV 和问题清单。",
      "problem": "每个客户项目都要重写一次清洗脚本，并在单位换算和编码映射上反复返工。",
      "evidence": [
        {"session": "3f2a9c1e", "turns": ["T4", "T9"], "quote": "单位要按采购单位换算成库存单位"},
        {"session": "a81b77d0", "turns": ["T2"]}
      ],
      "scores": {"fit": 5, "reuse": 4, "leverage": 4, "maturity": 3},
      "fit_rationale": "服务长期目标 2（制造业可复用组件库），属于采购域。",
      "dedupe": {"action": "new", "target": null, "note": ""},
      "packaging": {
        "form": "skill",
        "scripts": ["normalize.py", "mapping.example.yaml"],
        "triggers": ["清洗采购单", "ERP 导出的 Excel 字段对不上"],
        "tags": ["procurement", "erp", "excel"]
      },
      "risks": "示例数据必须用虚构供应商；原脚本里有客户编码前缀，需要参数化。"
    }
  ]
}
```

没有值得固化的资产时，写空列表并说明原因：`{"run": "...", "candidates": [], "none_reason": "两个会话都是一次性客户数据和通用 git 操作"}`。

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 将来的 skill 名。小写加短横线，不超过 64 字符，不含 claude 或 anthropic。在本次 run 中唯一 |
| `title` | 是 | 中文短名 |
| `kind` | 是 | `rule` / `rule+code` / `methodology` / `workflow` / `component` |
| `summary` | 是 | 资产本身是什么、怎么用。scaffold 会把它写进 skill 的 description |
| `problem` | 是 | 它解决的反复出现的问题 |
| `evidence` | 是 | 至少 1 条。`session` 写会话 id 或其前缀，必须在本次 run 里；`turns` 必须是摘要里真实存在的轮次；`quote` 可选，写简短原话（已脱敏） |
| `scores` | 是 | `fit` / `reuse` / `leverage` / `maturity`，整数 0–5，标准见 rubric.md |
| `fit_rationale` | 是 | 对应画像里的哪个目标或领域 |
| `dedupe` | 是 | `action`: `new` / `merge` / `duplicate`；后两种必须写 `target`（已有 skill 名） |
| `packaging` | 是 | `form`: `skill` / `rule-snippet` / `reference`；`scripts` 写计划包含的脚本（`rule+code` 必须写）；`triggers` 写用户会说的话，会进入 description；`tags` 写进 hub.yaml |
| `risks` | 否 | 敏感信息、客户特定逻辑等注意事项 |
