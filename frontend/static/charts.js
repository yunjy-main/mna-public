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
    const W = o.w || 340, H = o.h || 205, mL = 44, mR = 8, mT = o.title ? 20 : 8, mB = 28;
    let xs = [], ys = [];
    (o.series || []).forEach(s => { xs = xs.concat(s.x); ys = ys.concat(s.y); });
    (o.hlines || []).forEach(h => ys.push(h.y));
    (o.vlines || []).forEach(h => xs.push(h.x));
    (o.points || []).forEach(p => { xs.push(p.x); ys.push(p.y); });
    xs = xs.filter(isFinite); ys = ys.filter(isFinite);
    if (!xs.length) { el.innerHTML = ''; return; }
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (x0 === x1) { x0 -= 1; x1 += 1; } if (y0 === y1) { y0 -= 1; y1 += 1; }
    const px = (x1 - x0) * .03, py = (y1 - y0) * .07; x0 -= px; x1 += px; y0 -= py; y1 += py;
    const X = x => mL + (x - x0) / (x1 - x0) * (W - mL - mR);
    const Y = y => H - mB - (y - y0) / (y1 - y0) * (H - mT - mB);
    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
    if (o.shade) {
      const a = X(Math.max(x0, o.shade[0])), b = X(Math.min(x1, o.shade[1]));
      s += '<rect x="' + a + '" y="' + mT + '" width="' + (b - a) + '" height="' + (H - mT - mB) + '" fill="#eef3f8"/>';
    }
    for (let i = 0; i <= 4; i++) {
      const xv = x0 + (x1 - x0) * i / 4, yv = y0 + (y1 - y0) * i / 4;
      s += '<line x1="' + X(xv) + '" y1="' + mT + '" x2="' + X(xv) + '" y2="' + (H - mB) + '" stroke="' + C.grid + '"/>'
        + '<line x1="' + mL + '" y1="' + Y(yv) + '" x2="' + (W - mR) + '" y2="' + Y(yv) + '" stroke="' + C.grid + '"/>'
        + '<text x="' + X(xv) + '" y="' + (H - mB + 13) + '" text-anchor="middle" font-size="8.5" fill="' + C.gray + '">' + fmtN(xv) + '</text>'
        + '<text x="' + (mL - 4) + '" y="' + (Y(yv) + 3) + '" text-anchor="end" font-size="8.5" fill="' + C.gray + '">' + fmtN(yv) + '</text>';
    }
    s += '<rect x="' + mL + '" y="' + mT + '" width="' + (W - mL - mR) + '" height="' + (H - mT - mB) + '" fill="none" stroke="' + C.frame + '"/>';
    (o.hlines || []).forEach(h => {
      s += '<line x1="' + mL + '" y1="' + Y(h.y) + '" x2="' + (W - mR) + '" y2="' + Y(h.y) + '" stroke="' + (h.color || C.fail) + '" stroke-dasharray="5 4"/>';
      if (h.label) s += '<text x="' + (W - mR - 3) + '" y="' + (Y(h.y) - 3) + '" text-anchor="end" font-size="8.5" fill="' + (h.color || C.fail) + '">' + h.label + '</text>';
    });
    (o.vlines || []).forEach(h => {
      s += '<line x1="' + X(h.x) + '" y1="' + mT + '" x2="' + X(h.x) + '" y2="' + (H - mB) + '" stroke="' + (h.color || C.gray) + '" stroke-dasharray="4 4"/>';
    });
    (o.series || []).forEach(sr => {
      const pts = sr.x.map((x, i) => X(x).toFixed(1) + ',' + Y(sr.y[i]).toFixed(1)).join(' ');
      s += '<polyline points="' + pts + '" fill="none" stroke="' + sr.color + '" stroke-width="1.7"'
        + (sr.dash ? ' stroke-dasharray="5 4"' : '') + '/>';
    });
    (o.points || []).forEach(p => {
      s += '<circle cx="' + X(p.x) + '" cy="' + Y(p.y) + '" r="' + (p.r || 3) + '" fill="' + (p.color || C.gray) + '"/>';
    });
    if (o.title) s += '<text x="' + (mL + 2) + '" y="13" font-size="10.5" fill="#20242a">' + o.title + '</text>';
    if (o.xlabel) s += '<text x="' + ((mL + W - mR) / 2) + '" y="' + (H - 3) + '" text-anchor="middle" font-size="8.5" fill="' + C.gray + '">' + o.xlabel + '</text>';
    let lx = mL + 5, ly = mT + 11;
    (o.series || []).forEach(sr => {
      if (!sr.label) return;
      s += '<line x1="' + lx + '" y1="' + (ly - 3) + '" x2="' + (lx + 13) + '" y2="' + (ly - 3) + '" stroke="' + sr.color + '" stroke-width="2"'
        + (sr.dash ? ' stroke-dasharray="4 3"' : '') + '/>'
        + '<text x="' + (lx + 17) + '" y="' + ly + '" font-size="8.5" fill="' + C.gray + '">' + sr.label + '</text>';
      ly += 11;
    });
    el.innerHTML = s + '</svg>';
  }

  // 방사형: 바깥=위험, 200% 스케일, 100% 경계 점선(주석용) — 창립 확정 스펙
  function radar(el, title, labels, vals, ghosts, size) {
    const W = size || 220, H = W, cx = W / 2, cy = H / 2 + 5, R = W * 0.36, n = labels.length, MAX = 2.0;
    const pt = (k, v) => {
      const a = -Math.PI / 2 + 2 * Math.PI * k / n, r = R * Math.min(v, MAX) / MAX;
      return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
    };
    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
    for (const g of [0.5, 1.5, 2.0]) {
      const pts = labels.map((_, k) => pt(k, g).map(v => v.toFixed(1)).join(',')).join(' ');
      s += '<polygon points="' + pts + '" fill="none" stroke="' + C.grid + '"/>';
    }
    {
      const pts = labels.map((_, k) => pt(k, 1).map(v => v.toFixed(1)).join(',')).join(' ');
      s += '<polygon points="' + pts + '" fill="none" stroke="' + C.fail + '" stroke-dasharray="4 3"/>';
    }
    labels.forEach((lb, k) => {
      const [x, y] = pt(k, MAX * 1.06); const a = pt(k, MAX);
      s += '<line x1="' + cx + '" y1="' + cy + '" x2="' + a[0] + '" y2="' + a[1] + '" stroke="' + C.grid + '"/>'
        + '<text x="' + x + '" y="' + y + '" text-anchor="middle" font-size="8" fill="' + C.gray + '">' + lb + '</text>';
    });
    (ghosts || []).forEach(g => {
      const pts = g.vals.map((v, k) => pt(k, v).map(q => q.toFixed(1)).join(',')).join(' ');
      s += '<polygon points="' + pts + '" fill="none" stroke="#b9c2cc" stroke-width="1" opacity="0.7"/>';
    });
    {
      const pts = vals.map((v, k) => pt(k, v).map(q => q.toFixed(1)).join(',')).join(' ');
      s += '<polygon points="' + pts + '" fill="' + C.accent + '22" stroke="' + C.accent + '" stroke-width="1.8"/>';
    }
    s += '<text x="' + cx + '" y="11" text-anchor="middle" font-size="10.5" fill="#20242a">' + title + '</text>';
    el.innerHTML = s + '</svg>';
  }

  // 게이지: kind 'window'(0~1 위치) | 기본(usage, 200% 스케일 + 100% 마커)
  function gauge(el, name, val, lim, kind) {
    const okv = kind === 'window' ? (val >= 0 && val <= 1) : (val <= 1);
    const w = Math.max(0, Math.min(1, kind === 'window' ? val : val / 2)) * 100;
    const col = okv ? C.pass : C.fail;
    el.insertAdjacentHTML('beforeend',
      '<div class="gauge"><div class="lbl"><span>' + name + '</span><span style="color:' + (okv ? C.pass : C.fail) + '">'
      + (kind === 'window' ? ('pos ' + pct(val)) : pct(val)) + ' · ' + (okv ? 'PASS' : 'FAIL') + '</span></div>'
      + '<div class="bar"><i style="width:' + w + '%;background:' + col + '"></i>'
      + (kind !== 'window' ? '<i style="left:50%;width:2px;background:' + C.fail + '"></i>' : '')
      + '</div></div>');
  }

  return { C: C, lineChart: lineChart, radar: radar, gauge: gauge, f: f, pct: pct, fmtN: fmtN };
})();
