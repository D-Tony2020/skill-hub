#!/usr/bin/env node
// Publish every `published` skill in this repo to a self-hosted SkillHub (phase 1: localhost).
//
//   npm run publish:local -- [--dry-run] [--skill <name>] [--force]
//                            [--registry <url>] [--namespace <slug>] [--visibility public|namespace-only|private]
//
// Needs the SkillHub CLI (`npm i -g @astron-team/skillhub`) and a one-time
// `skillhub login --registry <url>`. The registry is always passed explicitly:
// the CLI's own default is a public server, and nothing should ever go there by accident.
//
// Each skill is staged in a temp folder (see stageForSkillHub), checked with
// `skillhub publish --dry-run`, then submitted. CLI tokens can only submit, so
// public and namespace-only submissions wait in SkillHub's review queue until an
// admin approves them in the web UI. Submitted versions are recorded in
// .hub-state.json (git-ignored) and skipped next time unless --force is given.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { loadSkills, validateSkill, stageForSkillHub } from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const STATE_FILE = path.join(ROOT, '.hub-state.json');
const VISIBILITIES = ['public', 'namespace-only', 'private'];

function parseArgs(argv) {
  const opts = {
    registry: process.env.SKILLHUB_REGISTRY || 'http://localhost:8088',
    namespace: process.env.SKILLHUB_NAMESPACE || 'blacklake',
    visibility: process.env.SKILLHUB_VISIBILITY || 'public',
    skill: null, dryRun: false, force: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => {
      const v = argv[i + 1];
      if (v === undefined || v.startsWith('--')) throw new Error(`${a} needs a value`);
      i += 1;
      return v;
    };
    if (a === '--registry') opts.registry = next();
    else if (a === '--namespace') opts.namespace = next();
    else if (a === '--visibility') opts.visibility = next();
    else if (a === '--skill') opts.skill = next();
    else if (a === '--dry-run') opts.dryRun = true;
    else if (a === '--force') opts.force = true;
    else throw new Error(`unknown option ${a}`);
  }
  if (!VISIBILITIES.includes(opts.visibility)) throw new Error(`--visibility must be one of ${VISIBILITIES.join(', ')}`);
  opts.registry = opts.registry.replace(/\/+$/, '');
  return opts;
}

// Windows needs a shell for the .cmd shim, and the shell re-splits the joined
// command line, so every argument is quoted there (paths with spaces).
const quoteWin = (a) => (/[\s"&|<>^]/.test(a) ? `"${a.replace(/"/g, '""')}"` : a);
const RATE_LIMITED = /429|rate.?limit|too many requests/i;
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

function skillhub(args, { retries = 3, waitMs = Number(process.env.SKILLHUB_RETRY_WAIT_MS ?? 65_000) } = {}) {
  const bin = process.env.SKILLHUB_BIN || 'skillhub';
  const win = process.platform === 'win32';
  for (let attempt = 0; ; attempt += 1) {
    const res = win
      ? spawnSync([bin, ...args].map(quoteWin).join(' '), { encoding: 'utf8', shell: true })
      : spawnSync(bin, args, { encoding: 'utf8' });
    if (res.error) throw new Error(`cannot run ${bin}: ${res.error.message} (install with npm i -g @astron-team/skillhub or set SKILLHUB_BIN)`);
    const out = `${res.stdout ?? ''}${res.stderr ?? ''}`.trim();
    // SkillHub allows about 10 publish calls a minute per user; dry runs count too.
    if (res.status !== 0 && RATE_LIMITED.test(out) && attempt < retries) {
      console.log(`     rate limited by SkillHub, waiting ${Math.round(waitMs / 1000)}s before retry ${attempt + 1}/${retries}`);
      sleep(waitMs);
      continue;
    }
    return { code: res.status, out };
  }
}

function readState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return {}; }
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const reg = ['--registry', opts.registry];

  const who = skillhub(['whoami', ...reg]);
  if (who.code !== 0) {
    console.error(`not logged in to ${opts.registry}. Run once:\n  skillhub login --registry ${opts.registry}\n\n${who.out}`);
    return 1;
  }

  let skills = loadSkills(ROOT).filter((s) => s.status === 'published');
  if (opts.skill) skills = skills.filter((s) => s.dirName === opts.skill);
  if (!skills.length) {
    console.log(opts.skill ? `no published skill named ${opts.skill}` : 'no published skills');
    return opts.skill ? 1 : 0;
  }

  const state = readState();
  const done = (state[opts.registry] ??= {});
  const stageRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-hub-publish-'));
  let failed = 0;
  let submitted = 0;

  for (const skill of skills) {
    const label = `${skill.dirName}@${skill.version}`;
    const { errors } = validateSkill(skill);
    if (errors.length) {
      console.log(`FAIL ${label}: ${errors.join('; ')}`);
      failed += 1;
      continue;
    }
    const prev = done[skill.dirName];
    if (!opts.force && prev?.version === skill.version) {
      console.log(`skip ${label}: already submitted ${prev.at}; if it was rejected or superseded, resend with --skill ${skill.dirName} --force`);
      continue;
    }
    if (prev && prev.version !== skill.version) {
      console.log(`     ${label}: ${prev.version} was submitted ${prev.at}. If it is still waiting for review, this submission replaces it in the queue.`);
    }

    const staged = stageForSkillHub(skill, path.join(stageRoot, skill.dirName));
    if (staged.dropped.length) console.log(`     ${label}: left out for SkillHub: ${staged.dropped.join(', ')}`);
    const base = ['publish', staged.dir, ...reg, '--namespace', opts.namespace, '--visibility', opts.visibility];

    const check = skillhub([...base, '--dry-run']);
    if (check.code !== 0) {
      console.log(`FAIL ${label}: SkillHub rejected the package\n${check.out}`);
      failed += 1;
      continue;
    }
    if (opts.dryRun) {
      console.log(`ok   ${label}: dry run passed (${staged.files.length} files)`);
      continue;
    }

    const pub = skillhub(base);
    if (pub.code !== 0) {
      console.log(`FAIL ${label}: publish failed\n${pub.out}`);
      failed += 1;
      continue;
    }
    done[skill.dirName] = { version: skill.version, namespace: opts.namespace, at: new Date().toISOString() };
    fs.writeFileSync(STATE_FILE, `${JSON.stringify(state, null, 2)}\n`);
    // CLI 0.3.1 prints "Status: undefined" against server 0.2.28: the real state is on the review page.
    console.log(`ok   ${label}: submitted to ${opts.namespace}\n${pub.out.replace(/^.*Status: undefined.*$/m, '').trim()}`);
    if (/BLOCKED|CRITICAL/.test(pub.out)) console.log(`WARN ${label}: the scan reported BLOCKED or CRITICAL findings; do not approve it until they are fixed or signed off.`);
    submitted += 1;
  }

  fs.rmSync(stageRoot, { recursive: true, force: true });
  if (submitted && opts.visibility !== 'private') {
    console.log(`\n${submitted} skill(s) submitted. Submitted is not the same as passing the scan: SkillHub scans each one first.`);
    console.log(`Open ${opts.registry}/dashboard/reviews once the scan has finished (approving earlier fails) and read each scan verdict.`);
    console.log('A BLOCKED verdict means do not approve: reject it, fix the findings, and submit a new version. A finding that is required behaviour needs a written reason and an explicit sign-off from the owner, not a silenced rule.');
  }
  return failed ? 1 : 0;
}

try {
  process.exitCode = main();
} catch (err) {
  console.error(err.message);
  process.exitCode = 2;
}
