#!/usr/bin/env node
// Usage:
//   node tools/hub/cli.mjs validate            check every skill, exit 1 on errors
//   node tools/hub/cli.mjs build [--check]     write .claude-plugin/marketplace.json (or fail if stale)
//   node tools/hub/cli.mjs list [--json]       show skills with status and version
//   node tools/hub/cli.mjs files <skill>       list files that go into the release package
//   node tools/hub/cli.mjs import <dir> [--name n] [--version x.y.z] [--force]   bring an existing skill in as a draft
//   node tools/hub/cli.mjs bump <skill> <major|minor|patch|x.y.z> [-m note]     raise the version, open a CHANGELOG entry
//   node tools/hub/cli.mjs install <skill> [--dest dir] [--force]               copy the release files into ~/.claude/skills
//   node tools/hub/cli.mjs status [--dest dir] [--json]                         repo vs installed versions, missing requirements
//   node tools/hub/cli.mjs chain [skill] [--json]                               where each skill stands in the chain: intent -> qa -> published -> suite
//   node tools/hub/cli.mjs suite [--check] [--json]                             infra suite members vs the repo; what to enter in SkillHub's suite editor
//   node tools/hub/cli.mjs new <name> [--owner o]                               scaffold skills/<name> (draft) with hub.yaml, CHANGELOG, evals, INTENT.md
//   node tools/hub/cli.mjs upstream <skill> --from <dir> --commit <sha>         refresh a mirrored skill from a local upstream checkout
import fs from 'node:fs';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  loadSkills, validateSkill, buildMarketplace, serializeMarketplace, packageFiles,
  importSkill, bumpSkill, installSkill, readInstalled,
} from './lib.mjs';
import { reportStatus, staticChecks, VERDICTS } from '../../skills/skill-qa/scripts/qa.mjs';
import { readIntent, initIntent } from '../../skills/skill-intent/scripts/intent.mjs';
import { suiteReport, syncUpstream, scaffoldSkill } from './chain.mjs';

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

function flag(name) {
  const i = args.indexOf(name);
  return i === -1 ? undefined : args[i + 1];
}
const DEFAULT_DEST = path.join(os.homedir(), '.claude', 'skills');

function gitCommit() {
  const r = spawnSync('git', ['-C', ROOT, 'rev-parse', '--short', 'HEAD'], { encoding: 'utf8' });
  return r.status === 0 ? r.stdout.trim() : null;
}

function onPath(cmd) {
  const probe = process.platform === 'win32' ? ['where', [cmd]] : ['sh', ['-c', `command -v "${cmd}"`]];
  return spawnSync(probe[0], probe[1], { stdio: 'ignore' }).status === 0;
}

function requirementGaps(skill, dest) {
  const installed = new Set(readInstalled(dest).map((s) => s.name));
  return [
    ...skill.requires.skills.filter((s) => !installed.has(s)).map((s) => `skill ${s} not installed in ${dest}`),
    ...skill.requires.commands.filter((c) => !onPath(c)).map((c) => `command ${c} not on PATH`),
    ...skill.requires.env.filter((e) => !process.env[e]).map((e) => `env ${e} not set`),
  ];
}

function importCmd(src) {
  if (!src) { console.error('usage: import <dir> [--name n] [--version x.y.z] [--force]'); return 2; }
  const r = importSkill(ROOT, path.resolve(src), { name: flag('--name'), version: flag('--version'), force: args.includes('--force') });
  console.log(`imported ${r.name} v${r.version} as draft -> ${path.relative(ROOT, r.dir)} (${r.files.length} files)`);
  for (const e of r.errors) console.log(`     error: ${e}`);
  for (const w of r.warnings) console.log(`     warn:  ${w}`);
  if (r.onlySkillMd) console.log('     warn:  only SKILL.md came across; if it references scripts/ or references/, the source was incomplete (claude.ai synced copies hold SKILL.md only)');
  const qa = reportStatus(r.dir);
  const qaLine = {
    missing: 'no QA_REPORT.md: run skill-qa on the full source before opening a PR',
    unreadable: 'QA_REPORT.md was not written by skill-qa: re-run skill-qa',
    stale: 'QA_REPORT.md does not match these files (changed after the report): re-run skill-qa report on skills/' + r.name,
    'not-pass': `QA_REPORT.md is current but the verdict is ${qa.meta?.verdict}: fix and re-run skill-qa`,
    pass: `QA_REPORT.md is current, verdict include (${qa.meta?.date})`,
  }[qa.state];
  console.log(`     qa:    ${qaLine}`);
  console.log('next: fix errors, declare requires in hub.yaml, then set status: published and open a PR with the QA report');
  return r.errors.length ? 1 : 0;
}

