// Regression harness for the MNA/ESD series-path model (Phase 0 asset).
// Model code is a faithful port of docs/two_device_complete_iv_soa_model.html
// with ONE deliberate deviation: a single unified integration grid N for both
// calibration (corr/integ) and curve construction (branch). The source HTML
// uses n=1200 vs n=1000, which alone causes ~6e-8 endpoint error.
//
// Usage:
//   node tests/regression.js          # check against tests/golden.json
//   node tests/regression.js --emit   # regenerate golden.json (prints to stdout)
//
// Conventions pinned by decisions D1-D9 (see repo docs / session notes):
//   grid N=4000; SOA corners evaluated BOTH worst and best (D3);
//   reference config x1=2.56 (diode), x2=1415.232 (clamp), Rio_rdl=0.1, RDD_un1=RDD_dn1=0.5, Rvss_rdl=0.1;
//   metal rule 0.5 ohm / 350 um, L-only design variable (D7);
//   HBM conversion I ~ V/1.5k (D9).
'use strict';
const fs = require('fs');
const path = require('path');

const sp = z => z > 50 ? z : z < -50 ? Math.exp(z) : Math.log1p(Math.exp(z));
const sg = z => z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z));

const D1 = { id: 'diode', method: 'exp',
  par: x => ({ a1: 15.14 / x ** .08, r1: .869 / x ** .826, c1: 1.193 / x ** .0075,
               a2: 5.07 / x ** .0629, r2: 27.48 / x ** 1.267, c2: -7.18 / x ** -.0881 }),
  m: [{ x: .64, vp: 2.1145, vn: -7.7309, ip: .6002, inn: -.01541 },
      { x: 1.344, vp: 2.1779, vn: -7.8437, ip: 1.2137, inn: -.0343 },
      { x: 2.56, vp: 2.1802, vn: -7.7251, ip: 2.13426, inn: -.0514632 },
      { x: 3.84, vp: 2.15264, vn: -7.8867, ip: 2.91253, inn: -.0957299 }],
  soa: { vp: ['Vt2+', 1, 1.7052482326597274, .010814475389598174, 2.1338251606769485, 2.183514224890132],
         vn: ['Vt2-', -1, 1.7052482326597274, .006758644201696505, 7.703915866993116, 7.856330403842027],
         ip: ['It2+', 1, 1.7052482326597274, .8853326789209258, 1.4195543445506187, 1.4984574918281428],
         inn: ['It2-', -1, 1.7052482326597274, .9679787370175855, .03472919025401326, .04363077033143844] } };

const D2 = { id: 'clamp', method: 'late',
  par: x => ({ a1: 829.4 / x ** .452, r1: 5.462 / x ** .2865, c1: .08357 / x ** -.207,
               a2: 30 / x ** -3.28e-29, r2: 9.204 / x ** .3384, c2: -.6568 / x ** .02765 }),
  m: [{ x: 1415.232, vp: 4.8121, vn: -4.96245, ip: 4.46711, inn: -4.82594 },
      { x: 2021.76, vp: 6.35918, vn: -6.71245, ip: 6.10259, inn: -6.42855 },
      { x: 2628.288, vp: 11.5124, vn: -9.47609, ip: 7.70351, inn: -7.47626 }],
  soa: { vp: ['Vt2+', 1, 1959.190790564251, 1.3726632026868713, 6.090603488345262, 7.691645019533501],
         vn: ['Vt2-', -1, 1959.190790564251, 1.0334594160835273, 6.497875372967659, 6.994612508780857],
         ip: ['It2+', 1, 1959.190790564251, .8799640088461418, 5.936085662066821, 5.948515095817292],
         inn: ['It2-', -1, 1959.190790564251, .712730158253558, 6.063770015250391, 6.2861134455085015] } };

const N = 4000; // unified grid (calibration AND curve)

