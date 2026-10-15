/**
 * stock-research — 多智能体 A 股研究流水线 skill 插件 for DeepSeek Harness.
 *
 * Pure skill bundle: registers the `stock-research` skill (6-role research
 * pipeline with a pre-write PII gate) into the Host's skill registry.
 * It declares NO hard `inject` — Cordis 4.0.4 treats every injected service
 * as required and would hang the plugin if `skills` were absent. The skill is
 * therefore contributed through a scoped `ctx.inject(['skills'], ...)` and the
 * plugin loads fine on hosts without a skill registry (no-op).
 *
 * @module stock-research
 */
import { registerSkillWhenAvailable } from './skill.js';

export const name = 'stock-research';

/** @param ctx - Host context. @param _config - unused (no runtime config in v0.1). */
export function apply(ctx) {
  const skill = registerSkillWhenAvailable(ctx);
  ctx.effect(() => () => {
    // Keep a handle so disposal ordering stays explicit even though the
    // provider disposer is registered inside registerSkillWhenAvailable.
    void skill;
  });
}

export default { name, apply };
