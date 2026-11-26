# 状态位与配置清单（G15 / G16）

一个 Skill 能不能分发，关键看它有没有把"作者自己的值"当成"所有人的值"写死。比如把作者的名字、作者自己的分支前缀（形如 `<作者名>-cc/`）、作者电脑上的路径写进 SKILL.md，换一个人装上就不对。

做法：把每个因人、因项目而异的值做成**状态位**，写进 Skill 根目录的 `config.schema.json`，由 Skill 在首次使用时推断、询问、保存。

## 四层分类

| 层 | 含义 | 例子 | 怎么定值 |
| --- | --- | --- | --- |
| 固定 fixed | 安全边界或协议本身，不提供开关 | 禁止 force push；只建 Draft MR | 写死在代码里 |
| 预设 preset | 团队统一的默认值，个别项目可以改 | 目标分支默认 `main`；扫描策略 | 带默认值，首次请用户确认或直接用 |
| 实例 instance | 每个人、每个项目都不同 | 仓库地址、分支前缀、账号 | **不带默认值**：推断建议值，问用户确认 |
| 角色 role | 由人担任的职责 | 审批人、管理员 | 问"是不是你本人"，记下分工 |

另外一类是**环境前提**（操作系统、网络拓扑、依赖的外部系统）。它不是状态位，而是适用范围：写进 SKILL.md 开头的「适用前提」和清单的 `env`，不满足时第一步就告诉用户不适用，不要硬做或绕行。

## 规则

1. **人名改成角色**。文档里写"用户""审批人""管理员"，不写具体的人。一个人可以兼多个角色。
2. **命名类的值是开放槽位**。分支前缀、目录名、账号名这类值没有默认值：Skill 先推断一个建议值（例如从 `git config user.email` 推出 `zhangsan-cc/`），问用户确认，用户可以改成任何合法值。不要沿用作者或别的项目的值。
3. **先推断，再一次问完**。能从环境推断的先推断；要问的放在一条消息里一次问完，不要一问一答。
4. **确认后才保存**。用户确认之前不写入；写入位置在 `store` 里写明（用户目录下的状态文件、目标系统的配置），不写进 Skill 目录（升级时会被覆盖）。
5. **可查看、可修改**。说清楚怎么看当前值、怎么改；改一个值时，所有存了这个值的地方要一起改。
6. **敏感值不经过 Agent**。令牌、密码只由人在目标系统里输入；Agent 不索要、不接收、不保存。清单里标 `sensitive: true`，`ask: false`。
7. **更新渠道跟着安装来源走**。从 SkillHub 装的用 `skillhub upgrade`，从仓库装的用仓库的方式；不要让 SkillHub 安装的副本绕过审核从 git 自更新。
8. **前提写清楚**。不支持的环境明确说不支持，并给出支持的替代做法。

## config.schema.json 格式

```json
{
  "$comment": "一句话说明这个 Skill 有哪些状态位",
  "skill": "<name>",
  "schema_version": 1,
  "onboarding": "何时问（例如首次搭建第 1 步）、先推断什么、一条消息问完哪些项、确认后由什么命令写入、之后怎么查看和修改",
  "slots": [
    { "key": "branch_prefix", "layer": "instance", "default": null,
      "infer": "git 邮箱 @ 前部分 + -cc/", "ask": true, "required": true,
      "store": ["~/.<skill>/state.env"], "sensitive": false,
      "desc": "开放槽位：没有默认值，用户确认后才写入" },
    { "key": "target_branch", "layer": "preset", "default": "main", "ask": true, "store": ["~/.<skill>/state.env"] },
    { "key": "api_token", "layer": "instance", "ask": false, "sensitive": true, "store": ["目标系统，由人输入"] },
    { "key": "approver", "layer": "role", "default": "用户本人", "ask": true, "store": ["~/.<skill>/learnings.md"] },
    { "key": "no_force_push", "layer": "fixed", "default": "禁止", "ask": false }
  ],
  "env": [
    { "key": "same_network", "require": "开发机和服务器在同一局域网", "check": "怎么判断", "on_fail": "告知不适用" }
  ]
}
```

G16 的校验规则：

- 每个状态位有 `key`（不重复）和 `layer`（四选一）；非固定项写 `ask`。
- 实例层**不能**带 `default`；实例层要么 `ask: true`，要么写 `infer`（敏感项除外）。
- 敏感项要写 `store`，而且不能存在 Skill 目录里。
- 只要有 `ask: true` 的项，就要写 `onboarding`。
- `env` 每项要有 `key` 和 `require`，建议写 `check`。
- SKILL.md 要提到 `config.schema.json`，否则 Agent 不会去读它。

没有状态位的 Skill 不需要这个文件。如果 `QA check` 报"有状态位迹象"（读取环境变量、有首次配置步骤），而你确认它确实没有状态位，就在 review.json 写 `"stateless_confirmed": true` 并写明理由。读取的环境变量本身就是状态位（例如可覆盖的源码地址），这时应该写清单而不是确认无状态。

## 盘点耦合点的步骤

1. `QA check`，看 G15 列出的每一处。
2. 再人工通读 SKILL.md 和 references，找 G15 查不出来的：拓扑假设（"两台机器连同一个热点"）、作者的习惯（"他喜欢……"）、写死的仓库、项目、团队名。
3. 每一处归到四层之一，或归为环境前提。
4. 列成表给用户看：值、现状、归层、改成什么。用户确认后再改。
5. 用三类人走查一遍：作者本人、另一位同事、全新环境的使用者。每类人从安装到第一次用成功，哪一步会卡住，就是还没做完的地方。

示例：`skills/blacklake-auto-git/config.schema.json`（2.0.0 起）。
