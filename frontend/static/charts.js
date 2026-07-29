/* mna 공통 차트 라이브러리 — 모든 화면의 그래프는 이 파일만 사용한다.
   규칙: 데이터 시리즈는 실선 기본(점선은 한계선 등 주석용만),
   worst corner = MNA.C.worst(붉은계열), best corner = MNA.C.best(푸른계열),
   corner 의미가 없는 시리즈는 MNA.C.s[...] 중립 팔레트.
   기본 크기는 소형(340×205) — 페이지에서 grid-2/3/4로 수평 배열한다. */
'use strict';
window.MNA = (function () {
  const C = {
    worst: '#b3261e', worst2: '#e0663a',
    best: '#0b57a4', best2: '#56b4e9',
    accent: '#1f5f99',
    s: ['#1f5f99', '#00796b', '#6a4fa3', '#8a6d00', '#444444'],
    gray: '#5b6673', pass: '#0a7d38', fail: '#b3261e', gold: '#c88a00',
    grid: '#eceff3', frame: '#c6ccd4',
  };

  // 보기 배율 (사용자 지시 2026-07-29, viewctl.js overlay가 구동):
  // font = SVG 내부 글자 크기 배율(생성된 font-size 후처리),
  // h = lineChart/soaMap viewBox 높이 배율 — viewBox라 내부 그래프가 좌표계째 확대.
  // radar는 방사형(폭 구속)이라 높이 배율 비적용, gauge는 HTML이라 페이지 배율이 담당.
  const SZ = { font: 1, h: 1 };
  const REG = new Map();  // el → {fn, args}: 마지막 렌더 재현용 (배율 변경 시 전체 재렌더)
  function remember(el, fn, args) {
    if (REG.size > 400) REG.forEach((v, k) => { if (!document.contains(k)) REG.delete(k); });
    REG.set(el, { fn: fn, args: args });
  }
  function setScale(font, h) {
    SZ.font = (isFinite(font) && font > 0) ? font : 1;
    SZ.h = (isFinite(h) && h > 0) ? h : 1;
    REG.forEach((r, el) => {
      if (!document.contains(el)) { REG.delete(el); return; }
      r.fn.apply(null, r.args);
    });
  }
  function emit(el, s) {  // SVG 문자열 마감 — font 배율은 생성물 후처리로 일괄 적용
    if (SZ.font !== 1)
      s = s.replace(/font-size="([0-9.]+)"/g,
        (m, v) => 'font-size="' + (parseFloat(v) * SZ.font).toFixed(2) + '"');
    el.innerHTML = s + '</svg>';
  }

  function fmtN(v) {
    const a = Math.abs(v);
    if (a >= 1000) return v.toFixed(0);
    if (a >= 10) return v.toFixed(1);
    if (a >= .01 || a === 0) return (+v.toFixed(3)).toString();
    return v.toExponential(0);
  }
  function f(v, d) {
    return (v === null || v === undefined || !isFinite(v)) ? '—' : (+v).toFixed(d === undefined ? 3 : d);
  }
  function pct(v) { return (100 * v).toFixed(1) + '%'; }

  // 공통 선형 차트: series[{x,y,color,label,dash?}], hlines/vlines, points, shade[x0,x1]
  function lineChart(el, o) {
    remember(el, lineChart, arguments);
    // 여백은 눈금 라벨 실폭에서 계산 — SVG는 overflow:hidden이라 viewBox를 넘는 글자가
    // 잘린다(우측 끝 x 눈금이 대표 증상). 글자 배율(SZ.font)도 함께 반영.
    const TFS = 8.5 * SZ.font;               // 눈금 글자 크기 (emit 후 실제 크기)
    const tw = t => String(t).length * 0.56 * TFS;   // 숫자 글리프 평균 폭 (여백 산정용)
    const twC = t => String(t).length * 0.65 * TFS;  // 클램프용 보수적 추정(−·% 등 넓은 글리프)
    const grow = Math.max(0, SZ.font - 1);
    const W = o.w || 340, H = (o.h || 205) * SZ.h;
    const mT = (o.title ? 20 : 8) + grow * 14, mB = 31 + grow * 20;
    let mL = 44, mR = 8;
    let xs = [], ys = [];
    (o.series || []).forEach(s => { xs = xs.concat(s.x); ys = ys.concat(s.y); });
    (o.hlines || []).forEach(h => ys.push(h.y));
    (o.vlines || []).forEach(h => xs.push(h.x));
    (o.points || []).forEach(p => { xs.push(p.x); ys.push(p.y); });
    xs = xs.filter(isFinite); ys = ys.filter(isFinite);
    if (!xs.length) { el.innerHTML = ''; return; }
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (o.origin || o.sym) { x0 = Math.min(x0, 0); x1 = Math.max(x1, 0); y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
    if (o.sym) { // 양/음 최대 대칭 — 원점이 항상 plot 정중앙 (snap도 대칭 유지)
      const mx = Math.max(-x0, x1), my = Math.max(-y0, y1);
      x0 = -mx; x1 = mx; y0 = -my; y1 = my;
    }
    if (x0 === x1) { x0 -= 1; x1 += 1; } if (y0 === y1) { y0 -= 1; y1 += 1; }
    const px = (x1 - x0) * .03, py = (y1 - y0) * .07; x0 -= px; x1 += px; y0 -= py; y1 += py;
    // graph 기본: 눈금은 1-2-5 계열의 '딱 떨어지는' step, 0에 정렬 —
    // 축 경계를 step 배수로 snap하면 0이 범위 안에 있을 때 항상 정확한 눈금이 된다.
    function niceStep(span, target) {
      const raw = span / target, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p;
      return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
    }
    const xst = niceStep(x1 - x0, 4), yst = niceStep(y1 - y0, 4);
    x0 = Math.floor(x0 / xst) * xst; x1 = Math.ceil(x1 / xst) * xst;
    y0 = Math.floor(y0 / yst) * yst; y1 = Math.ceil(y1 / yst) * yst;
    // 마지막 x 눈금은 중앙정렬이라 반폭이 우측으로 넘친다. 여백은 필요분의 절반만 주고
    // (사용자 지시 2026-07-29 — 그래프 간 간격 과다), 나머지는 라벨 위치 클램프로 흡수.
    mR = Math.max(mR, (mR + tw(fmtN(x1)) / 2 + 2) / 2);
    // y 눈금은 우측정렬(mL−4 기준)이라 최장 라벨 전폭이 mL 안에 들어와야 한다.
    let ylw = 0;
    for (let n = Math.round(y0 / yst); n <= Math.round(y1 / yst); n++)
      ylw = Math.max(ylw, tw(fmtN(n * yst)));
    mL = Math.max(mL, ylw + 8);
    const X = x => mL + (x - x0) / (x1 - x0) * (W - mL - mR);
    const Y = y => H - mB - (y - y0) / (y1 - y0) * (H - mT - mB);
    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
    if (o.shade) {
      const a = X(Math.max(x0, o.shade[0])), b = X(Math.min(x1, o.shade[1]));
      s += '<rect x="' + a + '" y="' + mT + '" width="' + (b - a) + '" height="' + (H - mT - mB) + '" fill="#eef3f8"/>';
    }
    if (o.shadeRect) { // SOA 안전영역 등 2D 박스 음영 [x0,y0,x1,y1] — plot 영역으로 클램프
      const a = X(Math.max(x0, o.shadeRect[0])), b = X(Math.min(x1, o.shadeRect[2]));
      const t = Y(Math.min(y1, o.shadeRect[3])), bt = Y(Math.max(y0, o.shadeRect[1]));
      if (b > a && bt > t)
        s += '<rect x="' + a + '" y="' + t + '" width="' + (b - a) + '" height="' + (bt - t)
          + '" fill="' + (o.shadeColor || 'rgba(10,125,56,.10)') + '"/>';
    }
    for (let n = Math.round(x0 / xst); n <= Math.round(x1 / xst); n++) {
      const xv = n * xst, zero = n === 0;  // 원점 축은 진하게
      s += '<line x1="' + X(xv) + '" y1="' + mT + '" x2="' + X(xv) + '" y2="' + (H - mB) + '" stroke="'
        + (zero ? '#aeb7c2' : C.grid) + '"/>'
        // 양 끝 눈금 라벨은 viewBox 안으로 클램프 — 여백을 늘리지 않고 잘림만 막는다
        + '<text x="' + Math.min(Math.max(X(xv), twC(fmtN(xv)) / 2 + 1), W - twC(fmtN(xv)) / 2 - 1)
        + '" y="' + (H - mB + TFS + 4.5) + '" text-anchor="middle" font-size="8.5" fill="' + C.gray + '">' + fmtN(xv) + '</text>';
    }
    for (let n = Math.round(y0 / yst); n <= Math.round(y1 / yst); n++) {
      const yv = n * yst, zero = n === 0;
      s += '<line x1="' + mL + '" y1="' + Y(yv) + '" x2="' + (W - mR) + '" y2="' + Y(yv) + '" stroke="'
        + (zero ? '#aeb7c2' : C.grid) + '"/>'
        + '<text x="' + (mL - 4) + '" y="' + (Y(yv) + TFS * .35) + '" text-anchor="end" font-size="8.5" fill="' + C.gray + '">' + fmtN(yv) + '</text>';
    }
    s += '<rect x="' + mL + '" y="' + mT + '" width="' + (W - mL - mR) + '" height="' + (H - mT - mB) + '" fill="none" stroke="' + C.frame + '"/>';
    (o.hlines || []).forEach(h => {
      s += '<line x1="' + mL + '" y1="' + Y(h.y) + '" x2="' + (W - mR) + '" y2="' + Y(h.y) + '" stroke="' + (h.color || C.fail) + '" stroke-dasharray="5 4"/>';
      if (h.label) s += '<text x="' + (W - mR - 3) + '" y="' + (Y(h.y) - 3) + '" text-anchor="end" font-size="8.5" fill="' + (h.color || C.fail) + '">' + h.label + '</text>';
    });
    (o.vlines || []).forEach(h => {
      s += '<line x1="' + X(h.x) + '" y1="' + mT + '" x2="' + X(h.x) + '" y2="' + (H - mB) + '" stroke="' + (h.color || C.gray) + '" stroke-dasharray="4 4"/>';
      if (h.label) {
        const right = X(h.x) > (mL + W - mR) / 2;  // 위치에 따라 선 안쪽으로 라벨
        s += '<text x="' + (X(h.x) + (right ? -3 : 3)) + '" y="' + (H - mB - 4) + '" text-anchor="'
          + (right ? 'end' : 'start') + '" font-size="8.5" fill="' + (h.color || C.gray) + '">' + h.label + '</text>';
      }
    });
    (o.series || []).forEach(sr => {
      const pts = sr.x.map((x, i) => X(x).toFixed(1) + ',' + Y(sr.y[i]).toFixed(1)).join(' ');
      s += '<polyline points="' + pts + '" fill="none" stroke="' + sr.color + '" stroke-width="1.7"'
        + (sr.dash ? ' stroke-dasharray="5 4"' : '') + '/>';
    });
    (o.points || []).forEach(p => {
      s += '<circle cx="' + X(p.x) + '" cy="' + Y(p.y) + '" r="' + (p.r || 3) + '" fill="' + (p.color || C.gray) + '"/>';
    });
    if (o.title) {  // 긴 제목은 폭에 맞춰 축소 — viewBox 밖으로 잘리지 않게
      const avail = W - mL - 4, need = String(o.title).length * 0.55 * 10.5 * SZ.font;
      const tfs = need > avail ? Math.max(5, 10.5 * avail / need) : 10.5;
      s += '<text x="' + (mL + 2) + '" y="' + (13 + grow * 10) + '" font-size="' + tfs.toFixed(2)
        + '" fill="#20242a">' + o.title + '</text>';
    }
    if (o.xlabel) s += '<text x="' + ((mL + W - mR) / 2) + '" y="' + (H - TFS * .7) + '" text-anchor="middle" font-size="8.5" fill="' + C.gray + '">' + o.xlabel + '</text>';
    let lx = mL + 5, ly = mT + TFS + 2.5;
    (o.series || []).forEach(sr => {
      if (!sr.label) return;
      s += '<line x1="' + lx + '" y1="' + (ly - 3) + '" x2="' + (lx + 13) + '" y2="' + (ly - 3) + '" stroke="' + sr.color + '" stroke-width="2"'
        + (sr.dash ? ' stroke-dasharray="4 3"' : '') + '/>'
        + '<text x="' + (lx + 17) + '" y="' + ly + '" font-size="8.5" fill="' + C.gray + '">' + sr.label + '</text>';
      ly += TFS + 2.5;
    });
    emit(el, s);
  }

  // 방사형: 바깥=위험, 200% 스케일, 100% 경계 점선 — v4 원형(꼭짓점 점·100%/200% 라벨 포함)
  function radar(el, title, labels, vals, ghosts, size) {
    remember(el, radar, arguments);
    const W = size || 230, H = W, cx = W / 2, cy = H / 2 + 5, n = labels.length, MAX = 2.0;
    // 축 라벨(R*1.3 링)이 viewBox 밖으로 나가지 않게 R을 라벨 최장폭으로 제한 —
    // 좌우 라벨은 start/end 정렬이라 전폭이 필요하다 (사용자 지시 2026-07-29)
    const LFS = 8 * SZ.font;
    const lw = Math.max(0, ...labels.map(l => String(l).length * 0.65 * LFS));  // −·% 등 넓은 글리프 여유
    const R = Math.max(W * 0.16, Math.min(W * 0.34, (W / 2 - lw - 5) / 1.3));
    const pt = (k, v) => {
      const a = -Math.PI / 2 + 2 * Math.PI * k / n, r = R * Math.max(0, Math.min(v, MAX)) / MAX;
      return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
    };
    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
    for (const g of [0.5, 1.0, 1.5, 2.0]) {
      const pts = labels.map((_, k) => pt(k, g).map(v => v.toFixed(1)).join(',')).join(' ');
      s += (g === 1.0)
        ? '<polygon points="' + pts + '" fill="none" stroke="' + C.fail + '" stroke-width="1.3" stroke-dasharray="5 4"/>'
        : '<polygon points="' + pts + '" fill="none" stroke="' + C.grid + '"/>';
    }
    labels.forEach((lb, k) => {
      const a = -Math.PI / 2 + 2 * Math.PI * k / n;
      const lx = cx + R * 1.3 * Math.cos(a), ly = cy + R * 1.3 * Math.sin(a);
      const anchor = Math.abs(Math.cos(a)) < 0.25 ? 'middle' : (Math.cos(a) > 0 ? 'start' : 'end');
      const e = pt(k, MAX);
      s += '<line x1="' + cx + '" y1="' + cy + '" x2="' + e[0] + '" y2="' + e[1] + '" stroke="' + C.grid + '"/>'
        + '<text x="' + lx + '" y="' + ly + '" text-anchor="' + anchor + '" font-size="8" fill="' + C.gray + '">' + lb + '</text>';
    });
    (ghosts || []).forEach(g => {
      const pts = g.vals.map((v, k) => pt(k, v).map(q => q.toFixed(1)).join(',')).join(' ');
      s += '<polygon points="' + pts + '" fill="none" stroke="#64748b" stroke-width="1" stroke-dasharray="2 4" opacity="0.4"/>';
    });
    {
      const pts = vals.map((v, k) => pt(k, v).map(q => q.toFixed(1)).join(',')).join(' ');
      s += '<polygon points="' + pts + '" fill="' + C.accent + '22" stroke="' + C.accent + '" stroke-width="1.8"/>';
      vals.forEach((v, k) => {
        const q = pt(k, v);
        s += '<circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="2.8" fill="' + (v > 1 ? C.fail : C.accent) + '"/>';
      });
    }
    // 제목 baseline·크기도 글자 배율을 따라간다 (상단/좌우 잘림 방지)
    const rtNeed = String(title).length * 0.55 * 10.5 * SZ.font;
    const rtFs = rtNeed > W - 6 ? Math.max(5, 10.5 * (W - 6) / rtNeed) : 10.5;
    s += '<text x="' + cx + '" y="' + (11 + Math.max(0, SZ.font - 1) * 10)
      + '" text-anchor="middle" font-size="' + rtFs.toFixed(2) + '" fill="#20242a">' + title + '</text>'
      + '<text x="' + cx + '" y="' + (cy - R * 0.5) + '" text-anchor="middle" font-size="7.5" fill="' + C.fail + '">100%</text>'
      + '<text x="' + cx + '" y="' + (cy - R * 1.02) + '" text-anchor="middle" font-size="7.5" fill="' + C.gray + '">200%</text>';
    emit(el, s);
  }

  // 게이지 — v4 gaugeHtml 원형: 값 텍스트 + min/max 라벨 + marker + PASS/FAIL
  // 호출: gauge(el, name, val, lim(무시), kind, opts={valueText,minLabel,maxLabel,pass})
  function gauge(el, name, val, lim, kind, opts) {
    opts = opts || {};
    const okv = (opts.pass !== undefined) ? opts.pass
      : (kind === 'window' ? (val >= 0 && val <= 1) : (val <= 1));
    const w = Math.max(0, Math.min(1, kind === 'window' ? val : val / 2)) * 100;
    const col = okv ? C.pass : C.fail;
    const right = (opts.valueText ? opts.valueText + ' · ' : '')
      + (kind === 'window' ? ('pos ' + pct(val)) : pct(val)) + ' · ' + (okv ? 'PASS' : 'FAIL');
    let sub = '';
    if (opts.minLabel || opts.maxLabel) {
      sub = '<div class="lbl" style="margin-top:0"><span>' + (opts.minLabel || '') + '</span><span>'
        + (opts.maxLabel || '') + '</span></div>';
    }
    el.insertAdjacentHTML('beforeend',
      '<div class="gauge"><div class="lbl"><span>' + name + '</span><span style="color:' + col + '">'
      + right + '</span></div>'
      + '<div class="bar"><i style="width:' + w + '%;background:' + col + '"></i>'
      + (kind !== 'window' ? '<i style="left:50%;width:2px;background:' + C.fail + '"></i>' : '')
      + '</div>' + sub + '</div>');
  }

  // V-I SOA map — v4 drawSOAMap 원형: safe region 음영 + Vlim/Ilim 점선 + sweep 궤적 + 동작점
  function soaMap(el, o) {
    remember(el, soaMap, arguments);
    const W = o.w || 340, H = (o.h || 225) * SZ.h, mL = 44, mR = 12, mT = o.title ? 20 : 10, mB = 30;
    const iw = W - mL - mR, ih = H - mT - mB;
    const pairs = o.pairs || [];
    const vmax = Math.max(o.Vlim * 2.0, o.V * 1.15, ...pairs.map(p => p.V * 1.05), 1e-9);
    const imax = Math.max(o.Ilim * 2.0, o.I * 1.15, ...pairs.map(p => p.I * 1.05), 1e-9);
    const X = v => mL + v / vmax * iw, Y = i => mT + (imax - i) / imax * ih;
    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
    s += '<rect x="' + mL + '" y="' + mT + '" width="' + iw + '" height="' + ih + '" fill="#fff" stroke="' + C.frame + '"/>';
    s += '<rect x="' + mL + '" y="' + Y(o.Ilim) + '" width="' + (X(o.Vlim) - mL) + '" height="' + (Y(0) - Y(o.Ilim)) + '" fill="rgba(10,125,56,.14)"/>';
    s += '<line x1="' + X(o.Vlim) + '" y1="' + mT + '" x2="' + X(o.Vlim) + '" y2="' + (mT + ih) + '" stroke="' + C.fail + '" stroke-width="1.2" stroke-dasharray="5 4"/>';
    s += '<line x1="' + mL + '" y1="' + Y(o.Ilim) + '" x2="' + (mL + iw) + '" y2="' + Y(o.Ilim) + '" stroke="' + C.fail + '" stroke-width="1.2" stroke-dasharray="5 4"/>';
    if (pairs.length) {
      s += '<path d="' + pairs.map((p, i) => (i ? 'L' : 'M') + X(p.V).toFixed(1) + ',' + Y(p.I).toFixed(1)).join(' ')
        + '" fill="none" stroke="#64748b" stroke-width="1.3" stroke-dasharray="4 4"/>';
    }
    const pass = o.V <= o.Vlim && o.I <= o.Ilim;
    s += '<circle cx="' + X(o.V) + '" cy="' + Y(o.I) + '" r="5" fill="' + (pass ? C.pass : C.fail) + '"/>';
    s += '<text x="' + (X(o.Vlim) - 3) + '" y="' + (mT + 10) + '" text-anchor="end" font-size="8.5" fill="' + C.fail + '">Vlim</text>';
    s += '<text x="' + (mL + 3) + '" y="' + (Y(o.Ilim) - 4) + '" font-size="8.5" fill="' + C.fail + '">Ilim</text>';
    s += '<text x="' + (mL + iw - 3) + '" y="' + (mT + ih - 4) + '" text-anchor="end" font-size="9" fill="'
      + (pass ? C.pass : C.fail) + '">' + o.V.toFixed(3) + (o.unitV || 'V') + ', ' + o.fmtI(o.I) + '</text>';
    if (o.title) s += '<text x="' + (mL + 2) + '" y="12" font-size="10.5" fill="#20242a">' + o.title + '</text>';
    s += '<text x="' + (mL + iw / 2) + '" y="' + (H - 3) + '" text-anchor="middle" font-size="8.5" fill="' + C.gray + '">' + (o.xlabel || 'Voltage') + '</text>';
    emit(el, s);
  }

  return { C: C, lineChart: lineChart, radar: radar, gauge: gauge, soaMap: soaMap,
           setScale: setScale, f: f, pct: pct, fmtN: fmtN };
})();
