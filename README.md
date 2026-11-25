# skill-hub

Skills 工厂的 skill 仓库：所有自定义 Claude Skill 的唯一事实来源。同一份源码分发到三处：

| 去向 | 怎么到达 |
|---|---|
| Claude Code（本机 / 项目） | 本仓库即 Claude Code 插件市场，`.claude-plugin/marketplace.json` 由工具生成 |
| claude.ai 账号（含 Cowork、云端会话） | 每次发版 GitHub Release 附带可直接上传的 zip |
| SkillHub 看板（一期本机部署） | 本地一键发布脚本推送到 SkillHub（后续 PR 补充） |

方案文档：Skill Hub 看板系统技术方案（开源路线：SkillHub + Git 源仓库 + 薄 CI）。

## 安装

```
claude plugin marketplace add D-Tony2020/skill-hub
claude plugin install <skill-name>@blacklake-skill-hub
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
```

## 校验规则

`npm run validate` 检查：name 与目录同名、小写短横线、不超过 64 字符、不含 anthropic/claude；description 必填、不超过 1024 字符、不含 `<` `>`；status 合法；版本是 semver 且 hub.yaml 与 VERSION 一致；不允许顶层 `bin/`。未知 frontmatter 字段只告警。

## 工具

需要 Node 20+，`npm ci` 后：

| 命令 | 作用 |
|---|---|
| `npm run validate` | 校验所有 skill，有错误退出 1 |
| `npm run build` | 重新生成 `.claude-plugin/marketplace.json`（请勿手改，改完提交） |
| `npm run build:check` | CI 用：清单过期则失败 |
| `npm run list` | 列出 skill、状态、版本 |
| `node tools/hub/cli.mjs files <skill>` | 查看进入发布包的文件 |
| `npm test` | 工具自身的单元测试 |

## CI

- `validate.yml`（PR 与 main）：单测、校验、清单是否最新、`claude plugin validate .`
- `release.yml`（合入 main）：每个 published skill 若还没有 `<name>@v<version>` 标签，就打 zip 并创建 GitHub Release。改版本号即发版。

## 分支

`main` 为唯一主干，所有改动通过 PR 合入。需要锁定版本的使用方可用 `owner/repo#<tag>` 固定。
