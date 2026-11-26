// Skill Hub repository tooling: discover skills, validate them, build the
// Claude Code plugin marketplace manifest and list files for release packages.
// Only dependency: the `yaml` package. Node >= 20.
import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';

export const MARKETPLACE_NAME = 'blacklake-skill-hub';
export const MARKETPLACE_OWNER = { name: 'D-Tony2020' };
export const STATUSES = ['draft', 'published', 'archived'];

// Frontmatter keys documented for SKILL.md across Claude surfaces. Anything else
// is reported as a warning: Claude Code ignores it, some upload paths may not.
const KNOWN_FRONTMATTER = new Set([
  'name', 'description', 'license', 'allowed-tools', 'metadata', 'compatibility',
  'when_to_use', 'argument-hint', 'disable-model-invocation', 'user-invocable',
  'model', 'effort', 'context', 'agent', 'hooks', 'paths', 'shell',
]);
const KNOWN_HUB_KEYS = new Set(['version', 'status', 'owner', 'tags', 'notes', 'requires', 'source']);
const REQUIRES_KEYS = new Set(['skills', 'commands', 'env']);
// Files that are development material, not part of what an agent loads.
// QA_REPORT.md and qa-exceptions.json are review material for the repo PR; skill-qa leaves them out of the package too.
const PACKAGE_EXCLUDES = new Set(['hub.yaml', 'tests', 'evals', '.gitattributes', '.DS_Store', '__pycache__', '.hub-source.json', 'QA_REPORT.md', 'qa-exceptions.json']);

const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/;

export function parseFrontmatter(text) {
  const normalized = text.replace(/^﻿/, '').replace(/\r\n/g, '\n');
  const match = normalized.match(/^---\n([\s\S]*?)\n---(\n|$)/);
  if (!match) return { error: 'SKILL.md does not start with a --- frontmatter block' };
  try {
    const data = YAML.parse(match[1]);
    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
      return { error: 'frontmatter is not a mapping' };
    }
    return { data };
  } catch (err) {
    return { error: `frontmatter is not valid YAML: ${err.message.split('\n')[0]}` };
  }
}

function readIfExists(file) {
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
}

export function loadSkill(skillsDir, dirName) {
  const dir = path.join(skillsDir, dirName);
  const skill = { dirName, dir, frontmatter: null, hub: null, versionFile: null, loadErrors: [] };

  const skillMd = readIfExists(path.join(dir, 'SKILL.md'));
  if (skillMd === null) {
    skill.loadErrors.push('missing SKILL.md');
  } else {
    const fm = parseFrontmatter(skillMd);
    if (fm.error) skill.loadErrors.push(fm.error);
    else skill.frontmatter = fm.data;
  }

  const hubText = readIfExists(path.join(dir, 'hub.yaml'));
  if (hubText !== null) {
    try {
      const parsed = YAML.parse(hubText) ?? {};
      if (typeof parsed !== 'object' || Array.isArray(parsed)) skill.loadErrors.push('hub.yaml is not a mapping');
      else skill.hub = parsed;
    } catch (err) {
      skill.loadErrors.push(`hub.yaml is not valid YAML: ${err.message.split('\n')[0]}`);
    }
  }

  const versionText = readIfExists(path.join(dir, 'VERSION'));
  if (versionText !== null) skill.versionFile = versionText.trim();

  const hub = skill.hub ?? {};
  skill.name = skill.frontmatter?.name ?? dirName;
  skill.description = typeof skill.frontmatter?.description === 'string' ? skill.frontmatter.description.trim() : '';
  skill.version = hub.version != null ? String(hub.version) : skill.versionFile;
  skill.status = hub.status ?? 'draft';
  skill.tags = Array.isArray(hub.tags) ? hub.tags.map(String) : [];
  const req = hub.requires && typeof hub.requires === 'object' ? hub.requires : {};
  skill.requires = {
    skills: Array.isArray(req.skills) ? req.skills.map(String) : [],
    commands: Array.isArray(req.commands) ? req.commands.map(String) : [],
    env: Array.isArray(req.env) ? req.env.map(String) : [],
  };
  return skill;
}

