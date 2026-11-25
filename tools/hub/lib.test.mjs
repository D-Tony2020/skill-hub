import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadSkills, validateSkill, buildMarketplace, packageFiles, parseFrontmatter } from './lib.mjs';

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
