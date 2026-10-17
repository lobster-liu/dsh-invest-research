/**
 * smoke.mjs — 不依赖 DSH 宿主,模拟 Cordis ctx 验证插件的 skill 注册逻辑:
 *   T1 正常宿主: 两个 skill 都注册上, list()/get() 各自独立, rank/source 正确
 *   T2 无 skills 服务: apply() 不抛错, 静默降级
 *   T3 其中一个 SKILL.md 损坏: 另一个照常注册, 坏的那个只 warn
 *   T4 parseSkillFile 边界 + 目录解析
 */
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const ROOT = (process.argv[2] ?? '.').replace(/\\/g, '/');
// 生产路径约定: skill.js 收到的是以 / 结尾的普通文件系统路径(与 fileURLToPath 输出一致)
const SKILLS_ROOT = ROOT + '/assets/skills/';
const STOCK_DIR = SKILLS_ROOT + 'stock-research/';
const FUND_DIR = SKILLS_ROOT + 'fund-research/';

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

const { registerSkillsWhenAvailable, registerSkillWhenAvailable, createSkillProvider,
        readSkill, parseSkillFile, SKILL_DIRS, providerNameFor } =
  await import('file://' + (ROOT + '/lib/skill.js').replace(/\\/g, '/'));

// ---- T1 正常宿主：两个 skill 都注册 ----
{
  const { ctx, registered } = makeCtx();
  const h = registerSkillsWhenAvailable(ctx, SKILL_DIRS);
  ok('T1 both skills registered', h.isAvailable() && registered.length === 2);
  ok('T1 available() lists 2 dirs', h.available().length === 2);

  const providers = registered.map((f) => f());
  const all = [];
  for (const p of providers) all.push(...(await p.list()));
  const names = all.map((s) => s.name).sort();
  ok('T1 list has stock-research + fund-research',
     names.length === 2 && names[0] === 'fund-research' && names[1] === 'stock-research');
  ok('T1 rank=600 source=bundled for both',
     all.every((s) => s.rank === 600 && s.source === 'bundled'));
  ok('T1 provider is the plugin name for both skills',
     all.every((s) => s.provider === 'dsh-invest-research'));

  // The real Host calls get(candidate) with the Candidate object it kept from
  // list() (dsh-skill/lib/index.js: `match.provider.get(match.candidate, options)`).
  // Testing only the string form hid a bug that made the skill unresolvable
  // ("unknown or no longer available") on the live Host.
  const byCandidate = await providers[0].get(all[0]);
  ok('T1 get(candidate) has body', !!byCandidate && typeof byCandidate.content === 'string'
     && byCandidate.content.length > 200);
  const byName = await providers[0].get('stock-research');
  ok('T1 get(name) has body', !!byName && byName.content.includes('多智能体'));
  ok('T1 get() unknown name -> undefined', (await providers[0].get('nope')) === undefined);
  ok('T1 get() foreign candidate -> undefined',
     (await providers[0].get({ name: 'other-skill' })) === undefined);
  // 每个 provider 只服务自己那个 skill，不能串台：
  // providers[0] 是 stock-research，问它要 fund-research 必须给 undefined
  ok('T1 provider refuses the other skill',
     (await providers[0].get('fund-research')) === undefined);
  ok('T1 fund provider serves fund-research',
     !!(await providers[1].get('fund-research')));
}

// ---- T1b 单个 skill 的兼容入口(registerSkillWhenAvailable) ----
{
  const { ctx, registered } = makeCtx();
  const h = registerSkillWhenAvailable(ctx, STOCK_DIR);
  ok('T1b single-skill entry works', h.isAvailable() && registered.length === 1);
  const p = registered[0]();
  const l = await p.list();
  ok('T1b single list = stock-research', l.length === 1 && l[0].name === 'stock-research');
}

// ---- T2 无 skills 服务(老宿主/精简 profile) ----
{
  const { ctx, registered, warns } = makeCtx({ withSkills: false });
  const h = registerSkillsWhenAvailable(ctx, SKILL_DIRS);
  ok('T2 silent no-op', h.isAvailable() === false && registered.length === 0 && warns.length === 0);
}

// ---- T3 其中一个 SKILL.md 坏(缺 frontmatter) -> 只 warn, 另一个照常注册 ----
{
  const { ctx, registered, warns } = makeCtx();
  // 把 stock-research 临时换成坏文件: 用一个只含 fund-research 的目录列表 + 一个坏目录
  const bad = mkdtempSync(join(tmpdir(), 'sk-bad-'));
  writeFileSync(join(bad, 'SKILL.md'), 'no frontmatter here', 'utf8');
  let threw = false;
  try {
    registerSkillsWhenAvailable(ctx, [bad.replace(/\\/g, '/') + '/', FUND_DIR]);
  } catch { threw = true; }
  ok('T3 malformed -> warn not crash', !threw && warns.length === 1);
  ok('T3 the good skill still registered', registered.length === 1);
  const p = registered[0]();
  const l = await p.list();
  ok('T3 surviving skill is fund-research', l.length === 1 && l[0].name === 'fund-research');
  rmSync(bad, { recursive: true, force: true });
}

// ---- T4 解析与目录工具 ----
{
  const r = parseSkillFile('---\nname: a\n---\nbody with ```powershell block```');
  ok('T4 parse keeps body', r.name === 'a' && r.body.includes('powershell'));
  ok('T4 SKILL_DIRS has 2 entries', SKILL_DIRS.length === 2
     && SKILL_DIRS.every((d) => d.endsWith('/')));
  ok('T4 providerNameFor returns the plugin name',
     providerNameFor('/x/stock-research/') === 'dsh-invest-research');
  const fund = readSkill(FUND_DIR);
  ok('T4 fund-research description loaded', fund.description.length > 30
     && fund.description.includes('基金'));
}

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
