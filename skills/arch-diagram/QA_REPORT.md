# skill-qa 报告：arch-diagram 2.1.3

**结论：可分发**（SkillHub 分级：include）。可以导入 skill-hub 仓库（hub import），提 PR 时附上本报告。

- 日期：2026-11-27；skill-qa 0.2.1；评审：agent
- 内容哈希：`89c49487b40aeaf1b4544f7625e29f1d116c09f021dcfab1da4a5f10cd005cc4`（改动任何文件后报告即失效，需重跑）
- 阈值为规范建议值（评测 80%、触发 90%、误触发 10%、评分 8/10），待负责人确认

## 门禁

| # | 检查项 | 级别 | 结果 | 说明 |
| --- | --- | --- | --- | --- |
| G1 | 结构与 frontmatter 合规（agentskills 规范 + Claude 限制） | 阻断 | 通过 |  |
| G2 | SKILL.md 提到的文件都在，或属于已声明的依赖 Skill | 阻断 | 通过 | 缺 references/autolayout.md, references/derasterize.md, references/diagram-types.md, references/xml-authoring.md, scripts/autolayout.py, scripts/edgeports.py；需确认它们都属于 requires.skills（drawio-skill）；Agent 已确认 |
| G3 | 不写死自己的安装路径 | 阻断 | 通过 |  |
| G4 | 依赖（Skill、命令、环境变量）全部写进 requires | 阻断 | 通过 | 已声明：{"skills":["drawio-skill"],"commands":["py"]}；脚本里用到但未声明的命令候选：draw.io, feishu, go, lark-cli, npm, npx, skillhub；G2：缺的 6 个文件（references/autolayout.md、derasterize.md、diagram-types.md、xml-authoring.md，scripts/autolayout.py、edgeports.py）都属于 requires.skills 的 drawio-skill，SKILL.md 以 $DS 引用。G4：已声明 py；draw.io 是桌面程序，由脚本自动定位、不要求在 PATH 上（notes 写明）；lark-cli、npm、npx 只用于可选的飞书同步与 --dry-run 预览（notes 写明）；go、feishu、skillhub 只出现在说明文字或报错提示里，属误报 |
| G5 | （可选）evals 至少 3 条任务用例 + 3 条不该触发用例 | 提示 | 通过 | 任务用例 6 条（要求 ≥ 3），不该触发用例 9 条（要求 ≥ 3），该触发用例 10 条 |
| G6 | （可选）任务评测通过率 ≥ 80%，且不低于不装 Skill 的基线 | 提示 | 可选未跑 | 默认不跑；需要时用 skill-creator 跑并写进 review.json |
| G7 | （可选）触发评测：该触发的 ≥ 90%，误触发 ≤ 10% | 提示 | 可选未跑 | 默认不跑；需要时用 skill-creator 跑并写进 review.json |
| G8 | 评分表总分 ≥ 8/10，且“安全”不为 0 | 阻断 | 通过 | 9/10（触发 2，可执行 2，确定性 2，安全 2，可移植 1） |
| G9 | 打包副本自包含（SKILL.md 引用的文件都在打包里） | 阻断 | 通过 | 打包 15 个文件，引用完整；VERSION 没有扩展名，SkillHub 打包会去掉，而脚本或 SKILL.md 读取了它：冒烟必须在去掉这些文件的副本上跑，确认有回退（不允许靠删文件过关）；Agent 读代码确认有回退后在 review.json 写 evals.smoke.ok=true；读代码确认：VERSION 文件没有被脚本读取（diagram.py 的 VERSION 是代码内常量）。并按 tools/hub/cli.mjs files 的打包清单去掉无扩展名文件（VERSION）和 .gitignore 后拷到临时目录，在副本上真实跑通 doctor → new smoke → round（check 通过、导出 PNG/SVG、快照 r01） |
| G10 | 本版本的 CHANGELOG 条目写了实际内容 | 阻断 | 通过 |  |
| G11 | 不含密钥、内网地址、客户名 | 阻断 | 通过 | 未配置客户名脱敏词（~/.skill-qa/redact.txt） |
| G12 | 脚本有单元测试 | 警告 | 通过 | 6 个脚本，33 个测试文件 |
| G13 | SKILL.md 不超过 500 行 | 警告 | 通过 | 111 行 |
| G14 | 没有未知 frontmatter 字段和无扩展名文件 | 警告 | 警告 | VERSION 没有扩展名，SkillHub 打包时会去掉 |
| G15 | 没有个人化耦合（作者姓名、个人路径、个人分支前缀、邮箱） | 阻断 | 通过 | 按 5 个作者身份词检查 |
| G16 | 状态位写进 config.schema.json（固定/预设/实例/角色四层 + 首次引导） | 阻断 | 通过 | 16 个状态位，1 个需要问用户 |
| S1 | 没有“下载即执行”、高危删除等危险操作 | 阻断 | 通过 |  |
| S2 | 包体积与目录限制（单文件 ≤ 10 MB，总计 ≤ 100 MB，无顶层 bin/） | 阻断 | 通过 | 15 个文件，177 KB |
| S4 | 安全扫描器（与 SkillHub 同款）的每条告警都已处置：修复，或登记为例外 | 阻断 | 通过 | cisco skill-scanner (default policy)：SAFE 共 0 条，MEDIUM 及以上 0 条 |
| R1 | SKILL.md 写明源码仓库，以及更新和反馈问题的方式 | 阻断 | 通过 |  |
| S3 | 写明 license（SkillHub 扫描会提示） | 提示 | 通过 |  |

