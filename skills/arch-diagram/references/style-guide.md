# 图形规范（style-guide）

本文件的样式字符串与 `scripts/house_style.py` 逐字一致（单测强制）。**画图时写样式代号，不要手改颜色**：
`style="@agent"`；自己定的键（端口、对齐、间距等）照常写全，接在代号后面，如 `style="@sync;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"`。
任何命令读图前都会把代号原样展开成下表的完整样式串（与整段复制逐字节相同）；拼错的代号 `check` 会报错。标题用 `@title`。规范外的样式照常整段写。

## 1. 节点类型（spec 里的 `kind`）

<!-- kinds:start -->
| kind | 代号 | 用途 | 默认尺寸 | 展开后的 style |
| --- | --- | --- | --- | --- |
| `agent` | `@agent` | 智能体 Agent | 160×60 | `rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#e3f2fd;strokeColor=#1565c0;fontFamily=Arial;fontSize=12;` |
| `service` | `@service` | 服务 / 模块 | 160×60 | `rounded=0;whiteSpace=wrap;html=1;fillColor=#e0f2f1;strokeColor=#00796b;fontFamily=Arial;fontSize=12;` |
| `control` | `@control` | 编排 / 网关 | 160×60 | `rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#f3e5f5;strokeColor=#6a1b9a;fontFamily=Arial;fontSize=12;` |
| `datastore` | `@datastore` | 存储 / 记忆 / 知识库 | 120×80 | `shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;whiteSpace=wrap;html=1;fillColor=#e8f5e9;strokeColor=#2e7d32;fontFamily=Arial;fontSize=12;` |
| `external` | `@external` | 外部系统 | 160×60 | `rounded=1;arcSize=12;dashed=1;whiteSpace=wrap;html=1;fillColor=#eceff1;strokeColor=#455a64;fontFamily=Arial;fontSize=12;` |
| `channel` | `@channel` | 触点 / 渠道 | 140×50 | `rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#fff3e0;strokeColor=#e65100;fontFamily=Arial;fontSize=12;` |
| `actor` | `@actor` | 角色 | 40×70 | `shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;outlineConnect=0;fillColor=#eceff1;strokeColor=#455a64;fontFamily=Arial;fontSize=12;` |
| `step` | `@step` | 流程步骤 | 140×50 | `rounded=1;arcSize=20;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#455a64;fontFamily=Arial;fontSize=12;` |
| `decision` | `@decision` | 判断 | 140×80 | `rhombus;whiteSpace=wrap;html=1;fillColor=#fff9c4;strokeColor=#f57c00;fontFamily=Arial;fontSize=12;` |
| `terminal` | `@terminal` | 开始 / 结束 | 120×40 | `rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#e8f5e9;strokeColor=#2e7d32;fontFamily=Arial;fontSize=12;` |
| `note` | `@note` | 备注 | 180×60 | `shape=note;size=12;whiteSpace=wrap;html=1;align=left;spacingLeft=6;fillColor=#fffde7;strokeColor=#fbc02d;fontFamily=Arial;fontSize=11;` |
| `group` | `@group` | 分层 / 分组容器 | 600×200 | `swimlane;startSize=28;collapsible=0;rounded=0;html=1;whiteSpace=wrap;fillColor=#fafafa;strokeColor=#90a4ae;fontStyle=1;fontFamily=Arial;fontSize=13;` |
| `lane` | `@lane` | 泳道 | 900×140 | `swimlane;horizontal=0;startSize=32;collapsible=0;html=1;whiteSpace=wrap;fillColor=#fafafa;strokeColor=#90a4ae;fontStyle=1;fontFamily=Arial;fontSize=13;` |
<!-- kinds:end -->

选型要点：
- `agent` 只给有自主决策的智能体；普通后端服务、模块用 `service`。
- `control` 给编排器、调度器、网关、路由这类"控制流量/调度他人"的组件。
- `datastore` 覆盖数据库、记忆（Memory）、知识库、向量库、缓存。
- `external` 给不归本方案建设的系统：ERP/MES/WMS/SRM/第三方 API。
- `channel` 给用户触点：飞书、企微、Web、App。
- 流程图用 `step` / `decision` / `terminal`；泳道用 `lane` 做容器。

## 2. 待定项（spec 里 `"status": "tbd"`）

在该节点原样式末尾追加：

`dashed=1;dashPattern=8 4;fillColor=#fffde7;strokeColor=#f9a825;fontColor=#8d6e00;`

并在标签最前面加 `【待定】`。用代号时写 `@<kind>+tbd`（如 `@external+tbd`），等价于 kind 样式末尾追加上面这段。例：`value="【待定】排产 Agent"`。
待定的连线（spec 关系写 `"status": "tbd"`）：在连线样式末尾追加

`dashed=1;dashPattern=8 4;strokeColor=#f9a825;fontColor=#8d6e00;`

