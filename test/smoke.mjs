/**
 * smoke.mjs — 不依赖 DSH 宿主,模拟 Cordis ctx 验证插件的 skill 注册逻辑:
 *   T1 正常宿主: list() 返回 stock-research 条目, get() 有正文, rank/source 正确
 *   T2 无 skills 服务: apply() 不抛错, 静默降级
 *   T3 SKILL.md 缺失/坏 frontmatter: warn 不 crash
 */
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const ROOT = (process.argv[2] ?? '.').replace(/\\/g, '/');
// 生产路径约定: skill.js 收到的是以 / 结尾的普通文件系统路径(与 fileURLToPath 输出一致)
const SKILL_DIR = ROOT + '/assets/skills/stock-research/';

let pass = 0, fail = 0;
const ok = (name, cond) => {
  console.log((cond ? 'PASS ' : 'FAIL ') + name);
  cond ? pass++ : fail++;
};

function makeCtx({ withSkills = true } = {}) {
  const effects = [];
  const warns = [];
  const registered = [];
  const ctx = {
    inject(deps, cb) {
      if (deps.includes('skills') && !withSkills) return; // Host 无该服务 -> 回调不执行
      cb({
        skills: {
          registerProvider(factory) {
            registered.push(factory);
            return () => registered.shift();
          },
        },
        logger: () => ({ warn: (m) => warns.push(String(m)) }),
        effect: (fn) => effects.push(fn),
      });
    },
  };
  return { ctx, registered, warns, effects };
}

const { registerSkillWhenAvailable, createSkillProvider, readSkill, parseSkillFile } =
  await import('file://' + (ROOT + '/lib/skill.js').replace(/\\/g, '/'));

// ---- T1 正常宿主 ----
{
  const { ctx, registered } = makeCtx();
  const h = registerSkillWhenAvailable(ctx, SKILL_DIR);
  ok('T1 registered with host', h.isAvailable() && registered.length === 1);
  const provider = registered[0]();
  const list = await provider.list();
  ok('T1 list name=stock-research', list.length === 1 && list[0].name === 'stock-research');
  ok('T1 rank=600 source=bundled', list[0].rank === 600 && list[0].source === 'bundled');
  // The real Host calls get(candidate) with the Candidate object it kept from
  // list() (dsh-skill/lib/index.js: `match.provider.get(match.candidate, options)`).
  // Testing only the string form hid a bug that made the skill unresolvable
  // ("unknown or no longer available") on the live Host.
  const gotByCandidate = await provider.get(list[0]);
  ok('T1 get(candidate) has body', !!gotByCandidate && gotByCandidate.content.includes('多智能体'));
  const got = await provider.get('stock-research');
  ok('T1 get() has body', !!got && got.content.includes('多智能体'));
  ok('T1 get() unknown name -> undefined', (await provider.get('nope')) === undefined);
  ok('T1 get() foreign candidate -> undefined', (await provider.get({ name: 'other-skill' })) === undefined);
  const skill = readSkill(SKILL_DIR);
  ok('T1 description loaded', skill.description.length > 30);
}

// ---- T2 无 skills 服务(老宿主/精简 profile) ----
{
  const { ctx, registered, warns } = makeCtx({ withSkills: false });
  const h = registerSkillWhenAvailable(ctx, SKILL_DIR);
  ok('T2 silent no-op', h.isAvailable() === false && registered.length === 0 && warns.length === 0);
}

// ---- T3 坏 SKILL.md(缺 frontmatter) -> warn 不 crash ----
{
  const tmp = mkdtempSync(join(tmpdir(), 'sk-bad-'));
  writeFileSync(join(tmp, 'SKILL.md'), 'no frontmatter here', 'utf8');
  const { ctx, warns } = makeCtx();
  let threw = false;
  try { registerSkillWhenAvailable(ctx, tmp.replace(/\\/g, '/') + '/'); }
  catch { threw = true; }
  ok('T3 malformed -> warn not crash', !threw && warns.length === 1);
  rmSync(tmp, { recursive: true, force: true });
}

// ---- T4 parseSkillFile 边界 ----
{
  const r = parseSkillFile('---\nname: a\n---\nbody with ```powershell block```');
  ok('T4 parse keeps body', r.name === 'a' && r.body.includes('powershell'));
}

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
