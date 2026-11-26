#!/usr/bin/env node
// INTENT.md (the target card written by skill-intent) — create, validate, read.
//
//   node intent.mjs init  <skill-dir> [--name n]   write a blank card from assets/INTENT.template.md (never overwrites)
//   node intent.mjs check <skill-dir> [--json]     validate fields and required sections; exit 1 on errors
//   node intent.mjs show  <skill-dir> [--json]     print skill, scope, bound_to, verdict, date
//
// skill-qa and the repo tools import readIntent()/checkIntent() from this file.
// Node 18+, no dependencies, no child processes.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const INTENT_FILE = 'INTENT.md';
export const LEGACY_INTENT_FILE = path.join('references', 'intent.md');
export const SCOPES = ['personal', 'team', 'org', 'customer'];
export const VERDICTS = ['aligned', 'needs-clarification', 'rejected'];
export const HUB_SCOPES = ['team', 'org']; // what the phase-1 Hub accepts
export const SECTIONS = ['一句话目标', '给谁用', '触发说法', '不做什么', '成功标准', '输入与输出', '环境前提', '与已有 Skill 的关系', '未决问题'];
const COUNTED = ['触发说法', '不做什么', '成功标准'];
const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

// Flat `key: value` frontmatter only; that is all the card uses.
export function parseCard(text) {
  const t = text.replace(/^﻿/, '').replace(/\r\n/g, '\n');
  const m = t.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!m) return { error: 'INTENT.md does not start with a --- frontmatter block' };
  const fields = {};
  for (const line of m[1].split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue;
    const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!kv) return { error: `frontmatter line is not "key: value": ${line}` };
    fields[kv[1]] = kv[2].replace(/^["']|["']$/g, '').trim();
  }
  const sections = {};
  let current = null;
  for (const line of m[2].split('\n')) {
    const h = line.match(/^##\s+(.+?)\s*$/);
    if (h) { current = h[1]; sections[current] = []; continue; }
    if (current) sections[current].push(line);
  }
  return { fields, sections };
}

const stripComments = (lines) => lines.join('\n').replace(/<!--[\s\S]*?-->/g, '');
// An item counts when it has real text after the list marker, and is not a template blank.
export function countItems(lines) {
  return stripComments(lines).split('\n').filter((l) => {
    const m = l.match(/^\s*(?:\d+[.)、]|[-*])\s+(.*)$/);
    if (!m) return false;
    const body = m[1].replace(/"___"\s*→\s*交给\s*___/, '').replace(/_{3,}/g, '').trim();
    return body.length > 1;
  }).length;
}
const hasText = (lines) => stripComments(lines).replace(/[-*\d.、:：\s_]|角色|使用频率|输入|输出|Hub 查重|仓库查重/g, '').length > 0;

export function findIntent(dir) {
  for (const rel of [INTENT_FILE, LEGACY_INTENT_FILE]) {
    const f = path.join(dir, rel);
    if (fs.existsSync(f)) return { file: f, rel, legacy: rel !== INTENT_FILE };
  }
  return null;
}

