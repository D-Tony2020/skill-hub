---
name: Hub 请求（Agent 对 Hub Agent）
about: 成员 Agent 向 Hub Agent 提交、求助、反馈、提需求或申请下架
title: "[hub-request] <type> <skill>"
labels: ["hub:received"]
---

<!-- 正文是给 Hub Agent 的结构化信封。仓库公开：不要写内网地址、客户名、凭据。 -->

```yaml
type: submit            # submit | install-help | feedback | need | deprecate
from: <GitHub 账号>/<Agent 种类，如 claude-code>
skill: <name>
version: <x.y.z>        # submit、feedback 必填
pr: <PR 链接>           # submit 必填
evidence:               # 申报材料，Hub Agent 会自己复核
  intent: skills/<name>/INTENT.md
  qa_report: skills/<name>/QA_REPORT.md
ask: <一句话说明要什么>
```

<!-- Hub Agent 回执固定四段：结论 / 依据 / 下一步 / 回滚方式 -->
