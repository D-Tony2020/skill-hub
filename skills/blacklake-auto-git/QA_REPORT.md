# skill-qa 报告：blacklake-auto-git 2.0.1

**结论：可分发**（SkillHub 分级：include）。可以导入 skill-hub 仓库（hub import），提 PR 时附上本报告。

- 日期：2026-11-26；skill-qa 0.2.0；评审：agent
- 内容哈希：`bdda998224ad8151535d52f3021a04ec2890fded4af0d0883de40a7bd89ce776`（改动任何文件后报告即失效，需重跑）
- 阈值为规范建议值（评测 80%、触发 90%、误触发 10%、评分 8/10），待负责人确认

## 门禁

| # | 检查项 | 级别 | 结果 | 说明 |
| --- | --- | --- | --- | --- |
| G1 | 结构与 frontmatter 合规（agentskills 规范 + Claude 限制） | 阻断 | 通过 |  |
| G2 | SKILL.md 提到的文件都在，或属于已声明的依赖 Skill | 阻断 | 通过 |  |
| G3 | 不写死自己的安装路径 | 阻断 | 通过 |  |
| G4 | 依赖（Skill、命令、环境变量）全部写进 requires | 阻断 | 通过 | 已声明：{"commands":["git","ssh","ssh-keygen","ssh-keyscan","curl"]}；脚本里用到但未声明的命令候选：skillhub；G4 候选 skillhub 只出现在 bag.sh:516 的 E_SRC_HUB 报错提示文字里（提示用户用 skillhub upgrade），脚本不调用它，不是依赖。skill-qa 误报，已记入 skill-qa 待修 |
| G5 | evals 至少 3 条任务用例 + 3 条不该触发用例 | 阻断 | 通过 | 任务用例 16 条（要求 ≥ 3），不该触发用例 6 条（要求 ≥ 3），该触发用例 7 条 |
| G6 | 任务评测通过率 ≥ 80%，且不低于不装 Skill 的基线 | 阻断 | 通过 | 15/16（94%），基线 1/16，skill-creator / claude-opus-5-5 |
| G7 | 触发评测：该触发的 ≥ 90%，误触发 ≤ 10% | 阻断 | 通过 | 该触发 7/7（100%），误触发 0/6（0%） |
| G8 | 评分表总分 ≥ 8/10，且“安全”不为 0 | 阻断 | 通过 | 8/10（触发 1，可执行 2，确定性 2，安全 2，可移植 1） |
| G9 | 干净目录安装后可用（打包副本自包含 + 跑通一条评测） | 阻断 | 通过 | 打包 13 个文件，引用完整；还需在安装副本上跑一条评测；VERSION 没有扩展名，SkillHub 打包会去掉，而脚本或 SKILL.md 读取了它：冒烟必须在去掉这些文件的副本上跑，确认有回退（不允许靠删文件过关）；按 SkillHub 打包形态（去掉 VERSION、tests、evals、hub.yaml）装进全新目录：16 条任务评测都在该副本上跑（15 过）；另在全新 HOME 下真实执行 bag version / init / doctor，init 给出 suggested_prefix=zhangsan-cc/，doctor 正确停在 E_NOT_PAIRED；VERSION 缺失时回退为 0.0.0，不影响运行 |
| G10 | 本版本的 CHANGELOG 条目写了实际内容 | 阻断 | 通过 |  |
| G11 | 不含密钥、内网地址、客户名 | 阻断 | 通过 | 测试/评测夹具里有 14 处像密钥或内网地址的假值（evals/evals.json:45、tests/harness.py:22、tests/harness.py:22、tests/test_airlock.py:118、tests/test_airlock.py:221 等），不进发布包；Agent 需确认都是假的；未配置客户名脱敏词（~/.skill-qa/redact.txt） |
| G12 | 脚本有单元测试 | 警告 | 通过 | 5 个脚本，6 个测试文件 |
| G13 | SKILL.md 不超过 500 行 | 警告 | 通过 | 157 行 |
| G14 | 没有未知 frontmatter 字段和无扩展名文件 | 警告 | 警告 | VERSION 没有扩展名，SkillHub 打包时会去掉 |
| G15 | 没有个人化耦合（作者姓名、个人路径、个人分支前缀、邮箱） | 阻断 | 通过 | 按 1 个作者身份词检查 |
| G16 | 状态位写进 config.schema.json（固定/预设/实例/角色四层 + 首次引导） | 阻断 | 通过 | 11 个状态位，5 个需要问用户 |
| S1 | 没有“下载即执行”、高危删除等危险操作 | 阻断 | 通过 | 提权操作 13 处（scripts/bag.sh:200、scripts/bag.sh:214、scripts/mac/airlock.py:423、scripts/mac/install.sh:5、scripts/mac/install.sh:6、scripts/mac/install.sh:7 等），评分“安全”项需说明理由；SkillHub 扫描可能判为 CRITICAL，必要的写进 qa-exceptions.json |
| S2 | 包体积与目录限制（单文件 ≤ 10 MB，总计 ≤ 100 MB，无顶层 bin/） | 阻断 | 通过 | 13 个文件，135 KB |
| S4 | 安全扫描器（与 SkillHub 同款）的每条告警都已处置：修复，或登记为例外 | 阻断 | 通过 | cisco skill-scanner (default policy)：NOT SAFE, max CRITICAL 共 4 条，MEDIUM 及以上 3 条；已登记例外：CRITICAL COMPOUND_FETCH_EXECUTE scripts/bag.sh：扫描器按整个文件匹配 curl 和 sudo bash；给 Mac 的安装命令在执行前用 shasum -a 256 -c 核对安装器哈希，哈希不一致就不执行（1.1.2 起），同网段篡改无法生效（Dean 确认）；MEDIUM DATA_EXFIL_ENV_VARS scripts/mac/airlock.py：气闸调用 git 转推 GitLab 时复制当前进程环境变量并加入 GIT_* 和代理设置，只传给本机 git 子进程，不发往任何网络地址；令牌只经 GitLab HTTPS 认证头使用（Dean 确认）；CRITICAL TOOL_ABUSE_SYSTEM_MODIFICATION scripts/mac/install.sh：安装器要创建专用 airlock 用户、写 sshd 限制配置和 launchd 系统服务，这些文件必须 root 所有（chown root），否则 launchd/sshd 拒绝加载；这是气闸的安全边界本身（Dean 确认） |
| R1 | SKILL.md 写明源码仓库，以及更新和反馈问题的方式 | 阻断 | 通过 |  |
| S3 | 写明 license（SkillHub 扫描会提示） | 提示 | 通过 |  |

