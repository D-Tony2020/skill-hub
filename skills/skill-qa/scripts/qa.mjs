#!/usr/bin/env node
// skill-qa: checks a skill folder against the distributable-skill spec and writes QA_REPORT.md.
// No dependencies, Node >= 18, runs on Windows, macOS and Linux.
//
//   node qa.mjs check  <skill-dir> [--json]                 static gates only
//   node qa.mjs review-template <skill-dir>                  prints the review.json the agent fills in
//   node qa.mjs report <skill-dir> --review <review.json>    all gates, verdict, writes <skill-dir>/QA_REPORT.md
//   node qa.mjs status <skill-dir> [--json]                  is there a current passing report?
//
// The script does the checks a program can do. The agent supplies what needs judgement
// (rubric scores, eval results from skill-creator, confirmation of requires) in review.json.
// The verdict is computed here, not by the agent.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

export const QA_VERSION = '0.1.0';
export const REPORT_FILE = 'QA_REPORT.md';
export const EXCEPTIONS_FILE = 'qa-exceptions.json';

// Proposed thresholds from the spec; Dean has not confirmed them yet.
export const THRESHOLDS = { taskPass: 0.8, triggerHit: 0.9, falseTrigger: 0.1, rubricTotal: 8, minTasks: 3, minNegatives: 3, maxLines: 500 };

const WALK_SKIP = new Set(['.git', 'node_modules', '__pycache__', '.DS_Store', '.venv', 'venv', '.hub-source.json', '.pytest_cache']);
// Development material that does not ship in a package.
const PACKAGE_EXCLUDES = new Set(['hub.yaml', 'tests', 'evals', '.gitattributes', REPORT_FILE, EXCEPTIONS_FILE]);
// Left out of the content hash: the report itself, and hub.yaml, which `hub import` writes.
const HASH_EXCLUDES = new Set([REPORT_FILE, 'hub.yaml']);
const TEXT_EXT = /\.(md|txt|sh|bash|zsh|ps1|psm1|py|js|mjs|cjs|ts|json|ya?ml|toml|cmd|bat|html|css|xml|csv|ini|cfg|conf)$/i;
const KNOWN_FRONTMATTER = new Set([
  'name', 'description', 'license', 'allowed-tools', 'metadata', 'compatibility',
  'when_to_use', 'argument-hint', 'disable-model-invocation', 'user-invocable',
  'model', 'effort', 'context', 'agent', 'hooks', 'paths', 'shell',
]);
const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/;
const MB = 1024 * 1024;

// ---------------------------------------------------------------------------
// Minimal YAML subset: enough for SKILL.md frontmatter and hub.yaml
// (scalars, quoted strings, | and > blocks, nested maps, - lists, [a, b] lists).

function unquote(v) {
  if (v.startsWith('"') && v.endsWith('"') && v.length >= 2) {
    return v.slice(1, -1).replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }
  if (v.startsWith("'") && v.endsWith("'") && v.length >= 2) return v.slice(1, -1).replace(/''/g, "'");
  return v;
}