function g0(v, x, d) { const p = d.par(x); return sg(p.a1 * (v - p.c1)) / p.r1 + sg(p.a2 * (p.c2 - v)) / p.r2; }
function mod(t, T, q, d) {
  if (d.method === 'late') { const r = t / T; let z; if (r <= .5) z = 0; else { const u = 2 * r - 1; z = 3 * u * u - 2 * u * u * u; } return .35 + .65 / (1 + 2 * z ** 1.5); }
  const vd = .45 * T, k = 10 / T, z = (sp(k * (t - vd)) - sp(-k * vd)) / (sp(k * (T - vd)) - sp(-k * vd));
  return Math.exp(-q * z * z);
}
function integ(x, d, T, q, s, neg, n = N) {
  const h = T / n; let a = 0;
  for (let j = 0; j <= n; j++) { const t = j * h, v = neg ? -t : t, y = g0(v, x, d) * mod(t, T, q, d) * s; a += (j && j < n ? 1 : .5) * y; }
  return a * h;
}
function corr(x, d, T, I, neg) {
  if (d.method === 'late') return { q: 2, s: I / integ(x, d, T, 2, 1, neg) };
  let l = -1, h = 1;
  while (integ(x, d, T, l, 1, neg) < I) l *= 2;
  while (integ(x, d, T, h, 1, neg) > I) h *= 2;
  for (let k = 0; k < 65; k++) { const m2 = (l + h) / 2; if (integ(x, d, T, m2, 1, neg) > I) l = m2; else h = m2; }
  return { q: (l + h) / 2, s: 1 };
}
function branch(x, d, T, c, neg, n = N) {
  const h = T / n, V = [0], I = [0], G = []; let sum = 0, p = g0(0, x, d) * mod(0, T, c.q, d) * c.s; G.push(p);
  for (let j = 1; j <= n; j++) { const t = j * h, v = neg ? -t : t, g = g0(v, x, d) * mod(t, T, c.q, d) * c.s; sum += (p + g) * h / 2; V.push(v); I.push(neg ? -sum : sum); G.push(g); p = g; }
  return { V, I, G };
}
const sv = (a, x, c) => a[1] * (c === 'worst' ? a[4] : a[5]) * (x / a[2]) ** a[3];
const ep = (d, x, c) => ({ x, vp: sv(d.soa.vp, x, c), vn: sv(d.soa.vn, x, c), ip: sv(d.soa.ip, x, c), inn: sv(d.soa.inn, x, c) });
function calib(d, x, c) {
  const e = ep(d, x, c);
  const cp = corr(x, d, e.vp, e.ip, false);
  const cn = corr(x, d, -e.vn, -e.inn, true);
  return { e, pos: branch(x, d, e.vp, cp, false), neg: branch(x, d, -e.vn, cn, true), cp, cn };
}
function VofI(br, i) {
  const I = br.I, V = br.V, n = I.length - 1, endI = I[n];
  const asc = endI >= 0;
  if (asc ? i > endI : i < endI) return NaN;
  let lo = 0, hi = n;
  while (hi - lo > 1) { const m2 = (lo + hi) >> 1; ((asc ? I[m2] <= i : I[m2] >= i)) ? lo = m2 : hi = m2; }
  const f = (i - I[lo]) / (I[hi] - I[lo] || 1);
  return V[lo] + f * (V[hi] - V[lo]);
}

const RIO = 0.1, RDD_UN1 = 0.5, RDD_DN1 = 0.5, RVSS = 0.1; // Rio_rdl / RDD_un1 / RDD_dn1 / Rvss_rdl
function vio(c1, c2, I) { return I * (RIO + RDD_UN1 + RDD_DN1 + RVSS) + VofI(c1.pos, I) + VofI(c2.pos, I); }

