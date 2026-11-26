# 基建套件与官方镜像

## 基建套件 `@blacklake/infra`

SkillHub 的 Suite 是一组**已发布的精确版本**的集合，有自己的版本号；装套件就是一次装齐这些版本。它不复制文件，也不替成员重新扫描或审核。成员发了新版，旧的套件版本不会自动跟着变，要建新的套件版本。

唯一事实来源是仓库里 hub-starter 目录下的 `infra-suite.json`（与 SkillHub 的 suite.yaml 结构一致）。hub-starter 读它来给新人装基建，所以它随 hub-starter 一起发布。

### 什么时候要改

- 某个基建 Skill 发了新版，希望新人装到新版；
- 新增或撤下一个基建 Skill；
- 套件的可见范围或入口 Skill 变了。

### 步骤

1. 改 infra-suite.json：成员的 `version`、成员列表；`metadata.version` 升一级（成员只升 patch 时套件也升 patch）。
2. hub-starter 升 patch（`hub bump hub-starter patch -m "套件 <新版本>"`），`spec.entrySkill` 里的 hub-starter 版本跟着改。
3. 新加入的 Skill 在 `hub.yaml` 的 `tags` 里加 `infra`。
4. `hub suite --check` 通过；hub-starter 重跑 skill-qa；开 PR。
5. 合并、发布 hub-starter 和改动过的成员，等它们在 SkillHub 上都是"已发布"。
6. `hub suite` 打印最终清单。SkillHub CLI 还不能发布套件：**请负责人在网页的套件编辑器里**按清单新建套件版本（成员、版本、入口 Skill、可见范围逐项一致），提交审核并批准。
7. 验证：一个全新目录里 `skillhub suite install @blacklake/infra --version <版本> --registry <Hub 地址> --scope project --agent claude-code`。

可见范围规则：PUBLIC 套件只能包含 PUBLIC 成员。`@global/skillhub-cli` 是 SkillHub 内置的 PUBLIC Skill，可以跨空间加入。

## 官方镜像（skill-creator）

镜像 = 原样复制上游目录 + 固定 commit + 只在 SKILL.md 末尾追加一节来源说明（`<!-- hub:mirror-note begin/end -->` 之间）+ NOTICE.md 记录改动，许可文件原样保留。`hub.yaml` 的 `upstream` 记录 `repo`、`path`、`commit`、`license`、`synced`。

### 同步步骤

1. 克隆上游到临时目录：`git clone --depth 1 https://github.com/anthropics/skills <临时目录>`，记下 `git -C <临时目录> rev-parse HEAD`。
2. 和 `hub.yaml` 的 `upstream.commit` 一样就结束。
3. 新建分支 `mirror/skill-creator-<短 commit>`，`hub upstream skill-creator --from <临时目录>/skills/skill-creator --commit <sha>`。它会替换上游文件、删掉上游已删的文件、保留我们的文件（hub.yaml、CHANGELOG.md、NOTICE.md、evals/ 等）并把来源说明接回 SKILL.md 末尾。
4. 看一眼 `git diff --stat` 和 SKILL.md 的改动，判断要不要升 minor（行为变化）还是 patch（文字修订）：`hub bump skill-creator <part> -m "同步上游 <短 commit>：<一句话>"`。NOTICE.md 里的 commit 也改掉。
5. 重跑 skill-qa（扫描结论可能变），开 PR；发布后如在套件里，按上面的套件步骤更新。

不在镜像里改上游内容。确实需要不同的行为，就提给上游，或者另做一个我们自己的 Skill。
