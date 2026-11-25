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
const KNOWN_HUB_KEYS = new Set(['version', 'status', 'owner', 'tags', 'notes']);
// Files that are development material, not part of what an agent loads.
const PACKAGE_EXCLUDES = new Set(['hub.yaml', 'tests', 'evals', '.gitattributes', '.DS_Store', '__pycache__']);

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
