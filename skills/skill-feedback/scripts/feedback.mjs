#!/usr/bin/env node
// skill-feedback helper: find where an installed skill came from, scrub a draft, build a prefilled issue link.
//
//   node feedback.mjs locate <skill> [--dir <skills-dir> ...] [--json]
//   node feedback.mjs scrub  <draft.md> [--fix] [--json]      exit 1 while anything sensitive remains
//   node feedback.mjs url    --repo <owner/repo> --title <t> --body-file <draft.md> [--label <l>]
//
// Never sends anything: `url` prints a link the user opens and submits under their own account.
// Node 18+, no dependencies, no child processes, no network.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const home = () => process.env.SKILL_FEEDBACK_HOME || os.homedir();
const readJson = (f) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return null; } };
const readText = (f) => { try { return fs.readFileSync(f, 'utf8'); } catch { return null; } };

export function defaultDirs(cwd = process.cwd()) {
  const h = home();
  const dirs = [path.join(cwd, '.claude', 'skills'), path.join(h, '.claude', 'skills')];
  const synced = path.join(h, '.claude', 'skills', 'synced');
  if (fs.existsSync(synced)) for (const e of fs.readdirSync(synced, { withFileTypes: true })) if (e.isDirectory()) dirs.push(path.join(synced, e.name));
  return dirs;
}

const REPO_RE = /https:\/\/github\.com\/([A-Za-z0-9-]+)\/([A-Za-z0-9._-]+?)(?:\.git)?(?=[/)\s>`'"，。]|$)/;

export function sourceRepo(skillMd) {
  if (!skillMd) return null;
  // Prefer the line that says it is the source repository.
  const lines = skillMd.split(/\r?\n/);
  const marked = lines.find((l) => /源码仓库|source repo/i.test(l) && REPO_RE.test(l));
  const m = (marked ?? skillMd).match(REPO_RE);
  return m ? `${m[1]}/${m[2]}` : null;
}

export function locate(name, dirs = defaultDirs()) {
  const found = [];
  for (const root of dirs) {
    const dir = path.join(root, name);
    const md = readText(path.join(dir, 'SKILL.md'));
    if (md == null) continue;
    const sh = readJson(path.join(dir, '.skillhub', 'metadata.json'));
    const hs = readJson(path.join(dir, '.hub-source.json'));
    const vf = readText(path.join(dir, 'VERSION'))?.trim() || null;
    let channel = 'manual';
    if (sh) channel = 'skillhub';
    else if (hs) channel = 'repo';
    else if (dir.includes(`${path.sep}synced${path.sep}`)) channel = 'claude.ai-sync';
    found.push({
      dir,
      channel,
      version: sh?.version ?? hs?.version ?? vf ?? null,
      registry: sh?.registry ?? null,
      coordinate: sh?.namespace && sh?.slug ? `@${sh.namespace}/${sh.slug}` : null,
      commit: hs?.commit ?? null,
      repo: sourceRepo(md),
      updateHint: {
        skillhub: 'skillhub upgrade <坐标> --registry <Hub 地址> --check',
        repo: '在源码仓库 git pull 后 hub install <skill> --force',
        'claude.ai-sync': '在 claude.ai 上传新版 zip',
        manual: '手工放置的副本，先问用户从哪来',
      }[channel],
    });
  }
  return found;
}

const PATTERNS = [
  ['私钥', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['令牌', /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[abp]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b/],
  ['疑似密码或令牌', /\b(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S{6,}/i],
  ['内网地址', /\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b/],
  ['邮箱', /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/],
  ['个人目录', /(?:[A-Za-z]:\\Users\\[^\\\s]+|\/(?:Users|home)\/[^/\s]+)/],
];

export function loadRedactWords() {
  const t = readText(path.join(home(), '.skill-qa', 'redact.txt'));
  return t ? t.split(/\r?\n/).map((w) => w.trim()).filter((w) => w && !w.startsWith('#')) : [];
}

export function scrub(text, { fix = false, words = loadRedactWords() } = {}) {
  const hits = [];
  const out = text.split(/\r?\n/).map((line, i) => {
    let l = line;
    for (const [kind, re] of PATTERNS) {
      const g = new RegExp(re.source, re.flags.includes('g') ? re.flags : `${re.flags}g`);
      if (g.test(l)) {
        hits.push({ line: i + 1, kind });
        if (fix) {
          const rep = { 邮箱: '<邮箱>', 个人目录: '~', 内网地址: '<内网地址>' }[kind] ?? '<已删除>';
          l = l.replace(new RegExp(re.source, g.flags), rep);
        }
      }
    }
    for (const w of words) {
      if (l.includes(w)) { hits.push({ line: i + 1, kind: '客户名' }); if (fix) l = l.split(w).join('某客户'); }
    }
    return l;
  }).join('\n');
  return { hits, text: out, clean: fix ? scrub(out, { words }).hits.length === 0 : hits.length === 0 };
}

export const URL_LIMIT = 7000;
export function issueUrl({ repo, title, body, label }) {
  if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/.test(repo ?? '')) throw new Error('--repo must look like owner/repo');
  if (!title) throw new Error('--title is required');
  const q = new URLSearchParams({ title, body: body ?? '' });
  if (label) q.set('labels', label);
  const url = `https://github.com/${repo}/issues/new?${q.toString()}`;
  return { url, tooLong: url.length > URL_LIMIT, length: url.length };
}

