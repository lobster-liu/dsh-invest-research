/**
 * The bundled skills of this plugin: each one is a multi-agent research
 * pipeline (roles + tools + a pre-write PII gate) that emits source-cited
 * reports.
 *
 *   stock-research — A-share single-name pipeline (coordinator / data / policy
 *                    / valuation / risk / auditor)
 *   fund-research  — fund look-through pipeline (coordinator / fund-profile /
 *                    macro-policy / industry-trend / company-valuation /
 *                    performance / red-team)
 *
 * v0.5.0 adds the pick-funds analyst suite (ported from the ZCode pick-funds
 * plugin v0.1.1): a lightweight single-agent workflow layer that covers
 * screening, per-fund profiles, manager profiles, holdings/style analysis,
 * ongoing fund watch, and PDF / DOCX / XLSX delivery.
 *
 *   pick-funds      — suite entry: work-mode routing + shared guardrails + the
 *                     DSH data-source mapping
 *   fund-screen     — multi-criteria screening
 *   fund-profile    — single-fund deep profile
 *   fund-watch      — window monitoring of held / shortlisted funds
 *   holdings-style  — holdings-based + RBSA style analysis, cross-fund overlap
 *   manager-profile — manager career profile by tenure
 *   report-render   — paginated PDF / DOCX deliverables (fin_report)
 *   xlsx-author     — professional .xlsx workbooks (openpyxl + recalc gate)
 *   decision-loop   — decision ledger: register a decision, settle it against
 *                     what happened, reflect, and score decision quality
 *
 * Every skill is registered with the Host's skill registry when that service
 * exists. It must never be a hard dependency of the plugin: Cordis 4.0.4 treats
 * every declared `inject` as required, so a missing `skills` service would hang
 * the whole plugin. The plugin therefore asks for it through a scoped
 * `ctx.inject(['skills'], ...)` and works the same without it.
 *
 * Each packaged SKILL.md is re-read on every call, so a provider object is
 * never stale.
 * @module dsh-invest-research/skill
 */
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

/** Skill ids, in load order. */
export const SKILL_NAMES = [
  'stock-research',
  'fund-research',
  'pick-funds',
  'fund-screen',
  'fund-profile',
  'fund-watch',
  'holdings-style',
  'manager-profile',
  'report-render',
  'xlsx-author',
  'decision-loop',
];

/** `assets/skills/`, resolved next to the built `lib/`. */
export const SKILLS_ROOT = fileURLToPath(new URL('../assets/skills/', import.meta.url));

/** Absolute directory of one packaged skill (always with a trailing slash). */
export function skillDir(name, root = SKILLS_ROOT) {
  const base = root.endsWith('/') ? root : root + '/';
  return base + name + '/';
}

/** Rank the Host gives packaged skills (`BUNDLED_SKILL_RANK`). */
const BUNDLED_SKILL_RANK = 600;

/** `assets/skills/stock-research/` — kept as the default for compatibility. */
export const SKILL_DIR = skillDir('stock-research');

/** `assets/skills/fund-research/`. */
export const FUND_SKILL_DIR = skillDir('fund-research');

/** Every packaged skill directory, in load order. */
export const SKILL_DIRS = SKILL_NAMES.map((n) => skillDir(n));

/** The plugin's own name — every skill this bundle ships is attributed to it. */
export const PLUGIN_NAME = 'dsh-invest-research';

/** Skill id from a skill directory (`.../assets/skills/<id>/` → `<id>`). */
export function skillIdFromDir(dir) {
  const parts = String(dir).replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : '';
}

/**
 * **Provider name for one packaged skill — must be unique per provider.**
 *
 * The Host's `skills.registerProvider()` **throws on duplicate provider names
 * within one layer** ("Duplicate names within one layer and reserved names
 * throw"). This bundle ships 11 skills, so handing every provider the same name
 * made the first registration succeed and the rest throw; the throw escaped the
 * `ctx.inject` callback, Cordis disposed that inject fiber, and *every*
 * registered provider went with it — the plugin loaded `active` while exposing
 * **zero** skills. The old mock-based smoke test never checked for duplicates,
 * so it stayed green.
 *
 * Namespacing by skill id keeps the plugin attribution readable
 * (`dsh-invest-research:stock-research`) while guaranteeing uniqueness.
 */
