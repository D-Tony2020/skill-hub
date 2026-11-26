---
skill: skill-hub-ops
scope: team
bound_to: skill-hub
verdict: needs-clarification
producer: 负责人
date: 2026-11-26
---

# skill-hub-ops 目标卡

## 一句话目标

当一个 Skill 已对齐、已质检，或使用者反馈了问题时，它会在 skill-hub 源码仓库里完成入库、升版、发版、提交 SkillHub 并跟进到上架，维护基建套件和官方镜像，处理回滚、下架和反馈分诊，产出 PR、Release 和 Hub 上的已发布版本。

## 给谁用

- 角色：作者（入库、升版）、负责人和发布人（发布、审批前后的跟进、套件、下架）
- 使用频率：每次发版；每月巡检

## 触发说法

1. 把 po-helper 放进 Hub，帮我开 PR
2. skill-qa 0.3.0 合并了，提交到 SkillHub
3. 看看现在各个 skill 走到哪一步了
4. 基建套件更新一下
5. hub-starter 新版有问题，回滚

## 不做什么

1. "这个 skill 能不能上 Hub" → 交给 skill-qa
2. "帮我接入 Hub" → 交给 hub-starter
3. "Hub 上有没有写周报的 skill，装一个" → 交给 skillhub-cli
4. "这个 skill 有 bug，反馈给作者" → 交给 skill-feedback

## 成功标准

1. 没有已对齐的 INTENT.md 和有效可分发报告时不入库、不提交
2. 所有改动走分支和 PR，不直接推 main、不合并
3. 提交 SkillHub 前确认上一版不在审核队列；提交后跟进扫描结论
4. 不使用管理员密码、不自批例外
5. 套件改动后 `hub suite --check` 通过

## 输入与输出

- 输入：Skill 目录、仓库、Hub
- 输出：PR、Release、SkillHub 提交、套件清单

## 环境前提

- skill-hub 仓库克隆与写权限；Node 20+；发布一步需要 Hub 访问和已登录的 CLI

## 与已有 Skill 的关系

- Hub 查重：skillhub-cli 管使用者侧的安装升级，本 Skill 管仓库侧和发布侧
- 仓库查重：无

## 未决问题

- 负责人确认本目标卡
