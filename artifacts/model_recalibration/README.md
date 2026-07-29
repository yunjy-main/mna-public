# #16 SOA-local 재보정 — before/after 검증 아티팩트

- `diode_iv.png` / `clamp_iv.png`: worst corner positive branch — 좌(before, branch-wide
  보정) vs 우(after, SOA-local). ×표 = SOA endpoint(양쪽 모두 정확 통과).
- `summary.json`: 대표 전류에서의 V(I,x) before/after.

## 핵심 수치 (worst corner)

| clamp V@1.33A | x=1415.232 | x=2021.76 | x=2628.288 | size 경향 |
|---|---|---|---|---|
| before | 1.288 | 1.537 | 1.742 | **역전(결함)** |
| after | 1.284 | 1.225 | 1.188 | **정상(감소)** |

diode V@0.5A는 before/after 모두 단조감소(1.6V 이하 raw 정확 보존으로 저전압 값이
raw로 수렴). 알려진 잔여: clamp 0.5A 저전류에서 x2 2021↔2628 간 ~0.2mV raw-model
미세교차(보정과 무관한 원본 특성 — CLAUDE_REVIEW 허용 조항).

## 검증 요약

- focused 8 tests PASS, full grid 192 calib(endpoint err ≤3.6e-15, min endpoint G 1.7e-4)
- calib_table/golden 재생성 후 Python 50 golden + netlist 241건 PASS
- JS witness 동일 방정식 이식 → 50 golden PASS (Python-emitted golden 공유)
- optimizer smoke: W 단독 PASS(99.4%) 유지, x2 단독 INFEASIBLE(정직 보고)
