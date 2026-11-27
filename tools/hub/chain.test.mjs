import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { suiteReport, syncUpstream, scaffoldSkill, mirrorNote, MIRROR_BEGIN, MIRROR_END, SUITE_REL } from './chain.mjs';
import { loadSkills, validateSkill, packageFiles } from './lib.mjs';

function repo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'chain-'));
  fs.mkdirSync(path.join(root, 'skills'));
  return root;
}
function skill(root, name, hub, md = '') {
  const d = path.join(root, 'skills', name);
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, 'SKILL.md'), `---\nname: ${name}\ndescription: test skill\n---\n${md}`);
  fs.writeFileSync(path.join(d, 'hub.yaml'), hub);
  return d;
}
function suite(root, members, entry = '@team/starter@0.1.0') {
  const f = path.join(root, SUITE_REL);
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify({ metadata: { namespace: 'team', slug: 'infra', version: '0.1.0' }, spec: { visibility: 'PUBLIC', entrySkill: entry, members } }));
}

test('suite report passes when members match the repo and flags every kind of drift', () => {
  const root = repo();
  skill(root, 'hub-starter', 'status: draft\nversion: 0.0.1\n');
  skill(root, 'starter', 'status: published\nversion: 0.1.0\ntags: [infra]\n');
  skill(root, 'qa', 'status: published\nversion: 0.2.0\ntags: [infra]\n');
  suite(root, [
    { skill: '@team/starter', version: '0.1.0' },
    { skill: '@team/qa', version: '0.2.0' },
    { skill: '@global/skillhub-cli', version: '2.0.2' },
  ]);
  assert.deepEqual(suiteReport(root).problems, []);

  skill(root, 'extra', 'status: published\nversion: 1.0.0\ntags: [infra]\n');
  skill(root, 'qa', 'status: published\nversion: 0.3.0\n');
  suite(root, [
    { skill: '@team/starter', version: '0.1.0' },
    { skill: '@team/qa', version: '0.2.0' },
    { skill: '@team/ghost', version: '1.0.0' },
  ], '@team/starter@0.0.9');
  const p = suiteReport(root).problems.join('\n');
  assert.match(p, /@team\/qa@0\.2\.0: repo is 0\.3\.0/);
  assert.match(p, /ghost.*not in repo/);
  assert.match(p, /entry skill version 0\.0\.9/);
  assert.match(p, /extra is tagged infra but not in the suite/);
});

test('the real repo suite file parses and names hub-starter as entry', () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
  const r = suiteReport(root);
  assert.equal(r.coordinate, '@blacklake/infra');
  assert.match(r.entry, /^@blacklake\/hub-starter@/);
});

test('upstream sync replaces upstream files, keeps ours and the mirror note', () => {
  const root = repo();
  const note = `${MIRROR_BEGIN}\nmirror of x\n${MIRROR_END}`;
  const d = skill(root, 'mirrored', 'status: published\nversion: 1.0.0\nupstream:\n  repo: https://example.com/up\n  path: skills/mirrored\n  commit: aaaaaaa\n  license: Apache-2.0\n', `old body\n\n${note}\n`);
  fs.mkdirSync(path.join(d, 'scripts'));
  fs.writeFileSync(path.join(d, 'scripts', 'gone.py'), 'old');
  fs.writeFileSync(path.join(d, 'NOTICE.md'), 'ours');
  fs.mkdirSync(path.join(d, 'evals'));
  fs.writeFileSync(path.join(d, 'evals', 'evals.json'), '{}');

  const up = fs.mkdtempSync(path.join(os.tmpdir(), 'up-'));
  fs.writeFileSync(path.join(up, 'SKILL.md'), '---\nname: mirrored\ndescription: new\n---\nnew body\n');
  fs.mkdirSync(path.join(up, 'scripts'));
  fs.writeFileSync(path.join(up, 'scripts', 'new.py'), 'new');

  assert.throws(() => syncUpstream(root, 'mirrored', up, 'not-a-sha'), /--commit/);
  const r = syncUpstream(root, 'mirrored', up, 'bbbbbbbbbbbb');
  assert.equal(r.previous, 'aaaaaaa');
  assert.deepEqual(r.removed, ['scripts/gone.py']);
  const md = fs.readFileSync(path.join(d, 'SKILL.md'), 'utf8');
  assert.match(md, /new body/);
  assert.equal(mirrorNote(md), note);
  assert.equal(fs.readFileSync(path.join(d, 'NOTICE.md'), 'utf8'), 'ours');
  assert.ok(fs.existsSync(path.join(d, 'evals', 'evals.json')));
  assert.match(fs.readFileSync(path.join(d, 'hub.yaml'), 'utf8'), /commit: bbbbbbbbbbbb/);
  const s = loadSkills(root).find((x) => x.dirName === 'mirrored');
  assert.deepEqual(validateSkill(s).errors, []);
});

test('upstream sync refuses a skill without a mirror note', () => {
  const root = repo();
  skill(root, 'm', 'status: draft\nversion: 1.0.0\nupstream:\n  repo: r\n  path: p\n  commit: aaaaaaa\n  license: MIT\n');
  const up = fs.mkdtempSync(path.join(os.tmpdir(), 'up-'));
  fs.writeFileSync(path.join(up, 'SKILL.md'), '---\nname: m\ndescription: d\n---\n');
  assert.throws(() => syncUpstream(root, 'm', up, 'abcdef1'), /mirror note/);
});

test('upstream block in hub.yaml is validated', () => {
  const root = repo();
  skill(root, 'm', 'status: draft\nversion: 1.0.0\nupstream:\n  repo: r\n  commit: xyz\n');
  const { errors } = validateSkill(loadSkills(root)[0]);
  assert.ok(errors.some((e) => e.includes('upstream.path')));
  assert.ok(errors.some((e) => e.includes('commit must be')));
});

test('scaffold creates a valid draft that names its source repo', () => {
  const root = repo();
  scaffoldSkill(root, 'po-helper', { owner: 'someone', today: '2026-11-26' });
  const s = loadSkills(root)[0];
  assert.equal(s.status, 'draft');
  assert.deepEqual(validateSkill(s).errors, []);
  assert.match(fs.readFileSync(path.join(s.dir, 'SKILL.md'), 'utf8'), /源码仓库/);
  assert.ok(!packageFiles(s).some((f) => f.startsWith('evals/')));
  assert.throws(() => scaffoldSkill(root, 'po-helper'), /already exists/);
  assert.throws(() => scaffoldSkill(root, 'Claude-Thing'), /not a valid/);
});

test('INTENT.md never ships in a package', () => {
  const root = repo();
  const d = skill(root, 'x', 'status: draft\nversion: 0.1.0\n');
  fs.writeFileSync(path.join(d, 'INTENT.md'), 'card');
  assert.ok(!packageFiles(loadSkills(root)[0]).includes('INTENT.md'));
});
