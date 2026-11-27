// Unit tests for scripts/intent.mjs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const I = await import(pathToFileURL(path.join(HERE, '..', 'scripts', 'intent.mjs')).href);

function skillDir(name = 'demo-skill') {
  const d = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'intent-')), name);
  fs.mkdirSync(d);
  return d;
}

const ALIGNED = `---
skill: demo-skill
scope: team
verdict: aligned
producer: 作者本人
date: 2026-11-26
---

## 一句话目标
当用户想把采购订单 Excel 导入 MES 时，它会校验字段并生成导入文件。（生产者确认）

## 给谁用
- 角色：实施 FDE

## 触发说法
1. 把这个采购订单表导进 MES
2. 帮我检查 PO 表能不能导入
3. 供应商发来的订单 Excel 转成 MES 模板

## 不做什么
1. "帮我写个采购审批流程" → 交给 Claude 直接做
2. "MES 接口报 500" → 交给排障
3. "做一张采购看板" → 交给 dataviz

## 成功标准
1. 缺失物料编码的行被列出并给出行号
2. 生成的文件列顺序与 MES 模板一致
3. 不修改原始 Excel

## 输入与输出
- 输入：采购订单 Excel
- 输出：MES 导入 CSV

## 环境前提
- 无

## 与已有 Skill 的关系
- Hub 查重：无相似

## 未决问题
- 无
`;

test('init writes a card once and never overwrites', () => {
  const d = skillDir();
  assert.equal(I.initIntent(d, undefined, '2026-11-26').created, true);
  const text = fs.readFileSync(path.join(d, 'INTENT.md'), 'utf8');
  assert.match(text, /skill: demo-skill/);
  assert.match(text, /date: 2026-11-26/);
  fs.writeFileSync(path.join(d, 'INTENT.md'), 'mine');
  assert.equal(I.initIntent(d).created, false);
  assert.equal(fs.readFileSync(path.join(d, 'INTENT.md'), 'utf8'), 'mine');
});

test('a blank template is a valid needs-clarification card but not aligned', () => {
  const d = skillDir();
  I.initIntent(d, undefined, '2026-11-26');
  assert.equal(I.checkIntent(d).state, 'needs-clarification');
  fs.writeFileSync(path.join(d, 'INTENT.md'), fs.readFileSync(path.join(d, 'INTENT.md'), 'utf8').replace('verdict: needs-clarification', 'verdict: aligned'));
  const r = I.checkIntent(d);
  assert.equal(r.state, 'invalid');
  assert.ok(r.errors.some((e) => e.includes('触发说法')), r.errors.join('\n'));
  assert.ok(r.errors.some((e) => e.includes('一句话目标')));
});

test('a filled aligned card passes and lets the skill proceed to QA', () => {
  const d = skillDir();
  fs.writeFileSync(path.join(d, 'INTENT.md'), ALIGNED);
  const r = I.checkIntent(d);
  assert.deepEqual(r.errors, []);
  assert.equal(I.readIntent(d).proceed, true);
});

test('personal and customer scopes never proceed; bound_to is carried', () => {
  const d = skillDir();
  fs.writeFileSync(path.join(d, 'INTENT.md'), ALIGNED.replace('scope: team', 'scope: personal'));
  assert.equal(I.readIntent(d).proceed, false);
  fs.writeFileSync(path.join(d, 'INTENT.md'), ALIGNED.replace('scope: team', 'scope: customer'));
  assert.equal(I.readIntent(d).proceed, false);
  fs.writeFileSync(path.join(d, 'INTENT.md'), ALIGNED.replace('date:', 'bound_to: skill-hub\ndate:'));
  assert.equal(I.readIntent(d).bound_to, 'skill-hub');
});

test('rejected needs a reason; bad fields are errors', () => {
  const d = skillDir();
  fs.writeFileSync(path.join(d, 'INTENT.md'), ALIGNED.replace('verdict: aligned', 'verdict: rejected'));
  assert.ok(I.checkIntent(d).errors.some((e) => e.includes('驳回理由')));
  fs.writeFileSync(path.join(d, 'INTENT.md'), `${ALIGNED.replace('verdict: aligned', 'verdict: rejected')}\n## 驳回理由\n与 Hub 上的 po-import 重复。\n`);
  assert.equal(I.checkIntent(d).state, 'rejected');
  fs.writeFileSync(path.join(d, 'INTENT.md'), ALIGNED.replace('scope: team', 'scope: everyone').replace('date: 2026-11-26', 'date: yesterday'));
  const r = I.checkIntent(d);
  assert.ok(r.errors.some((e) => e.startsWith('scope')));
  assert.ok(r.errors.some((e) => e.startsWith('date')));
});

test('missing card, and the legacy references/intent.md fallback', () => {
  const d = skillDir();
  assert.equal(I.readIntent(d).state, 'missing');
  fs.mkdirSync(path.join(d, 'references'));
  fs.writeFileSync(path.join(d, 'references', 'intent.md'), ALIGNED);
  const r = I.checkIntent(d);
  assert.equal(r.state, 'aligned');
  assert.ok(r.warnings.some((w) => w.includes('move it')));
});

test('CRLF files parse the same', () => {
  const d = skillDir();
  fs.writeFileSync(path.join(d, 'INTENT.md'), ALIGNED.replace(/\n/g, '\r\n'));
  assert.equal(I.checkIntent(d).state, 'aligned');
});
