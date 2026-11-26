#!/usr/bin/env node
// hub-starter helper: read-only checks and the install plan for joining a SkillHub.
//
//   node starter.mjs doctor  [--registry <url>] [--agent claude-code] [--role author|user|admin] [--evidence <dir>] [--json]
//   node starter.mjs plan    [--registry <url>] [--agent claude-code] [--role author|user|admin] [--scope user|project]
//   node starter.mjs profile [show | set key=value ...]
//
// The script runs no commands and opens no connections. The Agent runs the read-only
// commands that `doctor` lists, saves their output under ~/.skill-hub/evidence/, and
// doctor interprets it; `plan` prints the install commands for the Agent to run, one
// at a time, after telling the user. The only write is `profile set`, called after the
// user confirmed the values. Node 18+, no dependencies.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const SUITE_FILE = path.join(HERE, '..', 'assets', 'infra-suite.json');
export const ROLES = ['author', 'user', 'admin'];
const PROFILE_KEYS = new Set(['registry', 'namespace', 'agent', 'role', 'repo_url', 'repo_dir', 'owner_role_name']);

const home = () => process.env.HUB_STARTER_HOME || os.homedir();
export const profilePath = () => path.join(home(), '.skill-hub', 'profile.json');

export function readJsonFile(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

export function loadSuite(file = SUITE_FILE) {
  const s = readJsonFile(file);
  if (!s?.spec?.members?.length) throw new Error(`cannot read the suite definition at ${file}`);
  return s;
}

export function parseCoordinate(c) {
  const m = String(c).match(/^@([a-z0-9][a-z0-9-]*)\/([a-z0-9][a-z0-9-]*)(?:@(.+))?$/);
  if (!m) throw new Error(`bad coordinate ${c}`);
  return { namespace: m[1], slug: m[2], version: m[3] ?? null };
}

export function readProfile() {
  return readJsonFile(profilePath()) ?? {};
}

export function writeProfile(updates) {
  for (const k of Object.keys(updates)) if (!PROFILE_KEYS.has(k)) throw new Error(`unknown profile key ${k} (known: ${[...PROFILE_KEYS].join(', ')})`);
  if (updates.role && !ROLES.includes(updates.role)) throw new Error(`role must be one of ${ROLES.join(', ')}`);
  if (updates.registry) updates.registry = normalizeRegistry(updates.registry);
  const next = { ...readProfile(), ...updates, updated_at: new Date().toISOString() };
  fs.mkdirSync(path.dirname(profilePath()), { recursive: true });
  fs.writeFileSync(profilePath(), `${JSON.stringify(next, null, 2)}\n`);
  return next;
}

export function normalizeRegistry(url) {
  let u;
  try { u = new URL(String(url)); } catch { throw new Error(`registry ${url} is not a URL`); }
  if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password || u.search || u.hash) {
    throw new Error('registry must be an http(s) URL without credentials, query or fragment');
  }
  return u.toString().replace(/\/+$/, '');
}

// Same precedence as the SkillHub CLI, plus our profile, and never the CLI's public default:
// joining the team Hub must not silently talk to a public server.
export function resolveRegistry(flagValue) {
  const cfg = readJsonFile(path.join(home(), '.skillhub', 'config.json'));
  const candidates = [
    ['argument', flagValue],
    ['SKILLHUB_REGISTRY', process.env.SKILLHUB_REGISTRY],
    ['~/.skillhub/config.json', cfg?.registry],
    ['~/.skill-hub/profile.json', readProfile().registry],
  ];
  for (const [source, value] of candidates) if (value) return { registry: normalizeRegistry(value), source };
  return { registry: null, source: null };
}

function parseJsonOut(text) {
  if (text == null) return null;
  try { return JSON.parse(text); } catch {
    const line = String(text).split(/\r?\n/).reverse().find((l) => l.trim().startsWith('{'));
    try { return line ? JSON.parse(line) : null; } catch { return null; }
  }
}

export function membersForRole(suite, role) {
  return suite.spec.members.filter((m) => !role || !m.roles || m.roles.includes(role));
}

// The script never runs commands or opens connections. The Agent runs the read-only
// commands below and saves their output in an evidence folder; doctor interprets it.
export const EVIDENCE = {
  version: { file: 'version.txt', cmd: (r) => ['skillhub', 'version'] },
  whoami: { file: 'whoami.json', cmd: (r) => ['skillhub', 'whoami', '--registry', r, '--json'] },
  list: { file: 'list.json', cmd: (r, a) => ['skillhub', 'list', '--registry', r, '--agent', a, '--json'] },
  git: { file: 'git.txt', cmd: () => ['git', '--version'] },
};
export const evidenceDir = () => path.join(home(), '.skill-hub', 'evidence');

