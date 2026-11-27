# Changelog

## 0.1.0 - 2026-11-26

- 首版：质检前的意图对齐。先按已有材料起草目标卡，查 Hub 和仓库重复，一次问完缺口，收敛成单一目标，给出 aligned / needs-clarification / rejected。
- 目标卡 `INTENT.md` 放在 Skill 根目录、不进发布包；字段 scope（受众）与可选 bound_to（平台绑定）正交，skill-qa 0.3.0 的 G0 按它分诊。
- `scripts/intent.mjs`：init / check / show，导出 `readIntent()` 供 skill-qa 与仓库工具使用；兼容旧位置 `references/intent.md`。
