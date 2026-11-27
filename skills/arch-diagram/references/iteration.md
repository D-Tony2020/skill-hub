# 清单与迭代规则（iteration）

## 1. 清单文件 `<slug>.spec.json`

清单是图的**语义真相**（有哪些东西、谁连谁），`.drawio` 是**布局真相**（东西摆在哪、长什么样）。
两者必须一致，`diagram.py check` 会逐条核对。

```json
{
  "title": "缺料齐套 Agent 架构",
  "nodes": {
    "sales":   {"label": "业务员", "kind": "actor"},
    "feishu":  {"label": "飞书", "kind": "channel"},
    "kitting": {"label": "齐套 Agent\n齐套率计算", "kind": "agent"},
    "memory":  {"label": "催料记忆", "kind": "datastore"},
    "erp":     {"label": "ERP\nBOM / 库存", "kind": "external"},
    "app":     {"label": "应用层", "kind": "group"},
    "sched":   {"label": "排产 Agent", "kind": "agent", "group": "app", "status": "tbd"},
    "detail":  {"label": "规划器", "kind": "service", "page": "齐套 Agent 内部"}
  },
  "edges": [
    {"from": "sales", "to": "feishu", "label": "发起查询"},
    {"from": "kitting", "to": "erp", "label": "查 BOM / 库存"},
    {"from": "expedite", "to": "supplier", "label": "发催料消息", "type": "async"},
    {"from": "kitting", "to": "memory", "label": "读写", "type": "readwrite"}
  ]
}
```

字段：
- `nodes` 的键就是 **drawio 里的 cell id**（必须完全相同）。用有语义的英文小写：`kitting`、`erp`、`memory`。
- `label`：与图中文字一致，用 `\n` 表示换行（图中对应 `&lt;br&gt;`）；待定项的 `【待定】` 前缀不用写进清单。
- `kind`：见 style-guide.md 第 1 节。
- `group`：所在容器的 id（容器本身也是一个 kind=group/lane 的节点）。
- `status`：`"tbd"` 表示待定。
- `page`：不在第一页时写页面名。
- `edges[].type`：`sync`（默认，含同步调用外部系统）/ `async`（异步消息、事件推送）/ `readwrite`（双向，方向不限）/ `feedback`（反馈、打回）。
- `edges[].status`：`"tbd"` 表示这条关系待定（含你推断、用户没明说的关系）。
- `by` / `since` / `intent`（节点和关系都可以有）：这个元素的当前状态出自人手——`by` 是 `"user"` / `"team"` / `"team:张三"`，`since` 是合入的版本，`intent` 是你分析出的意图。带 `by` 的元素受保护（human-edits 第 5 节）。
- 顶层 `decisions`：从人工改动里提炼出、每轮都要遵守的规则，如 `{"rule": "统一用「调度」", "from": "h012", "status": "confirmed"}`（human-edits 第 3 节）。

## 2. 每轮迭代的标准动作

1. `diagram.py inspect <slug>` —— **每轮都先读当前文件**，不要凭记忆。
   输出末尾的「自 rNN 以来的变化」如果不是你上轮做的，就是用户在 draw.io 里手改的；飞书画板上的团队改动先 `reconcile` 合回（v2.2）。
   有人工改动时先按第 3 节和 `human-edits.md` 处理（合回 → 分析意图 → 更新清单的 `by` / `intent` / `decisions`），再做本轮新修改。
2. 改清单：把本轮讨论的变化写进 `spec.json`（增 / 删 / 改节点和关系）。
3. 改图：**只改受影响的 cell**。用 Edit 工具对 .drawio 做局部替换，不要整份重写；新加的 cell 用样式代号（style-guide）。
   第 2、3 步改的是两个不同文件，**放在同一条消息里同时发出**；同一个文件的多处修改按顺序发，不要并行（并行写同一文件会互相覆盖）。
   - 新增节点：放进空白区域；实在没地方，只移动 1–2 个相关节点并在回复里说明。
   - 删除节点：同时删掉以它为端点的连线。
   - 改关系：改 edge 的 `source`/`target` 或删掉重加，保留其他 edge 的 id 不变。
4. `diagram.py round <slug> -m "本轮改动一句话"`（= 展开样式代号 → 图例（首轮判断，之后刷新）→ check → 导出 PNG + SVG（PNG 即预览图）→ snapshot；check 不通过则只出预览、不导出交付物、不快照；末尾一行 ⏱ 是各阶段耗时）。
5. 看预览图，有问题就修，修完再跑 `round`。

## 3. 人工改动（必须先合回，再分析意图）

人工改动的完整规则（来源、标记、意图分析、优先级与冲突）在 `human-edits.md`，这里是 draw.io 侧的操作细节。
用户可能在 draw.io 里拖动节点、改颜色、加备注、改文字，然后保存（可能是**压缩格式**，check / inspect 会自动解压并备份原文件）。

- 识别：`inspect` / `check` 里「自 rNN 以来的变化」列出的、不是你本轮做的改动。
- 处理：
  - 位置 / 颜色 / 尺寸：原样保留，后续修改不得覆盖。
  - 用户移动了节点：连到它的连线如果带拐点（`<Array as="points">`），按新位置调整拐点坐标，避免出现台阶状折线——**只改连线，不动用户的节点**。
  - 用户新增的节点或连线：check 会报「清单外元素」或「图中多出关系」—— **把它并入清单**（这是用户的决定），不要删。
    并入时给用户新增的节点在清单里用它现有的 cell id（如 `zbXk2-7`），不要改 id，并标 `"by": "user"`。
  - 用户改了文字：check 报「标签不一致」—— 以图为准，更新清单。
  - 用户加的自由文本备注（纯文本、不连线）：不入清单，check 只做提示，原样保留。
- 每条改动都要分析意图并写进清单（`by` / `since` / `intent`，能提炼成规则的写进 `decisions`）；回复第一段按「谁 · 改了什么 · 我理解的意图（把握度）」交代。
- 用户的 draw.io 开着这份图也没关系，不用关掉或重开，导出照常可用。draw.io 桌面版默认不自动保存：你改完文件几秒后，它顶部会出现红色提示「文件已经被修改。点击这里进行同步。」，用户点一下就载入你的修改（用户没保存的改动也保留）；如果用户直接保存，会被问「是否保存文件并覆盖这些更改？」，要选「同步」，选「覆盖」会冲掉你这轮的修改。`round` / `restore` / `adopt` 发现 draw.io 开着这张图时会打印这条提醒，原样转告用户。用户开了自动保存时，draw.io 会自动同步。

## 4. 版本

- `round` / `snapshot` 每轮在 `history/` 留 `<slug>.rNN.drawio` + `<slug>.rNN.spec.json`，并写 `history/CHANGELOG.md`（含自动 diff）。内容无变化时不会重复快照。
- 「这轮改了什么」：`diagram.py diff <slug>`（默认：最近快照 → 当前），或 `--from r01 --to r03`。
- 「回到第 2 版」：`diagram.py restore <slug> r02`（会先自动快照当前状态，可再恢复）。
- 评审用变更高亮：`diagram.py export <slug> --highlight`，生成 `<slug>.changes.png`（红色粗框标出本轮新增 / 修改的元素，**不改源文件**；删除的元素无法画出，会在输出里列出）。

## 5. 何时允许重新排版

只有用户明确说「重画 / 换个方向 / 推倒重来」，或新增元素后已经无法在不大动的情况下放下（这时先问用户）。
重排前先 `snapshot`。