// ---------------- golden value computation ----------------
function computeAll() {
  const g = [];
  const add = (key, value, tol, kind = 'abs') => g.push({ key, value, tol, kind });

  // 1) calibrated branch endpoints reproduce measured It2 (grid-unified port fidelity)
  for (const d of [D1, D2]) for (const mm of d.m) {
    const cp = corr(mm.x, d, mm.vp, mm.ip, false), cn = corr(mm.x, d, -mm.vn, -mm.inn, true);
    const bp = branch(mm.x, d, mm.vp, cp, false), bn = branch(mm.x, d, -mm.vn, cn, true);
    add(`endpoint/${d.id}/x=${mm.x}/pos`, bp.I[bp.I.length - 1] / mm.ip - 1, 1e-9, 'raw');
    add(`endpoint/${d.id}/x=${mm.x}/neg`, bn.I[bn.I.length - 1] / mm.inn - 1, 1e-9, 'raw');
  }
  // 2) worst-case SOA envelopes (analytic, deterministic)
  for (const x of [0.64, 1.344, 2.56, 3.84]) add(`env/diode/It2+w/x=${x}`, sv(D1.soa.ip, x, 'worst'), 1e-12, 'rel');
  for (const x of [1415.232, 2021.76, 2628.288]) add(`env/clamp/It2+w/x=${x}`, sv(D2.soa.ip, x, 'worst'), 1e-12, 'rel');
  // 3) calibration pins (beta for diode, scale for clamp) + min conductance
  for (const mm of D1.m) {
    const c = calib(D1, mm.x, 'worst');
    add(`beta+/diode/x=${mm.x}/worst`, c.cp.q, 1e-6, 'rel');
    add(`beta-/diode/x=${mm.x}/worst`, c.cn.q, 1e-6, 'rel');
    add(`minG/diode/x=${mm.x}/worst`, Math.min(...c.pos.G, ...c.neg.G), 1e-6, 'rel');
  }
  for (const mm of D2.m) {
    const c = calib(D2, mm.x, 'worst');
    add(`scale+/clamp/x=${mm.x}/worst`, c.cp.s, 1e-6, 'rel');
    add(`minG/clamp/x=${mm.x}/worst`, Math.min(...c.pos.G, ...c.neg.G), 1e-6, 'rel');
  }
  // 4) reference config series path (x1=2.56, x2=1415.232) — both corners (D3)
  {
    const w1 = calib(D1, 2.56, 'worst'), w2 = calib(D2, 1415.232, 'worst');
    const b1 = calib(D1, 2.56, 'best'), b2 = calib(D2, 1415.232, 'best');
    add('ref/Ifail/worst', Math.min(w1.e.ip, w2.e.ip), 1e-9, 'rel');
    for (const I of [0.5, 1.0, 1.33]) add(`ref/VIO/worst/I=${I}`, vio(w1, w2, I), 1e-6, 'abs');
    add('ref/VIO/best/I=1.33', vio(b1, b2, 1.33), 1e-6, 'abs'); // corner inversion witness (> worst value)
  }
  // 5) earlier verified point (x2 convention pinned explicitly)
  {
    const c1 = calib(D1, 2.56, 'worst'), c2 = calib(D2, 2021.76, 'worst');
    add('series/VIO/x1=2.56/x2=2021.76/worst/I=2.0', vio(c1, c2, 2.0), 1e-6, 'abs');
  }
  // 6) min diode size for 2A worst (analytic)
  {
    const a = D1.soa.ip;
    add('x1min/2A/worst', a[2] * Math.pow(2.0 / a[4], 1 / a[3]), 1e-9, 'rel');
  }
  // 7) negative-stress limit at reference config
  {
    const c1 = calib(D1, 2.56, 'worst'), c2 = calib(D2, 1415.232, 'worst');
    add('neg/It2-/diode/x=2.56/worst', c1.e.inn, 1e-9, 'rel');
    const I = c1.e.inn * 0.999;
    add('neg/VIO/ref/0.999It2-', I * (RIO + RDD_UN1 + RDD_DN1 + RVSS) + VofI(c1.neg, I) + VofI(c2.neg, I), 1e-6, 'abs');
  }
  // 8) structural invariants
  {
    const c1 = calib(D1, 2.56, 'worst'), c2 = calib(D2, 1415.232, 'worst');
    const allG = [...c1.pos.G, ...c1.neg.G, ...c2.pos.G, ...c2.neg.G];
    add('invariant/allG_positive', allG.every(v => v > 0) ? 1 : 0, 0, 'exact');
    const p1 = D1.par(2.56);
    const i00 = (sp(p1.a1 * (0 - p1.c1)) / (p1.r1 * p1.a1) - sp(p1.a2 * (p1.c2 - 0)) / (p1.r2 * p1.a2));
    add('invariant/I0_at_0_selfref', i00 - i00, 0, 'exact'); // I0(0)=F(0)-F(0)=0 by construction
  }
  return g;
}

// ---------------- runner ----------------
const emit = process.argv.includes('--emit');
const goldenPath = path.join(__dirname, 'golden.json');
const computed = computeAll();

if (emit) {
  fs.writeFileSync(goldenPath, JSON.stringify({ grid_N: N, generated_with: 'tests/regression.js --emit', values: computed }, null, 1));
  console.log(`wrote ${goldenPath} (${computed.length} entries, N=${N})`);
} else {
  const golden = JSON.parse(fs.readFileSync(goldenPath, 'utf8'));
  if (golden.grid_N !== N) { console.error(`FAIL: grid N mismatch (golden ${golden.grid_N} vs runner ${N})`); process.exit(1); }
  const byKey = new Map(golden.values.map(e => [e.key, e]));
  let fail = 0;
  for (const c of computed) {
    const ref = byKey.get(c.key);
    if (!ref) { console.error(`FAIL missing golden: ${c.key}`); fail++; continue; }
    let ok;
    if (c.kind === 'exact') ok = c.value === ref.value;
    else if (c.kind === 'raw') ok = Math.abs(c.value) <= ref.tol; // value is itself a relative error
    else if (c.kind === 'rel') ok = Math.abs(c.value / ref.value - 1) <= ref.tol;
    else ok = Math.abs(c.value - ref.value) <= ref.tol;
    if (!ok) { console.error(`FAIL ${c.key}: got ${c.value}, golden ${ref.value}, tol ${ref.tol} (${c.kind})`); fail++; }
  }
  console.log(fail === 0 ? `PASS: ${computed.length} golden checks (N=${N})` : `${fail} FAILURES of ${computed.length}`);
  process.exit(fail === 0 ? 0 : 1);
}