## 评分表

| 项 | 分数（0–2） | 依据 |
| --- | --- | --- |
| 触发 | 2 | description 写明做什么（讨论→可编辑 draw.io 架构图→多轮迭代）、列出画/改/diff/回退/导出/同步飞书等真实说法，并写明不用于数据图表和 UI 原型；与 Hub 现有的 skill-hub-ops、blacklake-auto-git 无冲突。'同步飞书'限定在架构图语境，与飞书文档正文类 Skill 的边界写在 references/intent.md |
| 可执行 | 2 | SKILL.md 111 行：第 0 节适用前提与执行环境（含 doctor 首查），第 1 节 8 条核心规则，第 2–5 节新建/迭代/交付/画法路径，每个 reference 写明何时读（iteration.md 首次必读、human-edits.md 有人工改动时、feishu-sync.md 报错时） |
| 确定性 | 2 | 文件管理、校验、导出、快照/diff/restore、人工改动识别、飞书画板转换都在 scripts/diagram.py 等 6 个脚本里，tests/ 下 91 个单测（Windows 上全过）；SKILL.md 只负责内容判断（节点、关系、意图分析） |
| 安全 | 2 | 飞书画板被人改过时不自动 --force（SKILL.md 第 4 节，只在用户明确要求时覆盖）；密钥与授权不经过 Agent（config.schema.json lark_auth sensitive、feishu-sync.md）；只覆盖本工具建的画板、不改文档其他内容；安全扫描 SAFE、零告警 |
| 可移植 | 1 | 路径改为从 SKILL.md 所在目录推导，drawio-skill 按同级/项目级/用户级查找，依赖写进 requires，用户数据在 ARCH_DIAGRAMS_ROOT（升级不丢），开头写明适用前提；但只在 Windows 上实际验证过，requires.commands 里的 py 是 Windows 写法（macOS/Linux 用 python3 只在 notes 说明），且 drawio-skill 还不在 Hub 上，需另行安装 |

## 备注

- 评测（G5–G7）按 skill-qa 0.2.1 为可选，未跑；用例已按目标卡写好放在 evals/，需要时可补跑
- 目标卡按交接文档第 3 版放在 ~/.skill-qa/work/arch-diagram-INTENT.md（PR #15 合并前不进 Skill 目录）；Skill 内另有 references/intent.md 作为说明文档

<!-- skill-qa {"qa_version":"0.2.1","name":"arch-diagram","version":"2.1.3","verdict":"include","hash":"89c49487b40aeaf1b4544f7625e29f1d116c09f021dcfab1da4a5f10cd005cc4","date":"2026-11-27"} -->
