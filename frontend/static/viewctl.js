/* 보기 배율 overlay — 모든 frontend 페이지 공용 (사용자 지시 2026-07-29).
   우상단 소형 컨트롤 3조(각 −/0/+):
     화면    : body zoom — 페이지 전체 배율(글자 포함), 0=100% 복원
     SVG글자 : chart SVG 내부 font-size 배율 (MNA.setScale → 전체 재렌더)
     SVG높이 : lineChart/soaMap viewBox 높이 배율 — 내부 그래프가 좌표계째 확대
   차트가 없는 페이지(MNA 부재)는 SVG 조가 비활성(미연계=비활성 원칙).
   설정은 localStorage 공유로 페이지 간·재방문 간 유지된다. */
'use strict';
(function () {
  var KEY = 'mna_view_scale';
  var st = { ui: 1, sf: 1, sh: 1 };
  try {
    var saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    ['ui', 'sf', 'sh'].forEach(function (k) {
      if (typeof saved[k] === 'number' && isFinite(saved[k]) && saved[k] > 0) st[k] = saved[k];
    });
  } catch (e) { /* 손상 시 기본값 */ }

  var GROUPS = [
    { key: 'ui', label: '화면', lo: 0.5, hi: 2.0, needsMNA: false },
    { key: 'sf', label: 'SVG글자', lo: 0.5, hi: 2.5, needsMNA: true },
    { key: 'sh', label: 'SVG높이', lo: 0.5, hi: 2.5, needsMNA: true },
  ];
  var labels = {};

  function apply() {
    document.body.style.zoom = st.ui;
    if (window.MNA && MNA.setScale) MNA.setScale(st.sf, st.sh);
    try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) { /* 저장 실패 무시 */ }
    GROUPS.forEach(function (g) {
      if (labels[g.key])
        labels[g.key].textContent = g.label + (st[g.key] !== 1 ? ' ×' + st[g.key] : '');
    });
  }

  function init() {
    if (document.getElementById('mnaViewCtl')) return;
    var hasMNA = !!(window.MNA && MNA.setScale);
    var box = document.createElement('div');
    box.id = 'mnaViewCtl';
    box.style.cssText = 'position:fixed;top:4px;right:4px;z-index:10000;display:flex;'
      + 'gap:8px;align-items:center;background:rgba(255,255,255,.9);border:1px solid #c6ccd4;'
      + 'border-radius:5px;padding:2px 6px;font:10px/1.5 system-ui,sans-serif;color:#5b6673;'
      + 'opacity:.35;transition:opacity .15s;user-select:none';
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
      [['−', -0.1], ['0', 0], ['+', +0.1]].forEach(function (bd) {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = bd[0];
        b.disabled = off;
        b.title = off ? '이 페이지에는 차트 SVG가 없습니다'
          : g.label + (bd[1] === 0 ? ' 100% 복원' : (bd[1] > 0 ? ' 확대' : ' 축소'));
        b.style.cssText = 'border:1px solid #c6ccd4;background:#fff;border-radius:3px;'
          + 'padding:0 4px;font-size:10px;line-height:14px;cursor:pointer;color:#20242a';
        b.addEventListener('click', function () {
          st[g.key] = bd[1] === 0 ? 1
            : Math.max(g.lo, Math.min(g.hi, Math.round((st[g.key] + bd[1]) * 10) / 10));
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
