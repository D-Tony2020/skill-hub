---
skill: hub-starter
scope: team
bound_to: skill-hub
verdict: aligned
producer: 负责人
date: 2026-11-27
---

# hub-starter 目标卡

## 一句话目标

当黑湖同事第一次（或换电脑后）要用团队 Skill Hub 时，它会装好官方 CLI、引导设备码登录、一次装齐基建套件并按角色补齐作者配置，产出一台"全生命周期工具可用"的环境和一份体检结果。（基建清单文档「第二个用户的第一天」第 1 步）

## 给谁用

- 角色：所有人（作者、使用者、管理员），按角色装不同的成员
- 使用频率：每人每台电脑一次；Hub 地址变了、登录过期时再用

## 触发说法

1. 帮我接入一下团队的 Skill Hub，地址管理员发我了
2. 我新入职，听说大家的 skill 都在 hub 上，我要怎么开始用
3. 换了台新电脑，skillhub 那套基建工具帮我重新装一遍
4. skillhub 登录过期了，帮我看看接入状态

## 不做什么

1. "Hub 上有没有画架构图的 skill，帮我装上" → 交给 skillhub-cli
2. "把我写好的 skill 发布到 SkillHub" → 交给 skill-hub-ops
3. "在服务器上部署一套 SkillHub" → 交给 Claude 直接做（部署不是接入）
4. "这个 skill 能不能上 Hub" → 交给 skill-qa

## 成功标准

1. 结束时 `starter.mjs doctor` 全部 ok，或只剩用户知情的 warn
2. 全程没有向用户索要密码或令牌，登录走设备码
3. 装上的基建成员与 infra-suite.json 的版本一致
4. Hub 地址推断不到时询问用户，从不落到 CLI 的公网默认地址
5. 重复运行不重装、不覆盖

## 输入与输出

- 输入：Hub 地址（推断或询问）、角色
- 输出：已安装的基建 Skill、`~/.skill-hub/profile.json`、体检结果

## 环境前提

- Agent 能在用户电脑上跑命令；Node 18+；能访问团队 Hub

## 与已有 Skill 的关系

- Hub 查重：SkillHub 内置 skillhub-cli 负责连接 Hub 和装单个 Skill，但不知道团队有哪些基建、不做角色化配置；hub-starter 调用它的规则，不重复实现
- 仓库查重：无

## 未决问题

- 负责人确认本目标卡（Agent 依据基建清单文档起草）