function scalar(raw) {
  let v = raw.trim();
  if (!v.startsWith('"') && !v.startsWith("'")) v = v.replace(/\s+#.*$/, '');
  if (v.startsWith('[') && v.endsWith(']')) {
    const inner = v.slice(1, -1).trim();
    return inner ? inner.split(',').map((s) => scalar(s)) : [];
  }
  if (v === 'true') return true;
  if (v === 'false') return false;
  if (v === 'null' || v === '~' || v === '') return v === '' ? '' : null;
  if (/^-?\d+$/.test(v)) return Number(v);
  return unquote(v);
}

export function parseYamlSubset(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  const indentOf = (l) => l.match(/^ */)[0].length;
  const skippable = (l) => /^\s*(#.*)?$/.test(l);

  function block(style, parentIndent) {
    const out = [];
    let ind = null;
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === '') { out.push(''); i += 1; continue; }
      const n = indentOf(l);
      if (n <= parentIndent) break;
      if (ind === null) ind = n;
      out.push(l.slice(Math.min(ind, n)));
      i += 1;
    }
    while (out.length && out[out.length - 1] === '') out.pop();
    if (style.startsWith('|')) return out.join('\n');
    return out.reduce((acc, l) => (l === '' ? `${acc}\n` : acc && !acc.endsWith('\n') ? `${acc} ${l}` : acc + l), '');
  }

  function node(indent) {
    while (i < lines.length && skippable(lines[i])) i += 1;
    if (i >= lines.length) return null;
    const first = lines[i];
    if (indentOf(first) < indent) return null;
    const ind = indentOf(first);
    if (first.trim().startsWith('- ') || first.trim() === '-') {
      const arr = [];
      while (i < lines.length) {
        if (skippable(lines[i])) { i += 1; continue; }
        const l = lines[i];
        if (indentOf(l) !== ind || !(l.trim().startsWith('- ') || l.trim() === '-')) break;
        const rest = l.trim().slice(1).trim();
        i += 1;
        if (rest === '') arr.push(node(ind + 1));
        else if (/^[^'"[\]{}#][^:]*:(\s|$)/.test(rest)) {
          // "- key: value" item: re-read it as a map indented past the dash
          lines[i - 1] = `${' '.repeat(ind + 2)}${rest}`;
          i -= 1;
          arr.push(node(ind + 2));
        } else arr.push(scalar(rest));
      }
      return arr;
    }
    const obj = {};
    while (i < lines.length) {
      if (skippable(lines[i])) { i += 1; continue; }
      const l = lines[i];
      const n = indentOf(l);
      if (n < ind) break;
      if (n > ind) throw new Error(`unexpected indentation at line ${i + 1}`);
      const m = l.match(/^\s*("[^"]*"|'[^']*'|[^:#][^:]*?)\s*:(?:\s+(.*))?$/);
      if (!m) throw new Error(`cannot read line ${i + 1}: ${l.trim()}`);
      const key = unquote(m[1].trim());
      const rest = (m[2] ?? '').trim();
      i += 1;
      if (/^[|>][+-]?$/.test(rest)) obj[key] = block(rest, ind);
      else if (rest === '' || rest.startsWith('#')) obj[key] = node(ind + 1);
      else obj[key] = scalar(rest);
    }
    return obj;
  }

  const result = node(0);
  return result ?? {};
}

export function parseFrontmatter(text) {
  const normalized = text.replace(/^﻿/, '').replace(/\r\n/g, '\n');
  const match = normalized.match(/^---\n([\s\S]*?)\n---(\n|$)/);
  if (!match) return { error: 'SKILL.md 开头没有 --- frontmatter 块' };
  try {
    const data = parseYamlSubset(match[1]);
    if (data === null || typeof data !== 'object' || Array.isArray(data)) return { error: 'frontmatter 不是键值映射' };
    return { data, body: normalized.slice(match[0].length), bodyStartLine: match[0].split('\n').length };
  } catch (err) {
    return { error: `frontmatter 无法解析：${err.message}` };
  }
}

// ---------------------------------------------------------------------------
// Files and hashing

export function walkFiles(dir) {
  const out = [];
  const walk = (rel) => {
    for (const e of fs.readdirSync(path.join(dir, rel), { withFileTypes: true })) {
      if (WALK_SKIP.has(e.name)) continue;
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) walk(r);
      else if (e.isFile()) out.push(r);
    }
  };
  walk('');
  return out.sort();
}

export function packageFilesOf(dir) {
  return walkFiles(dir).filter((r) => !PACKAGE_EXCLUDES.has(r.split('/')[0]));
}

// Content hash of everything the report vouches for. Text files are hashed with LF line
// endings so a Windows checkout and a Linux checkout of the same skill give the same hash.
export function contentHash(dir) {
  const h = crypto.createHash('sha256');
  for (const rel of walkFiles(dir)) {
    if (HASH_EXCLUDES.has(rel)) continue;
    let buf = fs.readFileSync(path.join(dir, rel));
    if (TEXT_EXT.test(rel) || rel === 'SKILL.md') buf = Buffer.from(buf.toString('utf8').replace(/\r\n/g, '\n'));
    h.update(rel).update('\0').update(buf).update('\0');
  }
  return h.digest('hex');
}

function readText(file) {
  try { return fs.readFileSync(file, 'utf8'); } catch { return null; }
}

function readJson(file) {
  const t = readText(file);
  if (t === null) return { missing: true };
  try { return { data: JSON.parse(t.replace(/^﻿/, '')) }; } catch (e) { return { error: e.message }; }
}

// ---------------------------------------------------------------------------
// Loading

export function loadSkill(dir) {
  const abs = path.resolve(dir);
  const s = { dir: abs, dirName: path.basename(abs), errors: [], frontmatter: null, body: '', hub: null, version: null, versionSource: null };
  const md = readText(path.join(abs, 'SKILL.md'));
  if (md === null) { s.errors.push('缺少 SKILL.md'); return s; }
  s.skillMd = md;
  const fm = parseFrontmatter(md);
  if (fm.error) s.errors.push(fm.error);
  else { s.frontmatter = fm.data; s.body = fm.body; }
  const hubText = readText(path.join(abs, 'hub.yaml'));
  if (hubText !== null) {
    try { s.hub = parseYamlSubset(hubText) ?? {}; } catch (e) { s.errors.push(`hub.yaml 无法解析：${e.message}`); }
  }
  const vf = readText(path.join(abs, 'VERSION'));
  if (vf !== null && vf.trim()) { s.version = vf.trim(); s.versionSource = 'VERSION'; }
  else if (s.hub?.version != null) { s.version = String(s.hub.version); s.versionSource = 'hub.yaml'; }
  else if (s.frontmatter?.metadata?.version != null) { s.version = String(s.frontmatter.metadata.version); s.versionSource = 'metadata.version'; }
  s.name = typeof s.frontmatter?.name === 'string' ? s.frontmatter.name : s.dirName;
  s.requires = (s.hub?.requires && typeof s.hub.requires === 'object' && !Array.isArray(s.hub.requires)) ? s.hub.requires : null;
  return s;
}

function loadExceptions(dir) {
  const r = readJson(path.join(dir, EXCEPTIONS_FILE));
  if (r.missing) return { list: [], problems: [] };
  if (r.error || !Array.isArray(r.data)) return { list: [], problems: [`${EXCEPTIONS_FILE} 不是 JSON 数组：${r.error ?? '格式不对'}`] };
  const list = [];
  const problems = [];
  r.data.forEach((e, idx) => {
    if (!e || !e.gate || !e.reason || !e.approved_by) {
      problems.push(`${EXCEPTIONS_FILE} 第 ${idx + 1} 条缺少 gate / reason / approved_by，未生效`);
    } else if (!EXCEPTABLE.has(e.gate)) {
      problems.push(`${EXCEPTIONS_FILE} 第 ${idx + 1} 条：${e.gate} 不允许豁免`);
    } else list.push(e);
  });
  return { list, problems };
}

// Gates where a finding may be required behaviour. Secrets, evals and the rubric can never be excepted.
const EXCEPTABLE = new Set(['G3', 'G12', 'G13', 'G14', 'S1', 'S2', 'SCAN']);

function excepted(exceptions, gate, finding) {
  return exceptions.find((e) => e.gate === gate
    && (!e.file || e.file === finding.file)
    && (!e.rule || e.rule === finding.rule)
    && (!e.match || (finding.text ?? '').includes(e.match)));
}

// ---------------------------------------------------------------------------
// Pattern scans

const SECRET_PATTERNS = [
  ['私钥', /-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----/],
  ['Anthropic API key', /sk-ant-[A-Za-z0-9_-]{20,}/],
  ['OpenAI 风格 key', /\bsk-[A-Za-z0-9]{32,}\b/],
  ['GitHub token', /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|github_pat_[A-Za-z0-9_]{40,}/],
  ['GitLab token', /\bglpat-[A-Za-z0-9_-]{20,}\b/],
  ['AWS access key', /\bAKIA[0-9A-Z]{16}\b/],
  ['Slack token', /\bxox[abposr]-[A-Za-z0-9-]{10,}\b/],
  ['飞书/Lark app secret', /\b(?:app_secret|appSecret)\s*[:=]\s*["']?[A-Za-z0-9]{24,}/],
  ['写死的密码', /\b(?:password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*["'][^"'\s$%{}<>]{8,}["']/i],
];
const INTRANET_PATTERNS = [
  ['内网 IP', /\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b/],
  ['内网域名', /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:corp|internal|intranet|lan)\b/i],
];
// Documentation ranges and obvious placeholders are fine.
// Values in test fixtures that are clearly made up.
const FAKE_VALUE = /test|fake|dummy|wrong|sample|example|ABCDEFGH|abcdefgh|0123456|1234567|(.)\1{5}/i;
const PLACEHOLDER = /(?:x{2,}|\bexample\b|<[^>]+>|\.\.\.|your[_-]|placeholder|1\.2\.3\.4|172\.20\.10\.x|192\.168\.43\.x)/i;

const DOWNLOAD_EXEC = /\b(?:curl|wget|iwr|Invoke-WebRequest)\b[^\n]*(?:\|\s*(?:sudo\s+)?(?:ba|z)?sh\b|&&\s*(?:sudo\s+)?(?:ba|z)?sh\s|\|\s*iex\b|;\s*(?:sudo\s+)?bash\s)/i;
const HASH_CHECK = /(?:sha256sum|shasum\s+-a\s+256|Get-FileHash|openssl\s+dgst)[^\n]*(?:-c|--check|-eq|==)/i;
const DESTRUCTIVE = /\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(?:\/(?:\s|$)|~\/?(?:\s|$)|\$HOME\/?(?:\s|$)|\/\*)|\bchmod\s+(?:-R\s+)?777\b|\bmkfs\b|\bdd\s+if=.*of=\/dev\//;
const ELEVATION = /\bsudo\b|\bchown\s+root|\bRunAs\b|-Verb\s+RunAs/;

function scanLines(dir, files, fn) {
  for (const rel of files) {
    if (!TEXT_EXT.test(rel) && rel !== 'SKILL.md' && !/(^|\/)[A-Za-z0-9_-]+$/.test(rel)) continue;
    const t = readText(path.join(dir, rel));
    if (t === null || t.includes('\0')) continue;
    t.split(/\r?\n/).forEach((line, i) => fn(rel, i + 1, line));
  }
}

function loadRedactWords() {
  const words = [];
  for (const f of [path.join(os.homedir(), '.skill-qa', 'redact.txt'), path.join(os.homedir(), '.session-distiller', 'redact.txt')]) {
    const t = readText(f);
    if (t) for (const w of t.split(/\r?\n/)) { const s = w.trim(); if (s && !s.startsWith('#')) words.push(s); }
  }
  return [...new Set(words)];
}

// ---------------------------------------------------------------------------
// Static gates

const SKILL_PATH_RE = /(?:~|\$HOME|\$\{HOME\}|%USERPROFILE%|\$env:USERPROFILE|[A-Za-z]:\\Users\\[^\\\s"'`]+|\/(?:home|Users)\/[^/\s"'`]+)[\\/]+\.claude[\\/]+skills(?:[\\/]+[A-Za-z0-9_.-]+)?/g;
const REF_RE = /(?<![\w.-])(scripts|references|assets|templates)[\\/]([\w.\-\\/]*\.[A-Za-z0-9]+)/g;
const KNOWN_COMMANDS = ['git', 'gh', 'glab', 'curl', 'wget', 'jq', 'docker', 'kubectl', 'python', 'python3', 'pip', 'node', 'npm', 'npx', 'pnpm', 'uv', 'java', 'mvn', 'go', 'ssh', 'scp', 'rsync', 'openssl', 'ffmpeg', 'pandoc', 'drawio', 'draw.io', 'lark-cli', 'feishu', 'psql', 'mysql', 'redis-cli', 'az', 'aws', 'gcloud', 'terraform', 'ansible', 'powershell', 'pwsh', 'skillhub'];

function gate(id, title, level, status, detail = '', findings = []) {
  return { id, title, level, status, detail, findings };
}

export function staticChecks(dir) {
  const s = loadSkill(dir);
  const all = fs.existsSync(s.dir) ? walkFiles(s.dir) : [];
  const pkg = all.filter((r) => !PACKAGE_EXCLUDES.has(r.split('/')[0]));
  const { list: exceptions, problems: exceptionProblems } = loadExceptions(s.dir);
  const gates = [];
  const fm = s.frontmatter;

  // G1 structure and frontmatter
  {
    const errs = [...s.errors];
    if (fm) {
      const { name, description } = fm;
      if (typeof name !== 'string' || !name) errs.push('frontmatter 缺少 name');
      else {
        if (name !== s.dirName) errs.push(`name "${name}" 与目录名 "${s.dirName}" 不一致`);
        if (!NAME_RE.test(name)) errs.push(`name "${name}" 只能用小写字母、数字和单个短横线`);
        if (name.length > 64) errs.push(`name 有 ${name.length} 个字符，上限 64`);
        if (/anthropic|claude/.test(name)) errs.push('name 不能包含保留词 anthropic 或 claude');
      }
      if (typeof description !== 'string' || !description.trim()) errs.push('frontmatter 缺少 description');
      else {
        if (description.length > 1024) errs.push(`description 有 ${description.length} 个字符，上限 1024`);
        if (/[<>]/.test(description)) errs.push('description 不能含 < 或 >（上传时会被拒）');
      }
    }
    if (!s.version) errs.push('没有版本号：写在 VERSION、hub.yaml 的 version 或 metadata.version 之一');
    else if (!SEMVER_RE.test(s.version)) errs.push(`版本 "${s.version}" 不是 semver（x.y.z）`);
    if (fs.existsSync(path.join(s.dir, 'VERSION')) && s.hub?.version != null && String(s.hub.version) !== s.version) {
      errs.push(`hub.yaml version ${s.hub.version} 与 VERSION ${s.version} 不一致`);
    }
    gates.push(gate('G1', '结构与 frontmatter 合规（agentskills 规范 + Claude 限制）', 'block', errs.length ? 'fail' : 'pass', errs.join('；')));
  }

  // G2 referenced files exist
  const refsMissing = [];
  if (s.skillMd) {
    const refs = new Set();
    for (const m of s.skillMd.matchAll(REF_RE)) refs.add(`${m[1]}/${m[2].replace(/\\/g, '/')}`);
    for (const r of [...refs].sort()) if (!fs.existsSync(path.join(s.dir, r))) refsMissing.push(r);
  }
  {
    const depSkills = Array.isArray(s.requires?.skills) ? s.requires.skills : [];
    let status = 'pass';
    let detail = '';
    if (refsMissing.length && depSkills.length) {
      status = 'review';
      detail = `缺 ${refsMissing.join(', ')}；需确认它们都属于 requires.skills（${depSkills.join(', ')}）`;
    } else if (refsMissing.length) {
      status = 'fail';
      detail = `SKILL.md 提到但目录里没有：${refsMissing.join(', ')}`;
    }
    gates.push(gate('G2', 'SKILL.md 提到的文件都在，或属于已声明的依赖 Skill', 'block', status, detail));
  }

  // G3 hardcoded own install path
  {
    const hits = [];
    scanLines(s.dir, pkg, (file, line, text) => {
      for (const m of text.matchAll(SKILL_PATH_RE)) {
        if (m[0].split(/[\\/]+/).pop() === s.dirName) hits.push({ file, line, text: m[0] });
      }
    });
    gates.push(withExceptions(gate('G3', '不写死自己的安装路径', 'block', 'pass'), hits, exceptions,
      (h) => `${h.file}:${h.line} 写死了 ${h.text}；改为以 SKILL.md 所在目录为基准`));
  }

  // G4 dependencies declared (candidates; the agent confirms)
  {
    const declared = new Set((Array.isArray(s.requires?.commands) ? s.requires.commands : []).map(String));
    const used = new Set();
    scanLines(s.dir, pkg.filter((r) => r.startsWith('scripts/') || r === 'SKILL.md'), (file, line, text) => {
      for (const c of KNOWN_COMMANDS) {
        const re = new RegExp(`(?:^|[\\s;&|(\`$])${c.replace('.', '\\.')}(?=\\s)`);
        if (re.test(text)) used.add(c);
      }
    });
    const undeclared = [...used].filter((c) => !declared.has(c) && !['git', 'python', 'python3', 'node'].includes(c)).sort();
    const detail = [
      s.requires ? `已声明：${JSON.stringify(s.requires)}` : '没有 requires（hub.yaml）',
      undeclared.length ? `脚本里用到但未声明的命令候选：${undeclared.join(', ')}` : '',
    ].filter(Boolean).join('；');
    gates.push(gate('G4', '依赖（Skill、命令、环境变量）全部写进 requires', 'block', 'review', detail));
  }

  // G5 eval cases exist
  let evalCounts = { tasks: 0, negatives: 0, positives: 0 };
  {
    const problems = [];
    const ev = readJson(path.join(s.dir, 'evals', 'evals.json'));
    if (ev.error) problems.push(`evals/evals.json 不是合法 JSON：${ev.error}`);
    const list = ev.data ? (Array.isArray(ev.data) ? ev.data : ev.data.evals ?? []) : [];
    for (const e of list) {
      if (e?.should_trigger === false) evalCounts.negatives += 1;
      else if (e?.prompt) evalCounts.tasks += 1;
    }
    const tr = readJson(path.join(s.dir, 'evals', 'trigger-evals.json'));
    if (tr.error) problems.push(`evals/trigger-evals.json 不是合法 JSON：${tr.error}`);
    for (const q of Array.isArray(tr.data) ? tr.data : []) {
      if (q?.should_trigger === false) evalCounts.negatives += 1;
      else if (q?.should_trigger === true) evalCounts.positives += 1;
    }
    const ok = evalCounts.tasks >= THRESHOLDS.minTasks && evalCounts.negatives >= THRESHOLDS.minNegatives && !problems.length;
    const detail = `任务用例 ${evalCounts.tasks} 条（要求 ≥ ${THRESHOLDS.minTasks}），不该触发用例 ${evalCounts.negatives} 条（要求 ≥ ${THRESHOLDS.minNegatives}），该触发用例 ${evalCounts.positives} 条${problems.length ? `；${problems.join('；')}` : ''}`;
    gates.push(gate('G5', `evals 至少 ${THRESHOLDS.minTasks} 条任务用例 + ${THRESHOLDS.minNegatives} 条不该触发用例`, 'block', ok ? 'pass' : 'fail', detail));
  }

  // G6-G8 need review.json; placeholders filled in by applyReview
  gates.push(gate('G6', `任务评测通过率 ≥ ${pct(THRESHOLDS.taskPass)}，且不低于不装 Skill 的基线`, 'block', 'pending', '需要 skill-creator 评测结果'));
  gates.push(gate('G7', `触发评测：该触发的 ≥ ${pct(THRESHOLDS.triggerHit)}，误触发 ≤ ${pct(THRESHOLDS.falseTrigger)}`, 'block', 'pending', '需要 skill-creator 触发评测结果'));
  gates.push(gate('G8', `评分表总分 ≥ ${THRESHOLDS.rubricTotal}/10，且“安全”不为 0`, 'block', 'pending', '需要 Agent 按 references/rubric.md 打分'));

  // G9 install smoke: package copy is self-contained
  {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-qa-'));
    const target = path.join(tmp, s.dirName);
    let broken = [];
    const droppedButRead = [];
    try {
      for (const rel of pkg) {
        fs.mkdirSync(path.dirname(path.join(target, rel)), { recursive: true });
        fs.copyFileSync(path.join(s.dir, rel), path.join(target, rel));
      }
      const refs = new Set();
      for (const m of (s.skillMd ?? '').matchAll(REF_RE)) refs.add(`${m[1]}/${m[2].replace(/\\/g, '/')}`);
      broken = [...refs].filter((r) => fs.existsSync(path.join(s.dir, r)) && !fs.existsSync(path.join(target, r)));
      // Files SkillHub drops (no extension) that SKILL.md or scripts read.
      const dropped = pkg.filter((r) => r !== 'SKILL.md' && !/\.[A-Za-z0-9]+$/.test(r.split('/').pop()));
      for (const d of dropped) {
        const base = d.split('/').pop();
        let used = false;
        scanLines(s.dir, pkg.filter((r) => r.startsWith('scripts/') || r === 'SKILL.md'), (f, l, text) => { if (text.includes(base)) used = true; });
        if (used) droppedButRead.push(d);
      }
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
    const dropNote = droppedButRead.length
      ? `；${droppedButRead.join('、')} 没有扩展名，SkillHub 打包会去掉，而脚本或 SKILL.md 读取了它：冒烟必须在去掉这些文件的副本上跑，确认有回退（不允许靠删文件过关）`
      : '';
    gates.push(gate('G9', '干净目录安装后可用（打包副本自包含 + 跑通一条评测）', 'block',
      broken.length ? 'fail' : 'pending',
      broken.length ? `安装副本缺：${broken.join('；')}${dropNote}` : `打包 ${pkg.length} 个文件，引用完整；还需在安装副本上跑一条评测${dropNote}`));
  }

  // G10 changelog entry
  {
    const cl = readText(path.join(s.dir, 'CHANGELOG.md'));
    let status = 'fail';
    let detail = '没有 CHANGELOG.md';
    if (cl !== null) {
      if (!s.version) detail = '没有版本号，无法核对';
      else {
        const lines = cl.replace(/\r\n/g, '\n').split('\n');
        const idx = lines.findIndex((l) => /^#{1,3}\s/.test(l) && l.includes(s.version));
        if (idx < 0) detail = `CHANGELOG.md 里没有 ${s.version} 的条目`;
        else {
          const rest = [];
          for (let k = idx + 1; k < lines.length && !/^#{1,3}\s/.test(lines[k]); k += 1) if (lines[k].trim()) rest.push(lines[k]);
          if (!rest.length || rest.every((l) => /TODO|待补|tbd/i.test(l))) detail = `${s.version} 的条目是空的`;
          else { status = 'pass'; detail = ''; }
        }
      }
    }
    gates.push(gate('G10', '本版本的 CHANGELOG 条目写了实际内容', 'block', status, detail));
  }

  // G11 secrets, intranet addresses, customer names
  {
    const hits = [];
    const words = loadRedactWords();
    const fixtures = [];
    scanLines(s.dir, all.filter((r) => r !== REPORT_FILE), (file, line, text) => {
      // tests/ and evals/ never ship; obviously fake fixtures there are fine, anything else is still reported.
      const devOnly = PACKAGE_EXCLUDES.has(file.split('/')[0]);
      for (const [kind, re] of SECRET_PATTERNS) {
        const m = text.match(re);
        if (!m || PLACEHOLDER.test(m[0])) continue;
        if (devOnly && (FAKE_VALUE.test(m[0]) || kind === '私钥')) fixtures.push(`${file}:${line}`);
        else hits.push({ file, line, text: `${kind}` });
      }
      for (const [kind, re] of INTRANET_PATTERNS) {
        const m = text.match(re);
        if (!m || PLACEHOLDER.test(text.slice(Math.max(0, m.index - 20), m.index + m[0].length + 20))) continue;
        if (devOnly) fixtures.push(`${file}:${line}`);
        else hits.push({ file, line, text: `${kind} ${m[0]}` });
      }
      for (const w of words) if (text.includes(w)) hits.push({ file, line, text: '客户名（redact.txt）' });
    });
    const notes = [];
    if (hits.length) notes.push(hits.slice(0, 20).map((h) => `${h.file}:${h.line} ${h.text}`).join('；') + (hits.length > 20 ? ` 等共 ${hits.length} 处` : ''));
    if (fixtures.length) notes.push(`测试/评测夹具里有 ${fixtures.length} 处像密钥或内网地址的假值（${fixtures.slice(0, 5).join('、')}${fixtures.length > 5 ? ' 等' : ''}），不进发布包；Agent 需确认都是假的`);
    notes.push(words.length ? `已按 ${words.length} 个客户名脱敏词检查` : '未配置客户名脱敏词（~/.skill-qa/redact.txt）');
    gates.push(gate('G11', '不含密钥、内网地址、客户名', 'block', hits.length ? 'fail' : 'pass', notes.join('；'), hits));
  }

  // G12 scripts have tests
  {
    const scripts = pkg.filter((r) => r.startsWith('scripts/') && /\.(sh|py|js|mjs|cjs|ts|ps1)$/.test(r));
    const tests = all.filter((r) => r.startsWith('tests/') || /(^|\/)test_[^/]+\.py$|\.test\.(m?js|ts)$/.test(r));
    const f = scripts.length && !tests.length ? [{ file: 'scripts/', text: `${scripts.length} 个脚本没有测试` }] : [];
    gates.push(withExceptions(gate('G12', '脚本有单元测试', 'warn', 'pass', scripts.length ? `${scripts.length} 个脚本，${tests.length} 个测试文件` : '没有脚本'), f, exceptions, (h) => h.text));
  }

  // G13 SKILL.md length
  {
    const n = (s.skillMd ?? '').split(/\r?\n/).length;
    const f = n > THRESHOLDS.maxLines ? [{ file: 'SKILL.md', text: `${n} 行` }] : [];
    gates.push(withExceptions(gate('G13', `SKILL.md 不超过 ${THRESHOLDS.maxLines} 行`, 'warn', 'pass', `${n} 行`), f, exceptions, (h) => `SKILL.md 有 ${h.text}，细节下沉到 references/`));
  }

  // G14 unknown frontmatter keys, extensionless files
  {
    const f = [];
    for (const k of Object.keys(fm ?? {})) if (!KNOWN_FRONTMATTER.has(k)) f.push({ file: 'SKILL.md', text: `frontmatter 字段 ${k} 不在文档列出的字段内，Hub 元数据请放 hub.yaml` });
    for (const r of pkg) if (r !== 'SKILL.md' && !/\.[A-Za-z0-9]+$/.test(r.split('/').pop())) f.push({ file: r, text: `${r} 没有扩展名，SkillHub 打包时会去掉` });
    gates.push(withExceptions(gate('G14', '没有未知 frontmatter 字段和无扩展名文件', 'warn', 'pass'), f, exceptions, (h) => h.text));
  }

  // S1 dangerous execution patterns
  {
    const f = [];
    const elev = [];
    scanLines(s.dir, pkg, (file, line, text) => {
      if (DOWNLOAD_EXEC.test(text) && !HASH_CHECK.test(text)) f.push({ file, line, text: '下载后直接执行，执行前没有核对哈希' });
      if (DESTRUCTIVE.test(text)) f.push({ file, line, text: '高危删除或权限放开' });
      if (file.startsWith('scripts/') && ELEVATION.test(text)) elev.push(`${file}:${line}`);
    });
    const g = withExceptions(gate('S1', '没有“下载即执行”、高危删除等危险操作', 'block', 'pass'), f, exceptions, (h) => `${h.file}:${h.line} ${h.text}`);
    if (elev.length) g.detail = [g.detail, `提权操作 ${elev.length} 处（${elev.slice(0, 6).join('、')}${elev.length > 6 ? ' 等' : ''}），评分“安全”项需说明理由；SkillHub 扫描可能判为 CRITICAL，必要的写进 ${EXCEPTIONS_FILE}`].filter(Boolean).join('；');
    gates.push(g);
  }

  // S2 package limits
  {
    const f = [];
    let total = 0;
    for (const r of pkg) {
      const size = fs.statSync(path.join(s.dir, r)).size;
      total += size;
      if (size > 10 * MB) f.push({ file: r, text: `${(size / MB).toFixed(1)} MB，单文件上限 10 MB` });
    }
    if (total > 100 * MB) f.push({ file: '.', text: `包共 ${(total / MB).toFixed(1)} MB，上限 100 MB` });
    if (fs.existsSync(path.join(s.dir, 'bin'))) f.push({ file: 'bin/', text: '顶层 bin/ 会被 claude.ai 组织同步拒绝，改放 scripts/' });
    gates.push(withExceptions(gate('S2', '包体积与目录限制（单文件 ≤ 10 MB，总计 ≤ 100 MB，无顶层 bin/）', 'block', 'pass', `${pkg.length} 个文件，${(total / 1024).toFixed(0)} KB`), f, exceptions, (h) => `${h.file} ${h.text}`));
  }

  // S4 security scanner (same Cisco skill-scanner SkillHub runs); filled in by applyReview
  gates.push(gate('S4', '安全扫描器（与 SkillHub 同款）的每条告警都已处置：修复，或登记为例外', 'block', 'pending', '需要扫描结果；装不了扫描器时写 scanner.available=false'));

  // R1 source repo and feedback route (Skills 工厂 rule)
  {
    const body = s.skillMd ?? '';
    const hasRepo = /https?:\/\/(?:github\.com|gitlab\.[^/\s]+|[^/\s]*git[^/\s]*)\/[^\s)]+/i.test(body) || /源码仓库|source repo/i.test(body);
    const hasFeedback = /反馈|报告问题|提 ?issue|issue|PR|自更新|update/i.test(body);
    const ok = hasRepo && hasFeedback;
    gates.push(gate('R1', 'SKILL.md 写明源码仓库，以及更新和反馈问题的方式', 'block', ok ? 'pass' : 'fail',
      ok ? '' : `${hasRepo ? '' : '没写源码仓库地址；'}${hasFeedback ? '' : '没写怎么更新或反馈问题'}`));
  }

  // S3 license
  {
    const has = fm?.license || all.some((r) => /^LICENSE(\.(md|txt))?$/i.test(r));
    gates.push(gate('S3', '写明 license（SkillHub 扫描会提示）', 'info', has ? 'pass' : 'warn', has ? '' : '在 frontmatter 加 license，例如 license: Proprietary'));
  }

  return { skill: { name: s.name, dir: s.dir, version: s.version, versionSource: s.versionSource, requires: s.requires, files: pkg.length }, gates, evalCounts, exceptions, exceptionProblems, hash: fs.existsSync(s.dir) ? contentHash(s.dir) : null };
}

function withExceptions(g, findings, exceptions, describe) {
  const open = [];
  const waived = [];
  for (const f of findings) {
    const e = excepted(exceptions, g.id, f);
    if (e) waived.push({ ...f, reason: e.reason, approved_by: e.approved_by });
    else open.push(f);
  }
  g.findings = open;
  g.waived = waived;
  if (open.length) g.status = g.level === 'block' ? 'fail' : 'warn';
  const parts = [];
  if (g.detail) parts.push(g.detail);
  if (open.length) parts.push(open.slice(0, 10).map(describe).join('；') + (open.length > 10 ? ` 等共 ${open.length} 处` : ''));
  if (waived.length) parts.push(`已豁免 ${waived.length} 处（${waived.map((w) => `${w.file}${w.line ? `:${w.line}` : ''}：${w.reason}，${w.approved_by} 确认`).join('；')}）`);
  g.detail = parts.join('；');
  return g;
}

const pct = (x) => `${Math.round(x * 100)}%`;

// ---------------------------------------------------------------------------
// Security scanner: Cisco skill-scanner, the same engine SkillHub runs on upload.
// It scans the package as SkillHub receives it (no tests/, evals/, caches, hub.yaml).

export function runScanner(dir, { bin = process.env.SKILL_SCANNER_BIN || 'skill-scanner' } = {}) {
  const s = loadSkill(dir);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-qa-scan-'));
  const target = path.join(tmp, s.dirName);
  try {
    for (const rel of packageFilesOf(s.dir)) {
      fs.mkdirSync(path.dirname(path.join(target, rel)), { recursive: true });
      fs.copyFileSync(path.join(s.dir, rel), path.join(target, rel));
    }
    const win = process.platform === 'win32';
    const res = spawnSync(bin, ['scan', target, '--format', 'json'], { encoding: 'utf8', shell: win, maxBuffer: 64 * MB });
    if (res.error || (res.status !== 0 && !res.stdout.trim().startsWith('{'))) {
      return { available: false, note: res.error ? `${bin} 不可用（pip install cisco-ai-skill-scanner）` : (res.stderr || '').trim().split('\n').slice(-1)[0] };
    }
    const out = JSON.parse(res.stdout.slice(res.stdout.indexOf('{')));
    return {
      tool: `cisco skill-scanner (${out.scan_metadata?.policy_name ?? 'default'} policy)`,
      available: true,
      verdict: out.is_safe ? 'SAFE' : `NOT SAFE, max ${out.max_severity}`,
      findings: (out.findings ?? []).map((f) => ({ rule: f.rule_id, severity: f.severity, file: f.file_path, line: f.line_number ?? null, title: f.title })),
    };
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

// The agent records how each finding was handled; merge that into fresh scan results.
function mergeScanner(scan, reviewScanner) {
  if (!scan) return reviewScanner;
  const disp = Array.isArray(reviewScanner?.dispositions) ? reviewScanner.dispositions : [];
  for (const f of scan.findings ?? []) {
    const d = disp.find((x) => x.rule === f.rule && (!x.file || x.file === f.file));
    if (d) { f.disposition = d.disposition; f.note = d.note; }
  }
  return scan;
}

// ---------------------------------------------------------------------------
// Review (agent judgement) and verdict

const RUBRIC_KEYS = [['trigger', '触发'], ['actionable', '可执行'], ['deterministic', '确定性'], ['safety', '安全'], ['portable', '可移植']];

export function reviewTemplate() {
  return {
    qa_version: QA_VERSION,
    reviewer: 'agent',
    rubric: Object.fromEntries(RUBRIC_KEYS.map(([k]) => [k, { score: null, why: '' }])),
    evals: {
      runner: 'skill-creator',
      model: '',
      tasks: { total: null, passed: null, baseline_passed: null },
      triggers: { should: { total: null, hit: null }, should_not: { total: null, hit: null } },
      smoke: { ok: null, note: '在干净目录的安装副本上跑的那条评测' },
    },
    scanner: { dispositions: [{ rule: 'RULE_ID', file: 'scripts/x.sh', disposition: 'fixed | exception', note: '' }] },
    requires_confirmed: null,
    requires_note: '',
    reject_reason: null,
    notes: [],
  };
}

function num(v) { return typeof v === 'number' && Number.isFinite(v) ? v : null; }

export function applyReview(result, review) {
  const g = Object.fromEntries(result.gates.map((x) => [x.id, x]));
  const r = review ?? {};
  const ev = r.evals ?? {};

  // G2 dependency confirmation and G4
  if (g.G2.status === 'review') {
    if (r.requires_confirmed === true) { g.G2.status = 'pass'; g.G2.detail += '；Agent 已确认'; }
    else g.G2.status = 'pending';
  }
  if (r.requires_confirmed === true) { g.G4.status = 'pass'; if (r.requires_note) g.G4.detail += `；${r.requires_note}`; }
  else if (r.requires_confirmed === false) { g.G4.status = 'fail'; g.G4.detail += `；${r.requires_note || 'Agent 判定依赖未声明全'}`; }
  else g.G4.status = 'pending';

  // G6 task evals
  const t = ev.tasks ?? {};
  const total = num(t.total);
  const passed = num(t.passed);
  const base = num(t.baseline_passed);
  if (total && passed !== null) {
    const rate = passed / total;
    const ok = rate >= THRESHOLDS.taskPass && (base === null || passed >= base);
    g.G6.status = ok ? 'pass' : 'fail';
    g.G6.detail = `${passed}/${total}（${pct(rate)}）${base !== null ? `，基线 ${base}/${total}` : '，没有基线对比'}${ev.runner ? `，${ev.runner}${ev.model ? ` / ${ev.model}` : ''}` : ''}`;
    if (base === null) { g.G6.status = ok ? 'pending' : 'fail'; g.G6.detail += '；缺基线，补跑不装 Skill 的对照'; }
  }

  // G7 triggers
  const sh = ev.triggers?.should ?? {};
  const sn = ev.triggers?.should_not ?? {};
  if (num(sh.total) && num(sh.hit) !== null && num(sn.total) && num(sn.hit) !== null) {
    const hit = sh.hit / sh.total;
    const fals = sn.hit / sn.total;
    g.G7.status = hit >= THRESHOLDS.triggerHit && fals <= THRESHOLDS.falseTrigger ? 'pass' : 'fail';
    g.G7.detail = `该触发 ${sh.hit}/${sh.total}（${pct(hit)}），误触发 ${sn.hit}/${sn.total}（${pct(fals)}）`;
  }

  // G8 rubric
  const scores = RUBRIC_KEYS.map(([k]) => num(r.rubric?.[k]?.score));
  if (scores.every((x) => x !== null)) {
    const bad = scores.find((x) => x < 0 || x > 2);
    const sum = scores.reduce((a, b) => a + b, 0);
    const safety = scores[3];
    g.G8.status = bad === undefined && sum >= THRESHOLDS.rubricTotal && safety > 0 ? 'pass' : 'fail';
    g.G8.detail = `${sum}/10（${RUBRIC_KEYS.map(([, zh], i) => `${zh} ${scores[i]}`).join('，')}）`;
  }

  // G9 smoke
  if (g.G9.status === 'pending' && ev.smoke?.ok === true) { g.G9.status = 'pass'; if (ev.smoke.note) g.G9.detail += `；${ev.smoke.note}`; }
  else if (g.G9.status === 'pending' && ev.smoke?.ok === false) { g.G9.status = 'fail'; g.G9.detail += `；${ev.smoke.note || '安装副本上的评测没通过'}`; }

  // S4 scanner findings: every MEDIUM+ finding is fixed or a registered exception
  const sc = r.scanner;
  if (sc && sc.available === false) {
    g.S4.level = 'warn';
    g.S4.status = 'warn';
    g.S4.detail = `本机没有扫描器（${sc.note || '未说明原因'}），发布到 SkillHub 时由服务端扫描兜底`;
  } else if (sc && Array.isArray(sc.findings)) {
    const serious = sc.findings.filter((f) => !/^(info|low)$/i.test(f.severity ?? ''));
    const open = [];
    const waived = [];
    for (const f of serious) {
      const finding = { file: f.file, rule: f.rule, text: f.title ?? f.rule ?? '' };
      if (f.disposition === 'fixed') continue;
      const e = excepted(result.exceptions, 'SCAN', finding);
      if (e) waived.push(`${f.severity} ${f.rule ?? ''} ${f.file ?? ''}：${e.reason}（${e.approved_by} 确认）`);
      else open.push(`${f.severity} ${f.rule ?? ''} ${f.file ?? ''}${f.line ? `:${f.line}` : ''}${f.disposition ? `（标为 ${f.disposition}，但没有登记在 ${EXCEPTIONS_FILE}）` : '（未处置）'}`);
    }
    g.S4.status = open.length ? 'fail' : 'pass';
    g.S4.detail = [`${sc.tool ?? '扫描器'}：${sc.verdict ?? ''} 共 ${sc.findings.length} 条，MEDIUM 及以上 ${serious.length} 条`,
      open.length ? `未处置：${open.join('；')}` : '',
      waived.length ? `已登记例外：${waived.join('；')}` : ''].filter(Boolean).join('；');
  }

  result.review = r;
  result.verdict = verdictOf(result);
  return result;
}

export const VERDICTS = {
  include: { zh: '可分发', next: '可以导入 skill-hub 仓库（hub import），提 PR 时附上本报告。' },
  adapt: { zh: '需修改', next: '修掉下面“未通过”的阻断项后重跑 skill-qa；不要导入。' },
  hold: { zh: '暂缓', next: '还有阻断项没有结论（多半是评测没跑），补齐后重跑；不要导入。' },
  reject: { zh: '不收录', next: '不进 Hub。原因见下；如有异议由 Dean 决定。' },
};

export function verdictOf(result) {
  const rubricSafety = num(result.review?.rubric?.safety?.score);
  if (result.review?.reject_reason || rubricSafety === 0) return 'reject';
  const blocking = result.gates.filter((g) => g.level === 'block');
  if (blocking.some((g) => g.status === 'fail')) return 'adapt';
  if (blocking.some((g) => g.status !== 'pass')) return 'hold';
  return 'include';
}

// ---------------------------------------------------------------------------
// Report

const STATUS_ZH = { pass: '通过', fail: '未通过', warn: '警告', pending: '待评测', review: '待确认', info: '提示' };
const LEVEL_ZH = { block: '阻断', warn: '警告', info: '提示' };
const cell = (s) => String(s ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');

export function renderReport(result, { date = new Date().toISOString().slice(0, 10) } = {}) {
  const v = VERDICTS[result.verdict];
  const r = result.review ?? {};
  const out = [];
  out.push(`# skill-qa 报告：${result.skill.name} ${result.skill.version ?? '(无版本)'}`);
  out.push('');
  out.push(`**结论：${v.zh}**（SkillHub 分级：${result.verdict}）。${v.next}`);
  out.push('');
  out.push(`- 日期：${date}；skill-qa ${QA_VERSION}；评审：${r.reviewer ?? 'agent'}`);
  out.push(`- 内容哈希：\`${result.hash}\`（改动任何文件后报告即失效，需重跑）`);
  out.push(`- 阈值为规范建议值（评测 ${pct(THRESHOLDS.taskPass)}、触发 ${pct(THRESHOLDS.triggerHit)}、误触发 ${pct(THRESHOLDS.falseTrigger)}、评分 ${THRESHOLDS.rubricTotal}/10），待 Dean 确认`);
  if (r.reject_reason) out.push(`- 不收录原因：${r.reject_reason}`);
  out.push('');
  out.push('## 门禁');
  out.push('');
  out.push('| # | 检查项 | 级别 | 结果 | 说明 |');
  out.push('| --- | --- | --- | --- | --- |');
  for (const g of result.gates) out.push(`| ${g.id} | ${cell(g.title)} | ${LEVEL_ZH[g.level]} | ${STATUS_ZH[g.status] ?? g.status} | ${cell(g.detail)} |`);
  out.push('');
  if (r.rubric) {
    out.push('## 评分表');
    out.push('');
    out.push('| 项 | 分数（0–2） | 依据 |');
    out.push('| --- | --- | --- |');
    for (const [k, zh] of RUBRIC_KEYS) out.push(`| ${zh} | ${r.rubric[k]?.score ?? '—'} | ${cell(r.rubric[k]?.why)} |`);
    out.push('');
  }
  if (result.exceptionProblems.length || (r.notes ?? []).length) {
    out.push('## 备注');
    out.push('');
    for (const p of result.exceptionProblems) out.push(`- ${p}`);
    for (const n of r.notes ?? []) out.push(`- ${n}`);
    out.push('');
  }
  const meta = { qa_version: QA_VERSION, name: result.skill.name, version: result.skill.version, verdict: result.verdict, hash: result.hash, date };
  out.push(`<!-- skill-qa ${JSON.stringify(meta)} -->`);
  out.push('');
  return out.join('\n');
}

// Is there a report for exactly this content, and what did it conclude?
export function reportStatus(dir) {
  const text = readText(path.join(dir, REPORT_FILE));
  if (text === null) return { state: 'missing' };
  const m = text.match(/<!-- skill-qa (\{.*\}) -->/);
  if (!m) return { state: 'unreadable' };
  let meta;
  try { meta = JSON.parse(m[1]); } catch { return { state: 'unreadable' }; }
  const hash = contentHash(dir);
  if (meta.hash !== hash) return { state: 'stale', meta, hash };
  return { state: meta.verdict === 'include' ? 'pass' : 'not-pass', meta, hash };
}

// ---------------------------------------------------------------------------
// CLI

function summary(result) {
  const lines = [`${result.skill.name} ${result.skill.version ?? '(无版本)'}  ${result.skill.dir}`];
  for (const g of result.gates) lines.push(`  ${(STATUS_ZH[g.status] ?? g.status).padEnd(4, '　')} ${g.id.padEnd(3)} ${g.title}${g.detail ? `\n         ${g.detail}` : ''}`);
  for (const p of result.exceptionProblems) lines.push(`  注意：${p}`);
  return lines.join('\n');
}

function main(argv) {
  const [cmd, dir, ...rest] = argv;
  const flag = (n) => rest.includes(n);
  const opt = (n) => { const i = rest.indexOf(n); return i >= 0 ? rest[i + 1] : undefined; };
  if (!cmd || !dir || ['-h', '--help'].includes(cmd)) {
    console.log('usage: qa.mjs check|scan|review-template|report|status <skill-dir> [--review review.json] [--no-scan] [--json]');
    return cmd ? 0 : 2;
  }
  if (!fs.existsSync(path.join(dir, 'SKILL.md'))) { console.error(`${dir} 里没有 SKILL.md`); return 2; }

  if (cmd === 'check') {
    const res = staticChecks(dir);
    res.verdict = verdictOf(res);
    if (flag('--json')) console.log(JSON.stringify(res, null, 2));
    else console.log(`${summary(res)}\n\n静态检查结论：${VERDICTS[res.verdict].zh}（G4/G6/G7/G8/G9 需要 review.json 才能有结论）`);
    return res.gates.some((g) => g.level === 'block' && g.status === 'fail') ? 1 : 0;
  }
  if (cmd === 'scan') {
    const scan = runScanner(dir);
    console.log(JSON.stringify(scan, null, 2));
    return scan.available ? 0 : 1;
  }
  if (cmd === 'review-template') { console.log(JSON.stringify(reviewTemplate(), null, 2)); return 0; }
  if (cmd === 'report') {
    const reviewPath = opt('--review');
    if (!reviewPath) { console.error('report 需要 --review <review.json>（先用 review-template 生成）'); return 2; }
    const rv = readJson(reviewPath);
    if (rv.missing || rv.error) { console.error(`读不了 ${reviewPath}：${rv.error ?? '文件不存在'}`); return 2; }
    if (!flag('--no-scan')) {
      const scan = runScanner(dir);
      rv.data.scanner = scan.available ? mergeScanner(scan, rv.data.scanner) : (rv.data.scanner?.findings ? rv.data.scanner : scan);
    }
    const res = applyReview(staticChecks(dir), rv.data);
    const file = path.join(dir, REPORT_FILE);
    fs.writeFileSync(file, renderReport(res));
    if (flag('--json')) console.log(JSON.stringify(res, null, 2));
    else console.log(`${summary(res)}\n\n结论：${VERDICTS[res.verdict].zh}。${VERDICTS[res.verdict].next}\n报告：${file}`);
    return res.verdict === 'include' ? 0 : 1;
  }
  if (cmd === 'status') {
    const st = reportStatus(dir);
    if (flag('--json')) console.log(JSON.stringify(st));
    else console.log({ missing: '没有 QA_REPORT.md：先跑 skill-qa', unreadable: 'QA_REPORT.md 不是 skill-qa 生成的', stale: '报告已过期：报告之后文件有改动，需重跑', pass: `报告有效，结论：可分发（${st.meta?.date}）`, 'not-pass': `报告有效，结论：${VERDICTS[st.meta?.verdict]?.zh ?? st.meta?.verdict}，不能导入` }[st.state]);
    return st.state === 'pass' ? 0 : 1;
  }
  console.error(`未知命令 ${cmd}`);
  return 2;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(e.stack || e.message); process.exitCode = 2; }
}

export { fileURLToPath };
