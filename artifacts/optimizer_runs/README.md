# Optimizer 실행 기록 (리뷰 아티팩트)

## 자동 기록 (2026-07-29부터)

`/api/optimize/mna`(feas)·`/api/optimize/mna/legacy`(legacy) 실행마다 요청 query와
응답 전체가 이 디렉터리에 `<시각>_<kind>_<status>.json`으로 자동 저장된다
(server/main.py `_save_opt_run`). 응답의 `run_file` 필드가 저장 경로를 가리킨다.
solver가 결정론적이므로 같은 query로 동일 결과가 재현된다.

## 2026-07-29 수동 재현 2건 — W 고정/해제 (UI 기본 설정, adjoint·barrier off·30 iters)

사용자 UI 실행의 동일-조건 재현본 (`2026-07-29_feas_W_frozen.json` / `_W_free.json`,
요약 `2026-07-29_summary.json`). 요청 URL은 각 파일의 `request` 필드.

| 시나리오 | status | 최종 (x1, x2, W, L) | worst | loss_total |
|---|---|---|---|---|
| W 고정 (L·W 잠금, x1/x2 자유) | **INFEASIBLE** | 3.50, 1229.0, 5, 350 | 122.0% (VGS+) | 6.0e-2 |
| W 해제 (L만 잠금) | **INFEASIBLE** | 3.46, 1548.4, 12.04, 350 | 100.4% (VGS+) | 2.2e-5 |

## 2026-07-29 13:19 사용자 UI 실행 2건 — 자동 기록 원본 (#14 반영판)

`20260729_131921_559`(W 고정: freeze=L,W) · `20260729_131957_001`(W 해제: freeze=L),
둘 다 adjoint·barrier off·policy max_margin·30 iters. **결과가 위 수동 재현본과
동일**(W 고정 122.0% / W 해제 100.4%, 동일 final) — solver 결정론 재확인.
#14 반영으로 이번 기록에는 pass 분해가 포함된다: 두 실행 모두
`{rule: FAIL, soa: FAIL, spec: PASS}` — W 해제 실행의 rule FAIL은 최종점
W=12.035가 창 밖(위반량 0.035µm)이기 때문으로, "objective가 작아도 g>0이면
INFEASIBLE" 판정이 분해 필드로 정확히 드러난다.
(`20260729_130553` 은 서버 검증용 6-iter 스모크 실행 기록.)

### 리뷰 포인트

1. **W 고정**: W 없이는 불가 판정이 정상 동작. 주목할 것은 hinge gradient가
   x2를 창 min(1415.232) **아래(1229)까지** 밀었다는 점 — VGS+ 관점에서 클램프
   축소가 이득(강하 증가 → PMOS source 상승 → VGS 축소)이라 rule hinge와 SOA
   hinge가 x2min 경계에서 줄다리기. barrier off 설계의 의도된 동작(탐색 중 위반
   허용, L_rule이 복원)이며 최종 판정은 정직하게 INFEASIBLE + `x2·min` FAIL.
2. **W 해제**: loss_total 2.2e-5로 feasible 경계 바로 옆까지 갔으나 궤적이
   feasible 지점을 한 번도 방문하지 못함(W가 12를 살짝 넘나드는 진동 + VGS+
   100.4%). "objective가 작아도 constraint FAIL이면 PASS 아님" 판정(#13 §8)이
   그대로 보이는 사례. 참고로 **x1/x2를 잠그고 W만 풀면 PASS** (W=11.97,
   전 loss 0 — 회귀 테스트 `S2 opt: W 단독`에 고정).
3. 개선 후보(후속 논의): feasible 근방 lr 감쇠, first-feasible 탐색 후 진동
   억제, 또는 iters 증가. 현 데이터는 기본 설정 그대로의 정직한 기록이다.
