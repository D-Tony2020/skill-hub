---
name: {{name}}
description: {{description}}
---

# {{title}}

> 草稿：由 session-distiller 从历史会话提炼（run {{run}}，形态 {{kind}}）。
> 上架前按 skill-creator 流程补全：写清步骤、补脚本、写评测，再把 hub.yaml 的 status 改为 published。

## 解决什么问题

{{problem}}

## 做法

{{summary}}

TODO：改写成可执行的步骤。说明每一步为什么这么做；确定性的部分放进 `scripts/`。

## 参考

- [references/evidence.md](references/evidence.md)：提炼依据的会话片段（已脱敏）

## 源码与反馈

- 唯一源码：<https://github.com/D-Tony2020/skill-hub>，目录 `skills/{{name}}/`，分支 `main`。只改源码仓库并走 PR，不要改已安装的副本。
- 更新：在源码克隆里 `git pull`，然后运行 `python skills/{{name}}/scripts/install_local.py`（或用插件市场 `/plugin update {{name}}`）。
- 问题回报：在 skill-hub 仓库提 issue，标题以 `[{{name}}]` 开头，写明复现步骤和期望结果。
