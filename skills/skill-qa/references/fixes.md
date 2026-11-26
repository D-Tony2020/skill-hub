# 常见问题的修法

按门禁编号排列。修改用户的文件前先说明改什么，用户同意后再改。

| 门禁 | 现象 | 修法 |
| --- | --- | --- |
| G1 | name 与目录名不一致 | 改目录名或 name，二者一致；只用小写字母、数字、单个短横线 |
| G1 | description 超长或含尖括号 | 压到 1024 字符内，三段式：做什么；用户怎么说时用；不用于什么 |
| G1 | 没有版本号 | 在 SKILL.md frontmatter 加 `metadata: {version: "0.1.0"}`；进仓库后由 hub.yaml 或 VERSION 管理 |
| G2 | SKILL.md 提到的文件不在 | 拿到完整源码；确属另一个 Skill 的，写进 `hub.yaml` 的 `requires.skills` |
| G3 | 写死 `~/.claude/skills/<name>` | 改成"本 SKILL.md 所在目录"。shell：`SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"`；Python：`Path(__file__).resolve().parent.parent` |
| G4 | 用到的命令、Skill、环境变量没声明 | 写进 `hub.yaml`：`requires: {skills: [...], commands: [...], env: [...]}`；没有 hub.yaml 就新建一个，`status: draft` |
| G5 | 评测用例不够 | 见 evals.md；不该触发的用例要选近似说法 |
| G9 | 无扩展名文件被读取（如 VERSION） | 脚本读取失败时回退到 SKILL.md 的 `metadata.version`；不要删掉读取逻辑 |
| G10 | CHANGELOG 没有本版本 | 在 CHANGELOG.md 顶部加 `## x.y.z - 日期` 和实际改动 |
| G11 | 密钥 | 删掉，改成从环境变量或用户目录读取；密钥已经提交到 Git 历史里的，要请用户作废这个密钥 |
| G11 | 内网地址、客户名 | 改成占位符（`<gitlab-url>`），真实值让用户在使用时提供 |
| S1 | 下载后直接执行 | 执行前核对哈希：`echo "<sha256>  file" \| shasum -a 256 -c - && sudo bash file`；能用 HTTPS 就用 HTTPS |
| S1 | 提权 | 确有必要的，在 SKILL.md 写明理由，并登记例外；能不用就不用 |
| S2 | 顶层 bin/ | 挪到 scripts/ |
| S3 | 没有 license | frontmatter 加 `license: Proprietary`（或实际的开源协议） |
| S4 | 扫描告警 | 真问题修掉；必要行为或误报按 exceptions.md 登记，由负责人确认 |
| R1 | 没写源码仓库和反馈方式 | 在 SKILL.md 加一节：源码仓库地址和目录、如何更新、如何反馈问题 |
