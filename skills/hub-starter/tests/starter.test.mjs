// Unit tests for scripts/starter.mjs. A fake `skillhub` (tests/fake-skillhub.mjs) stands in for the CLI.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const S = await import(pathToFileURL(path.join(HERE, '..', 'scripts', 'starter.mjs')).href);

let home;
let ev;
function evidence(files) {
  fs.mkdirSync(ev, { recursive: true });
  for (const [name, text] of Object.entries(files)) fs.writeFileSync(path.join(ev, name), text);
}

beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'starter-home-'));
  ev = path.join(home, '.skill-hub', 'evidence');
  process.env.HUB_STARTER_HOME = home;
  delete process.env.SKILLHUB_REGISTRY;
});

test('suite definition is well formed and the entry skill is a member', () => {
  const s = S.loadSuite();
  assert.equal(s.kind, 'SkillSuite');
  const coords = s.spec.members.map((m) => m.skill);
  assert.equal(new Set(coords).size, coords.length, 'duplicate member');
  const entry = S.parseCoordinate(s.spec.entrySkill);
  assert.ok(coords.includes(`@${entry.namespace}/${entry.slug}`));
  for (const m of s.spec.members) {
    S.parseCoordinate(m.skill);
    assert.match(m.version, /^\d+\.\d+\.\d+$/);
    for (const r of m.roles) assert.ok(S.ROLES.includes(r));
  }
});

test('registry resolution never falls back to a public default', () => {
  assert.deepEqual(S.resolveRegistry(), { registry: null, source: null });
  fs.mkdirSync(path.join(home, '.skillhub'));
  fs.writeFileSync(path.join(home, '.skillhub', 'config.json'), JSON.stringify({ registry: 'http://hub.example.lan:8088/' }));
  assert.equal(S.resolveRegistry().registry, 'http://hub.example.lan:8088');
  process.env.SKILLHUB_REGISTRY = 'http://env.example.lan';
  assert.equal(S.resolveRegistry().source, 'SKILLHUB_REGISTRY');
  assert.equal(S.resolveRegistry('http://arg.example.lan').source, 'argument');
  assert.throws(() => S.resolveRegistry('http://u:p@x.example.lan'), /credentials/);
});

test('profile set validates keys and roles and round-trips', () => {
  assert.throws(() => S.writeProfile({ password: 'x' }), /unknown profile key/);
  assert.throws(() => S.writeProfile({ role: 'boss' }), /role must be/);
  S.writeProfile({ registry: 'http://hub.example.lan:8088/', role: 'author' });
  const p = S.readProfile();
  assert.equal(p.registry, 'http://hub.example.lan:8088');
  assert.equal(p.role, 'author');
});

test('plan prefers the suite and filters members by role', () => {
  S.writeProfile({ registry: 'http://hub.example.lan:8088', role: 'user' });
  const p = S.plan({});
  assert.deepEqual(p.suite.command.slice(0, 4), ['skillhub', 'suite', 'install', '@blacklake/infra']);
  assert.ok(p.suite.command.includes('http://hub.example.lan:8088'));
  const names = p.members.map((m) => m.skill);
  assert.ok(names.includes('@global/skillhub-cli'));
  assert.ok(!names.includes('@blacklake/skill-qa'), 'users do not need the QA gate');
  assert.ok(S.plan({ role: 'author' }).members.length > p.members.length);
});

test('doctor lists the commands to run when nothing has been checked yet', () => {
  const r = S.doctor({ registry: 'http://hub.example.lan:8088', role: 'author' });
  const cli = r.checks.find((c) => c.id === 'cli');
  assert.equal(cli.status, 'skipped');
  assert.match(cli.next, /^skillhub version > .*version\.txt" 2>&1$/);
  assert.equal(r.checks.find((c) => c.id === 'git').status, 'skipped');
  assert.equal(r.ok, false);
});

test('doctor reports a missing CLI with the install command', () => {
  evidence({ 'version.txt': '' });
  const r = S.doctor({ registry: 'http://hub.example.lan:8088' });
  const cli = r.checks.find((c) => c.id === 'cli');
  assert.equal(cli.status, 'fail');
  assert.match(cli.next, /@astron-team\/skillhub/);
});

test('doctor flags a non-official skillhub binary instead of trusting it', () => {
  evidence({ 'version.txt': 'skillhub 0.4.1', 'whoami.json': '{"ok":true,"handle":"x"}' });
  const r = S.doctor({ registry: 'http://hub.example.lan:8088' });
  assert.equal(r.checks.find((c) => c.id === 'cli').status, 'warn');
  assert.equal(r.checks.find((c) => c.id === 'login'), undefined, 'does not trust further output of a foreign CLI');
});

test('doctor passes when logged in and every member for the role is installed', () => {
  const suite = S.loadSuite();
  const items = S.membersForRole(suite, 'user').map((m) => {
    const c = S.parseCoordinate(m.skill);
    return { namespace: c.namespace, slug: c.slug, version: m.version, agent: 'claude-code', status: 'ok' };
  });
  evidence({ 'version.txt': 'SkillHub CLI 0.3.1', 'whoami.json': JSON.stringify({ ok: true, handle: 'member01' }), 'list.json': JSON.stringify({ ok: true, items }) });
  S.writeProfile({ registry: 'http://hub.example.lan:8088', role: 'user' });
  const r = S.doctor({});
  assert.equal(r.ok, true, JSON.stringify(r.checks, null, 1));
  assert.equal(r.checks.find((c) => c.id === 'infra').status, 'pass');
});

test('doctor separates an unreachable Hub from an expired login and lists missing members', () => {
  evidence({ 'version.txt': 'SkillHub CLI 0.3.1', 'whoami.json': 'Error: fetch failed (ECONNREFUSED)', 'list.json': '{"ok":true,"items":[]}', 'git.txt': 'git version 2.47.0' });
  let r = S.doctor({ registry: 'http://hub.example.lan:8088', role: 'author' });
  assert.match(r.checks.find((c) => c.id === 'login').detail, /连不上/);
  assert.match(r.checks.find((c) => c.id === 'infra').detail, /skill-qa/);
  assert.equal(r.checks.find((c) => c.id === 'git').status, 'pass');
  evidence({ 'whoami.json': 'not logged in' });
  r = S.doctor({ registry: 'http://hub.example.lan:8088', role: 'author' });
  assert.match(r.checks.find((c) => c.id === 'login').next, /skillhub login --registry/);
});

test('evidence written by Windows PowerShell 5 (UTF-16LE) is readable', () => {
  assert.equal(S.decodeText(Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from('SkillHub CLI 0.3.1', 'utf16le')])), 'SkillHub CLI 0.3.1');
  assert.equal(S.decodeText(Buffer.from('\ufeffabc')), 'abc');
});
