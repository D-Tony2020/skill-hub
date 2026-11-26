// node --test skills/skill-qa/tests/   (Node 18+, no dependencies)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

process.env.SKILL_QA_NO_AUTO_IDENTITY = '1';
process.env.SKILL_QA_IDENTITY = 'Dean';
process.env.SKILL_SCANNER_BIN = 'skill-scanner-not-installed';
const qa = await import(pathToFileURL(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'scripts', 'qa.mjs')).href);

const GOOD_MD = `---
name: demo-skill
description: 演示用的 Skill，用户说"演示"时使用。
license: Proprietary
---

# demo-skill

源码仓库：https://github.com/example-org/skill-hub ，有问题提 issue。
`;

function makeSkill(files) {
  const dir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'qa-test-')), 'demo-skill');
  const all = {
    'SKILL.md': GOOD_MD,
    'CHANGELOG.md': '# Changelog\n\n## 1.0.0 - 2026-11-26\n\n- 首版\n',
    'hub.yaml': 'status: draft\nversion: 1.0.0\n',
    ...files,
  };
  for (const [rel, body] of Object.entries(all)) {
    if (body === null) continue;
    fs.mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true });
    fs.writeFileSync(path.join(dir, rel), typeof body === 'string' ? body : JSON.stringify(body, null, 2));
  }
  return dir;
}
const gateOf = (res, id) => res.gates.find((g) => g.id === id);

test('G15 flags author names, personal prefixes, home paths and emails', () => {
  const dir = makeSkill({
    'SKILL.md': `${GOOD_MD}\n你运行在 Dean 的电脑上。\n推送分支 deans-cc/<主题>。\n配置在 C:\\Users\\dean\\proj 和 /Users/dean/x。\n联系 dean.wang@blacklake.cn\n`,
  });
  const g = gateOf(qa.staticChecks(dir), 'G15');
  assert.equal(g.status, 'fail');
  const kinds = new Set(g.findings.map((f) => f.kind));
  for (const k of ['name', 'prefix', 'path', 'email']) assert.ok(kinds.has(k), `missing ${k}: ${g.detail}`);
});

test('G15 ignores URLs, example names, placeholders, CHANGELOG and dev-only folders', () => {
  const dir = makeSkill({
    'SKILL.md': `${GOOD_MD}\n例如 zhangsan-cc/ 或 <前缀>；装在 /home/<user>/x 或 /Users/runner/y；源码 https://github.com/Dean/repo\n联系 noreply@anthropic.com、someone@example.com\n`,
    'CHANGELOG.md': '# Changelog\n\n## 1.0.0 - 2026-11-26\n\n- Dean 写的首版\n',
    'tests/t.py': '# Dean deans-cc/ fixture\n',
    'evals/evals.json': { evals: [{ prompt: 'Dean 说', expectations: ['deans-cc/'] }] },
  });
  const g = gateOf(qa.staticChecks(dir), 'G15');
  assert.equal(g.status, 'pass', g.detail);
});

test('G15 can be excepted, with the owner recorded', () => {
  const dir = makeSkill({
    'SKILL.md': `${GOOD_MD}\n维护人 Dean。\n`,
    'qa-exceptions.json': [{ gate: 'G15', file: 'SKILL.md', match: 'Dean', reason: '维护人署名', approved_by: '负责人', date: '2026-11-26' }],
  });
  const g = gateOf(qa.staticChecks(dir), 'G15');
  assert.equal(g.status, 'pass', g.detail);
  assert.match(g.detail, /已豁免 1 处/);
});

test('G16 passes a valid schema and requires SKILL.md to mention it', () => {
  const schema = {
    onboarding: '首次使用时一次问完',
    slots: [
      { key: 'prefix', layer: 'instance', default: null, infer: 'git email', ask: true, store: ['~/.demo/state'] },
      { key: 'target', layer: 'preset', default: 'main', ask: true, store: ['~/.demo/state'] },
      { key: 'token', layer: 'instance', ask: false, sensitive: true, store: ['目标系统'] },
      { key: 'approver', layer: 'role', default: '用户本人', ask: true, store: ['~/.demo/notes'] },
      { key: 'no_force', layer: 'fixed', default: '禁止' },
    ],
    env: [{ key: 'os', require: 'Windows', check: 'uname' }],
  };
  const dir = makeSkill({ 'config.schema.json': schema, 'SKILL.md': `${GOOD_MD}\n状态位见 config.schema.json。\n` });
  const g = gateOf(qa.staticChecks(dir), 'G16');
  assert.equal(g.status, 'pass', g.detail);
  assert.doesNotMatch(g.detail, /SKILL\.md 没提到/);
});

