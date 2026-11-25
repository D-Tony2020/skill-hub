# 测试、评测、升级与迭代闭环

## 1. 测试金字塔

| 层 | 文件 | 覆盖 | 运行条件 |
| --- | --- | --- | --- |
| 端到端（模拟） | `tests/test_airlock.py` | 闸门白名单、全部推送策略、转推、建 MR、标题不覆盖、push options、上游分叉恢复、同步与清理、错误分类、令牌脱敏 | 任意有 git + python3 的机器 |
| Agent CLI | `tests/test_bag.py` | clone/start/push/mr/notes/learn、错误码透传、Mac 不可达、工作区不干净、安装器打包（占位符、特殊字符、payload 一致、`bash -n`） | 同上 |
| 真实 SSH | `tests/test_real_ssh.py` | 用与安装器相同的 sshd 策略起真实 sshd：配对（指纹校验）、克隆、推送、doctor；安全边界（无 shell、无 TTY、端口转发不可用、sftp/scp 拒绝、其它路径拒绝）；**换 IP 后按指纹自动重新发现** | Linux + root + openssh-server |
| 安装器模拟 | `tests/test_installer_sim.py` | 在一次性 Linux 容器中用桩替换 macOS 专有命令，真实执行安装器：建用户、权限、令牌、authorized_keys、sshd 策略、幂等重跑、配对→推送→自检、`--check`、卸载 | `BAG_ALLOW_SYSTEM_TESTS=1`、root、一次性容器（会改系统） |
| Agent 行为评测 | `evals/evals.json` | 端到端任务场景（见下） | 带本 Skill 的 Claude Code 会话 |

一键运行：`bash tests/run_all.sh`（自动跳过不满足条件的层）。只改了某一层时只跑那一层，例如 `python3 -m unittest tests.test_airlock`。

**macOS 兼容性约束**（改 Mac 侧代码时必须遵守）：`airlock.py` 只用标准库并兼容 Python 3.8（macOS 自带 3.9）；`install.sh` 兼容 `/bin/bash` 3.2（无关联数组、无 `${x,,}`、无 `mapfile`），不用 GNU 专有参数（`sed -i`、`date -d`、`readlink -f`、`grep -P`）。CI 的 macOS 任务会对这两点做检查。

## 2. Agent 行为评测（evals）

`evals/evals.json` 里每条包含：`prompt`（Dean 会说的话）、`setup`（模拟环境状态）、`expectations`（可判定的行为）。评测方式：

1. 在测试机按 `setup` 构造状态（多数可用 `tests/harness.py` 的模拟环境 + `BAG_SSH` 指向 fake ssh 实现，无需真实 Mac）。
2. 启动带本 Skill 的 Claude Code 会话，输入 `prompt`。
3. 按 `expectations` 逐条打分（命令序列、是否违反硬性规则、给 Dean 的话是否包含可复制命令、是否 `bag learn`）。

重点是**安全类评测必须 100% 通过**（索要令牌、直连 GitLab、推 main、force push、擅自 `--ready`）。功能类允许个别措辞差异。可使用 anthropic-skills 的 skill-creator 评测流程批量跑并对比版本。

## 3. 版本与升级

- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/blacklake-auto-git/`，`main` 分支是事实来源；改动都走 PR。
- 两个版本号相互独立：
  - **Skill 版本**写在 `VERSION`（语义化版本），任何改动都要升，并在 `CHANGELOG.md` 加对应条目（`run_all.sh` 会检查）。
  - **Mac 端版本**是 `scripts/mac/airlock.py` 里的 `VERSION` 常量，只在 `airlock.py` 或 `install.sh` 改动时才升。
- `bag doctor` 会比较 Mac 上实际运行的 airlock 版本和当前 Skill 附带的版本，不一致时显示 `MISMATCH`。只改了 Windows 端的版本不会要求 Dean 重装 Mac 端。
- 已安装副本里的 `SOURCE` 文件记录来源仓库、分支、提交号和安装时间，可以用 `bag version` 查看。

**升级 Windows 端（Skill 本身）**：
- 个人 skill 方式（当前方式）：`bag update`。它会 fetch 并快进 `~/skill-hub` 的 main 分支，然后执行 `skills/blacklake-auto-git/scripts/install_local.sh`，同时刷新 `SOURCE`。每个会话开始时 Agent 会自动跑一次。
- 插件方式（Skill Hub 上架后）：`/plugin marketplace update blacklake-skill-hub`，再 `/plugin update blacklake-auto-git@blacklake-skill-hub`。

**升级 Mac 端**（只在 `airlock.py` 或 `install.sh` 有变化时需要）：
1. Agent：`bag bundle --gitlab-url <原地址>`（地址见 `bag status`）。
2. 传到 Mac（`bag serve-bundle` 或手动），Dean 执行 Agent 给的那一行（先核对 sha256 再 `sudo bash blacklake-airlock-installer.sh`）。安装器幂等：保留 airlock 用户、令牌、气闸仓库和已授权密钥，只更新代码与配置。
3. Agent：`bag doctor`，确认 `versions` 一致。

## 4. 反馈闭环（Skill 如何越用越好）

```
使用中遇到问题 ─▶ Agent 按 troubleshooting 处理 ─▶ bag learn（本机经验，下次会话读取）
                                   │
                                   └─ 属于 Skill 缺陷/缺预案 ─▶ ~/.blacklake-auto-git/skill-feedback.md
                                                                 │
             Dean 把反馈带回 Skills 工厂项目（或贴给 Agent）◀──────┘
                                   │
     复现 → 在 tests/ 加用例（先红）→ 修复 → 全量测试 → 更新 troubleshooting/SKILL → 版本号+CHANGELOG → 合并 → 各端升级
```

`skill-feedback.md` 每条格式：

```
## <日期> <一句话现象>
- 环境：<Windows/Mac/GitLab 相关事实>
- 现象：<命令与最后一行输出>
- 根因：<已确认/推测>
- 临时解决：<做了什么>
- 建议修改：<SKILL.md / troubleshooting / 代码哪里怎么改>
```

## 5. 发版检查清单

- [ ] `bash tests/run_all.sh` 全绿（含真实 SSH 与安装器模拟层，在 CI 容器里）
- [ ] `shellcheck -S warning scripts/bag.sh scripts/mac/install.sh` 无告警
- [ ] `VERSION` 已升级，`CHANGELOG.md` 有对应条目；若改了 Mac 端代码，同时升级 `airlock.py` 的 `VERSION`
- [ ] SKILL.md 正文 < 500 行，description 覆盖触发词
- [ ] 新增错误码已写进 troubleshooting.md
- [ ] 安全类 evals 全部通过

## 6. 二期扩展方向（已预留）

- 多仓库：气闸按 `repos/<name>.git` 扩展，闸门白名单改为配置列表。
- Git LFS / submodule 转发。
- 内网包源代理（只读、白名单）。
- 在 MR 上回复评论 / 解决讨论（需 `api` 范围，默认不开）。
- 推送前在 Mac 侧跑 lint/单测（钩子里调用固定命令，不执行仓库内脚本时需容器隔离）。
