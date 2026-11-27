# 飞书交付与同步（feishu-sync）

`diagram.py sync <slug>` 把 draw.io 图写成飞书文档里的**原生画板**：形状、文字、颜色、连线的端口与拐点都取自 draw.io 本身，
在飞书里可以直接改字、拖动、加评论。draw.io 文件始终是源头，飞书画板是它的发布副本。

## 用法

```powershell
py -3 "$AD\scripts\diagram.py" sync <slug> --doc https://xxx.feishu.cn/docx/<token>   # 首次：指定接收文档
py -3 "$AD\scripts\diagram.py" sync <slug>                # 之后：覆盖同一块画板；新图默认进上次的文档
py -3 "$AD\scripts\diagram.py" sync <slug> --dry-run      # 只转换不发送（可选本地近似预览，需 whiteboard-cli）
py -3 "$AD\scripts\diagram.py" sync <slug> --new-board    # 另起一块画板（旧画板保留）
py -3 "$AD\scripts\diagram.py" sync <slug> --page 2       # 只同步第 2 页（默认全部页面，每页一块画板）
```

`--doc` 也可以只给文档 token，脚本会补成 `https://feishu.cn/docx/<token>` 交给 lark-cli。访问飞书全部经由 lark-cli（飞书开放平台），脚本本身不直接发网络请求；只有 `--dry-run` 的本地预览在没装 whiteboard-cli 时会用 npx 从 npm 拉取固定版本。

每页的流程：取 draw.io 导出的 SVG（`round` 已生成；过期则重新导出）→ 转成画板节点 → 首次在文档末尾追加一块空白画板
→ 覆盖写入 → 读回画板算内容指纹 → 导出飞书预览 `feishu/<slug>.feishu.jpg`（**必须打开看一眼**）。

| 文件 | 内容 |
| --- | --- |
| `<slug>/feishu.json` | 文档、每页画板 token、上次写入的内容指纹 |
| `<slug>/feishu/<slug>.openapi.json` | 写入飞书的画板节点（OpenAPI raw 格式） |
| `<slug>/feishu/<slug>.feishu.jpg` | 写入后从飞书导出的预览 |
| `arch-diagrams/_feishu.json` | 默认接收文档（首次 `--doc` 时记下） |

## 安全约定

- 只覆盖**本工具建的那块画板**（记录在 `feishu.json`）；不改文档里的其他内容，只在末尾追加画板。
- 覆盖前读回画板比对指纹：如果有人在飞书里改过，返回 3 且不写入。这些是团队的**人工改动**，默认先 `reconcile` 合回（见下节），不要直接 `--force` 覆盖。
- 同样内容重复同步不会重复写入（「已是最新」）。写入带幂等 token，失败重试不会写两遍；画板先记账再写入，重试不会多建画板。
- lark-cli 遇到高风险确认（退出码 10）时停下来问用户，脚本不会自动追加确认参数。

## 飞书侧改动合回（reconcile，v2.2）

团队在飞书画板上的改动是人工改动（规则见 `human-edits.md`），要合回 draw.io，而不是被下一次发布覆盖。

1. **发布时记映射**：写入画板后，飞书按写入顺序返回节点 id；`feishu.json` 记下「飞书节点 id ↔ draw.io 元素 id」以及这次写入的内容。
2. **`diagram.py reconcile <slug>`**：读回画板，按映射逐个比对，翻译成清单语义的改动（「playbook 改名：04 编排 → 04 调度」「连线 e-x 的终点改到 action」），而不是坐标差：
   - 文字、颜色、线型、位置、尺寸、增删图形和连线、改连线端点：如实写回 .drawio 和清单，元素标 `by: team` 和 `since`；
   - 新增的便签 / 文本框：当作批注，原文和作者记入台账，不画进图；
   - 映射不上的东西（手绘、图片等）：列出来交给用户决定。
3. **留痕**：每条改动追加到 `history/human-edits.jsonl`，并快照为新版本，CHANGELOG 记「合入飞书画板人工改动 N 处」。
4. **交给下一轮**：输出改动清单，你按 human-edits 第 4 节分析意图、更新 `intent` / `decisions`，再 `round`、`sync` 发布（指纹随之更新）。

## 转换规则（draw.io → 飞书画板）

| draw.io | 飞书画板 |
| --- | --- |
| 矩形 / 圆角矩形 / 椭圆 / 菱形 / 备注 / 圆柱（高 ≥ 50） | 原生图形，文字在图形内（可直接编辑） |
| 角色（umlActor）、矮圆柱（图例样例） | SVG 图形（飞书原生角色画得很小、矮圆柱帽子会吞掉图形） |
| 容器 / 泳道 | 主体矩形 + 表头矩形 + 标题文本框（表头短，标题放进图形里会被裁） |
| HTML 标签 | 富文本：粗体 / 斜体 / 下划线，每行一段 |
| 连线 | 吸附到两端图形；端口位置（如 exitY=0.25）和拐点按 draw.io 实际走线；颜色、虚线、箭头、标签字号与颜色保持 |

飞书文字排版比 draw.io 松（行高约 1.45 倍、图形内有约 5px 边距）：draw.io 里刚好放下的三行字，在飞书 60px 高的框里会被裁掉一截。
`sync` 会估算每个图形的文字是否放得下，放不下时把该图形字号调小 1–2 号并提示「想保持原字号把框加高到约 N」。

## 前置条件（已完成于 2026-11-20）

1. lark-cli（npm `@larksuite/cli`）：`npm i -g @larksuite/cli`，`lark-cli config init --new`（浏览器里一键建应用），
   `lark-cli auth login --domain docs`（以用户身份授权文档 / 画板权限）。授权过期时重新运行 `lark-cli auth login --domain docs --no-wait --json`
   拿新链接，**链接和二维码原样发给用户**，用户确认后运行 `lark-cli auth login --device-code <code>`。
2. 可选：whiteboard-cli（npm `@larksuite/whiteboard-cli`）只用于 `--dry-run` 的本地近似预览。
3. 不要让用户把 App Secret / token 贴进对话；凭据由 lark-cli 保存在本机。

## 手动退路

lark-cli 不可用时：飞书文档里插入画板 → 画板右上角 → 导入 → 选 `<slug>.drawio`。
已知：飞书的 draw.io 导入器对部分图形（如 umlActor、cylinder3）可能报「未知错误」，以用户实测为准；`sync` 不经过这个导入器。