export function checkIntent(dir) {
  const found = findIntent(dir);
  if (!found) return { state: 'missing', errors: [`no ${INTENT_FILE}: run skill-intent first`], warnings: [] };
  const card = parseCard(fs.readFileSync(found.file, 'utf8'));
  const errors = [];
  const warnings = [];
  if (found.legacy) warnings.push(`read ${LEGACY_INTENT_FILE}; move it to ${INTENT_FILE} at the skill root (it is left out of the package there)`);
  if (card.error) return { state: 'invalid', file: found.rel, errors: [card.error], warnings };
  const f = card.fields;
  if (!f.skill || !NAME_RE.test(f.skill)) errors.push('skill must be a lowercase-hyphen name');
  else if (path.basename(path.resolve(dir)) !== f.skill) warnings.push(`skill "${f.skill}" differs from the folder name "${path.basename(path.resolve(dir))}"`);
  if (!SCOPES.includes(f.scope)) errors.push(`scope must be one of ${SCOPES.join(', ')}`);
  if (!VERDICTS.includes(f.verdict)) errors.push(`verdict must be one of ${VERDICTS.join(', ')}`);
  if (!f.producer) errors.push('producer is required (a role or account is enough)');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date ?? '')) errors.push('date must be YYYY-MM-DD');
  if ('bound_to' in f && !f.bound_to) errors.push('bound_to is empty: remove it or name the platform');
  for (const k of Object.keys(f)) if (!['skill', 'scope', 'bound_to', 'verdict', 'producer', 'date', 'supersedes'].includes(k)) warnings.push(`unknown field ${k}`);
  for (const s of SECTIONS) if (!(s in card.sections)) errors.push(`missing section "## ${s}"`);
  if (f.verdict === 'aligned') {
    for (const s of COUNTED) {
      const n = countItems(card.sections[s] ?? []);
      if (n < 3) errors.push(`aligned needs at least 3 items under "${s}" (found ${n})`);
    }
    const goal = card.sections['一句话目标'] ?? [];
    if (!hasText(goal) || /当用户想 ___/.test(goal.join('\n'))) errors.push('aligned needs a filled-in 一句话目标');
    if (!HUB_SCOPES.includes(f.scope)) warnings.push(`scope ${f.scope} is not accepted by the phase-1 Hub (only ${HUB_SCOPES.join(', ')})`);
  }
  if (f.verdict === 'rejected' && !('驳回理由' in card.sections && hasText(card.sections['驳回理由']))) errors.push('rejected needs a "## 驳回理由" section');
  return { state: errors.length ? 'invalid' : f.verdict, file: found.rel, fields: f, errors, warnings };
}

// What skill-qa's G0 triage needs: may this skill go on to the QA gates, and with which scope.
export function readIntent(dir) {
  const r = checkIntent(dir);
  return {
    state: r.state,
    file: r.file ?? null,
    scope: r.fields?.scope ?? null,
    bound_to: r.fields?.bound_to || null,
    verdict: r.fields?.verdict ?? null,
    date: r.fields?.date ?? null,
    proceed: r.state === 'aligned' && HUB_SCOPES.includes(r.fields.scope),
    errors: r.errors,
  };
}

export function initIntent(dir, name, today = new Date().toISOString().slice(0, 10)) {
  const target = path.join(dir, INTENT_FILE);
  if (fs.existsSync(target)) return { created: false, file: target };
  const skill = name ?? path.basename(path.resolve(dir));
  const tpl = fs.readFileSync(path.join(HERE, '..', 'assets', 'INTENT.template.md'), 'utf8');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(target, tpl.replaceAll('__SKILL__', skill).replaceAll('__DATE__', today));
  return { created: true, file: target };
}

function main(argv) {
  const [cmd, dir, ...rest] = argv;
  const json = rest.includes('--json');
  if (!dir || !['init', 'check', 'show'].includes(cmd)) {
    console.error('usage: intent.mjs init|check|show <skill-dir> [--name n] [--json]');
    return 2;
  }
  if (cmd === 'init') {
    const i = rest.indexOf('--name');
    const r = initIntent(dir, i === -1 ? undefined : rest[i + 1]);
    console.log(r.created ? `wrote ${r.file}` : `${r.file} already exists, left unchanged`);
    return 0;
  }
  if (cmd === 'check') {
    const r = checkIntent(dir);
    if (json) console.log(JSON.stringify(r, null, 2));
    else {
      console.log(`${r.errors.length ? 'FAIL' : 'ok  '} ${r.file ?? INTENT_FILE}  verdict=${r.fields?.verdict ?? '-'} scope=${r.fields?.scope ?? '-'}${r.fields?.bound_to ? ` bound_to=${r.fields.bound_to}` : ''}`);
      for (const e of r.errors) console.log(`     error: ${e}`);
      for (const w of r.warnings) console.log(`     warn:  ${w}`);
    }
    return r.errors.length ? 1 : 0;
  }
  const r = readIntent(dir);
  if (json) console.log(JSON.stringify(r, null, 2));
  else console.log(`${r.state}  scope=${r.scope ?? '-'}${r.bound_to ? ` bound_to=${r.bound_to}` : ''}  date=${r.date ?? '-'}  proceed_to_qa=${r.proceed}`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exit(main(process.argv.slice(2))); } catch (e) { console.error(e.message); process.exit(1); }
}