function bumpCmd(name, part) {
  const skill = loadSkills(ROOT).find((s) => s.dirName === name);
  if (!skill || !part) { console.error('usage: bump <skill> <major|minor|patch|x.y.z> [-m note]'); return 2; }
  const next = bumpSkill(skill, part, flag('-m'));
  console.log(`${name}: ${skill.version} -> ${next} (CHANGELOG entry added; edit it before committing)`);
  return 0;
}

function installCmd(name) {
  const dest = flag('--dest') ?? DEFAULT_DEST;
  const skill = loadSkills(ROOT).find((s) => s.dirName === name);
  if (!skill) { console.error(`no skill folder named ${name}`); return 1; }
  const { errors } = validateSkill(skill);
  if (errors.length) { console.error(`refusing to install ${name}: ${errors.join('; ')}`); return 1; }
  const to = installSkill(skill, dest, { force: args.includes('--force'), commit: gitCommit() });
  console.log(`installed ${name} v${skill.version} -> ${to} (start a new Claude session to load it)`);
  for (const g of requirementGaps(skill, dest)) console.log(`     missing: ${g}`);
  return 0;
}

function statusCmd(json) {
  const dest = flag('--dest') ?? DEFAULT_DEST;
  const installed = new Map(readInstalled(dest).map((s) => [s.name, s]));
  const rows = loadSkills(ROOT).map((s) => {
    const inst = installed.get(s.dirName);
    let state = 'not installed';
    if (inst && !inst.managed) state = 'installed by hand';
    else if (inst && inst.version === s.version) state = 'up to date';
    else if (inst) state = `outdated (${inst.version})`;
    return { name: s.dirName, status: s.status, version: s.version ?? '', installed: state, missing: inst ? requirementGaps(s, dest) : [] };
  });
  if (json) console.log(JSON.stringify(rows, null, 2));
  else for (const r of rows) console.log(`${r.name.padEnd(28)} ${r.status.padEnd(10)} ${r.version.padEnd(9)} ${r.installed}${r.missing.length ? `  missing: ${r.missing.join('; ')}` : ''}`);
  return 0;
}

// QA state of every skill: a current skill-qa report with verdict include, plus the static blocking gates.
// --strict fails on anything short of that for published skills; CI runs without it for now and annotates.
function qaCmd(strict, only) {
  let bad = 0;
  for (const skill of loadSkills(ROOT)) {
    if (only && skill.dirName !== only) continue;
    const st = reportStatus(skill.dir);
    const res = staticChecks(skill.dir);
    const failing = res.gates.filter((g) => g.level === 'block' && g.status === 'fail').map((g) => g.id);
    const report = st.state === 'pass' ? 'report ok' : st.state === 'not-pass' ? `report ${VERDICTS[st.meta?.verdict]?.zh ?? st.meta?.verdict}` : `report ${st.state}`;
    const ok = st.state === 'pass' && !failing.length;
    console.log(`${ok ? 'ok  ' : 'warn'} ${skill.dirName.padEnd(24)} ${String(skill.status).padEnd(10)} ${report}${failing.length ? `; static gates failing: ${failing.join(', ')}` : ''}`);
    if (!ok && process.env.GITHUB_ACTIONS) console.log(`::warning title=skill-qa ${skill.dirName}::${report}${failing.length ? `; failing ${failing.join(', ')}` : ''}`);
    if (!ok && skill.status === 'published') bad += 1;
  }
  if (bad) console.log(`\n${bad} published skill(s) without a current passing skill-qa report; publish:local will refuse them.`);
  return strict && bad ? 1 : 0;
}

// One line per skill: the chain stages it has passed. Read-only.
function chainCmd(only, json) {
  let suite = null;
  try { suite = suiteReport(ROOT); } catch { /* no suite file */ }
  const members = new Set((suite?.rows ?? []).map((r) => r.skill.split('/').pop()));
  const rows = loadSkills(ROOT).filter((s) => !only || s.dirName === only).map((s) => {
    const intent = readIntent(s.dir);
    const qa = reportStatus(s.dir);
    const mirror = !!s.hub?.upstream;
    let next;
    if (mirror) next = qa.state === 'pass' ? 'publish (mirror)' : 'skill-qa (mirror: intent not required)';
    else if (intent.state === 'missing') next = 'skill-intent';
    else if (intent.state === 'invalid') next = 'fix INTENT.md (intent.mjs check)';
    else if (intent.state !== 'aligned') next = `back to producer (${intent.state})`;
    else if (!intent.proceed) next = `not for the Hub (scope ${intent.scope})`;
    else if (qa.state !== 'pass') next = `skill-qa (${qa.state === 'not-pass' ? qa.meta?.verdict : qa.state})`;
    else if (s.status !== 'published') next = 'set status: published, PR';
    else next = 'publish:local, then approve in SkillHub';
    return {
      name: s.dirName, version: s.version ?? '', status: s.status,
      intent: mirror ? 'mirror' : intent.state === 'aligned' ? `aligned/${intent.scope}${intent.bound_to ? `@${intent.bound_to}` : ''}` : intent.state,
      qa: qa.state, suite: members.has(s.dirName), next,
    };
  });
  if (json) console.log(JSON.stringify(rows, null, 2));
  else {
    console.log(`${'skill'.padEnd(22)} ${'version'.padEnd(8)} ${'status'.padEnd(10)} ${'intent'.padEnd(20)} ${'qa'.padEnd(9)} suite  next`);
    for (const r of rows) console.log(`${r.name.padEnd(22)} ${r.version.padEnd(8)} ${r.status.padEnd(10)} ${r.intent.padEnd(20)} ${r.qa.padEnd(9)} ${(r.suite ? 'yes' : '-').padEnd(6)} ${r.next}`);
  }
  return 0;
}

