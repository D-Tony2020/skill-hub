// Skill chain tooling: the infra suite, mirrored upstream skills, and new-skill scaffolds.
//   suiteReport(root)        compare skills/hub-starter/assets/infra-suite.json with the repo
//   syncUpstream(...)        refresh a mirrored skill (e.g. skill-creator) from a local upstream checkout
//   scaffoldSkill(...)       create skills/<name> with everything the Hub expects
import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';
import { loadSkills } from './lib.mjs';

export const SUITE_REL = path.join('skills', 'hub-starter', 'assets', 'infra-suite.json');
export const HOME_NAMESPACE = 'blacklake';

export function parseCoordinate(c) {
  const m = String(c).match(/^@([a-z0-9][a-z0-9-]*)\/([a-z0-9][a-z0-9-]*)(?:@(.+))?$/);
  if (!m) throw new Error(`bad suite coordinate ${c}`);
  return { namespace: m[1], slug: m[2], version: m[3] ?? null };
}

export function loadSuite(root) {
  const file = path.join(root, SUITE_REL);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

// Every home-namespace member must be a published repo skill at the same version,
// the entry skill must be a member, and infra members should carry the infra tag.
export function suiteReport(root) {
  const suite = loadSuite(root);
  const skills = new Map(loadSkills(root).map((s) => [s.dirName, s]));
  const rows = [];
  const problems = [];
  const coords = new Set();
  for (const m of suite.spec.members) {
    const c = parseCoordinate(m.skill);
    if (coords.has(m.skill)) problems.push(`${m.skill} is listed twice`);
    coords.add(m.skill);
    if (c.namespace !== suite.metadata.namespace) {
      rows.push({ skill: m.skill, version: m.version, stage: m.stage, source: 'external', state: 'external (not in this repo)' });
      continue;
    }
    const s = skills.get(c.slug);
    let state = 'ok';
    if (!s) state = 'not in repo';
    else if (s.status !== 'published') state = `repo status ${s.status}`;
    else if (s.version !== m.version) state = `repo is ${s.version}`;
    else if (!s.tags.includes('infra')) state = 'missing infra tag';
    if (state !== 'ok') problems.push(`${m.skill}@${m.version}: ${state}`);
    rows.push({ skill: m.skill, version: m.version, stage: m.stage, source: 'repo', state });
  }
  const entry = parseCoordinate(suite.spec.entrySkill);
  const entryMember = suite.spec.members.find((m) => m.skill === `@${entry.namespace}/${entry.slug}`);
  if (!entryMember) problems.push(`entry skill ${suite.spec.entrySkill} is not a member`);
  else if (entry.version && entry.version !== entryMember.version) problems.push(`entry skill version ${entry.version} differs from member version ${entryMember.version}`);
  // Published repo skills tagged infra but missing from the suite.
  for (const s of skills.values()) {
    if (s.status === 'published' && s.tags.includes('infra') && !coords.has(`@${suite.metadata.namespace}/${s.dirName}`)) {
      problems.push(`${s.dirName} is tagged infra but not in the suite`);
    }
  }
  return { coordinate: `@${suite.metadata.namespace}/${suite.metadata.slug}`, version: suite.metadata.version, visibility: suite.spec.visibility, entry: suite.spec.entrySkill, rows, problems };
}

// ---- mirrored upstream skills -----------------------------------------------
// The mirror keeps upstream files byte for byte, except SKILL.md, which gets one
// appended block (between these markers) naming our repo, how to update, and
// where to report problems. The block survives every sync.
export const MIRROR_BEGIN = '<!-- hub:mirror-note begin -->';
export const MIRROR_END = '<!-- hub:mirror-note end -->';
const KEEP = new Set(['hub.yaml', 'CHANGELOG.md', 'NOTICE.md', 'evals', 'tests', 'QA_REPORT.md', 'qa-exceptions.json', 'INTENT.md', '.gitattributes']);

export function mirrorNote(text) {
  const i = text.indexOf(MIRROR_BEGIN);
  const j = text.indexOf(MIRROR_END);
  return i !== -1 && j > i ? text.slice(i, j + MIRROR_END.length) : null;
}

function listFiles(dir, rel = '') {
  const out = [];
  for (const e of fs.readdirSync(path.join(dir, rel), { withFileTypes: true })) {
    if (['.git', '__pycache__', '.DS_Store', 'node_modules'].includes(e.name)) continue;
    const r = rel ? `${rel}/${e.name}` : e.name;
    if (e.isDirectory()) out.push(...listFiles(dir, r));
    else if (e.isFile()) out.push(r);
  }
  return out;
}

// Replace the mirrored skill's upstream files with those in `fromDir` (a checkout of
// upstream.repo at `commit`, pointing at upstream.path). Our own files (KEEP) stay.
export function syncUpstream(root, name, fromDir, commit) {
  const dir = path.join(root, 'skills', name);
  const hubFile = path.join(dir, 'hub.yaml');
  if (!fs.existsSync(hubFile)) throw new Error(`skills/${name}/hub.yaml not found`);
  const doc = YAML.parseDocument(fs.readFileSync(hubFile, 'utf8'));
  const up = doc.get('upstream')?.toJSON?.() ?? doc.toJSON().upstream;
  if (!up) throw new Error(`skills/${name} is not a mirror (no upstream in hub.yaml)`);
  if (!/^[0-9a-f]{7,40}$/.test(commit ?? '')) throw new Error('--commit <hash> is required: record exactly which upstream commit was copied');
  if (!fs.existsSync(path.join(fromDir, 'SKILL.md'))) throw new Error(`${fromDir} has no SKILL.md`);
  const oldMd = fs.readFileSync(path.join(dir, 'SKILL.md'), 'utf8');
  const note = mirrorNote(oldMd);
  if (!note) throw new Error('current SKILL.md has no mirror note block; refusing to drop it');

  const before = new Set(listFiles(dir).filter((r) => !KEEP.has(r.split('/')[0])));
  const incoming = listFiles(fromDir);
  for (const r of before) if (!incoming.includes(r)) fs.rmSync(path.join(dir, r));
  const changed = [];
  for (const r of incoming) {
    if (KEEP.has(r.split('/')[0])) continue;
    const src = fs.readFileSync(path.join(fromDir, r));
    const dest = path.join(dir, r);
    const prev = fs.existsSync(dest) ? fs.readFileSync(dest) : null;
    let next = src;
    if (r === 'SKILL.md') next = Buffer.from(`${src.toString('utf8').replace(/\s*$/, '')}\n\n${note}\n`);
    if (!prev || !prev.equals(next)) changed.push(r);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, next);
  }
  const removed = [...before].filter((r) => !incoming.includes(r));
  const previous = up.commit;
  doc.setIn(['upstream', 'commit'], commit);
  doc.setIn(['upstream', 'synced'], new Date().toISOString().slice(0, 10));
  fs.writeFileSync(hubFile, doc.toString());
  // Clean up directories emptied by removals.
  for (const r of removed) {
    let d = path.dirname(path.join(dir, r));
    while (d.startsWith(dir) && d !== dir && fs.existsSync(d) && fs.readdirSync(d).length === 0) { fs.rmdirSync(d); d = path.dirname(d); }
  }
  return { previous, commit, changed, removed, upstream: up };
}

