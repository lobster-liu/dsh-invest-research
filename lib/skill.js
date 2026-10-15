/**
 * The bundled `stock-research` skill: a 6-role multi-agent A-share research
 * pipeline (orchestrator / data / policy / valuation / risk / auditor) that
 * emits source-cited reports behind a pre-write PII gate.
 *
 * The skill is registered with the Host's skill registry when that service
 * exists. It must never be a hard dependency of the plugin: Cordis 4.0.4 treats
 * every declared `inject` as required, so a missing `skills` service would hang
 * the whole plugin. The plugin therefore asks for it through a scoped
 * `ctx.inject(['skills'], ...)` and works the same without it.
 *
 * The packaged SKILL.md is re-read on every call, so a provider object is
 * never stale.
 * @module stock-research/skill
 */
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

export const SKILL_NAME = 'stock-research';
const PROVIDER_NAME = 'dsh-stock-research';

/** Same rank the Host gives packaged skills (`BUNDLED_SKILL_RANK`). */
const BUNDLED_SKILL_RANK = 600;

/** `assets/skills/stock-research/`, resolved next to the built `lib/`. */
export const SKILL_DIR = fileURLToPath(new URL('../assets/skills/stock-research/', import.meta.url));

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
 *  to avoid a build-time dependency on the Host's types). */
export function createSkillProvider(dir = SKILL_DIR) {
  const resourceBase = { kind: 'directory', path: dir };
  const invocation = { modelInvocable: true, userInvocable: true };
  // Fail at creation when the packaged file is missing or malformed.
  readSkill(dir);
  return {
    name: PROVIDER_NAME,
    list: async () => {
      const skill = readSkill(dir);
      return [
        {
          name: skill.name,
          description: skill.description,
          invocation,
          provider: PROVIDER_NAME,
          source: 'bundled',
          resourceBase,
          rank: BUNDLED_SKILL_RANK,
          locator: dir + 'SKILL.md',
        },
      ];
    },
    get: async (name) => {
      const current = readSkill(dir);
      if (name !== current.name) return undefined;
      return {
        name: current.name,
        description: current.description,
        invocation,
        provider: PROVIDER_NAME,
        source: 'bundled',
        resourceBase,
        content: current.body,
      };
    },
  };
}

/**
 * Register the skill when the Host exposes a skill registry, and report whether
 * it actually landed — the plugin stays functional (a no-op) otherwise.
 */
export function registerSkillWhenAvailable(ctx, dir = SKILL_DIR) {
  let available = false;
  ctx.inject(['skills'], (skillCtx) => {
    let provider;
    try {
      provider = createSkillProvider(dir);
    } catch (error) {
      skillCtx.logger(PROVIDER_NAME).warn(`${PROVIDER_NAME} skill not registered: ` + String(error));
      return;
    }
    // registerProvider returns the Cordis effect disposer that withdraws the provider.
    const unregister = skillCtx.skills.registerProvider(() => provider);
    available = true;
    skillCtx.effect(() => () => {
      try {
        unregister();
      } catch {
        /* the Host may already have dropped it */
      }
      available = false;
    });
  });
  return { isAvailable: () => available };
}