export function providerNameFor(dir) {
  const id = skillIdFromDir(dir);
  return id ? `${PLUGIN_NAME}:${id}` : PLUGIN_NAME;
}

/** Parse `name` and `description` out of a SKILL.md and return the body without the front matter. */
export function parseSkillFile(raw) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(raw);
  if (!match) throw new Error('SKILL.md is missing its front matter');
  const field = (key) => {
    const line = new RegExp(`^${key}:[ \\t]*(.*)$`, 'm').exec(match[1]);
    return line ? line[1].trim().replace(/^["']|["']$/g, '') : '';
  };
  return {
    name: field('name'),
    description: field('description'),
    body: match[2].replace(/^[ \t]+/, ''),
  };
}

export function readSkill(dir = SKILL_DIR) {
  return parseSkillFile(fs.readFileSync(dir + 'SKILL.md', 'utf8'));
}

/** A provider object shaped like the Host's `SkillProvider` (declared locally
 *  to avoid a build-time dependency on the Host's types). One provider serves
 *  exactly one packaged skill directory. */
export function createSkillProvider(dir = SKILL_DIR, providerName = providerNameFor(dir)) {
  const resourceBase = { kind: 'directory', path: dir };
  const invocation = { modelInvocable: true, userInvocable: true };
  // Fail at creation when the packaged file is missing or malformed.
  readSkill(dir);
  return {
    name: providerName,
    list: async () => {
      const skill = readSkill(dir);
      return [
        {
          name: skill.name,
          description: skill.description,
          invocation,
          provider: providerName,
          source: 'bundled',
          resourceBase,
          rank: BUNDLED_SKILL_RANK,
          locator: dir + 'SKILL.md',
        },
      ];
    },
    // The Host calls `provider.get(candidate, options)` with the Candidate
    // object it kept from `list()` — never a bare name string. Comparing the
    // argument to the name directly therefore always mismatched and made the
    // skill unresolvable ("unknown or no longer available"). Accept both shapes.
    get: async (candidate) => {
      const current = readSkill(dir);
      const asked = typeof candidate === 'string' ? candidate : candidate?.name;
      if (asked !== undefined && asked !== current.name) return undefined;
      return {
        name: current.name,
        description: current.description,
        invocation,
        provider: providerName,
        source: 'bundled',
        resourceBase,
        content: current.body,
      };
    },
  };
}

/**
 * Register every packaged skill when the Host exposes a skill registry, and
 * report whether they actually landed — the plugin stays functional (a no-op)
 * otherwise. A skill whose SKILL.md is missing/malformed is skipped with a
 * warning; the remaining skills still register.
 *
 * **Every step is guarded on purpose.** The Host's `registerProvider()` throws
 * on a duplicate or reserved provider name, and an unguarded throw would escape
 * this `ctx.inject` callback — Cordis would then dispose the inject fiber and
 * take *all* already-registered providers with it, leaving the plugin `active`
 * but exposing no skills at all. One bad skill must cost exactly one skill.
 */
export function registerSkillsWhenAvailable(ctx, dirs = SKILL_DIRS) {
  const registered = new Set();
  ctx.inject(['skills'], (skillCtx) => {
    const disposers = [];
    for (const dir of dirs) {
      const providerName = providerNameFor(dir);
      let provider;
      try {
        provider = createSkillProvider(dir, providerName);
      } catch (error) {
        skillCtx.logger(providerName).warn(`${providerName} skill not registered: ` + String(error));
        continue;
      }
      // registerProvider returns the Cordis effect disposer that withdraws the provider.
      try {
        disposers.push(skillCtx.skills.registerProvider(() => provider));
        registered.add(dir);
      } catch (error) {
        skillCtx.logger(providerName).warn(
          `${providerName} skill not registered (host rejected the provider): ` + String(error));
      }
    }
    skillCtx.effect(() => () => {
      for (const unregister of disposers.splice(0)) {
        try {
          unregister();
        } catch {
          /* the Host may already have dropped it */
        }
      }
      registered.clear();
    });
  });
  return {
    /** Skill directories that this call managed to register. */
    available: () => [...registered],
    isAvailable: () => registered.size > 0,
  };
}

/** Single-skill registration, kept for callers that register one directory. */
export function registerSkillWhenAvailable(ctx, dir = SKILL_DIR) {
  return registerSkillsWhenAvailable(ctx, [dir]);
}