export function loadSkills(root) {
  const skillsDir = path.join(root, 'skills');
  if (!fs.existsSync(skillsDir)) return [];
  return fs.readdirSync(skillsDir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith('.'))
    .map((e) => loadSkill(skillsDir, e.name))
    .sort((a, b) => a.dirName.localeCompare(b.dirName));
}

export function validateSkill(skill) {
  const errors = [...skill.loadErrors];
  const warnings = [];
  const fm = skill.frontmatter;

  if (fm) {
    const { name, description } = fm;
    if (typeof name !== 'string' || name.length === 0) {
      errors.push('frontmatter `name` is required');
    } else {
      if (name !== skill.dirName) errors.push(`frontmatter name "${name}" must equal the folder name "${skill.dirName}"`);
      if (!NAME_RE.test(name)) errors.push(`name "${name}" must be lowercase letters, digits and single hyphens`);
      if (name.length > 64) errors.push(`name is ${name.length} characters, the limit is 64`);
      if (/anthropic|claude/.test(name)) errors.push('name must not contain the reserved words "anthropic" or "claude"');
    }
    if (typeof description !== 'string' || description.trim().length === 0) {
      errors.push('frontmatter `description` is required');
    } else {
      if (description.length > 1024) errors.push(`description is ${description.length} characters, the limit is 1024`);
      if (/[<>]/.test(description)) errors.push('description must not contain < or > (XML tags are rejected on upload)');
    }
    for (const key of Object.keys(fm)) {
      if (!KNOWN_FRONTMATTER.has(key)) warnings.push(`frontmatter key "${key}" is not a documented SKILL.md field; put Hub metadata in hub.yaml`);
    }
  }

  if (skill.hub) {
    for (const key of Object.keys(skill.hub)) {
      if (!KNOWN_HUB_KEYS.has(key)) warnings.push(`hub.yaml key "${key}" is not recognised`);
    }
    if (!STATUSES.includes(skill.status)) errors.push(`hub.yaml status "${skill.status}" must be one of ${STATUSES.join(', ')}`);
    if (skill.hub.version != null && skill.versionFile != null && String(skill.hub.version) !== skill.versionFile) {
      errors.push(`hub.yaml version ${skill.hub.version} differs from VERSION ${skill.versionFile}`);
    }
  } else {
    warnings.push('no hub.yaml: treated as status "draft" and left out of the marketplace');
  }

  if (skill.version != null && !SEMVER_RE.test(skill.version)) errors.push(`version "${skill.version}" is not semver (x.y.z)`);
  if (skill.status === 'published' && skill.version == null) errors.push('a published skill needs a version (hub.yaml version or VERSION file)');
  if (fs.existsSync(path.join(skill.dir, 'bin'))) errors.push('top-level bin/ is rejected by claude.ai organization sync; use scripts/');

  const req = skill.hub?.requires;
  if (req != null) {
    if (typeof req !== 'object' || Array.isArray(req)) {
      errors.push('hub.yaml requires must be a mapping with skills / commands / env lists');
    } else {
      for (const [key, value] of Object.entries(req)) {
        if (!REQUIRES_KEYS.has(key)) warnings.push(`hub.yaml requires.${key} is not recognised (use skills, commands, env)`);
        else if (!Array.isArray(value)) errors.push(`hub.yaml requires.${key} must be a list`);
      }
    }
  }
  const missing = findMissingReferences(skill);
  if (missing.length) {
    // A warning, not an error: some of these may belong to a skill listed in requires.skills.
    warnings.push(`SKILL.md refers to files that are not in the skill folder: ${missing.join(', ')} (fine only if they belong to a required skill)`);
  }
  for (const hit of findHardcodedPaths(skill)) {
    warnings.push(`${hit.file}:${hit.line} hardcodes an install path (${hit.text}); resolve paths from the folder that holds SKILL.md, since plugin and SkillHub installs live elsewhere`);
  }

  return { errors, warnings };
}

