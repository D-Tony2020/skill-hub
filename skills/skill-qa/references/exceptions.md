# 已登记例外（qa-exceptions.json）

有些告警是必要行为（安装系统服务就得改属主），有些是扫描器误报（SkillHub 的扫描器只要在同一个文件里看到 curl 和 sudo bash 就报，不管执行前有没有核对哈希）。这类告警不应该靠改代码躲开扫描规则，那样安全性并不会提高；也不应该每发一个版本就重新判断一遍。做法是把它登记为例外，由负责人书面确认一次，之后的版本自动沿用。

## 能豁免什么

| 门禁 | 例子 |
| --- | --- |
| G3 写死安装路径 | 安装脚本本来就是要写到 `~/.claude/skills` |
| G12–G14 警告项 | 纯文档型 Skill 没有脚本测试 |
| S1 危险操作 | 安装系统服务时的 `chown root:wheel` |
| S2 包限制 | 确有必要的大文件 |
| SCAN 扫描告警 | 扫描器误报、必要行为 |

**不能豁免**：G1 结构、G2 缺文件、G4 依赖、G5–G8 评测与评分、G9 安装冒烟、G10 CHANGELOG、G11 密钥与内网信息、R1 源码仓库。

## 格式

放在 Skill 根目录的 `qa-exceptions.json`，不进发布包，进内容哈希，所以改了例外要重跑报告：

```json
[
  {
    "gate": "SCAN",
    "rule": "COMPOUND_FETCH_EXECUTE",
    "file": "scripts/bag.sh",
    "reason": "扫描器按整个文件匹配 curl 和 sudo bash；实际命令执行前用 shasum -a 256 -c 核对哈希，哈希不对就不执行",
    "approved_by": "Dean",
    "date": "2026-11-26"
  },
  {
    "gate": "SCAN",
    "rule": "TOOL_ABUSE_SYSTEM_MODIFICATION",
    "file": "scripts/mac/install.sh",
    "reason": "安装 launchd 系统服务必须 chown root:wheel",
    "approved_by": "Dean",
    "date": "2026-11-26"
  }
]
```

字段说明：
- `gate`：必填，门禁编号，扫描告警写 `SCAN`。
- `rule`：扫描告警的规则 ID，SCAN 必填。
- `file`：限定到具体文件，强烈建议填。不填就是对这个门禁的所有文件都生效，范围太大。
- `match`：可选，只豁免说明里包含这段文字的告警。
- `reason`：必填，写清楚为什么必要或为什么是误报，要让第三个人看得懂。
- `approved_by`：必填，负责人的名字。**只有负责人本人在对话里明确同意后才能填**。Agent 起草的条目在负责人确认前不写这个字段，这样它不会生效。
- `date`：确认日期。

## 上架时

SkillHub 服务端扫描仍会显示这些告警。审批时在审批意见里引用对应的 `reason`，这就是负责人的书面确认。
