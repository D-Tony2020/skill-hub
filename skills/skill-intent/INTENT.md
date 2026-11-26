---
skill: skill-intent
scope: team
bound_to: skill-hub
verdict: needs-clarification
producer: 负责人
date: 2026-11-26
---

# skill-intent 目标卡

## 一句话目标

当有人要把一个 Skill（或一个想法）交给团队用时，它会先和生产者对齐目标、查重、收敛成一件事，并写出 INTENT.md 给出 aligned / needs-clarification / rejected，让质检只检查值得检查的东西。（负责人 2026-11-26：质检前先做意图对齐，另做一个 Skill）

## 给谁用

- 角色：作者（生产者）；替别人检查的管理员
- 使用频率：每个新 Skill 一次；目标或范围变化时再用

## 触发说法

1. 这个 skill 想给整个 FDE 团队用，上架前先帮我对齐一下目标
2. 我有个想法，做个 skill 自动转 BOM 表，值不值得做
3. 帮我理一下这个 skill 到底该干嘛，感觉写乱了
4. Hub 里有没有和我这个排产助手重复的 skill

## 不做什么

1. "这个 skill 能不能上 Hub，跑门禁" → 交给 skill-qa
2. "帮我从零写一个 skill" → 交给 skill-creator
3. "把它导入仓库并提 PR" → 交给 skill-hub-ops
4. "写一份需求对齐会议纪要" → 交给 Claude 直接做

## 成功标准

1. 起草先于提问，每项注明依据
2. 一条消息最多 5 个问题，必含分发范围
3. 描述与正文的矛盾被原文引用出来
4. 结论按 rules.md 判定，`intent.mjs check` 通过
5. 不替生产者确认意图

## 输入与输出

- 输入：Skill 目录或一段想法描述；Hub 搜索结果
- 输出：Skill 根目录的 INTENT.md

## 环境前提

- Node 18+ 用于校验；查重需要 skillhub CLI（可选）

## 与已有 Skill 的关系

- Hub 查重：skill-creator 的 Capture Intent 只服务于写 Skill，不判定分发范围、不查重、不给驳回结论
- 仓库查重：skill-qa 的 G0 读本 Skill 的产出，不重复判定

## 未决问题

- 负责人确认本目标卡（Agent 依据项目记忆中的负责人原话起草）