export function buildMarketplace(skills) {
  const plugins = skills
    .filter((s) => s.status === 'published')
    .map((s) => {
      const entry = {
        name: s.name,
        source: `./skills/${s.dirName}`,
        description: s.description,
        version: s.version,
        // No plugin.json in the folder, so this entry is the manifest:
        // the skill folder itself is the plugin root and holds SKILL.md directly.
        skills: ['.'],
      };
      if (s.tags.length) entry.keywords = s.tags;
      return entry;
    });
  return {
    name: MARKETPLACE_NAME,
    owner: MARKETPLACE_OWNER,
    metadata: { description: 'Skills 工厂产出的自定义 Claude Skills（由 tools/hub 生成，请勿手改）' },
    plugins,
  };
}

export function serializeMarketplace(manifest) {
  return `${JSON.stringify(manifest, null, 2)}\n`;
}

// Files that belong in a release package (claude.ai upload zip, SkillHub publish).
export function packageFiles(skill) {
  const out = [];
  const walk = (rel) => {
    const abs = path.join(skill.dir, rel);
    for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
      if (rel === '' && PACKAGE_EXCLUDES.has(entry.name)) continue;
      if (entry.name === '.DS_Store' || entry.name === '__pycache__') continue;
      const childRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(childRel);
      else out.push(childRel);
    }
  };
  walk('');
  return out.sort();
}

// ---- SkillHub (self-hosted iflytek/skillhub) packaging ----------------------
// SkillHub warns on files outside its extension allowlist and the CLI treats any
// warning as a failure, so extensionless files (VERSION, LICENSE...) are left out.
// SkillHub ignores the VERSION file, so the version goes into SKILL.md as
// metadata.version (a documented frontmatter field) in the staged copy only.
export function skillHubFiles(skill) {
  const kept = [];
  const dropped = [];
  for (const rel of packageFiles(skill)) {
    const base = rel.split('/').pop();
    if (base !== 'SKILL.md' && !/\.[A-Za-z0-9]+$/.test(base)) dropped.push(rel);
    else kept.push(rel);
  }
  return { kept, dropped };
}

export function withMetadataVersion(skillMdText, version) {
  const text = skillMdText.replace(/^﻿/, '').replace(/\r\n/g, '\n');
  const match = text.match(/^---\n([\s\S]*?)\n---(\n|$)/);
  if (!match) throw new Error('SKILL.md has no frontmatter');
  const doc = YAML.parseDocument(match[1]);
  doc.setIn(['metadata', 'version'], String(version));
  return `---\n${doc.toString({ lineWidth: 0 }).trimEnd()}\n---${match[2]}${text.slice(match[0].length)}`;
}

