/**
 * dsh-invest-research — multi-agent equity & fund research skill bundle for
 * DeepSeek Harness.
 *
 * Pure skill bundle: registers the packaged skills (`stock-research` — A-share
 * single-name pipeline; `fund-research` — fund look-through pipeline) into the
 * Host's skill registry. Both emit source-cited reports behind the same
 * pre-write PII gate.
 *
 * It declares NO hard `inject` — Cordis 4.0.4 treats every injected service as
 * required and would hang the plugin if `skills` were absent. The skills are
 * therefore contributed through a scoped `ctx.inject(['skills'], ...)` and the
 * plugin loads fine on hosts without a skill registry (no-op).
 *
 * @module dsh-invest-research
 */
import { registerSkillsWhenAvailable } from './skill.js';

export const name = 'dsh-invest-research';

/** @param ctx - Host context. @param _config - unused (skills are packaged). */
export function apply(ctx) {
  const skills = registerSkillsWhenAvailable(ctx);
  ctx.effect(() => () => {
    // Keep a handle so disposal ordering stays explicit even though the
    // provider disposer is registered inside registerSkillsWhenAvailable.
    void skills;
  });
}

export default { name, apply };
