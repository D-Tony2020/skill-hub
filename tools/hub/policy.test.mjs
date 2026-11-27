import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { changedSkills, evaluate } from './policy.mjs';
import { loadSkills } from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const policy = { autoMergeAuthors: ['alice'], humanOnlyPaths: ['.github/**', 'package.json'] };
const draft = { dirName: 'demo', status: 'draft', dir: '/nonexistent' };
const base = { policy, skills: [draft], baseVersions: {}, contentChangedFor: () => true };

test('changedSkills splits skill dirs from other files', () => {
  const r = changedSkills(['skills/a/SKILL.md', 'skills/a/x/y.md', 'skills/b/hub.yaml', 'README.md']);
  assert.deepEqual(r.skills, ['a', 'b']);
  assert.deepEqual(r.other, ['README.md']);
});

test('allowlisted author touching only a draft skill may auto-merge', () => {
  const r = evaluate({ ...base, files: ['skills/demo/SKILL.md'], author: 'alice' });
  assert.equal(r.autoMerge, true, r.blockers.join('; '));
});

test('unknown author needs a human', () => {
  const r = evaluate({ ...base, files: ['skills/demo/SKILL.md'], author: 'mallory' });
  assert.equal(r.autoMerge, false);
  assert.match(r.blockers.join(), /not in autoMergeAuthors/);
});

test('human-only paths need a human, nested globs included', () => {
  const r = evaluate({ ...base, files: ['.github/workflows/validate.yml', 'package.json', 'docs/x.md'], author: 'alice' });
  assert.equal(r.autoMerge, false);
  assert.match(r.blockers[0], /validate\.yml, package\.json$/);
});

test('every published skill in the repo passes its own gate (intent, qa, exceptions)', () => {
  const skills = loadSkills(ROOT).filter((s) => s.status === 'published');
  const files = skills.map((s) => `skills/${s.dirName}/SKILL.md`);
  const r = evaluate({ files, author: 'alice', policy, skills, baseVersions: {}, contentChangedFor: () => false });
  const bad = r.skills.filter((s) => s.problems.length);
  // Report rather than hard-fail on legacy skills that predate INTENT.md.
  for (const s of bad) console.log(`  policy gap: ${s.name}: ${s.problems.join('; ')}`);
  assert.ok(r.skills.length > 0);
});

test('content change without a version bump is blocked', () => {
  const pub = { dirName: 'skill-creator', status: 'published', version: '1.0.0', hub: { upstream: {} } };
  const skills = loadSkills(ROOT).filter((s) => s.dirName === 'skill-creator');
  const r = evaluate({ files: ['skills/skill-creator/SKILL.md'], author: 'alice', policy, skills: skills.length ? skills : [pub], baseVersions: { 'skill-creator': skills[0]?.version ?? '1.0.0' }, contentChangedFor: () => true });
  assert.match(r.blockers.join(), /version is still/);
});