// Copy a skill into `outDir` the way SkillHub should receive it.
export function stageForSkillHub(skill, outDir) {
  if (!skill.version) throw new Error(`${skill.dirName} has no version`);
  const { kept, dropped } = skillHubFiles(skill);
  fs.rmSync(outDir, { recursive: true, force: true });
  for (const rel of kept) {
    const dest = path.join(outDir, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    if (rel === 'SKILL.md') {
      fs.writeFileSync(dest, withMetadataVersion(fs.readFileSync(path.join(skill.dir, rel), 'utf8'), skill.version));
    } else {
      fs.copyFileSync(path.join(skill.dir, rel), dest);
    }
  }
  return { dir: outDir, files: kept, dropped };
}

// ---- Agent operations: install-path checks, import, bump, install ----------

const TEXT_EXT = /\.(md|txt|sh|bash|ps1|psm1|py|js|mjs|cjs|ts|json|ya?ml|toml|cmd|bat)$/i;
// ~/.claude/skills/<x>, $HOME/.claude/skills, %USERPROFILE%\.claude\skills, C:\Users\me\.claude\skills ...
const SKILL_PATH_RE = /(?:~|\$HOME|\$\{HOME\}|%USERPROFILE%|\$env:USERPROFILE|[A-Za-z]:\\Users\\[^\\\s"'`]+|\/(?:home|Users)\/[^/\s"'`]+)[\\/]+\.claude[\\/]+skills(?:[\\/]+[A-Za-z0-9_.-]+)?/g;

export function findHardcodedPaths(skill) {
  const hits = [];
  const files = fs.existsSync(skill.dir) ? packageFiles(skill) : [];
  for (const rel of files) {
    if (!TEXT_EXT.test(rel) && rel !== 'SKILL.md') continue;
    const lines = fs.readFileSync(path.join(skill.dir, rel), 'utf8').split(/\r?\n/);
    lines.forEach((line, i) => {
      for (const m of line.matchAll(SKILL_PATH_RE)) {
        // Only a path to this skill's own folder breaks when it is installed elsewhere;
        // generic mentions of ~/.claude/skills (docs, installers) are fine.
        const last = m[0].split(/[\\/]+/).pop();
        if (last === skill.dirName) hits.push({ file: rel, line: i + 1, text: m[0] });
      }
    });
  }
  return hits;
}

// Paths like scripts/diagram.py or references/style-guide.md mentioned in SKILL.md
// must ship with the skill; a copy synced from claude.ai often holds SKILL.md only.
export function findMissingReferences(skill) {
  const file = path.join(skill.dir, 'SKILL.md');
  if (!fs.existsSync(file)) return [];
  const text = fs.readFileSync(file, 'utf8');
  const refs = new Set();
  for (const m of text.matchAll(/(?<![\w.-])(scripts|references|assets|templates)[\\/]([\w.\-\\/]*\.[A-Za-z0-9]+)/g)) {
    refs.add(`${m[1]}/${m[2].replace(/\\/g, '/')}`);
  }
  return [...refs].filter((rel) => !fs.existsSync(path.join(skill.dir, rel))).sort();
}

const IMPORT_SKIP = new Set(['.git', 'node_modules', '__pycache__', '.DS_Store', '.venv', 'venv', '.hub-source.json']);

function copyTree(src, dest, skip) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (skip.has(entry.name)) continue;
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyTree(s, d, skip);
    else if (entry.isFile()) fs.copyFileSync(s, d);
  }
}

// Bring an existing skill folder (local ~/.claude/skills/x, plugin cache, unzipped
// claude.ai export) into skills/<name> as a draft. Returns a report the agent can act on.
export function importSkill(root, srcDir, { name, version, force = false } = {}) {
  if (!fs.existsSync(path.join(srcDir, 'SKILL.md'))) throw new Error(`${srcDir} has no SKILL.md`);
  const fm = parseFrontmatter(fs.readFileSync(path.join(srcDir, 'SKILL.md'), 'utf8'));
  if (fm.error) throw new Error(fm.error);
  const skillName = name ?? fm.data.name ?? path.basename(srcDir);
  const dest = path.join(root, 'skills', skillName);
  if (fs.existsSync(dest)) {
    if (!force) throw new Error(`skills/${skillName} already exists (use --force to replace it)`);
    fs.rmSync(dest, { recursive: true, force: true });
  }

  let pluginVersion = null;
  const pluginJson = path.join(srcDir, '.claude-plugin', 'plugin.json');
  if (fs.existsSync(pluginJson)) {
    try { pluginVersion = JSON.parse(fs.readFileSync(pluginJson, 'utf8')).version ?? null; } catch { /* ignore */ }
  }
  const versionFile = fs.existsSync(path.join(srcDir, 'VERSION')) ? fs.readFileSync(path.join(srcDir, 'VERSION'), 'utf8').trim() : null;
  // A plugin.json would turn the folder into its own plugin; the marketplace entry is the manifest here.
  copyTree(srcDir, dest, new Set([...IMPORT_SKIP, '.claude-plugin']));

  const finalVersion = version ?? versionFile ?? pluginVersion ?? fm.data.metadata?.version ?? '0.1.0';
  if (!fs.existsSync(path.join(dest, 'hub.yaml'))) {
    const hub = { status: 'draft' };
    if (!versionFile || version) hub.version = String(finalVersion);
    fs.writeFileSync(path.join(dest, 'hub.yaml'), YAML.stringify(hub));
  }
  if (version && versionFile) fs.writeFileSync(path.join(dest, 'VERSION'), `${version}\n`);

  const skill = loadSkill(path.join(root, 'skills'), skillName);
  const { errors, warnings } = validateSkill(skill);
  const files = packageFiles(skill);
  return { name: skillName, dir: dest, version: skill.version, files, errors, warnings, onlySkillMd: files.filter((f) => f !== 'hub.yaml').length <= 1 };
}

export function nextVersion(current, part) {
  if (SEMVER_RE.test(part)) return part;
  const m = String(current ?? '').match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!m) throw new Error(`current version "${current}" is not semver`);
  const [maj, min, pat] = m.slice(1).map(Number);
  if (part === 'major') return `${maj + 1}.0.0`;
  if (part === 'minor') return `${maj}.${min + 1}.0`;
  if (part === 'patch') return `${maj}.${min}.${pat + 1}`;
  throw new Error('bump takes major, minor, patch or an explicit x.y.z');
}

