import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  loadSkills, validateSkill, buildMarketplace, packageFiles, parseFrontmatter, stageForSkillHub, withMetadataVersion,
  findHardcodedPaths, findMissingReferences, importSkill, bumpSkill, nextVersion, installSkill, readInstalled,
} from './lib.mjs';

function makeRepo(skills) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hub-'));
  for (const [name, files] of Object.entries(skills)) {
    for (const [rel, content] of Object.entries(files)) {
      const file = path.join(root, 'skills', name, rel);
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, content);
    }
  }
  return root;
}

const md = (name, description = 'Does a thing. Use when asked to do the thing.') =>
  `---\nname: ${name}\ndescription: ${description}\n---\n\n# ${name}\n`;

test('a published skill with hub.yaml validates and lands in the marketplace', () => {
  const root = makeRepo({
    'good-skill': { 'SKILL.md': md('good-skill'), 'hub.yaml': 'status: published\nversion: 1.2.0\ntags: [git]\n' },
  });
  const [skill] = loadSkills(root);
  assert.deepEqual(validateSkill(skill).errors, []);
  const manifest = buildMarketplace([skill]);
  assert.equal(manifest.plugins.length, 1);
  assert.deepEqual(manifest.plugins[0], {
    name: 'good-skill', source: './skills/good-skill', description: 'Does a thing. Use when asked to do the thing.',
    version: '1.2.0', skills: ['.'], keywords: ['git'],
  });
});

test('draft and archived skills stay out of the marketplace', () => {
  const root = makeRepo({
    'a-draft': { 'SKILL.md': md('a-draft') },
    'b-archived': { 'SKILL.md': md('b-archived'), 'hub.yaml': 'status: archived\nversion: 0.1.0\n' },
  });
  assert.equal(buildMarketplace(loadSkills(root)).plugins.length, 0);
});

test('VERSION file supplies the version and must agree with hub.yaml', () => {
  const root = makeRepo({
    agree: { 'SKILL.md': md('agree'), VERSION: '1.0.0\n', 'hub.yaml': 'status: published\n' },
    clash: { 'SKILL.md': md('clash'), VERSION: '1.0.0\n', 'hub.yaml': 'status: published\nversion: 2.0.0\n' },
  });
  const [agree, clash] = loadSkills(root);
  assert.equal(agree.version, '1.0.0');
  assert.deepEqual(validateSkill(agree).errors, []);
  assert.match(validateSkill(clash).errors.join('\n'), /differs from VERSION/);
});

test('name rules: folder match, format, reserved words', () => {
  const root = makeRepo({
    'folder-x': { 'SKILL.md': md('other-name') },
    'Bad_Name': { 'SKILL.md': md('Bad_Name') },
    'my-claude-helper': { 'SKILL.md': md('my-claude-helper') },
  });
  const byDir = Object.fromEntries(loadSkills(root).map((s) => [s.dirName, validateSkill(s).errors.join('\n')]));
  assert.match(byDir['folder-x'], /must equal the folder name/);
  assert.match(byDir['Bad_Name'], /lowercase letters/);
  assert.match(byDir['my-claude-helper'], /reserved words/);
});