// Windows PowerShell 5 writes `>` redirections as UTF-16LE with a BOM.
export function decodeText(buf) {
  if (buf[0] === 0xff && buf[1] === 0xfe) return buf.subarray(2).toString('utf16le');
  if (buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) return buf.subarray(3).toString('utf8');
  return buf.toString('utf8');
}

function readEvidence(dir, key) {
  try { return decodeText(fs.readFileSync(path.join(dir, EVIDENCE[key].file))).trim(); } catch { return null; }
}

export function doctor(opts) {
  const checks = [];
  const add = (id, status, detail, next) => checks.push({ id, status, detail, ...(next ? { next } : {}) });
  const suite = loadSuite();
  const profile = readProfile();
  const role = opts.role ?? profile.role ?? null;
  const agent = opts.agent ?? profile.agent ?? 'claude-code';
  const dir = opts.evidence ?? evidenceDir();
  const { registry, source } = resolveRegistry(opts.registry);
  const reg = registry ?? '<Hub 地址>';
  const howTo = (key) => `${EVIDENCE[key].cmd(reg, agent).join(' ')} > "${path.join(dir, EVIDENCE[key].file)}" 2>&1`;

  const major = Number(process.versions.node.split('.')[0]);
  add('node', major >= 18 ? 'pass' : 'fail', `Node ${process.versions.node}`, major >= 18 ? undefined : '请用户安装 Node.js 18 或更高版本');

  if (!registry) add('registry', 'fail', '没有 Hub 地址', '问用户要团队 Hub 地址（找 Hub 管理员），确认后 profile set registry=<地址>');
  else add('registry', 'pass', `${registry}（来自 ${source}）`);

  const ver = readEvidence(dir, 'version');
  if (ver == null) add('cli', 'skipped', '还没有检查', howTo('version'));
  else if (/not found|not recognized|无法将|找不到/i.test(ver) || !ver) add('cli', 'fail', 'skillhub 不在 PATH 上', 'npm install --global @astron-team/skillhub');
  else if (!/SkillHub CLI \d/.test(ver)) add('cli', 'warn', `skillhub version 输出不像官方 CLI：${ver.slice(0, 120)}`, '按 skillhub-cli 的规则核实这个命令的来源，不要直接覆盖');
  else add('cli', 'pass', ver.split('\n')[0]);
  const cliOk = checks.at(-1).status === 'pass';

  if (cliOk && registry) {
    const who = readEvidence(dir, 'whoami');
    const w = parseJsonOut(who);
    if (who == null) add('login', 'skipped', '还没有检查', howTo('whoami'));
    else if (w?.handle) add('login', 'pass', `已登录为 ${w.handle}（${registry} 可访问）`);
    else if (/ECONNREFUSED|ETIMEDOUT|ENOTFOUND|fetch failed|network/i.test(who)) add('login', 'fail', `连不上 Hub：${who.slice(0, 120)}`, '确认和 Hub 在同一网络、地址没变（局域网 IP 可能会变，问 Hub 管理员）');
    else add('login', 'fail', '未登录或登录已过期', `skillhub login --registry ${registry}（设备码登录：用户在浏览器里确认，不经过 Agent）`);

    const listText = readEvidence(dir, 'list');
    const items = parseJsonOut(listText)?.items;
    const wanted = membersForRole(suite, role);
    if (listText == null) add('infra', 'skipped', '还没有检查', howTo('list'));
    else if (!Array.isArray(items)) add('infra', 'warn', `skillhub list 的输出读不懂：${listText.slice(0, 120)}`);
    else {
      const have = new Map(items.filter((i) => i.status !== 'missing' && (!i.agent || i.agent === agent)).map((i) => [`${i.namespace}/${i.slug}`, i.version]));
      const absent = [];
      const old = [];
      for (const m of wanted) {
        const c = parseCoordinate(m.skill);
        const v = have.get(`${c.namespace}/${c.slug}`);
        if (!v) absent.push(m.skill);
        else if (v !== m.version) old.push(`${m.skill} ${v}→${m.version}`);
      }
      if (absent.length) add('infra', 'fail', `缺 ${absent.length}/${wanted.length} 个：${absent.join(', ')}`, '按 `starter.mjs plan` 的命令安装');
      else if (old.length) add('infra', 'warn', `版本与套件不一致：${old.join(', ')}`, '逐个 skillhub upgrade <坐标> --check 后再升级');
      else add('infra', 'pass', `${wanted.length} 个基建 Skill 都已装（${agent}）`);
    }
  }

  if (role === 'author' || role === 'admin') {
    const git = readEvidence(dir, 'git');
    if (git == null) add('git', 'skipped', '还没有检查', howTo('git'));
    else add('git', /^git version/.test(git) ? 'pass' : 'fail', git.split('\n')[0] || 'git 不在 PATH 上', /^git version/.test(git) ? undefined : '作者要用 git 向源码仓库提 PR，请用户安装 Git');
    const repoDir = profile.repo_dir;
    if (!repoDir) add('repo', 'warn', '还没有记录源码仓库的本地目录', '克隆后 profile set repo_dir=<目录>');
    else add('repo', fs.existsSync(path.join(repoDir, 'skills')) ? 'pass' : 'fail', repoDir);
  }

  add('profile', fs.existsSync(profilePath()) ? 'pass' : 'warn', profilePath(), fs.existsSync(profilePath()) ? undefined : '用户确认 Hub 地址和角色后 profile set');
  const failed = checks.filter((c) => c.status === 'fail').length;
  const skipped = checks.filter((c) => c.status === 'skipped').length;
  return { ok: failed === 0 && skipped === 0, role, agent, registry, evidence: dir, suite: `@${suite.metadata.namespace}/${suite.metadata.slug}@${suite.metadata.version}`, checks };
}

