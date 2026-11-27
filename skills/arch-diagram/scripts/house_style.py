"""House style: the single source of truth for node/edge styles.

references/style-guide.md documents these strings; tests/test_scripts.py asserts the doc and this
module agree, so the two cannot drift apart.
"""

FONT = "fontFamily=Arial;fontSize=12;"

# kind -> (中文名, style, default (w, h))
KINDS = {
    "agent": ("智能体 Agent", "rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#e3f2fd;strokeColor=#1565c0;" + FONT, (160, 60)),
    "service": ("服务 / 模块", "rounded=0;whiteSpace=wrap;html=1;fillColor=#e0f2f1;strokeColor=#00796b;" + FONT, (160, 60)),
    "control": ("编排 / 网关", "rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#f3e5f5;strokeColor=#6a1b9a;" + FONT, (160, 60)),
    "datastore": ("存储 / 记忆 / 知识库", "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;whiteSpace=wrap;html=1;fillColor=#e8f5e9;strokeColor=#2e7d32;" + FONT, (120, 80)),
    "external": ("外部系统", "rounded=1;arcSize=12;dashed=1;whiteSpace=wrap;html=1;fillColor=#eceff1;strokeColor=#455a64;" + FONT, (160, 60)),
    "channel": ("触点 / 渠道", "rounded=1;arcSize=12;whiteSpace=wrap;html=1;fillColor=#fff3e0;strokeColor=#e65100;" + FONT, (140, 50)),
    "actor": ("角色", "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;outlineConnect=0;fillColor=#eceff1;strokeColor=#455a64;" + FONT, (40, 70)),
    "step": ("流程步骤", "rounded=1;arcSize=20;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#455a64;" + FONT, (140, 50)),
    "decision": ("判断", "rhombus;whiteSpace=wrap;html=1;fillColor=#fff9c4;strokeColor=#f57c00;" + FONT, (140, 80)),
    "terminal": ("开始 / 结束", "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#e8f5e9;strokeColor=#2e7d32;" + FONT, (120, 40)),
    "note": ("备注", "shape=note;size=12;whiteSpace=wrap;html=1;align=left;spacingLeft=6;fillColor=#fffde7;strokeColor=#fbc02d;fontFamily=Arial;fontSize=11;", (180, 60)),
    "group": ("分层 / 分组容器", "swimlane;startSize=28;collapsible=0;rounded=0;html=1;whiteSpace=wrap;fillColor=#fafafa;strokeColor=#90a4ae;fontStyle=1;fontFamily=Arial;fontSize=13;", (600, 200)),
    "lane": ("泳道", "swimlane;horizontal=0;startSize=32;collapsible=0;html=1;whiteSpace=wrap;fillColor=#fafafa;strokeColor=#90a4ae;fontStyle=1;fontFamily=Arial;fontSize=13;", (900, 140)),
}

# appended to a node style when its spec status is "tbd"; label gets the prefix below
TBD_SUFFIX = "dashed=1;dashPattern=8 4;fillColor=#fffde7;strokeColor=#f9a825;fontColor=#8d6e00;"
TBD_PREFIX = "【待定】"
# appended to an edge style when the relation itself is undecided (spec edge "status": "tbd")
TBD_EDGE_SUFFIX = "dashed=1;dashPattern=8 4;strokeColor=#f9a825;fontColor=#8d6e00;"
# flowchart vocabulary is universal: never put it in a legend
FLOW_KINDS = ("step", "decision", "terminal")

EDGE_BASE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;"
             "endArrow=classic;endFill=1;fontFamily=Arial;fontSize=11;labelBackgroundColor=#ffffff;")
# edge type -> (中文名, style)
EDGES = {
    "sync": ("调用 / 数据流", EDGE_BASE + "strokeColor=#37474f;"),
    "async": ("异步 / 事件 / 消息", EDGE_BASE + "strokeColor=#37474f;dashed=1;"),
    "readwrite": ("读写（双向）", EDGE_BASE + "startArrow=classic;startFill=1;strokeColor=#2e7d32;fontColor=#2e7d32;"),
    "feedback": ("反馈 / 打回", EDGE_BASE + "strokeColor=#c62828;fontColor=#c62828;"),
}

HIGHLIGHT = "strokeColor=#E53935;strokeWidth=3;"
TITLE_STYLE = "text;html=1;fontSize=16;fontStyle=1;fontFamily=Arial;align=left;verticalAlign=middle;"
RESERVED_PREFIXES = ("title", "legend", "note-", "_")


# Style macros: Claude writes style="@agent" / "@sync;exitX=1;..." and every command expands them, before anything
# else reads the file, into exactly the strings above (rest of the style kept verbatim after the house string).
MACROS = {"title": TITLE_STYLE}
for _k, (_n, _s, _wh) in KINDS.items():
    MACROS[_k] = _s
    MACROS[_k + "+tbd"] = _s + TBD_SUFFIX
for _k, (_n, _s) in EDGES.items():
    MACROS[_k] = _s
    MACROS[_k + "+tbd"] = _s + TBD_EDGE_SUFFIX
