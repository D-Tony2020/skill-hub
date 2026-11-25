# 错误码与常见问题

| 错误码 | 含义 | 处理 |
|---|---|---|
| `E_NO_PYTHON` | 找不到 Python 3.8+ | Windows：`winget install Python.Python.3.12`，重开终端；macOS：`brew install python` |
| `E_DOCTOR` | 自检发现问题 | 看输出：`not_initialized` 就运行 `sd init`；`missing_source` 就检查 `config.json` 的 `sources` 路径 |
| `E_NO_SESSIONS` | 没有符合条件的未处理会话 | 放宽条件：`--all`、`--since 90d`、`--min-turns 1`；或用 `sd doctor` 看数据源里有没有 `.jsonl` |
| `E_NO_RUN` | 找不到 run | 先运行 `sd digest`；`ls ~/.session-distiller/runs` 查看已有的 run |
| `E_NO_CANDIDATES` | run 里没有 candidates.json | 按 candidate-schema.md 写好再运行 |
| `E_SCHEMA` | candidates.json 不合规 | 按 ERROR 行逐条修正；证据报错通常是会话 id 或轮次写错了，回摘要核对 |
| `E_BAD_JSON` | JSON 语法错误 | 按提示的行列修正 |
| `E_NO_CANDIDATE` | 该 run 里没有这个候选 id | `sd status` 查看 id |
| `E_NOT_ACCEPTED` | scaffold 前未记录采纳 | 先 `sd decide <run> <id> accept`；确需跳过时加 `--force` |
| `E_EXISTS` | 目标 skill 目录已存在 | 说明已有同名 skill，应改为 merge，或换一个 id |
| `E_NO_SESSION` / `E_AMBIGUOUS` | 会话 id 找不到或不唯一 | 用 `sd scan --all` 查看完整 id |
| `E_NO_FILE` | 该会话没写过匹配的文件 | `sd files <session>` 查看清单 |
| `E_SRC_*` | 自更新失败 | `CLONE` / `FETCH`：检查网络和 GitHub 登录（私有仓库）；`DIRTY` / `DIVERGED`：源码克隆有本地改动，先提交成 PR 或丢弃；`DOWNGRADE`：main 上的版本比已安装的旧，保持现状即可；`PLUGIN`：插件安装的副本改用 `/plugin update` |
| `E_INTERNAL` | 脚本内部异常 | 记进 `~/.session-distiller/skill-feedback.md`，附上命令和输出，再到 skill-hub 提 issue |

## 数据源

- **Claude Code 本机会话**：`~/.claude/projects/<编码后的工作目录>/<session-id>.jsonl`。设置了 `CLAUDE_CONFIG_DIR` 时以它为准。子代理的记录在 `<session>/subagents/` 下，默认跳过；`config.json` 里设 `"include_sidechains": true` 可以纳入。
- Claude Code 默认只保留约 30 天的会话记录（`settings.json` 的 `cleanupPeriodDays`）。想长期沉淀，可以调大这个值，或者定期跑提炼。
- **别的机器上的会话**：把那台机器的 `~/.claude/projects` 整个拷过来，在 `config.json` 的 `sources` 里加上这个目录即可，格式相同。
- **云端会话**（claude.ai/code、项目线程）：本机没有它们的记录。需要的话，在云端会话里让 Agent 把自己的记录导出成 `.jsonl` 拷回本机，再按上一条加入 sources。会话外层的 wake/relay 信封会被自动拆掉，只保留人类原话。

## 隐私

- 所有处理都在本机完成，脚本不联网（`sd update` 除外，它只访问 skill-hub 仓库）。
- 自动脱敏覆盖：私钥、Anthropic/OpenAI/GitHub/GitLab/Slack/AWS/飞书类密钥、JWT、Bearer token、URL 里的账号密码、`password=` 这类赋值、身份证号、手机号、邮箱。客户名、内部域名等无法自动识别的内容，写进 `redact.txt`。
- 每次 digest 的脱敏统计写在 `overview.md` 末尾和 `index.json` 的 `redactions` 字段里。
