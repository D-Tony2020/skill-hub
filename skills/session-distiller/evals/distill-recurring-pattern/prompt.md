---
tags: [skill-creator]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

帮我盘点一下最近这几个会话，看看有哪些东西值得沉淀成可复用的 skill，给我一份候选清单，我来挑。先别动 skill-hub 仓库。

（测试环境：会话记录和配置已准备好，执行命令前先 `export SD_HOME=$PWD/sdhome CLAUDE_CONFIG_DIR=$PWD/claude`。）

Input files: setup_env.py, fixtures.py, profile.md