export function plan(opts) {
  const suite = loadSuite();
  const profile = readProfile();
  const role = opts.role ?? profile.role ?? null;
  const agent = opts.agent ?? profile.agent ?? 'claude-code';
  const scope = opts.scope ?? 'user';
  const { registry } = resolveRegistry(opts.registry);
  const reg = registry ?? '<registry>';
  const coord = `@${suite.metadata.namespace}/${suite.metadata.slug}`;
  const common = ['--scope', scope, '--agent', agent, '--registry', reg, '--json'];
  return {
    registry,
    role,
    suite: { coordinate: coord, version: suite.metadata.version, command: ['skillhub', 'suite', 'install', coord, '--version', suite.metadata.version, ...common] },
    // Fallback when the server has no suite yet or the user only needs the members for their role.
    members: membersForRole(suite, role).map((m) => {
      const c = parseCoordinate(m.skill);
      return { skill: m.skill, version: m.version, stage: m.stage, command: ['skillhub', 'install', `@${c.namespace}/${c.slug}`, '--version', m.version, ...common] };
    }),
  };
}

function args(argv) {
  const o = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--json') o.json = true;
    else if (['--registry', '--agent', '--role', '--scope', '--evidence'].includes(a)) {
      const v = argv[i + 1];
      if (v === undefined || v.startsWith('--')) throw new Error(`${a} needs a value`);
      o[a.slice(2)] = v;
      i += 1;
    } else o._.push(a);
  }
  if (o.role && !ROLES.includes(o.role)) throw new Error(`--role must be one of ${ROLES.join(', ')}`);
  if (o.scope && !['user', 'project'].includes(o.scope)) throw new Error('--scope must be user or project');
  return o;
}

const MARK = { pass: 'ok  ', warn: 'warn', fail: 'FAIL', skipped: 'skip' };

async function main(argv) {
  const [cmd, ...rest] = argv;
  const o = args(rest);
  if (cmd === 'doctor') {
    const r = doctor(o);
    if (o.json) console.log(JSON.stringify(r, null, 2));
    else {
      console.log(`suite ${r.suite}  role ${r.role ?? '(未定)'}  agent ${r.agent}`);
      for (const c of r.checks) console.log(`${MARK[c.status]} ${c.id.padEnd(10)} ${c.detail}${c.next ? `\n           next: ${c.next}` : ''}`);
      if (r.checks.some((c) => c.status === 'skipped')) console.log(`\n把 next 里的命令依次跑一遍（输出存到 ${r.evidence}），再跑 doctor。`);
    }
    return r.ok ? 0 : 1;
  }
  if (cmd === 'plan') {
    const p = plan(o);
    if (o.json) console.log(JSON.stringify(p, null, 2));
    else {
      if (!p.registry) console.log('# 还没有 Hub 地址：先问用户，再用 --registry 传入');
      console.log(`# 首选：一次装齐套件 ${p.suite.coordinate}@${p.suite.version}`);
      console.log(p.suite.command.join(' '));
      console.log(`# 服务端没有这个套件时，逐个装（角色 ${p.role ?? '全部'}）：`);
      for (const m of p.members) console.log(`${m.command.join(' ')}    # ${m.stage}`);
    }
    return 0;
  }
  if (cmd === 'profile') {
    const [sub, ...pairs] = o._;
    if (!sub || sub === 'show') { console.log(JSON.stringify({ path: profilePath(), ...readProfile() }, null, 2)); return 0; }
    if (sub === 'set') {
      const updates = {};
      for (const p of pairs) {
        const i = p.indexOf('=');
        if (i < 1) throw new Error(`expected key=value, got ${p}`);
        updates[p.slice(0, i)] = p.slice(i + 1);
      }
      console.log(JSON.stringify(writeProfile(updates), null, 2));
      return 0;
    }
  }
  console.error('usage: starter.mjs doctor|plan [--registry url] [--agent a] [--role author|user|admin] [--json] | profile [show|set k=v ...]');
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then((code) => process.exit(code), (err) => { console.error(err.message); process.exit(1); });
}
