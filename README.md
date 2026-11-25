# skill-hub

Skills 工厂的 skill 仓库：所有自定义 Claude Skill 的唯一事实来源。同一份源码分发到三处：

| 去向 | 怎么到达 |
|---|---|
| Claude Code（本机 / 项目） | 本仓库即 Claude Code 插件市场，`.claude-plugin/marketplace.json` 由工具生成 |
| claude.ai 账号（含 Cowork、云端会话） | 每次发版 GitHub Release 附带可直接上传的 zip |
| SkillHub 看板（一期本机部署） | `npm run publish:local` 推送到本机 SkillHub，在网页审核后上架 |

方案文档：Skill Hub 看板系统技术方案（开源路线：SkillHub + Git 源仓库 + 薄 CI）。

## 安装

```
claude plugin marketplace add D-Tony2020/skill-hub
claude plugin install <skill-name>@blacklake-skill-hub
```

已上架：

```
/plugin install blacklake-auto-git --marketplace D-Tony2020/skill-hub
```

claude.ai：到本仓库 Releases 下载 `<skill>-<version>.zip`，在 claude.ai → Customize → Skills 上传。

## 目录规范

```
skills/<skill-name>/
├── SKILL.md        # 只写官方 frontmatter（name、description 等），不加自定义字段
├── hub.yaml        # Hub 元数据，见下文；没有它的 skill 视为草稿
├── VERSION         # 可选，与 hub.yaml 的 version 二选一，两者都写必须一致
├── CHANGELOG.md    # 发版说明
├── scripts/        # 可执行脚本（不要放在顶层 bin/，claude.ai 组织同步会拒收）
├── references/     # 按需加载的参考资料
├── tests/  evals/  # 开发材料，不进发布包
```

`hub.yaml`：

```yaml
status: published      # draft | published | archived，只有 published 进入市场和发版
version: 1.0.0         # semver；published 必填（或用 VERSION 文件）
owner: dean
tags: [git, gitlab]    # 写入插件市场的 keywords
notes: 可选备注
requires:              # 可选：运行时依赖，hub install / status 会检查
  skills: [drawio-skill]
  commands: [py]
  env: [SOME_VAR]
```

## 校验规则

`npm run validate` 检查（错误会阻止发布，警告需要人看）：name 与目录同名、小写短横线、不超过 64 字符、不含 anthropic/claude；description 必填、不超过 1024 字符、不含 `<` `>`；status 合法；版本是 semver 且 hub.yaml 与 VERSION 一致；不允许顶层 `bin/`；`requires` 格式。告警：未知 frontmatter 字段、SKILL.md 提到但目录里没有的 `scripts/`、`references/` 文件（常见于只同步了 SKILL.md 的 claude.ai 副本）、写死本 skill 安装路径（如 `~/.claude/skills/<name>`，插件市场和 SkillHub 安装后路径不同）。

Agent 按 `skills/skill-hub-ops/SKILL.md` 的手册来导入、升级、发布、安装、下架和巡检。

## 工具

需要 Node 20+，`npm ci` 后：

| 命令 | 作用 |
|---|---|
| `npm run validate` | 校验所有 skill，有错误退出 1 |
| `npm run build` | 重新生成 `.claude-plugin/marketplace.json`（请勿手改，改完提交） |
| `npm run build:check` | CI 用：清单过期则失败 |
| `npm run list` | 列出 skill、状态、版本 |
| `node tools/hub/cli.mjs files <skill>` | 查看进入发布包的文件 |
| `node tools/hub/cli.mjs import <dir>` | 把存量 skill 导入为 draft（去掉 plugin.json 和缓存，报告缺失文件和写死的路径） |
| `node tools/hub/cli.mjs bump <skill> patch\|minor\|major -m 说明` | 升版本（VERSION 或 hub.yaml）并在 CHANGELOG 顶部加一条 |
| `node tools/hub/cli.mjs install <skill> [--dest 目录]` | 装到 `~/.claude/skills/<skill>`，带 `.hub-source.json` 标记，不覆盖手工放置的同名目录 |
| `node tools/hub/cli.mjs status` | 仓库版本 vs 本机安装版本，以及缺失的依赖 |
| `npm test` | 工具自身的单元测试 |

## 发布到 SkillHub（一期：本机）

SkillHub 部署在 http://localhost:8088，界面默认中文。在部署目录启动：

```
docker compose --env-file .env.release -f compose.release.yml -f compose.zh.yml up -d
```

漏掉 `compose.zh.yml` 会退回按浏览器语言显示。CLI 首次使用：

```
npm i -g @astron-team/skillhub
skillhub login --registry http://localhost:8088
```

之后每次改完版本号：

```
npm run publish:local -- --dry-run      # 只让 SkillHub 校验，不提交
npm run publish:local                   # 提交所有 published 的新版本
npm run publish:local -- --skill blacklake-auto-git --force   # 重发单个
```

可用参数 `--registry`、`--namespace`（默认 blacklake 团队空间，需先在网页 /dashboard/namespaces 建好）、`--visibility`（默认 public），也可用环境变量 `SKILLHUB_REGISTRY`、`SKILLHUB_NAMESPACE`、`SKILLHUB_VISIBILITY`、`SKILLHUB_BIN`。脚本总是显式传 registry，CLI 自带的默认地址是公网服务器。

- CLI 登录得到的令牌只能"提交"，提交后进入 SkillHub 审核队列，由管理员在网页上批准才算上架。这一步就是看板里的审计与上架。
- SkillHub 不认 `VERSION` 这类无扩展名文件，也不读它；脚本在临时副本里去掉这些文件，并把版本写进 SKILL.md 的 `metadata.version`，源码不变。
- 已提交的版本记录在 `.hub-state.json`（不进 git），重复运行会跳过。SkillHub 不允许覆盖已上架的版本，改内容就升版本号。

## CI

- `validate.yml`（PR 与 main）：单测、校验、清单是否最新、`claude plugin validate .`
- `release.yml`（合入 main）：每个 published skill 若还没有 `<name>@v<version>` 标签，就打 zip 并创建 GitHub Release。改版本号即发版。

## 分支

`main` 为唯一主干，所有改动通过 PR 合入。需要锁定版本的使用方可用 `owner/repo#<tag>` 固定。
