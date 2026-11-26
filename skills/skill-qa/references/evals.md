# 评测（G5、G6、G7、G9）

评测引擎用 Anthropic 官方的 skill-creator，本 Skill 只负责定义门槛和记录结果。

## 用例文件

**任务用例**放在 `evals/evals.json`，沿用 skill-creator 的旧格式，至少 3 条：

```json
{
  "skill_name": "my-skill",
  "evals": [
    {
      "id": "first-time-setup",
      "prompt": "用户的原话，越接近真实说法越好",
      "setup": "执行前的环境状态（可选）",
      "expectations": ["可以逐条核对的预期行为", "..."]
    }
  ]
}
```

**触发用例**放在 `evals/trigger-evals.json`，格式和 skill-creator 的 description 优化一致：

```json
[
  { "query": "该触发的说法", "should_trigger": true },
  { "query": "近似但不该触发的说法", "should_trigger": false }
]
```

建议各写 8–10 条，不该触发的至少 3 条。不该触发的用例要选"近似但不该用"的说法：关键词相同但意图不同、相邻领域、应该交给另一个 Skill 的场景。像"写个斐波那契函数"这种明显无关的说法测不出东西。

用例要请用户确认，因为它定义了这个 Skill 该做到什么。

## 跑法

1. **任务评测（G6）**：按 skill-creator 的流程，每条用例分别在"装了这个 Skill"和"不装"两种情况下各跑一次，用 expectations 逐条判分。一条用例的 expectations 全部满足才算通过。记下 `total`、`passed`、`baseline_passed`。
2. **触发评测（G7）**：用 skill-creator 的 `scripts/run_eval.py --eval-set evals/trigger-evals.json`，每条跑 3 次取多数，模型用当前会话的模型。记下该触发的命中数和不该触发的误触发数。
3. **安装冒烟（G9）**：把打包副本装进一个全新目录（`hub install <name> --dest <临时目录>`，或者手动只拷打包文件），在这个副本上挑一条任务用例跑通。G9 提示有无扩展名文件被读取时，副本里要去掉这些文件再跑。

skill-creator 不可用时（例如 claude.ai 网页端），对应字段留空。结论会是"暂缓"，如实告诉用户在哪里可以补跑（装有 Claude Code 的电脑）。

## 写进 review.json 的格式

```json
"evals": {
  "runner": "skill-creator",
  "model": "当前会话的模型 ID",
  "tasks": { "total": 5, "passed": 5, "baseline_passed": 2 },
  "triggers": { "should": { "total": 10, "hit": 10 }, "should_not": { "total": 8, "hit": 0 } },
  "smoke": { "ok": true, "note": "在 /tmp/x 的安装副本上跑通 first-time-setup" }
}
```

门槛（规范建议值，待 Dean 确认）：任务通过率 ≥ 80% 且不低于基线；该触发的命中率 ≥ 90%；误触发率 ≤ 10%。
