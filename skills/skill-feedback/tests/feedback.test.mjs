// Unit tests for scripts/feedback.mjs.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const F = await import(pathToFileURL(path.join(HERE, '..', 'scripts', 'feedback.mjs')).href);

let home;
beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'fb-home-'));
  process.env.SKILL_FEEDBACK_HOME = home;
});

function install(root, name, { md, meta, hubSource, version } = {}) {
  const d = path.join(root, name);
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, 'SKILL.md'), md ?? `---\nname: ${name}\ndescription: x\n---\n\n- 源码仓库：<https://github.com/example-org/skills>，目录 skills/${name}/\n`);
  if (meta) { fs.mkdirSync(path.join(d, '.skillhub')); fs.writeFileSync(path.join(d, '.skillhub', 'metadata.json'), JSON.stringify(meta)); }
  if (hubSource) fs.writeFileSync(path.join(d, '.hub-source.json'), JSON.stringify(hubSource));
  if (version) fs.writeFileSync(path.join(d, 'VERSION'), `${version}\n`);
  return d;
}

test('locate reports channel, version and source repo for each copy', () => {
  const user = path.join(home, '.claude', 'skills');
  install(user, 'skill-qa', { meta: { registry: 'http://hub.example.lan:8088', namespace: 'blacklake', slug: 'skill-qa', version: '0.2.0' } });
  const proj = path.join(home, 'proj', '.claude', 'skills');
  install(proj, 'skill-qa', { hubSource: { version: '0.3.0', commit: 'abc123' } });
  const r = F.locate('skill-qa', [proj, user]);
  assert.equal(r.length, 2);
  assert.equal(r[0].channel, 'repo');
  assert.equal(r[0].commit, 'abc123');
  assert.equal(r[1].channel, 'skillhub');
  assert.equal(r[1].coordinate, '@blacklake/skill-qa');
  assert.equal(r[1].version, '0.2.0');
  assert.equal(r[1].repo, 'example-org/skills');
});

test('locate finds claude.ai synced copies and manual installs', () => {
  const synced = path.join(home, '.claude', 'skills', 'synced', 'org_acct');
  install(synced, 'arch-diagram', { md: '---\nname: arch-diagram\ndescription: x\n---\nno repo here\n' });
  const r = F.locate('arch-diagram');
  assert.equal(r.length, 1);
  assert.equal(r[0].channel, 'claude.ai-sync');
  assert.equal(r[0].repo, null);
  const manual = path.join(home, 'm');
  install(manual, 'tool', { version: '1.2.3' });
  assert.deepEqual([F.locate('tool', [manual])[0].channel, F.locate('tool', [manual])[0].version], ['manual', '1.2.3']);
});

test('sourceRepo prefers the line that names the source repository', () => {
  const md = 'see https://github.com/other/thing for background\n- 源码仓库：<https://github.com/D-Tony2020/skill-hub>，目录 skills/x/\n';
  assert.equal(F.sourceRepo(md), 'D-Tony2020/skill-hub');
  assert.equal(F.sourceRepo('clone https://github.com/a/b.git now'), 'a/b');
});

test('scrub finds and fixes sensitive content, including customer words', () => {
  fs.mkdirSync(path.join(home, '.skill-qa'));
  fs.writeFileSync(path.join(home, '.skill-qa', 'redact.txt'), '# customers\n某某重工\n');
  const draft = [
    '报错路径 C:\\Users\\zhangsan\\work\\a.txt 和 /home/lisi/x',
    '联系 zhangsan@example.com',
    'Hub 在 192.168.1.20:8088',
    '客户是某某重工',
    'token: abcdefghijkl',
  ].join('\n');
  const r = F.scrub(draft);
  assert.equal(r.clean, false);
  const kinds = new Set(r.hits.map((h) => h.kind));
  for (const k of ['个人目录', '邮箱', '内网地址', '客户名', '疑似密码或令牌']) assert.ok(kinds.has(k), k);
  const fixed = F.scrub(draft, { fix: true });
  assert.ok(!fixed.text.includes('zhangsan'));
  assert.ok(!fixed.text.includes('192.168.1.20'));
  assert.ok(fixed.text.includes('某客户'));
  assert.equal(fixed.clean, true);
});

test('issue url is prefilled, labelled and flags overly long bodies', () => {
  const r = F.issueUrl({ repo: 'D-Tony2020/skill-hub', title: '[skill-qa] 误报', body: '正文', label: 'skill:skill-qa' });
  const u = new URL(r.url);
  assert.equal(u.pathname, '/D-Tony2020/skill-hub/issues/new');
  assert.equal(u.searchParams.get('title'), '[skill-qa] 误报');
  assert.equal(u.searchParams.get('labels'), 'skill:skill-qa');
  assert.equal(r.tooLong, false);
  assert.equal(F.issueUrl({ repo: 'a/b', title: 't', body: 'x'.repeat(8000) }).tooLong, true);
  assert.throws(() => F.issueUrl({ repo: 'not a repo', title: 't' }), /owner\/repo/);
});
