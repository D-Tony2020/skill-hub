# 回滚与下架

SkillHub 上已经批准的版本内容不可改、版本号不可复用，所以"回滚"是两件事：让受影响的人先恢复工作，再往前发一个修好的版本。

## 1. 先止损

- 告诉受影响的使用者装回上一个好版本：`skillhub install @blacklake/<name> --version <好版本> --registry <Hub 地址> --scope user --agent claude-code`。本地有改动时 CLI 会拒绝覆盖，不要替用户加 `--force`。
- 用户是从仓库装的：在仓库里 `git checkout <好版本对应的提交> -- skills/<name>`（临时目录里做），再 `hub install <name> --dest <目录> --force`，用户同意后进行。

## 2. 往前修

1. 新建分支 `fix/<name>-<问题>`，`git revert` 出问题的提交，或直接修掉。
2. 把触发问题的那句话补进 evals（会坏的场景必须有用例，下次质检才拦得住）。
3. `hub bump <name> patch -m "回滚 <坏版本> 的 <改动>"`，重跑 skill-qa，开 PR。
4. 合并后发布；在套件里的，按 suite-and-mirror.md 更新套件版本。

## 3. 严重问题

会泄露凭据、破坏数据、或被利用的版本：请负责人在网页上把该版本下架（或隐藏整个 Skill），并在项目里通知所有可能装了它的人。这一步不可撤销，由负责人决定。

## 4. 下架整个 Skill

1. `hub.yaml` 的 `status` 改为 `archived`；若在基建套件里，从 infra-suite.json 去掉并按套件流程发新套件版本。
2. `npm run build`（插件市场清单里会去掉它），提 PR。
3. SkillHub 上的下架或删除由负责人在网页做；告诉他入口和影响（已装的人不会被自动卸载）。
4. 本机副本：用户同意后 `skillhub remove @blacklake/<name> --registry <Hub 地址> --agent claude-code`，或删除 `hub install` 装的目录。