test('description is required, limited to 1024 characters and free of angle brackets', () => {
  const root = makeRepo({
    empty: { 'SKILL.md': '---\nname: empty\n---\n' },
    long: { 'SKILL.md': md('long', 'x'.repeat(1025)) },
    tags: { 'SKILL.md': md('tags', 'Use <b>this</b>') },
  });
  const errs = Object.fromEntries(loadSkills(root).map((s) => [s.dirName, validateSkill(s).errors.join('\n')]));
  assert.match(errs.empty, /description` is required/);
  assert.match(errs.long, /limit is 1024/);
  assert.match(errs.tags, /must not contain < or >/);
});

test('published without a version, bad status and top-level bin/ are errors', () => {
  const root = makeRepo({
    noversion: { 'SKILL.md': md('noversion'), 'hub.yaml': 'status: published\n' },
    badstatus: { 'SKILL.md': md('badstatus'), 'hub.yaml': 'status: live\n' },
    withbin: { 'SKILL.md': md('withbin'), 'bin/run': '#!/bin/sh\n' },
  });
  const errs = Object.fromEntries(loadSkills(root).map((s) => [s.dirName, validateSkill(s).errors.join('\n')]));
  assert.match(errs.noversion, /needs a version/);
  assert.match(errs.badstatus, /must be one of/);
  assert.match(errs.withbin, /bin\//);
});

test('unknown frontmatter keys warn instead of failing', () => {
  const root = makeRepo({ extra: { 'SKILL.md': '---\nname: extra\ndescription: Something useful.\nowner: dean\n---\n' } });
  const result = validateSkill(loadSkills(root)[0]);
  assert.deepEqual(result.errors, []);
  assert.match(result.warnings.join('\n'), /"owner" is not a documented/);
});

test('frontmatter parsing handles CRLF and BOM, and rejects a missing block', () => {
  assert.equal(parseFrontmatter('﻿---\r\nname: a\r\ndescription: b\r\n---\r\nbody').data.name, 'a');
  assert.match(parseFrontmatter('# no frontmatter').error, /does not start/);
});

test('package files leave out tests, evals, hub.yaml and caches', () => {
  const root = makeRepo({
    pkg: {
      'SKILL.md': md('pkg'), 'hub.yaml': 'status: draft\n', 'scripts/run.sh': 'echo\n',
      'tests/test_x.py': '', 'evals/evals.json': '{}', 'scripts/__pycache__/x.pyc': '', '.gitattributes': '* text=auto\n',
    },
  });
  assert.deepEqual(packageFiles(loadSkills(root)[0]), ['SKILL.md', 'scripts/run.sh']);
});

test('SkillHub staging drops extensionless files and writes metadata.version', () => {
  const root = makeRepo({
    hubpkg: {
      'SKILL.md': '---\nname: hubpkg\ndescription: Does it.\nmetadata:\n  author: dean\n---\n\n# body\n',
      VERSION: '1.4.0\n', 'hub.yaml': 'status: published\n', 'scripts/run.sh': 'echo\n', 'scripts/Makefile': 'x\n',
    },
  });
  const [skill] = loadSkills(root);
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-'));
  const staged = stageForSkillHub(skill, path.join(out, 'hubpkg'));
  assert.deepEqual(staged.files, ['SKILL.md', 'scripts/run.sh']);
  assert.deepEqual(staged.dropped, ['VERSION', 'scripts/Makefile']);
  const fm = parseFrontmatter(fs.readFileSync(path.join(staged.dir, 'SKILL.md'), 'utf8')).data;
  assert.deepEqual(fm.metadata, { author: 'dean', version: '1.4.0' });
  assert.equal(fm.name, 'hubpkg');
  assert.match(fs.readFileSync(path.join(staged.dir, 'SKILL.md'), 'utf8'), /\n# body\n$/);
  // the source SKILL.md is untouched
  assert.doesNotMatch(fs.readFileSync(path.join(skill.dir, 'SKILL.md'), 'utf8'), /version/);
});

test('withMetadataVersion keeps CRLF/BOM input parseable and adds metadata when absent', () => {
  const out = withMetadataVersion('﻿---\r\nname: a\r\ndescription: b\r\n---\r\nbody', '2.0.0');
  assert.deepEqual(parseFrontmatter(out).data, { name: 'a', description: 'b', metadata: { version: '2.0.0' } });
});

test('hardcoded install paths and missing referenced files are reported', () => {
  const root = makeRepo({
    paths: {
      'SKILL.md': '---\nname: paths\ndescription: Uses scripts.\n---\nRun `py -3 "$env:USERPROFILE\\.claude\\skills\\paths\\scripts\\run.py"` or ~/.claude/skills/paths/scripts/run.py.\nSee references/guide.md and scripts/run.py.\n',
      'scripts/run.py': 'print(1)\n',
    },
  });
  const skill = loadSkills(root)[0];
  const hits = findHardcodedPaths(skill).map((h) => h.text);
  assert.deepEqual(hits, ['$env:USERPROFILE\\.claude\\skills\\paths', '~/.claude/skills/paths']);
  assert.deepEqual(findMissingReferences(skill), ['references/guide.md']);
  const { errors, warnings } = validateSkill(skill);
  assert.deepEqual(errors, []);
  assert.match(warnings.join('\n'), /hardcodes an install path/);
  assert.match(warnings.join('\n'), /references\/guide\.md/);
});

test('requires must be a mapping of lists', () => {
  const root = makeRepo({
    good: { 'SKILL.md': md('good'), 'hub.yaml': 'status: draft\nrequires:\n  skills: [drawio-skill]\n  commands: [py]\n' },
    bad: { 'SKILL.md': md('bad'), 'hub.yaml': 'status: draft\nrequires:\n  skills: drawio-skill\n  tools: [x]\n' },
  });
  const [bad, good] = loadSkills(root);
  assert.deepEqual(good.requires, { skills: ['drawio-skill'], commands: ['py'], env: [] });
  assert.deepEqual(validateSkill(good).errors, []);
  assert.match(validateSkill(bad).errors.join('\n'), /requires\.skills must be a list/);
  assert.match(validateSkill(bad).warnings.join('\n'), /requires\.tools is not recognised/);
});

test('import brings a folder in as a draft, drops plugin.json and keeps VERSION', () => {
  const root = makeRepo({});
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'src-'));
  fs.writeFileSync(path.join(src, 'SKILL.md'), md('ported'));
  fs.mkdirSync(path.join(src, '.claude-plugin'));
  fs.writeFileSync(path.join(src, '.claude-plugin', 'plugin.json'), '{"name":"ported","version":"2.3.0"}');
  fs.mkdirSync(path.join(src, 'scripts', '__pycache__'), { recursive: true });
  fs.writeFileSync(path.join(src, 'scripts', 'a.py'), '');
  fs.writeFileSync(path.join(src, 'scripts', '__pycache__', 'a.pyc'), '');
  const r = importSkill(root, src);
  assert.equal(r.name, 'ported');
  assert.equal(r.version, '2.3.0');
  assert.deepEqual(r.files, ['SKILL.md', 'scripts/a.py']);
  assert.equal(fs.existsSync(path.join(root, 'skills', 'ported', '.claude-plugin')), false);
  assert.equal(loadSkills(root)[0].status, 'draft');
  assert.throws(() => importSkill(root, src), /already exists/);
  assert.equal(r.onlySkillMd, false);
});

test('bump raises VERSION and hub.yaml consistently and opens a changelog entry', () => {
  const root = makeRepo({
    withfile: { 'SKILL.md': md('withfile'), VERSION: '1.2.3\n', 'hub.yaml': 'status: published\n', 'CHANGELOG.md': '# Changelog\n\n## 1.2.3 - 2026-01-01\n\n- old\n' },
    inhub: { 'SKILL.md': md('inhub'), 'hub.yaml': 'status: draft # keep\nversion: 0.1.0\n' },
  });
  const [inhub, withfile] = loadSkills(root);
  assert.equal(bumpSkill(withfile, 'minor', 'new thing', '2026-11-25'), '1.3.0');
  assert.equal(fs.readFileSync(path.join(withfile.dir, 'VERSION'), 'utf8'), '1.3.0\n');
  assert.doesNotMatch(fs.readFileSync(path.join(withfile.dir, 'hub.yaml'), 'utf8'), /version/);
  assert.match(fs.readFileSync(path.join(withfile.dir, 'CHANGELOG.md'), 'utf8'), /# Changelog\n\n## 1\.3\.0 - 2026-11-25\n\n- new thing\n\n## 1\.2\.3/);
  assert.equal(bumpSkill(inhub, 'major', null, '2026-11-25'), '1.0.0');
  const hubText = fs.readFileSync(path.join(inhub.dir, 'hub.yaml'), 'utf8');
  assert.match(hubText, /version: 1\.0\.0/);
  assert.match(hubText, /# keep/);
  assert.throws(() => nextVersion('1.0.0', 'huge'), /bump takes/);
  assert.equal(nextVersion('1.0.0', '3.1.4'), '3.1.4');
});

test('install copies release files, marks the copy, and protects hand-made folders', () => {
  const root = makeRepo({ inst: { 'SKILL.md': md('inst'), 'hub.yaml': 'status: published\nversion: 1.0.0\n', 'tests/t.py': '', 'scripts/r.sh': '' } });
  const dest = fs.mkdtempSync(path.join(os.tmpdir(), 'dest-'));
  const skill = loadSkills(root)[0];
  installSkill(skill, dest, { commit: 'abc123' });
  assert.deepEqual(fs.readdirSync(path.join(dest, 'inst')).sort(), ['.hub-source.json', 'SKILL.md', 'scripts']);
  assert.deepEqual(readInstalled(dest), [{ name: 'inst', managed: true, version: '1.0.0' }]);
  installSkill(skill, dest); // reinstall over our own copy is fine
  fs.mkdirSync(path.join(dest, 'other'));
  fs.writeFileSync(path.join(dest, 'other', 'SKILL.md'), md('other'));
  const other = { ...skill, dirName: 'other' };
  assert.throws(() => installSkill(other, dest), /not installed by skill-hub/);
  assert.equal(readInstalled(dest).find((s) => s.name === 'other').managed, false);
});
