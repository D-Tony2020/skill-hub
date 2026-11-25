#!/usr/bin/env node
// Usage:
//   node tools/hub/cli.mjs validate            check every skill, exit 1 on errors
//   node tools/hub/cli.mjs build [--check]     write .claude-plugin/marketplace.json (or fail if stale)
//   node tools/hub/cli.mjs list [--json]       show skills with status and version
//   node tools/hub/cli.mjs files <skill>       list files that go into the release package
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  loadSkills, validateSkill, buildMarketplace, serializeMarketplace, packageFiles,
} from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const MANIFEST = path.join(ROOT, '.claude-plugin', 'marketplace.json');
const [command, ...args] = process.argv.slice(2);

function validate() {
  const skills = loadSkills(ROOT);
  let failed = 0;
  for (const skill of skills) {
    const { errors, warnings } = validateSkill(skill);
    const mark = errors.length ? 'FAIL' : 'ok  ';
    console.log(`${mark} ${skill.dirName} (${skill.status}${skill.version ? ` v${skill.version}` : ''})`);
    for (const e of errors) console.log(`     error: ${e}`);
    for (const w of warnings) console.log(`     warn:  ${w}`);
    if (errors.length) failed += 1;
  }
  console.log(`\n${skills.length} skill(s), ${failed} with errors`);
  return failed ? 1 : 0;
}

function build(check) {
  const skills = loadSkills(ROOT);
  const invalid = skills.filter((s) => s.status === 'published' && validateSkill(s).errors.length);
  if (invalid.length) {
    console.error(`refusing to build: published skill(s) with errors: ${invalid.map((s) => s.dirName).join(', ')}`);
    return 1;
  }
  const text = serializeMarketplace(buildMarketplace(skills));
  if (check) {
    const current = fs.existsSync(MANIFEST) ? fs.readFileSync(MANIFEST, 'utf8') : '';
    if (current !== text) {
      console.error('.claude-plugin/marketplace.json is out of date: run `npm run build` and commit the result');
      return 1;
    }
    console.log('marketplace.json is up to date');
    return 0;
  }
  fs.mkdirSync(path.dirname(MANIFEST), { recursive: true });
  fs.writeFileSync(MANIFEST, text);
  console.log(`wrote ${path.relative(ROOT, MANIFEST)}`);
  return 0;
}

function list(json) {
  const rows = loadSkills(ROOT).map((s) => ({ name: s.dirName, status: s.status, version: s.version ?? '', description: s.description }));
  if (json) {
    console.log(JSON.stringify(rows, null, 2));
  } else {
    for (const r of rows) console.log(`${r.name.padEnd(32)} ${r.status.padEnd(10)} ${r.version.padEnd(10)} ${r.description.slice(0, 60)}`);
  }
  return 0;
}

function files(name) {
  const skill = loadSkills(ROOT).find((s) => s.dirName === name);
  if (!skill) {
    console.error(`no skill folder named ${name}`);
    return 1;
  }
  for (const f of packageFiles(skill)) console.log(f);
  return 0;
}

const handlers = {
  validate: () => validate(),
  build: () => build(args.includes('--check')),
  list: () => list(args.includes('--json')),
  files: () => files(args[0]),
};

if (!handlers[command]) {
  console.error('usage: cli.mjs <validate|build [--check]|list [--json]|files <skill>>');
  process.exit(2);
}
process.exit(handlers[command]());