## 评分表

| 项 | 分数（0–2） | 依据 |
| --- | --- | --- |
| 触发 | 1 | description 写清了做什么，并列出真实说法（拉一下最新代码、把改动推上去、提 MR 等），触发评测 13/13；但没有写不用于什么（例如 GitHub/公网仓库、普通 git 问答），按评分表只能给 1 |
| 可执行 | 2 | SKILL.md 157 行：第一屏是适用前提、角色和硬规则，搭建与日常流程分步有序；末尾 references 列表逐份写了什么时候读（setup-runbook、troubleshooting、architecture、iteration） |
| 确定性 | 2 | 拼 ssh/git、配对、打包、推送、读 MR 评论都在 scripts/bag.sh 与 scripts/mac/*，有 5 个测试文件，tests/run_all.sh 全部通过（真实 sshd 层在本容器跳过 1 项）；SKILL.md 只负责调度和判断 |
| 安全 | 2 | 只推 Agent 分支、只建 Draft MR、从不合并；改 main、force push、--ready 都要用户明确要求；token 只在 Mac 安装器输入（2.0.1 补了泄露 token 的轮换规则）；提权仅在 Mac 安装器，理由写在 qa-exceptions.json，3 条 MEDIUM 以上扫描告警均为负责人确认过的例外 |
| 可移植 | 1 | 路径从脚本自身目录推导、requires 已声明、开头写明只支持 Windows + Git Bash 和同网前提；但 SkillHub 打包会去掉无扩展名的 VERSION，安装副本 bag version 显示 skill=0.0.0（可运行，版本号不准），容易修，先扣 1 分 |

## 备注

- 触发评测按 skill-creator run_eval.py 跑，--num-workers 1、每条 3 次、在独立项目目录；第一次用默认并发得到 1/21 是并发互相抢触发的伪结果，已作废
- 任务评测在 Agent 提示里显式给出 Skill 路径（skill-creator 做法），命令不真实执行，按 expectations 由裁判模型逐条判；2.0.0 为 12/16，2.0.1 修复令牌泄露规则并修正 setup-pair 用例（负责人同意）后 15/16，未过的 mac-ip-changed 是继续任务前多问了一句
- 扫描器 2.3.2 另报 1 条 LOW UNDECLARED_NETWORK_DESTINATION（install.sh:251 plist 里的 apple.com DTD 声明，不发起网络请求），LOW 不要求处置

<!-- skill-qa {"qa_version":"0.2.0","name":"blacklake-auto-git","version":"2.0.1","verdict":"include","hash":"bdda998224ad8151535d52f3021a04ec2890fded4af0d0883de40a7bd89ce776","date":"2026-11-26"} -->
