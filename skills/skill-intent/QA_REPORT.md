# skill-qa 报告：skill-intent 0.1.0

**结论：可分发**（SkillHub 分级：include）。可以导入 skill-hub 仓库（hub import），提 PR 时附上本报告。

- 日期：2026-11-27；skill-qa 0.2.1；评审：agent
- 内容哈希：`b48381aeb81b28f52babaaa2503589496da61d32394366471efa47cc03681789`（改动任何文件后报告即失效，需重跑）
- 阈值为规范建议值（评测 80%、触发 90%、误触发 10%、评分 8/10），待负责人确认

## 门禁

| # | 检查项 | 级别 | 结果 | 说明 |
| --- | --- | --- | --- | --- |
| G1 | 结构与 frontmatter 合规（agentskills 规范 + Claude 限制） | 阻断 | 通过 |  |
| G2 | SKILL.md 提到的文件都在，或属于已声明的依赖 Skill | 阻断 | 通过 |  |
| G3 | 不写死自己的安装路径 | 阻断 | 通过 |  |
| G4 | 依赖（Skill、命令、环境变量）全部写进 requires | 阻断 | 通过 | 已声明：{"commands":["node"]}；脚本里用到但未声明的命令候选：go, skillhub；"go" 是英文注释里的单词（intent.mjs:97 "may this skill go on"），skillhub 只出现在更新说明里，脚本不调用；node 已声明 |
| G5 | （可选）evals 至少 3 条任务用例 + 3 条不该触发用例 | 提示 | 通过 | 任务用例 5 条（要求 ≥ 3），不该触发用例 5 条（要求 ≥ 3），该触发用例 5 条 |
| G6 | （可选）任务评测通过率 ≥ 80%，且不低于不装 Skill 的基线 | 提示 | 可选未跑 | 默认不跑；需要时用 skill-creator 跑并写进 review.json |
| G7 | （可选）触发评测：该触发的 ≥ 90%，误触发 ≤ 10% | 提示 | 可选未跑 | 默认不跑；需要时用 skill-creator 跑并写进 review.json |
| G8 | 评分表总分 ≥ 8/10，且“安全”不为 0 | 阻断 | 通过 | 10/10（触发 2，可执行 2，确定性 2，安全 2，可移植 2） |
| G9 | 打包副本自包含（SKILL.md 引用的文件都在打包里） | 阻断 | 通过 | 打包 7 个文件，引用完整 |
| G10 | 本版本的 CHANGELOG 条目写了实际内容 | 阻断 | 通过 |  |
| G11 | 不含密钥、内网地址、客户名 | 阻断 | 通过 | 未配置客户名脱敏词（~/.skill-qa/redact.txt） |
| G12 | 脚本有单元测试 | 警告 | 通过 | 1 个脚本，1 个测试文件 |
| G13 | SKILL.md 不超过 500 行 | 警告 | 通过 | 86 行 |
| G14 | 没有未知 frontmatter 字段和无扩展名文件 | 警告 | 通过 |  |
| G15 | 没有个人化耦合（作者姓名、个人路径、个人分支前缀、邮箱） | 阻断 | 通过 | 按 1 个作者身份词检查 |
| G16 | 状态位写进 config.schema.json（固定/预设/实例/角色四层 + 首次引导） | 阻断 | 通过 | 4 个状态位，1 个需要问用户 |
| S1 | 没有“下载即执行”、高危删除等危险操作 | 阻断 | 通过 |  |
| S2 | 包体积与目录限制（单文件 ≤ 10 MB，总计 ≤ 100 MB，无顶层 bin/） | 阻断 | 通过 | 7 个文件，24 KB |
| S4 | 安全扫描器（与 SkillHub 同款）的每条告警都已处置：修复，或登记为例外 | 阻断 | 通过 | cisco skill-scanner (default policy)：SAFE 共 3 条，MEDIUM 及以上 0 条 |
| R1 | SKILL.md 写明源码仓库，以及更新和反馈问题的方式 | 阻断 | 通过 |  |
| S3 | 写明 license（SkillHub 扫描会提示） | 提示 | 通过 |  |

## 评分表

| 项 | 分数（0–2） | 依据 |
| --- | --- | --- |
| 触发 | 2 | description 列出"这个 skill 想给团队用""先对齐一下目标"等说法，写明质检用 skill-qa、写正文用 skill-creator |
| 可执行 | 2 | 6 步流程有顺序；references/rules.md 与 assets/INTENT.template.md 都写明何时读；86 行 |
| 确定性 | 2 | init/check/show 在 scripts/intent.mjs，结构校验（每节 ≥3 条、驳回要理由）有 tests/intent.test.mjs；收敛判断交给 Agent 与用户对话，属于判断而非拼命令 |
| 安全 | 2 | 只写 Skill 目录里的 INTENT.md；没有删除、推送、发消息；扫描 SAFE |
| 可移植 | 2 | 脚本路径从 SKILL.md 所在目录算；只依赖 node；INTENT.md 不进安装包 |

## 备注

- 按负责人 2026-11-26 决定，评测（G6/G7）可选，本次只做静态质检

<!-- skill-qa {"qa_version":"0.2.1","name":"skill-intent","version":"0.1.0","verdict":"include","hash":"b48381aeb81b28f52babaaa2503589496da61d32394366471efa47cc03681789","date":"2026-11-27"} -->
