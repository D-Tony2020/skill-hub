# Changelog

## 2.1.3 - 2026-11-26

可分发化，首次导入 skill-hub（换一个黑湖同事、换一台机器装上就能用）：

- 路径一律从本 skill 所在目录推导，不再写死用户级安装路径；drawio-skill 依次从 `DRAWIO_SKILL_DIR`、同级目录、项目级、用户级查找，适配 SkillHub 和项目级安装
- 新增 `diagram.py doctor`：列出 skill、Python、drawio-skill、draw.io CLI、图档目录、lark-cli、默认飞书文档的定位结果，必需项缺失时退出码 3；找不到 drawio-skill 的报错改为指向 doctor
- draw.io CLI 自动定位补上 macOS 默认安装位置
- SKILL.md 开头写明适用前提（Python、draw.io 桌面版、drawio-skill；飞书同步为可选）；客户端相关的做法（Claude Code / 云端会话连接本机 / PowerShell 5.1）改为分情况说明；写明 Windows 用 `py -3`、macOS / Linux 用 `python3`
- 新增 `config.schema.json`（状态位四层清单与环境前提）、`references/intent.md`（目标卡，范围 team）、`evals/`（任务与触发评测用例）
- SKILL.md 新增「源码、更新与反馈」一节，frontmatter 加 license；hub.yaml 声明 requires（drawio-skill、python、draw.io；lark-cli 可选，写在 notes）
- 新增测试：同级 drawio-skill 查找、doctor 缺依赖时的输出
- 去掉 Skill 目录里的 .gitignore（SkillHub 不允许该扩展名，内容已被仓库根目录的 .gitignore 覆盖）

## 2.1.2 之前

在作者本机迭代，未进入仓库：v1.0 讨论 → 图 → 迭代流程；v2.0 质量门禁与版本历史；v2.1 飞书原生画板同步；v2.1.1–2.1.2 人工改动合回规则（`by` / `since` / `intent` / `decisions`）。