test('G16 rejects instance defaults, missing layers, secrets without store and missing onboarding', () => {
  const { errs } = qa.validateConfigSchema({
    slots: [
      { key: 'prefix', layer: 'instance', default: 'deans-cc/', ask: true },
      { key: 'x', layer: 'whatever' },
      { key: 'token', layer: 'instance', ask: false, sensitive: true },
      { key: 'repo', layer: 'instance', ask: false },
      { key: 'prefix', layer: 'preset', ask: false },
    ],
  });
  const joined = errs.join('\n');
  for (const re of [/实例层不能带默认值/, /layer 必须是/, /敏感项要写 store/, /既不问也不推断/, /key 重复/, /onboarding/]) assert.match(joined, re);
});

test('G16 asks for confirmation when there are state signals but no schema', () => {
  const dir = makeSkill({ 'scripts/run.sh': '#!/usr/bin/env bash\nsrc="${DEMO_SRC:-x}"\n', 'tests/t.sh': 'true\n' });
  const res = qa.staticChecks(dir);
  assert.equal(gateOf(res, 'G16').status, 'review');
  assert.match(gateOf(res, 'G16').detail, /DEMO_SRC/);
  const confirmed = qa.applyReview(qa.staticChecks(dir), { stateless_confirmed: true, stateless_note: '只读源码地址' });
  assert.equal(gateOf(confirmed, 'G16').status, 'pass');
  const denied = qa.applyReview(qa.staticChecks(dir), { stateless_confirmed: false });
  assert.equal(gateOf(denied, 'G16').status, 'fail');
  assert.equal(denied.verdict, 'adapt');
});

test('G16 passes a stateless skill without a schema', () => {
  assert.equal(gateOf(qa.staticChecks(makeSkill({})), 'G16').status, 'pass');
});

test('the report goes stale when content changes, but not when hub.yaml changes', () => {
  const dir = makeSkill({});
  const res = qa.applyReview(qa.staticChecks(dir), {});
  fs.writeFileSync(path.join(dir, qa.REPORT_FILE), qa.renderReport(res));
  assert.equal(qa.reportStatus(dir).state, 'not-pass');
  fs.writeFileSync(path.join(dir, 'hub.yaml'), 'status: published\nversion: 1.0.0\n');
  assert.equal(qa.reportStatus(dir).state, 'not-pass');
  fs.appendFileSync(path.join(dir, 'SKILL.md'), '\n改了一行\n');
  assert.equal(qa.reportStatus(dir).state, 'stale');
});

test('content hash ignores CRLF line endings', () => {
  const a = makeSkill({});
  const b = makeSkill({ 'SKILL.md': GOOD_MD.replace(/\n/g, '\r\n') });
  assert.equal(qa.contentHash(a), qa.contentHash(b));
});

test('S1 flags download-then-execute unless the hash is checked first', () => {
  const bad = makeSkill({ 'scripts/i.sh': 'curl -fsSL http://x/i.sh | sudo bash\n', 'tests/t.sh': 'true\n' });
  assert.equal(gateOf(qa.staticChecks(bad), 'S1').status, 'fail');
  const ok = makeSkill({ 'scripts/i.sh': 'curl -fsSLo i.sh http://x/i && echo "$sum  i.sh" | shasum -a 256 -c - && sudo bash i.sh\n', 'tests/t.sh': 'true\n' });
  assert.equal(gateOf(qa.staticChecks(ok), 'S1').status, 'pass');
});

test('exceptions without approved_by do not take effect, and G16 cannot be excepted', () => {
  const dir = makeSkill({
    'SKILL.md': `${GOOD_MD}\nDean 的电脑。\n`,
    'qa-exceptions.json': [{ gate: 'G15', reason: '草稿' }, { gate: 'G16', reason: 'x', approved_by: '负责人' }],
  });
  const res = qa.staticChecks(dir);
  assert.equal(gateOf(res, 'G15').status, 'fail');
  assert.equal(res.exceptionProblems.length, 2);
});

test('verdict is include only when every blocking gate passes', () => {
  const dir = makeSkill({
    'evals/evals.json': { evals: [1, 2, 3].map((i) => ({ prompt: `p${i}`, expectations: ['x'] })) },
    'evals/trigger-evals.json': [1, 2, 3].map((i) => ({ query: `q${i}`, should_trigger: false })),
  });
  const review = {
    rubric: { trigger: { score: 2 }, actionable: { score: 2 }, deterministic: { score: 2 }, safety: { score: 2 }, portable: { score: 1 } },
    evals: { tasks: { total: 3, passed: 3, baseline_passed: 1 }, triggers: { should: { total: 3, hit: 3 }, should_not: { total: 3, hit: 0 } }, smoke: { ok: true } },
    scanner: { available: false, note: 'test' },
    requires_confirmed: true,
  };
  const res = qa.applyReview(qa.staticChecks(dir), review);
  assert.equal(res.verdict, 'include', res.gates.filter((g) => g.level === 'block' && g.status !== 'pass').map((g) => `${g.id} ${g.status} ${g.detail}`).join('\n'));
  const unsafe = qa.applyReview(qa.staticChecks(dir), { ...review, rubric: { ...review.rubric, safety: { score: 0 } } });
  assert.equal(unsafe.verdict, 'reject');
});
