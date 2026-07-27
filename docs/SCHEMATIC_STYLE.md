# mna schematic 스타일 규칙

2026-07-27 사용자 지시로 확정된 회로도(server/schematic.py `DEFAULT_LAYOUT`) 배치 규칙.
레이아웃 JSON을 수정할 때 이 규칙을 지킨다. 텍스트/라벨 겹침은 규칙 대상이 아니다(심볼 우선).

**R0. 기본 원칙 — 별도 언급이 없으면 심볼은 연결 노드 사이 center align.**
endpoints를 노드에 두면 schemdraw가 몸체를 자동 중앙 배치하고, 표준 스팬(R4)이
노드 간 거리보다 짧으면 양쪽에 균등한 선을 두어 몸체를 중앙에 놓는다.

## R1. 좌표계 — 행(rail)

| 행 | y | 비고 |
|---|---|---|
| VDD rail | 4.0 | |
| IO rail | 2.0 | victim drain 행 겸용 |
| VSS rail | 0.0 | |
| MVSS rail | −2.0 | Main VSS — port(−3)에서 10.3까지 전폭, VSS와 수직 b2b로만 연결 |
| ground | −4.0 | ground 버스(−4.6→−3.8), GND 소스 2개의 공통 기준 |
| b2b 분기 | ±0.7 | VSS rail 기준 대칭 (도메인2 가로 쌍) |

rail 간격 2.0 고정 — 심볼 몸체 대비 리드가 균일해지는 값(저항/전류원/FET-rail 리드 0.5·0.64 스케일 전 기준).

## R2. 열(column) 배치 (x)

소스열 **−3.8** → port **−3** → RDL **[−2.6,−0.6]** → 1차 보호(D_up/D_down) **−0.2**
→ Resd **[0.2,2.2]** → 2차 보호(D_up2/D_down2) **2.6** → victim 상자 **[3.4,5.45]**(drain 5.1)
→ RDD **[5.1,7.1]** → clamp **7.1** → b2b **[7.9,9.5]** → 도메인2 port **10.3**

세로 요소: VSS↔MVSS 수직 b2b(D_b2b_m) — tap (1.2,0)/(1.2,−2), 분기 y=−0.55/−1.45,
arm x=0.9/1.5 (Resd center 1.2와 수직 정렬).

**b2b 쌍 공통 형태 — 2-port 묶음**: 각 net에 tap 1개만 두고
`tap → stub → 분기 → 역병렬 arm 2개 → 병합 → stub → tap` 구조로 그린다
(rail에 4-tap 병렬 금지). 치수: **arm 간격 0.6~0.7, arm 스팬 0.9**(꺾임이 diode 몸체
가까이 오도록 — 몸체 0.35 기준 arm 리드 ≈0.27). 가로(도메인2 D_b2b: 분기 x=8.25/9.15,
arm y=±0.35)·세로(D_b2b_m) 모두 동일 패턴.

## R3. 심볼 간격 균일

인접 심볼(스팬 가장자리) 간 거리 **0.8** 균일. 예외는 직결(간격 0) 규칙 R4.

## R4. 저항 배치

- 스팬 **2.0** 통일 (RDL 3종·RDD 2종·Resd — 동일 크기 심볼).
- 배치는 R0(노드 사이 center align)을 따른다:
  - **RDL**: port(−3) ↔ 1차 보호 열(−0.2) 중앙 → [−2.6,−0.6], center −1.6.
  - **Resd**: IO(−0.2) ↔ 2차 보호(2.6) 중앙 → [0.2,2.2], center 1.2.
  - **RDD_un1/dn1**: endpoints = 노드(tap 5.1 ↔ N3/N3B 7.1) — 몸체 자동 중앙(center 6.1).

## R5. 심볼 크기

`symbol_scale: 0.64` — resistor/diode/zener/sourcei/ground/pfet/nfet 몸체만 축소.
endpoints 스팬·anchor 접점은 불변(연결 유지). 접점 dot·port open-dot 크기는 스케일 제외.

## R6. 전류원 (스트레스 소스)

4개 모두 **x=−3.8 단일 열** 수직 정렬, 각 스팬 2.0 (몸체 y=3/1/−1/−3.7):
- IO→VDD (2→4, 화살표 ↑ VDD)
- IO→VSS (0→2, 화살표 ↑ IO)
- GND→VSS (−2→0, 화살표 ↑ VSS) — **전용 ground** 를 하단(−3.8,−2)에 직결
- GND→MVSS (−4.7→−2.7, 화살표 ↑ MVSS) — **전용 ground** 를 하단(−3.8,−4.7)에 직결.
  상단은 (−3,−2.7) 경유로 MVSS port에 **아래에서 진입** (위 소스의 ground와 충돌 회피)

공유 ground 버스 금지 — GND 기준 소스는 각자 ground 심볼을 갖는다.
화살표(to 단자) = 스트레스 전류 주입 방향.

## R7. 포트

open dot. 도메인1(VDD/IO/VSS, x=−3) 라벨은 좌상단(lofst [−0.45,0.38] — 선 위).
도메인2(VDD2/IO2/VSS2, x=10.3) 라벨은 우측(lofst [0.6~0.65,0]). 도메인2 리드 길이 0.8 통일.
도메인2는 독립 — VSS↔VSS2 back-to-back diode 쌍(D_b2b)으로만 연결.

## R8. subcircuit 상자

**victim과 보호 cell 전부**(D_up, D_down, D_up2, D_down2, D_b2b_m, D_b2b)를
점선 상자(rect) + 경계 port(open dot, 무명)로 감싼다. 소자 개별 라벨은 제거하고
상자 title(좌상단)로 이동 — 파라미터 포함(예: "D_up x1={x1}").

- 세로 diode cell: 상자 [열±0.5] × [rail+0.3, rail−0.3], port는 상/하 경계의 배선 교차점.
- b2b cell: 묶음 전체를 감싸고 port는 stub 교차점 (세로 (1.2,−0.35)/(1.2,−1.65),
  가로 (8.05,0)/(9.35,0)).
- **victim**: 3 port: **IN**(좌변 중앙) / **VDD**(상변) / **VSS**(하변).
  FET는 gate 왼쪽(theta 180 + flip), drain 공통(5.1, IO행), gate tie = diode-connected(OUT).
  내부 소자는 레이아웃 JSON에서 교체 가능(inverter ↔ 단일 NMOS/PMOS).
  상자는 FET 심볼 기준 좌우 대칭(±0.35).

상자 밖 라벨 overflow 허용(텍스트는 규칙 대상 아님). clamp·저항·전류원은 상자 없음.

## R9. 세로 소자 라벨 위치 (schemdraw 0.15 특성)

세로(위 방향) 소자: `loc:"top"` = **왼쪽 중앙**, `loc:"bottom"` = 오른쪽 중앙.
가로 소자: top/bottom이 그대로 위/아래. 다이오드 라벨은 왼쪽(top) 통일.

## R10. 주석 색

node 전압 = 파랑(`#0b57a4`) · 전류(I, I_v) = 청록(`#00796b`) · 구조 라벨 = 회색(`#5b6673`).

## R11. 수정 후 검증 절차

SVG의 `<circle>` 좌표를 32.4px/unit로 환산해 접점 전수 대조(junction audit):
설계 좌표와 일치 확인 + 옛 좌표 잔재 없음 확인. 심볼 크기는 반경/진폭으로 확인.
