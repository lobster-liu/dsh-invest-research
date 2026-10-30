/**
 * smoke.mjs — 不依赖 DSH 宿主,模拟 Cordis ctx 验证插件的 skill 注册逻辑:
 *   T1 正常宿主: 11 个 skill 都注册上, list()/get() 各自独立, rank/source 正确
 *   T2 无 skills 服务: apply() 不抛错, 静默降级
 *   T3 其中一个 SKILL.md 损坏: 其余照常注册, 坏的那个只 warn
 *   T4 parseSkillFile 边界 + 目录解析
 *   T6 所有 SKILL.md 的 frontmatter 顶层键必须顶格（缩进会让 YAML 解析器整体报错）
 */
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

// 默认仓库根 = 本脚本所在目录的上一级（不依赖 cwd，也不拼出非法 file:// URL；
// Qoder 复核发现的坑：ROOT='.' 时 'file://'+'./lib/skill.js' 的 host 段是 '.'）
const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = resolve(HERE, '..');
const ROOT = (process.argv[2] ?? DEFAULT_ROOT).replace(/\\/g, '/');
// 生产路径约定: skill.js 收到的是以 / 结尾的普通文件系统路径(与 fileURLToPath 输出一致)
const SKILLS_ROOT = ROOT + '/assets/skills/';
const STOCK_DIR = SKILLS_ROOT + 'stock-research/';
const FUND_DIR = SKILLS_ROOT + 'fund-research/';

let pass = 0, fail = 0;
const ok = (name, cond) => {
  console.log((cond ? 'PASS ' : 'FAIL ') + name);
  cond ? pass++ : fail++;
};

function makeCtx({ withSkills = true, rejectNames = [] } = {}) {
  const effects = [];
  const warns = [];
  const registered = [];
  const names = new Set();
  const ctx = {
    inject(deps, cb) {
      if (deps.includes('skills') && !withSkills) return; // Host 无该服务 -> 回调不执行
      cb({
        skills: {
          // 真实 Host 的行为：同一层内 provider 名重复（或命中保留名）会 **throw**。
          // 旧 mock 无条件收下，于是「11 个 provider 共用一个名字」这种必炸的写法
          // 也能全绿 —— 线上表现是第一个注册成功、其余抛出、inject fiber 被销毁并
          // 连带注销已注册的 provider，插件显示 active 却一个技能都没有。
          registerProvider(factory) {
            const provider = factory({ signal: undefined, invalidate() {} });
            const name = provider?.name;
            if (!name) throw new Error('provider has no name');
            if (rejectNames.includes(name)) throw new Error(`reserved provider name: ${name}`);
            if (names.has(name)) throw new Error(`duplicate provider name: ${name}`);
            names.add(name);
            registered.push(factory);
            return () => {
              names.delete(name);
              const at = registered.indexOf(factory);
              if (at >= 0) registered.splice(at, 1);
            };
          },
        },
        logger: () => ({ warn: (m) => warns.push(String(m)) }),
        effect: (fn) => effects.push(fn),
      });
    },
  };
  return { ctx, registered, warns, effects, names };
}

const { registerSkillsWhenAvailable, registerSkillWhenAvailable, createSkillProvider,
        readSkill, parseSkillFile, SKILL_DIRS, providerNameFor, skillIdFromDir, PLUGIN_NAME } =
  await import(pathToFileURL(resolve(ROOT, 'lib/skill.js')).href);

