# 提交到 SkillHub 并跟进到上架

由**发布人**执行（负责人或他指定的人）。提交前确认 PR 已合并、本地 main 是最新的。

## 前提

- 团队 Hub 在运行、能访问；SkillHub CLI 已登录到这个地址（`skillhub whoami --registry <Hub 地址>`）。登录走设备码，由发布人在浏览器里确认，Agent 不接触密码和令牌。
- 团队空间（默认 `blacklake`）已由负责人建好。
- 要发布的 Skill 有有效的"可分发"报告（`npm run qa -- <name>` 显示 `report ok`）。

## 步骤

1. **上一版是否还在审核队列里**：问负责人，或请他看 `<Hub 地址>/dashboard/reviews`。还在的话先审完或驳回；直接提交新版会把上一版从队列里顶掉，审核记录也就丢了。
2. `npm run publish:local -- --skill <name> --dry-run`：服务端预检（打包规则、元数据）。dry run 也算调用次数。
3. `npm run publish:local -- --skill <name>`：正式提交。脚本会：
   - 拒绝没有有效报告的 Skill（`--skip-qa "<理由>"` 只在负责人书面同意后用，并把理由原样转告）；
   - 去掉无扩展名文件（VERSION 等，SkillHub 会因它们报警告），把版本写进暂存副本 SKILL.md 的 `metadata.version`；
   - 遇到限流（大约每分钟 10 次）自动等 65 秒重试；
   - 跳过已经提交过的同版本（记录在 `.hub-state.json`）；被驳回后重发要 `--force`。
4. **等扫描**。提交成功只表示进了队列，SkillHub 会先扫描；扫描没结束时批准会失败。
5. 读扫描结论：
   - BLOCKED：不要批准。驳回，修掉问题，升 patch，重新质检和提交。
   - 告警是必要行为（例如安装器需要 sudo、脚本需要子进程）：在 Skill 的 `qa-exceptions.json` 起草一条例外，写清理由，**交负责人确认**；确认后在网页上放行。Agent 不能自己放行。
6. 负责人批准后做安装验证：在一个全新目录 `skillhub install @<空间>/<name> --version <版本> --registry <Hub 地址> --scope project --agent claude-code`，确认 `SKILL.md` 和 `.skillhub/metadata.json` 都在，新开会话确认它能被触发。
7. 如果它是基建套件成员，接着做套件维护（suite-and-mirror.md）。

## 已知情况

- CLI 0.3.1 对服务端 0.2.28 会打印 `Status: undefined`，真实状态以审核页面为准；脚本已把这一行去掉。
- `skillhub install` 的 `--dir` 不能和 `--agent`、`--scope` 同时用。
- 批准会永久占用版本号；版本号不要拿来做试验。