// ---- new skill scaffold -------------------------------------------------------
const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function scaffoldSkill(root, name, { owner = 'TODO', repoUrl = 'https://github.com/D-Tony2020/skill-hub', today = new Date().toISOString().slice(0, 10) } = {}) {
  if (!NAME_RE.test(name) || name.length > 64 || /anthropic|claude/.test(name)) throw new Error(`"${name}" is not a valid skill name (lowercase-hyphen, at most 64 characters, no anthropic/claude)`);
  const dir = path.join(root, 'skills', name);
  if (fs.existsSync(dir)) throw new Error(`skills/${name} already exists`);
  const files = {
    'SKILL.md': `---
name: ${name}
description: TODO 第一句说它做什么、产出什么；第二句列出用户会怎么说（"帮我……""……怎么办"），以及哪些近似说法不该用它、该交给谁。
license: Proprietary
---

# ${name}

TODO 一段话：它解决什么问题、为什么需要它。目标以 INTENT.md（skill-intent 产出）为准。

## 适用前提

- TODO 操作系统、依赖的外部系统、网络等；不满足时第一步告诉用户不适用。

## 源码、更新与反馈

- 源码仓库：<${repoUrl}>，目录 \`skills/${name}/\`，分支 \`main\`。改动经 PR 合并，不改已安装的副本。
- 更新：从 SkillHub 安装的用 \`skillhub upgrade @blacklake/${name} --registry <Hub 地址> --check\`；从仓库装的在仓库里 \`git pull\` 后 \`node tools/hub/cli.mjs install ${name} --force\`。
- 反馈：用 skill-feedback，或在仓库提 issue，标题以 \`[${name}]\` 开头。

## 流程

1. TODO
`,
    'hub.yaml': `status: draft\nversion: 0.1.0\nowner: ${owner}\ntags: []\n`,
    'CHANGELOG.md': `# Changelog\n\n## 0.1.0 - ${today}\n\n- TODO 首版说明\n`,
    'evals/evals.json': `${JSON.stringify({ skill_name: name, version: '0.1.0', evals: [1, 2, 3].map((i) => ({ id: `case-${i}`, category: 'function', prompt: 'TODO 用户真实会说的话（从 INTENT.md 的触发说法推出）', expectations: ['TODO 可逐条核对的结果（从 INTENT.md 的成功标准推出）'] })) }, null, 2)}\n`,
    'evals/trigger-evals.json': `${JSON.stringify([
      ...[1, 2, 3].map(() => ({ query: 'TODO 该触发的说法', should_trigger: true })),
      ...[1, 2, 3].map(() => ({ query: 'TODO 近似但不该触发的说法', should_trigger: false })),
    ], null, 2)}\n`,
  };
  for (const [rel, text] of Object.entries(files)) {
    const f = path.join(dir, rel);
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, text);
  }
  return { dir, files: Object.keys(files) };
}