// ---- T1 正常宿主：全部 11 个技能都注册 ----
{
  const { ctx, registered } = makeCtx();
  const h = registerSkillsWhenAvailable(ctx, SKILL_DIRS);
  ok('T1 all skills registered', h.isAvailable() && registered.length === 11);
  ok('T1 available() lists 11 dirs', h.available().length === 11);

  const providers = registered.map((f) => f());
  const all = [];
  for (const p of providers) all.push(...(await p.list()));
  const names = all.map((s) => s.name).sort();
  const expected = [
    'decision-loop', 'fund-profile', 'fund-research', 'fund-screen', 'fund-watch',
    'holdings-style', 'manager-profile', 'pick-funds', 'report-render',
    'stock-research', 'xlsx-author',
  ].sort();
  ok('T1 list has the 11 bundled skills',
     names.length === 11 && names.every((n, i) => n === expected[i]));
  ok('T1 rank=600 source=bundled for all',
     all.every((s) => s.rank === 600 && s.source === 'bundled'));
  // provider 名必须**逐个唯一**：Host 对同层重名直接 throw（见 makeCtx 注释）。
  ok('T1 provider names are unique per skill',
     new Set(all.map((s) => s.provider)).size === all.length);
  ok('T1 provider name is namespaced by the plugin name',
     all.every((s) => s.provider.startsWith(PLUGIN_NAME + ':')));
  ok('T1 provider name carries the skill id',
     all.every((s) => s.provider === PLUGIN_NAME + ':' + s.name));

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
  ok('T4 SKILL_DIRS has 11 entries', SKILL_DIRS.length === 11
     && SKILL_DIRS.every((d) => d.endsWith('/')));
  ok('T4 providerNameFor 带技能 id（逐个唯一）',
     providerNameFor('/x/assets/skills/stock-research/') === PLUGIN_NAME + ':stock-research');
  ok('T4 providerNameFor 接受反斜杠路径',
     providerNameFor('C:\\x\\assets\\skills\\fund-research\\') === PLUGIN_NAME + ':fund-research');
  ok('T4 skillIdFromDir 取末段',
     skillIdFromDir('/a/b/skills/decision-loop/') === 'decision-loop');
  const fund = readSkill(FUND_DIR);
  ok('T4 fund-research description loaded', fund.description.length > 30
     && fund.description.includes('基金'));
}

// ---- T6 frontmatter 结构：顶层键不得缩进 ----
// v0.6.2 上游复核发现 pick-funds 套件 8 个 SKILL.md 把 `tags:` 缩进了 4 空格：
//   - 严格 YAML 解析器直接抛 ScannerError（tags 被并进 author 标量）；
//   - 宽松解析器下 tags 键也不存在。
// 本插件自带的是**行式正则**解析器（只取 name/description，不读 tags），所以注册没炸；
// 但一旦宿主改用 YAML 解析、或任何工具按 tags 过滤/路由，这 8 个技能会整体失效
// （v0.6.1 刚修过「同层重名 → 一个技能都没注册」的同类阻断）。这里加一条离线结构断言。
{
  const bad = [];
  // SKILL_DIRS 项是绝对路径（asset/skills/<name>/），直接拼文件名即可
  for (const dir of SKILL_DIRS) {
    const p = dir + 'SKILL.md';
    let raw;
    try { raw = readFileSync(p, 'utf8'); } catch { bad.push(dir + ' (SKILL.md 缺失)'); continue; }
    const m = /^---\r?\n([\s\S]*?)\r?\n---/.exec(raw);
    if (!m) { bad.push(dir + ' (无 frontmatter)'); continue; }
    m[1].split(/\r?\n/).forEach((line, i) => {
      // 顶层键必须顶格；缩进的 `key:` 会让 YAML 把它并入上一个标量值
      if (/^\s+\S/.test(line) && /^\s*\S[^:]*:/.test(line)) {
        bad.push(`${dir}:第${i + 1}行 缩进顶层键「${line.trim()}」`);
      }
    });
  }
  ok('T6 无缩进的顶层 frontmatter 键（pick-funds 套件 tags 已顶格）', bad.length === 0);
  if (bad.length) console.log('    ' + bad.join('\n    '));
}

// ---- T5 注册健壮性：单个 provider 被 Host 拒绝，其余照常注册 ----
{
  // 只拒绝 decision-loop 的名字，模拟 Host 对该名 throw（保留名/重名等）。
  const rejected = PLUGIN_NAME + ':decision-loop';
  const { ctx, registered, warns } = makeCtx({ rejectNames: [rejected] });
  const h = registerSkillsWhenAvailable(ctx, SKILL_DIRS);
  ok('T5 被拒绝的那个技能不影响其余 10 个', h.isAvailable() && registered.length === 10);
  ok('T5 被拒绝时只 warn 不崩', warns.length === 1 && warns[0].includes('decision-loop'));
  const providers = registered.map((f) => f());
  ok('T5 被拒绝的技能确实不在结果里',
     !providers.some((p) => p.name === rejected));
  ok('T5 其余技能仍然可取到 body',
     !!(await providers[0].get((await providers[0].list())[0])));
}

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