function suiteCmd(check, json) {
  const r = suiteReport(ROOT);
  if (json) { console.log(JSON.stringify(r, null, 2)); return check && r.problems.length ? 1 : 0; }
  console.log(`suite ${r.coordinate}@${r.version}  visibility ${r.visibility}  entry ${r.entry}`);
  for (const row of r.rows) console.log(`  ${row.state === 'ok' || row.source === 'external' ? 'ok  ' : 'FAIL'} ${`${row.skill}@${row.version}`.padEnd(34)} ${String(row.stage ?? '').padEnd(10)} ${row.state}`);
  if (r.problems.length) {
    console.log(`\n${r.problems.length} problem(s):`);
    for (const p of r.problems) console.log(`  - ${p}`);
  } else if (!check) {
    console.log('\nSkillHub CLI cannot publish a suite yet. After every member above is PUBLISHED in SkillHub,');
    console.log('the Hub owner creates this suite version in the web suite editor with exactly these members and versions.');
  }
  return check && r.problems.length ? 1 : 0;
}

function newCmd(name) {
  if (!name) { console.error('usage: new <name> [--owner o]'); return 2; }
  const r = scaffoldSkill(ROOT, name, { owner: flag('--owner') ?? 'TODO' });
  initIntent(r.dir, name);
  console.log(`created skills/${name} (draft): ${[...r.files, 'INTENT.md'].join(', ')}`);
  console.log('next: skill-intent fills INTENT.md with the producer; skill-creator writes SKILL.md and the evals; then skill-qa');
  return 0;
}

function upstreamCmd(name) {
  const from = flag('--from');
  if (!name || !from) { console.error('usage: upstream <skill> --from <upstream skill dir> --commit <sha>'); return 2; }
  const r = syncUpstream(ROOT, name, path.resolve(from), flag('--commit'));
  console.log(`${name}: upstream ${r.upstream.repo} ${r.upstream.path} ${r.previous} -> ${r.commit}`);
  console.log(`  changed: ${r.changed.length ? r.changed.join(', ') : 'none'}`);
  if (r.removed.length) console.log(`  removed: ${r.removed.join(', ')}`);
  console.log(r.changed.length || r.removed.length
    ? `next: hub bump ${name} minor -m "sync upstream ${r.commit.slice(0, 7)}", re-run skill-qa, open a PR`
    : 'nothing changed upstream; hub.yaml records the new commit only');
  return 0;
}

const handlers = {
  chain: () => chainCmd(args.find((a) => !a.startsWith('--')), args.includes('--json')),
  suite: () => suiteCmd(args.includes('--check'), args.includes('--json')),
  new: () => newCmd(args[0]),
  upstream: () => upstreamCmd(args[0]),
  qa: () => qaCmd(args.includes('--strict'), args.find((a) => !a.startsWith('--'))),
  validate: () => validate(),
  build: () => build(args.includes('--check')),
  list: () => list(args.includes('--json')),
  files: () => files(args[0]),
  import: () => importCmd(args[0]),
  bump: () => bumpCmd(args[0], args[1]),
  install: () => installCmd(args[0]),
  status: () => statusCmd(args.includes('--json')),
};

if (!handlers[command]) {
  console.error('usage: cli.mjs <validate|build [--check]|list [--json]|files <skill>|import <dir>|bump <skill> <part>|install <skill>|status|qa [skill] [--strict]|chain [skill]|suite [--check]|new <name>|upstream <skill> --from <dir> --commit <sha>>');
  process.exit(2);
}
try {
  process.exit(handlers[command]());
} catch (err) {
  console.error(err.message);
  process.exit(1);
}
