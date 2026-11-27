# skill-qa 报告：skill-creator 1.0.0

**结论：可分发**（SkillHub 分级：include）。可以导入 skill-hub 仓库（hub import），提 PR 时附上本报告。

- 日期：2026-11-27；skill-qa 0.2.1；评审：agent
- 内容哈希：`03a2563d1f6467247f5c8031f98000073d89bd52c4e1c00d970d6af505abf763`（改动任何文件后报告即失效，需重跑）
- 阈值为规范建议值（评测 80%、触发 90%、误触发 10%、评分 8/10），待负责人确认

## 门禁

| # | 检查项 | 级别 | 结果 | 说明 |
| --- | --- | --- | --- | --- |
| G1 | 结构与 frontmatter 合规（agentskills 规范 + Claude 限制） | 阻断 | 通过 |  |
| G2 | SKILL.md 提到的文件都在，或属于已声明的依赖 Skill | 阻断 | 通过 |  |
| G3 | 不写死自己的安装路径 | 阻断 | 通过 |  |
| G4 | 依赖（Skill、命令、环境变量）全部写进 requires | 阻断 | 通过 | 已声明：{"commands":["python","claude"]}；脚本里用到但未声明的命令候选：go, skillhub；go 与 skillhub 是英文正文里的单词（如 "go straight to the eval"），不是命令；脚本只用 python 与 claude，已声明 |
| G5 | （可选）evals 至少 3 条任务用例 + 3 条不该触发用例 | 提示 | 通过 | 任务用例 3 条（要求 ≥ 3），不该触发用例 4 条（要求 ≥ 3），该触发用例 3 条 |
| G6 | （可选）任务评测通过率 ≥ 80%，且不低于不装 Skill 的基线 | 提示 | 可选未跑 | 默认不跑；需要时用 skill-creator 跑并写进 review.json |
| G7 | （可选）触发评测：该触发的 ≥ 90%，误触发 ≤ 10% | 提示 | 可选未跑 | 默认不跑；需要时用 skill-creator 跑并写进 review.json |
| G8 | 评分表总分 ≥ 8/10，且“安全”不为 0 | 阻断 | 通过 | 9/10（触发 2，可执行 2，确定性 1，安全 2，可移植 2） |
| G9 | 打包副本自包含（SKILL.md 引用的文件都在打包里） | 阻断 | 通过 | 打包 20 个文件，引用完整 |
| G10 | 本版本的 CHANGELOG 条目写了实际内容 | 阻断 | 通过 |  |
| G11 | 不含密钥、内网地址、客户名 | 阻断 | 通过 | 未配置客户名脱敏词（~/.skill-qa/redact.txt） |
| G12 | 脚本有单元测试 | 警告 | 警告 | 9 个脚本，0 个测试文件；9 个脚本没有测试 |
| G13 | SKILL.md 不超过 500 行 | 警告 | 通过 | 500 行 |
| G14 | 没有未知 frontmatter 字段和无扩展名文件 | 警告 | 通过 |  |
| G15 | 没有个人化耦合（作者姓名、个人路径、个人分支前缀、邮箱） | 阻断 | 通过 | 按 1 个作者身份词检查 |
| G16 | 状态位写进 config.schema.json（固定/预设/实例/角色四层 + 首次引导） | 阻断 | 通过 | 没有状态位迹象，不需要配置清单 |
| S1 | 没有“下载即执行”、高危删除等危险操作 | 阻断 | 通过 |  |
| S2 | 包体积与目录限制（单文件 ≤ 10 MB，总计 ≤ 100 MB，无顶层 bin/） | 阻断 | 通过 | 20 个文件，222 KB |
| S4 | 安全扫描器（与 SkillHub 同款）的每条告警都已处置：修复，或登记为例外 | 阻断 | 通过 | cisco skill-scanner (default policy)：NOT SAFE, max CRITICAL 共 4 条，MEDIUM 及以上 1 条；已登记例外：CRITICAL COMMAND_INJECTION_OS_SYSTEM eval-viewer/generate_review.py：上游原样代码：_kill_port 以参数数组调用固定命令 lsof -ti :<端口>（端口是整数），只为在启动评测查看器前结束占用同一端口的旧查看器进程；不经 shell，参数不来自用户输入。镜像不改上游代码，有顾虑应提给上游（Dean 确认） |
| R1 | SKILL.md 写明源码仓库，以及更新和反馈问题的方式 | 阻断 | 通过 |  |
| S3 | 写明 license（SkillHub 扫描会提示） | 提示 | 通过 |  |

## 评分表

| 项 | 分数（0–2） | 依据 |
| --- | --- | --- |
| 触发 | 2 | 上游 description 写明创建、修改、评测、优化 description 等用法；与 Hub 内其他 Skill 不冲突（写正文用它，对齐用 skill-intent，质检用 skill-qa） |
| 可执行 | 2 | 上游 SKILL.md 约 500 行（在上限内），流程按 捕获意图→写草稿→跑评测→迭代 展开；agents/、references/ 都写了何时读 |
| 确定性 | 1 | 评测、聚合、报告、打包都在 scripts/ 与 eval-viewer/，但上游没有附带单元测试（G12 警告）；镜像不改上游 |
| 安全 | 2 | 唯一 CRITICAL 是 generate_review.py 用参数数组调用固定 lsof 结束旧查看器进程，不经 shell，负责人 2026-11-27 批准例外；无密钥与内网信息；LOW 级为 HTML 报告引用 Google Fonts |
| 可移植 | 2 | 脚本路径从 Skill 目录算；python、claude 已写进 requires；Apache-2.0 LICENSE.txt 与 NOTICE.md 随包 |

## 备注

- 官方镜像，无需 INTENT.md；按负责人 2026-11-26 决定评测可选，本次只做静态质检
- G12 无测试为警告项，不另登记例外

<!-- skill-qa {"qa_version":"0.2.1","name":"skill-creator","version":"1.0.0","verdict":"include","hash":"03a2563d1f6467247f5c8031f98000073d89bd52c4e1c00d970d6af505abf763","date":"2026-11-27"} -->
