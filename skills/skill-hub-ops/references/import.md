# 导入存量 Skill

前提：用户手里的完整源码目录里已经有
- `INTENT.md`，`verdict: aligned`，`scope` 是 `team` 或 `org`（`node <skill-intent 目录>/scripts/intent.mjs check <目录>` 通过）；
- `QA_REPORT.md`，结论"可分发"，且内容哈希与当前文件一致（`node <skill-qa 目录>/scripts/qa.mjs status <目录>`）。

缺哪个就交回 skill-intent 或 skill-qa，不要先导入再说。

## 步骤

1. 找到**完整**源码目录（含 `scripts/`、`references/`）。`~/.claude/skills/synced/` 和 Claude 桌面端插件缓存里的是 claude.ai 同步下来的副本，通常**只有 SKILL.md**，不能当源码。
2. 在仓库新建分支 `skill/<name>`，`hub import <源目录>`：复制到 `skills/<name>/`，状态为 draft，版本取 VERSION / plugin.json / 默认 0.1.0，去掉 `.claude-plugin/` 和缓存目录。输出的 `qa:` 一行说明报告是否仍然有效。
3. 逐条处理输出：
   - `refers to files that are not in the skill folder`：源码不全，回去找；若属于依赖的另一个 Skill，写进 `requires.skills`。
   - `hardcodes an install path`：把 `~/.claude/skills/<name>` 这类写死的路径改成"本 SKILL.md 所在目录"，否则通过插件市场或 SkillHub 安装后会找不到脚本。
4. 在 `hub.yaml` 写依赖：
   ```yaml
   requires:
     skills: [drawio-skill]     # 其他 Skill
     commands: [python, draw.io]
     env: [ARCH_DIAGRAMS_ROOT]
   ```
5. 第 3、4 步改了文件，报告就失效了：在仓库副本上重跑 skill-qa 的出报告一步。
6. `npm run validate`、`npm run qa -- <name>`、`hub chain <name>` 都没问题后提 PR。PR 正文写：来源、去掉了什么、还剩哪些警告、目标卡的一句话目标和分发范围、质检结论和门禁表、待负责人确认的例外。
