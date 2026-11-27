// Policy gate: the machine check that replaces "a human looks at the PR before merging".
// A PR may be auto-merged only when every skill it touches passes these rules.
// Pure functions so they can be unit-tested; cli.mjs `policy` wires them to git and the filesystem.
import fs from 'node:fs';
import path from 'node:path';
import { reportStatus } from '../../skills/skill-qa/scripts/qa.mjs';
import { readIntent } from '../../skills/skill-intent/scripts/intent.mjs';

export const POLICY_FILE = path.join('.github', 'hub-policy.json');

export function loadPolicy(root) {
  const file = path.join(root, POLICY_FILE);
  const p = JSON.parse(fs.readFileSync(file, 'utf8'));
  return { autoMergeAuthors: p.autoMergeAuthors ?? [], humanOnlyPaths: p.humanOnlyPaths ?? [] };
}

// skills/<name>/... -> <name>; everything else is "non-skill" and checked against humanOnlyPaths.
export function changedSkills(files) {
  const skills = new Set();
  const other = [];
  for (const f of files) {
    const m = f.match(/^skills\/([^/]+)\//);
    if (m) skills.add(m[1]); else other.push(f);
  }
  return { skills: [...skills].sort(), other };
}

const globToRe = (g) => new RegExp(`^${g.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*/g, '\u0000').replace(/\*/g, '[^/]*').replace(/\u0000/g, '.*')}$`);

// One skill. `skill` is a loaded skill (lib.loadSkill); `baseVersion` is its version on the base branch (null if new).
export function checkSkill(skill, { baseVersion, contentChanged }) {
  const problems = [];
  if (skill.status !== 'published') return { name: skill.dirName, status: skill.status, problems, note: 'not published: no gate' };
  const mirror = !!skill.hub?.upstream;
  if (!mirror) {
    const intent = readIntent(skill.dir);
    if (intent.state !== 'aligned') problems.push(`INTENT.md is ${intent.state}, must be aligned`);
    else if (!intent.proceed) problems.push(`INTENT.md scope ${intent.scope} is not for the Hub`);
  }
  const qa = reportStatus(skill.dir);
  if (qa.state !== 'pass') problems.push(`QA_REPORT.md is ${qa.state === 'not-pass' ? `verdict ${qa.meta?.verdict}` : qa.state}, must be a current "include"`);
  const excFile = path.join(skill.dir, 'qa-exceptions.json');
  if (fs.existsSync(excFile)) {
    let list = [];
    try { list = JSON.parse(fs.readFileSync(excFile, 'utf8')); } catch { problems.push('qa-exceptions.json is not valid JSON'); }
    for (const e of Array.isArray(list) ? list : []) {
      if (!e.approved_by) problems.push(`exception ${e.gate}/${e.rule ?? '?'} on ${e.file ?? '?'} has no approved_by`);
    }
  }
  if (contentChanged && baseVersion && baseVersion === skill.version) problems.push(`content changed but version is still ${skill.version}; run hub bump`);
  return { name: skill.dirName, status: skill.status, version: skill.version, problems };
}

export function evaluate({ files, author, policy, skills, baseVersions, contentChangedFor }) {
  const { skills: touched, other } = changedSkills(files);
  const results = touched.map((name) => {
    const s = skills.find((x) => x.dirName === name);
    if (!s) return { name, status: 'removed', problems: [] };
    return checkSkill(s, { baseVersion: baseVersions[name] ?? null, contentChanged: contentChangedFor(name) });
  });
  const blockers = [];
  const res = policy.humanOnlyPaths.map(globToRe);
  const sensitive = other.filter((f) => res.some((r) => r.test(f)));
  if (sensitive.length) blockers.push(`touches human-only paths: ${sensitive.join(', ')}`);
  if (!policy.autoMergeAuthors.includes(author)) blockers.push(`author ${author || '(unknown)'} is not in autoMergeAuthors`);
  for (const r of results) for (const p of r.problems) blockers.push(`${r.name}: ${p}`);
  return { autoMerge: blockers.length === 0, blockers, skills: results, other };
}