标签加 `（待定）` 或 `（待确认）`。用代号时写 `@<type>+tbd`（如 `@async+tbd`）。推断出来、讨论里没明说的关系，也按待定关系画，交给用户确认。

## 3. 连线类型（spec 里 `edges[].type`，默认 `sync`）

<!-- edges:start -->
| type | 代号 | 用途 | 展开后的 style |
| --- | --- | --- | --- |
| `sync` | `@sync` | 调用 / 数据流 | `edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;fontFamily=Arial;fontSize=11;labelBackgroundColor=#ffffff;strokeColor=#37474f;` |
| `async` | `@async` | 异步 / 事件 / 消息 | `edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;fontFamily=Arial;fontSize=11;labelBackgroundColor=#ffffff;strokeColor=#37474f;dashed=1;` |
| `readwrite` | `@readwrite` | 读写（双向） | `edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;fontFamily=Arial;fontSize=11;labelBackgroundColor=#ffffff;startArrow=classic;startFill=1;strokeColor=#2e7d32;fontColor=#2e7d32;` |
| `feedback` | `@feedback` | 反馈 / 打回 | `edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;fontFamily=Arial;fontSize=11;labelBackgroundColor=#ffffff;strokeColor=#c62828;fontColor=#c62828;` |
<!-- edges:end -->

- 每条连线都要钉端口：`exitX/exitY/exitDx=0/exitDy=0` 与 `entryX/entryY/entryDx=0/entryDy=0`。
  连到圆柱（datastore）时再加 `entryPerimeter=0;`（或 `exitPerimeter=0;`），否则箭头会停在椭圆顶面而不是边框。
- 同一侧有多条线时，端口错开（0.25 / 0.5 / 0.75），不要都用 0.5。
- 绕行用 `<Array as="points">` 加拐点；最后一段直线 ≥ 20px，否则箭头会糊在拐角上。
- 标签要短（2–6 个字），是动词或数据名：「调用」「齐套结果」「读写」。

## 4. 布局网格

- 坐标取 10 的倍数；同层节点等高、顶端对齐。
- 节点间距：水平 ≥ 100px，垂直 ≥ 80px（给连线标签留位置）。
- 主流程方向：架构图从左到右（用户/触点在左，外部系统在右），分层图从上到下（接入层在上，数据层在下）。
- 标题：id 固定为 `title`，样式 `@title`（即 `text;html=1;fontSize=16;fontStyle=1;fontFamily=Arial;align=left;verticalAlign=middle;`），放左上角，坐标不为负。
- 标签换行用 `&lt;br&gt;`（`html=1` 时），第一行加粗写名称、第二行写职责：`&lt;b&gt;Planner Agent&lt;/b&gt;&lt;br&gt;任务拆解`。
- 中文标签按约 12px/字估算宽度；一行超过 10 个汉字就换行或加宽节点。
- **特殊字符（重要）**：`html=1` 时标签是 HTML，在 XML 属性里要**双重转义**：字面的 `<` `>` `&` 写成 `&amp;lt;` `&amp;gt;` `&amp;amp;`；
  只写一层时，`<` 后面紧跟英文字母的部分会被当成 HTML 标签吞掉（实测：`&lt;api&gt;` 渲染后消失，`&lt;服务&gt;`、`a &lt; b` 正常）。
  为免踩坑，字面的 `<` `>` `&` 一律双重转义。引号写 `&quot;`。`check` 会提示会被吞掉的文字。

## 5. 容器（分层 / 分组 / 泳道）

- 用 `group`（横向标题）或 `lane`（纵向标题，泳道）做容器；子节点 `parent` 设为容器 id，坐标**相对容器左上角**。
- spec 里子节点写 `"group": "<容器id>"`，check 会核对 parent。
- 容器内留边：子节点距容器边框 ≥ 20px。
- 子节点在容器内垂直居中：`y = startSize + (容器高 − startSize − 节点高) / 2`（group 的 startSize=28；lane 是左侧竖排标题，子节点 `y = (容器高 − 节点高) / 2`，`x` 从 startSize+20 起）。
- 跨容器的连线 `parent="1"`（挂在根层），不要挂在某个容器里。

## 6. 图例

首次 `round` 自动生成（也可手动运行 `diagram.py legend <slug>`）：**按页**判断，某页用到 ≥ 3 种 kind、或有待定项 / 待定关系、或用了默认以外的连线类型时，在该页底部生成图例（只含该页实际用到的类型，色块取图中实际样式）；之后每次 `round` 自动刷新。
流程图的通用符号（步骤 / 判断 / 开始结束）在纯流程图页不进图例；纯流程图只有出现待定项或特殊连线时才生成图例。

## 7. 保留 id

`title`、`legend*`、`note-*`、以下划线开头的 id（如 `adopt` 生成的 `_grp-1`）不参与清单一致性检查。
你加的备注用 `note` 类型、id 以 `note-` 开头；用户在 draw.io 里加的纯文本备注（不连线）也自动豁免、原样保留。