function opt(argv, name) {
  const i = argv.indexOf(name);
  if (i === -1) return undefined;
  const v = argv[i + 1];
  if (v === undefined || v.startsWith('--')) throw new Error(`${name} needs a value`);
  return v;
}

function main(argv) {
  const [cmd, ...rest] = argv;
  const json = rest.includes('--json');
  if (cmd === 'locate' && rest[0] && !rest[0].startsWith('--')) {
    const dirs = [];
    for (let i = 0; i < rest.length; i += 1) if (rest[i] === '--dir') dirs.push(path.resolve(rest[i + 1]));
    const r = locate(rest[0], dirs.length ? dirs : undefined);
    if (json) console.log(JSON.stringify(r, null, 2));
    else if (!r.length) console.log(`没有找到已安装的 ${rest[0]}（查过 ${(dirs.length ? dirs : defaultDirs()).join('、')}）`);
    else for (const x of r) console.log(`${x.dir}\n  来源 ${x.channel}  版本 ${x.version ?? '未知'}  源码仓库 ${x.repo ?? '未写明'}${x.coordinate ? `  坐标 ${x.coordinate}` : ''}\n  更新 ${x.updateHint}`);
    return 0;
  }
  if (cmd === 'scrub' && rest[0]) {
    const file = rest[0];
    const r = scrub(fs.readFileSync(file, 'utf8'), { fix: rest.includes('--fix') });
    if (rest.includes('--fix')) fs.writeFileSync(file, r.text);
    if (json) console.log(JSON.stringify({ hits: r.hits, clean: r.clean }, null, 2));
    else {
      for (const h of r.hits) console.log(`${file}:${h.line} ${h.kind}${rest.includes('--fix') ? '（已替换）' : ''}`);
      console.log(r.clean ? 'clean' : '还有需要人看的内容：改掉或删掉再发');
    }
    return r.clean ? 0 : 1;
  }
  if (cmd === 'url') {
    const bodyFile = opt(rest, '--body-file');
    const body = bodyFile ? fs.readFileSync(bodyFile, 'utf8') : '';
    const s = scrub(body);
    if (!s.clean) { console.error('草稿里还有敏感内容，先跑 scrub'); return 1; }
    const r = issueUrl({ repo: opt(rest, '--repo'), title: opt(rest, '--title'), body, label: opt(rest, '--label') });
    if (r.tooLong) console.error(`链接有 ${r.length} 个字符，浏览器可能截断：请用户打开 https://github.com/${opt(rest, '--repo')}/issues/new 手动粘贴正文`);
    console.log(r.url);
    return 0;
  }
  console.error('usage: feedback.mjs locate <skill> [--dir d] [--json] | scrub <file> [--fix] [--json] | url --repo o/r --title t --body-file f [--label l]');
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exit(main(process.argv.slice(2))); } catch (e) { console.error(e.message); process.exit(1); }
}