// Raise the version wherever it lives (VERSION file wins) and open a CHANGELOG entry.
export function bumpSkill(skill, part, note, today = new Date().toISOString().slice(0, 10)) {
  const next = nextVersion(skill.version, part);
  const hubFile = path.join(skill.dir, 'hub.yaml');
  if (skill.versionFile != null) fs.writeFileSync(path.join(skill.dir, 'VERSION'), `${next}\n`);
  if (skill.versionFile == null || skill.hub?.version != null) {
    const doc = fs.existsSync(hubFile) ? YAML.parseDocument(fs.readFileSync(hubFile, 'utf8')) : new YAML.Document({});
    doc.set('version', next);
    fs.writeFileSync(hubFile, doc.toString());
  }
  const changelog = path.join(skill.dir, 'CHANGELOG.md');
  const entry = `## ${next} - ${today}\n\n- ${note || 'TODO: describe the change'}\n\n`;
  if (fs.existsSync(changelog)) {
    const text = fs.readFileSync(changelog, 'utf8');
    const at = text.search(/^## /m);
    fs.writeFileSync(changelog, at === -1 ? `${text.trimEnd()}\n\n${entry}` : text.slice(0, at) + entry + text.slice(at));
  } else {
    fs.writeFileSync(changelog, `# Changelog\n\n${entry}`);
  }
  return next;
}

export const INSTALL_MARKER = '.hub-source.json';

// Copy the release files of a skill into <destRoot>/<name>. Refuses to replace a
// folder that this tool did not install, so hand-made copies are never lost.
export function installSkill(skill, destRoot, { force = false, commit = null } = {}) {
  const dest = path.join(destRoot, skill.dirName);
  const marker = path.join(dest, INSTALL_MARKER);
  if (fs.existsSync(dest) && !fs.existsSync(marker) && !force) {
    throw new Error(`${dest} exists and was not installed by skill-hub (use --force to replace it)`);
  }
  const tmp = `${dest}.hub-tmp`;
  fs.rmSync(tmp, { recursive: true, force: true });
  for (const rel of packageFiles(skill)) {
    const to = path.join(tmp, rel);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(path.join(skill.dir, rel), to);
  }
  fs.writeFileSync(path.join(tmp, INSTALL_MARKER), `${JSON.stringify({ name: skill.dirName, version: skill.version, commit, installedAt: new Date().toISOString() }, null, 2)}\n`);
  fs.rmSync(dest, { recursive: true, force: true });
  fs.renameSync(tmp, dest);
  return dest;
}

export function readInstalled(destRoot) {
  if (!fs.existsSync(destRoot)) return [];
  return fs.readdirSync(destRoot, { withFileTypes: true })
    .filter((e) => e.isDirectory() && fs.existsSync(path.join(destRoot, e.name, 'SKILL.md')))
    .map((e) => {
      const marker = path.join(destRoot, e.name, INSTALL_MARKER);
      let info = null;
      try { info = JSON.parse(fs.readFileSync(marker, 'utf8')); } catch { /* not ours */ }
      return { name: e.name, managed: !!info, version: info?.version ?? null };
    });
}
