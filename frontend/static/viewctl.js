/* 보기 배율 overlay — 모든 frontend 페이지 공용 (사용자 지시 2026-07-29).
   우상단 소형 컨트롤, 각 조는 −/0/+ 3버튼:
     화면    : body zoom — 페이지 전체 배율(글자 포함), 0=100% 복원
     SVG글자 : chart SVG 내부 font-size 배율 (MNA.setScale → 전체 재렌더)
     SVG굵기 : SVG text + gauge의 font-weight — 굵게 하면 캡처가 선명해진다(CSS 주입)
     SVG높이 : lineChart/soaMap viewBox 높이 배율 — 내부 그래프가 좌표계째 확대
     선굵기  : 축·grid·plot 등 stroke 성분 굵기 배율 (MNA.setScale → 전체 재렌더)
   차트가 없는 페이지(MNA 부재)는 SVG 재렌더 조가 비활성(미연계=비활성 원칙).
   설정은 localStorage 공유로 페이지 간·재방문 간 유지된다. */
'use strict';
(function () {
  var KEY = 'mna_view_scale';
  var GROUPS = [
    { key: 'ui', label: '화면', def: 1, step: 0.1, lo: 0.5, hi: 2.0, dec: 1, needsMNA: false },
    { key: 'sf', label: 'SVG글자', def: 1, step: 0.1, lo: 0.5, hi: 2.5, dec: 1, needsMNA: true },
    { key: 'fw', label: 'SVG굵기', def: 400, step: 100, lo: 300, hi: 900, dec: 0, needsMNA: false },
    { key: 'sh', label: 'SVG높이', def: 1, step: 0.1, lo: 0.5, hi: 2.5, dec: 1, needsMNA: true },
    { key: 'lw', label: '선굵기', def: 1, step: 0.1, lo: 0.5, hi: 3.0, dec: 1, needsMNA: true },
  ];
  var st = {};
  GROUPS.forEach(function (g) { st[g.key] = g.def; });
  try {
    var saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    GROUPS.forEach(function (g) {
      var v = saved[g.key];
      if (typeof v === 'number' && isFinite(v) && v >= g.lo && v <= g.hi) st[g.key] = v;
    });
  } catch (e) { /* 손상 시 기본값 */ }

  var labels = {}, fwStyle = null;

  function apply() {
    document.body.style.zoom = st.ui;
    // font-weight는 SVG text와 gauge(HTML) 양쪽에 걸쳐야 해 CSS로 주입한다.
    // 기본값(400)일 때는 규칙을 비워 원래 서식을 건드리지 않는다.
    if (!fwStyle) {
      fwStyle = document.createElement('style');
      fwStyle.id = 'mnaViewFwStyle';
      document.head.appendChild(fwStyle);
    }
    fwStyle.textContent = (st.fw === 400) ? ''
      : ('svg text{font-weight:' + st.fw + '}.gauge,.gauge *{font-weight:' + st.fw + '}');
    if (window.MNA && MNA.setScale) MNA.setScale(st.sf, st.sh, st.lw);
    try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) { /* 저장 실패 무시 */ }
    GROUPS.forEach(function (g) {
      if (!labels[g.key]) return;
      labels[g.key].textContent = g.label + (st[g.key] !== g.def
        ? (g.dec ? ' ×' + st[g.key].toFixed(g.dec) : ' ' + st[g.key]) : '');
    });
  }

  function init() {
    if (document.getElementById('mnaViewCtl')) return;
    var hasMNA = !!(window.MNA && MNA.setScale);
    var box = document.createElement('div');
    box.id = 'mnaViewCtl';
    box.style.cssText = 'position:fixed;top:4px;right:4px;z-index:10000;display:flex;'
      + 'gap:7px;align-items:center;background:rgba(255,255,255,.9);border:1px solid #c6ccd4;'
      + 'border-radius:5px;padding:2px 6px;font:10px/1.5 system-ui,sans-serif;color:#5b6673;'
      + 'opacity:.35;transition:opacity .15s;user-select:none;flex-wrap:wrap;max-width:60vw';
    box.addEventListener('mouseenter', function () { box.style.opacity = '1'; });
    box.addEventListener('mouseleave', function () { box.style.opacity = '.35'; });
    GROUPS.forEach(function (g) {
      var off = g.needsMNA && !hasMNA;  // 차트 없는 페이지 — 비활성(숨김 아님)
      var wrap = document.createElement('span');
      wrap.style.cssText = 'display:flex;gap:2px;align-items:center' + (off ? ';opacity:.45' : '');
      var lb = document.createElement('span');
      lb.textContent = g.label;
      labels[g.key] = lb;
      wrap.appendChild(lb);
      [['−', -1], ['0', 0], ['+', +1]].forEach(function (bd) {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = bd[0];
        b.disabled = off;
        b.title = off ? '이 페이지에는 차트 SVG가 없습니다'
          : g.label + (bd[1] === 0 ? ' 기본값 복원' : (bd[1] > 0 ? ' 증가' : ' 감소'));
        b.style.cssText = 'border:1px solid #c6ccd4;background:#fff;border-radius:3px;'
          + 'padding:0 4px;font-size:10px;line-height:14px;cursor:pointer;color:#20242a';
        b.addEventListener('click', function () {
          if (bd[1] === 0) st[g.key] = g.def;
          else {
            var v = st[g.key] + bd[1] * g.step;
            v = g.dec ? Math.round(v * 10) / 10 : Math.round(v);
            st[g.key] = Math.max(g.lo, Math.min(g.hi, v));
          }
          apply();
        });
        wrap.appendChild(b);
      });
      box.appendChild(wrap);
    });
    document.body.appendChild(box);
    apply();  // 저장된 배율 복원 (chart 렌더 전이라 이후 렌더는 자동 반영)
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', init);
  else init();
})();
