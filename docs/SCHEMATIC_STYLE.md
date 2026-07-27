# mna schematic 스타일 규칙

2026-07-27 사용자 지시로 확정된 회로도(server/schematic.py `DEFAULT_LAYOUT`) 배치 규칙.
레이아웃 JSON을 수정할 때 이 규칙을 지킨다. 텍스트/라벨 겹침은 규칙 대상이 아니다(심볼 우선).

**R0. 기본 원칙 — 별도 언급이 없으면 심볼은 연결 노드 사이 center align.**
endpoints를 노드에 두면 schemdraw가 몸체를 자동 중앙 배치하고, 표준 스팬(R4)이
노드 간 거리보다 짧으면 양쪽에 균등한 선을 두어 몸체를 중앙에 놓는다.

## R1. 좌표계 — 행(rail)

| 행 | y | 비고 |
|---|---|---|
| VDD rail | 6.0 | |
| IO rail | 3.0 | victim drain 행 겸용 |
| VSS rail | 0.0 | |
| MVSS rail | −3.0 | Main VSS — port(−3)에서 10.3까지 전폭, VSS와 수직 b2b로만 연결 |
| ground | −3.0 / −7.05 | 소스별 전용 ground (x=−3.8, 공유 버스 금지 — R6) |

rail 간격 **3.0** (2026-07-27 사용자 지시로 세로 간격 1.5배 — 이전 2.0).
가로(x) 간격·심볼 크기는 불변.

## R2. 열(column) 배치 (x)

소스열 **−3.8** → port **−3** → RDL **[−2.6,−0.6]** → 1차 보호(D_up/D_down) **−0.2**
→ Resd **[0.2,2.2]** → 2차 보호(D_up2/D_down2) **2.6** → victim 상자 **[3.4,5.45]**(drain 5.1)
→ RDD **[5.1,7.1]** → clamp **7.1** → b2b **[7.9,9.5]** → 도메인2 port **10.3**

세로 요소: 수직 b2b 2개 — 분기 y=−0.825/−2.175 공통:
- **D_b2b_m** (VSS↔MVSS): clamp 열(7.1) 아래, tap = N3B(7.1,0) / MVSS(7.1,−3), arm 6.8/7.4.
- **D_b2b_m2** (VSS2↔MVSS): VSS2 port 열(10.3) 아래, tap = VSS2 port(10.3,0) /
  MVSS rail 끝(10.3,−3), arm 10.0/10.6, 상자 [9.75,10.85]×[−0.6,−2.4].

**b2b 쌍 공통 형태 — 2-port 묶음**: 각 net에 tap 1개만 두고
`tap → stub → 분기 → 역병렬 arm 2개 → 병합 → stub → tap` 구조로 그린다
(rail에 4-tap 병렬 금지). 치수: **arm 간격 0.6 통일**(가로쌍 y=±0.3, 세로쌍 x=6.8/7.4),
arm 스팬 = 가로 0.9 / 세로 1.35 — 꺾임(분기)이 diode 몸체 가까이 오도록.
가로(도메인2 D_b2b: 분기 x=8.25/9.15)·세로(D_b2b_m) 모두 동일 패턴.

## R3. 심볼 간격 균일 (가로)

인접 심볼(스팬 가장자리) 간 거리 **0.8** 균일. 예외는 직결(간격 0) — RDD의 endpoints=노드.

## R4. 저항 배치

- 스팬 **2.0** 통일 (RDL 3종·RDD 2종·Resd — 동일 크기 심볼).
- 배치는 R0(노드 사이 center align)을 따른다:
  - **RDL**: port(−3) ↔ 1차 보호 열(−0.2) 중앙 → [−2.6,−0.6], center −1.6.
  - **Resd**: IO(−0.2) ↔ 2차 보호(2.6) 중앙 → [0.2,2.2], center 1.2.
  - **RDD_un1/dn1**: endpoints = 노드(tap 5.1 ↔ N3/N3B 7.1) — 몸체 자동 중앙(center 6.1).

## R5. 심볼 크기

`symbol_scale: 0.64` — resistor/diode/zener/sourcei/ground/pfet/nfet 몸체만 축소.
endpoints 스팬·anchor 접점은 불변(연결 유지). 접점 dot·port open-dot 크기는 스케일 제외.

**선 굵기**: `lw: 1.0` (schemdraw 기본 2의 **1/2**) — 배선·심볼·상자 등 모든 스트로크 공통.
두 canvas(본 회로·라이브러리) 동일 적용.

## R6. 전류원 (스트레스 소스)

4개 모두 **x=−3.8 단일 열**, 각 소스는 **주입 rail 바로 아래에 매달린 독립 유닛**:
`rail tap → 선(0.5) → 소스(스팬 1.0, 몸체 중심 rail−1.0) → 전용 ground 직결`.
rail-to-rail 스팬 금지, 소스 간 daisy-chain 금지.

| 소스 | 부착 rail | 소스 스팬 | 몸체 y | ground |
|---|---|---|---|---|
| I_ESD (IO→VDD) | VDD 6 | 4.5→5.5 | 5.0 | (−3.8,4.5) |
| I_ESD (IO→VSS) | IO 3 | 1.5→2.5 | 2.0 | (−3.8,1.5) |
| I_ESD (GND→VSS) | VSS 0 | −1.5→−0.5 | −1.0 | (−3.8,−1.5) |
| I_ESD (GND→MVSS) | MVSS −3 | −4.5→−3.5 | −4.0 | (−3.8,−4.5) |

**모든 소스가 전용 ground를 갖는다** (공유 버스 금지). 화살표는 위(주입 rail 방향) =
스트레스 전류 주입. title의 (A→B)가 주입/리턴 net 쌍을 문서화한다.
각 rail 행은 tap(−3.8) → 선 → port(−3) 패턴 공통.

각 소스 유닛은 **subcircuit 상자**(R8): [−4.3,−3.3] × [rail−2.0, rail−0.45],
경계 port는 상변(−3.8, rail−0.45) 1개 — ground는 상자 내부(1-port cell).
**심볼-상자 여백 ≥0.2** (몸체 상단↔상변 0.23, ground 하단↔하변 ≈0.2).
I_ESD 라벨은 상자 title.

## R7. 포트

open dot. 도메인1(VDD/IO/VSS/MVSS, x=−3) 라벨은 좌상단(lofst [−0.45,0.57] — 선 위).
도메인2(VDD2/IO2/VSS2, x=10.3) 라벨은 우측(lofst [0.6~0.65,0]). 도메인2 리드 길이 0.8 통일.
도메인2는 독립 — VSS↔VSS2 back-to-back diode 쌍(D_b2b)으로만 연결.

## R8. subcircuit 상자

**모든 소자**(D_up, D_down, D_up2, D_down2, Clamp, D_b2b_m/D_b2b_m2, D_b2b, I_ESD 4종,
저항 6종, Victim — 총 19 블록)를 점선 상자(rect) + 경계 port(open dot, 무명)로 감싼다.
소자 개별 라벨은 제거하고 상자의 라벨 3계층(R13: instance/model/equation)으로 표기한다.

- 세로 diode cell: 상자 [열**±0.7**] × [rail+0.9, rail−0.9] — 안쪽 라벨(softplus_bi)이
  외곽선을 넘지 않는 폭. port는 상/하 경계의 배선 교차점.
- Clamp cell: 두 rail 칸을 가로지르는 [6.4,7.8](±0.7)×[0.9,5.1], port (7.1,5.1)/(7.1,0.9).
- b2b cell: 묶음 전체를 감싸고 port는 stub 교차점 (세로 (7.1,−0.6)/(7.1,−2.4),
  가로 (8.05,0)/(9.35,0), 상자 y=±0.65).
- **victim**: 상자 [3.4,5.45]×[0.9,5.1], 3 port: **IN**(좌변 중앙) / **VDD**(상변 5.1) / **VSS**(하변 0.9).
  FET는 gate 왼쪽(theta 180 + flip), drain 공통(5.1, IO행 y=3),
  **bulk 단자 표시**(`"bulk": True`) + bulk→source 직결선 (렌더러 자동, source y=drain±0.96).
  **NMOS bulk 화살표는 채널 반대 방향**(사용자 지시 — 렌더러가 SVG 후처리로 반전,
  PMOS는 채널 방향 유지).
  **IN 배선은 gate까지만**(gate x = drain − 1.367·symbol_scale = 4.225, tie dot) —
  gate→drain(junction) 경로는 그리지 않는다(2026-07-27 사용자 지시). drain은 별도
  OUT 노드(주석은 drain 위치). 내부 소자는 레이아웃 JSON에서 교체 가능.
  상자는 FET 심볼 기준 좌우 대칭(±0.35).

- 전류원 cell: 1-port (R6) — 상자 내부에 소스+전용 ground.
- 저항 cell: **compact 상자** [center±0.65] × [rail±0.45] (몸체 0.64 기준 여백 0.33/0.29),
  port는 좌/우 경계의 배선 교차점.

**테두리 비접촉 원칙**: 상자끼리 겹치거나 맞닿지 않게 한다 — 세로 cell 상자는
rail∓0.9에서 끝나고 저항 상자는 rail±0.45까지라 rail마다 0.45 간격이 남는다.
(D_b2b_m 상자는 내부 분기점 여백 한계로 rail∓0.6 유지.)

**비활성(open) cell 표기**: 비활성화된 cell은 전체(소자·내부 배선·dot·상자·port·
rail 연결선)를 연한 회색(`#b0b6bf`)으로 그리고 title에 "(open)"을 붙인다 — 현재
VSS↔VSS2 가로 D_b2b와 **I_ESD 소스 4종**이 해당. 활성 net 위의 tap dot·port dot
(경계 밖)은 검정 유지. 렌더러의 `color` 키는 line/dot/port/ground/2단자 소자 공통.
라이브러리(Subcircuit Set) canvas의 cell들은 참조용이므로 항상 검정.

상자 밖 라벨 overflow 허용(텍스트는 규칙 대상 아님). 상자 없는 소자는 없다.

## R8.5. down diode 채움

**D_down·D_down2는 삼각형 안쪽을 검게 채운다**(`"fill": "black"`) — up/down 방향 구분용.
up diode·clamp·b2b arm은 미채움. 렌더러의 `fill` 키는 모든 2단자 소자에서 사용 가능.

## R9. 세로 소자 라벨 위치 (schemdraw 0.15 특성)

세로(위 방향) 소자: `loc:"top"` = **왼쪽 중앙**, `loc:"bottom"` = 오른쪽 중앙.
가로 소자: top/bottom이 그대로 위/아래. 다이오드 라벨은 왼쪽(top) 통일.

## R10. 주석 색

node 전압 = 파랑(`#0b57a4`) · 전류(I, I_v) = 청록(`#00796b`) · 구조 라벨 = 회색(`#5b6673`).

## R11. Subcircuit Set (라이브러리 행)

**cell마다 개별 canvas/div** — `LIBRARY_CELLS`(schematic.py)의 각 cell을
`GET /api/schematic/library/{id}`로 개별 SVG 서빙하고, `GET /api/schematic/library`는
목록 JSON(id/name/**models**)을 준다. HTML(#schemLib)은 flex-wrap 그리드로 cell div를
나열하고 **각 canvas 아래에 사용 가능한 process model list**를 표기한다.
현재 model list: D_up=esdvpnp·esdvpnp_rg / D_down=esdndsx·esdndsx_rg·esdnwsx /
R=rmres·metal / Clamp=nfet_clamp / D_b2b=essvpnp ×2 (나머지는 미지정 — 추후 추가).
Resd 제외 저항(RDL 3·RDD 2)은 동일 model **metal**에 저항값만 달리 쓴 instance.
형태 기준 중복 제거 cell 12종:
`I_ESD`(1-port 소스+ground) · `GND`(1-port, I_ESD와 동일 크기) · `R` ·
`short`(2-port 직결) · `open`(2-port 미연결, R와 동일 크기) ·
`D_up` · `D_down`(검게 채움) · `Clamp` · `D_b2b`(역병렬 묶음) ·
`Victim`(inverter FET쌍+bulk) · `Victim (NMOS)` · `Victim (PMOS)`(단일 FET,
gate 좌/drain·source 상하 port, 서로 거울 대칭).
각 cell은 본 회로와 동일한 subcircuit 문법(점선 상자+경계 port)이되,
**상자 밖 실선 배선 금지** — 소자 endpoints를 상자 경계에 맞춰 트림한다.
라이브러리 라벨: **type 이름(title)은 상자 밖 좌상단**(instance와 동일 위치·서식),
**model/equation은 상자 안**(R13과 동일) — D_up/D_down(model1+softplus_bi),
Clamp(model2+softplus_bi), Victim(SG_PFET+SG_NFET 2개 — 좌상단 순차 스택),
Victim (NMOS)/(PMOS)(각자 SG 모델 1개).
인접 상자 간 간격 0.8. 새 '형태'가 회로에 추가되면 이 목록에도 추가한다.

## R12. 수정 후 검증 절차

SVG의 `<circle>` 좌표를 32.4px/unit로 환산해 접점 전수 대조(junction audit):
설계 좌표와 일치 확인 + 옛 좌표 잔재 없음 확인. 심볼 크기는 반경/진폭으로 확인.

## R13. 라벨 3계층 (instance / model / equation)

| 계층 | 내용 | 위치 | 서식 |
|---|---|---|---|
| **instance** | subcircuit instant화 시 부여되는 고유 이름 — **X 접두**(SPICE 관례): XD_up, XRDD_un1, XVictim, XI_ESD (IO→VDD)... | **상자 밖**, 좌상단 기본 — 겹치면 반시계 fallback 좌상단→좌하단→우하단→우상단 (`instance_loc`: tl/bl/br/tr) | fs−1, 진한 색(#20242a); open cell은 회색+"(open)" |
| **model** | 내부 심볼의 **process 모델명** — cell의 model list에서 선택 (esdvpnp, esdndsx, nfet_clamp, metal, rmres(Resd), SG_PFET/SG_NFET 1stk_1rx). solver 내부명(model1/model2)은 화면에 쓰지 않는다 | **상자 안**, 좌상단부터 동일 반시계 순서 — 리스트 허용 (victim: PFET=tl, NFET=bl) | **fs−3(6pt)**, MUT |
| **equation** | 특성 equation의 **이름**만 (softplus_bi, rdd(L)) 또는 상수 (0.1Ω, 500Ω) — 파라미터 값(x1=2.56, L=350 등)은 표기하지 않는다(UI 입력이 원본) | **model 라벨 바로 아래**(같은 코너, 0.33 아래); model 없으면 model 자리 | **fs−3(6pt)**, MUT |

**회로 canvas에는 3계층 라벨만 표시한다**(2026-07-27 사용자 지시) — 노드 전압·전류
주석(`annotations: False`)과 port 이름은 삭제된 상태(추후 층별 재도입 예정).

현재 instance 배치 (충돌 실재 기준, 2026-07-27 전수 재판정):
- **tl(기본)**: RDL 3종, XResd, XRDD 2종, XD_up/XD_down/XD_up2/XD_down2, XClamp,
  XVictim, XD_b2b_m2, XD_b2b(open)
- **bl**: XI_ESD (GND→VSS)/(GND→MVSS) — tl이 저항 상자·MVSS rail과 충돌;
  XD_b2b_m — tl이 XRDD_dn1 상자 모서리와 충돌
- **br**: XI_ESD (IO→VDD)/(IO→VSS) — 긴 라벨이 저항 상자를 관통(왼쪽 빈 공간으로)

fallback은 충돌이 실재할 때만 유지한다 — 충돌 원인이 사라지면 tl로 복귀.
검증: 라벨 bbox vs 상자 4변 교차 전수 검사 = 0건.
**정렬/오프셋**: 좌상단(및 좌하단) 배치 시 좌측 들여쓰기 없음 — instance는 상자
좌변과 정확히 정렬(x=xa), 안쪽 model/equation은 +0.03만.
세로: **바깥(instance) 라벨은 외곽선과 겹치지 않게 띄운다** — 상변+0.24/하변−0.30
(descender/cap 포함 클리어, 하단도 외곽선에 붙임). **안쪽(model/equation) 라벨은
외곽선에 최대 밀착** — 첫 줄 baseline 상변−0.01(사용자 렌더 기준 확정), 좌 +0.01,
하단 슬롯 +0.12(descender가 선 아래로 침범하지 않는 최소값).
**model↔equation baseline pitch 0.18** (사용자 확정).
(schemdraw .label()의 자체 x오프셋 +0.10은 렌더러가 앵커에서 상쇄.)
렌더러 rect 키: `instance`/`instance_loc`/`model`(문자열|리스트)/`model_loc`/`equation`.
라이브러리 canvas의 cell type 이름은 `title` 키 — instance와 같은 자리(밖 좌상단)에 그린다.

## R14. instance→cell 매핑

**회로의 모든 instance는 Subcircuit Set의 cell을 골라 instant화한 것이다.** 데이터로:

- 각 instance rect는 `"cell": "<id>"` 참조 필수 (i_esd/r/d_up/d_down/clamp/d_b2b/victim...).
- `model`은 해당 cell의 **model list에서 선택**한 process 모델명 (목록이 비어 있으면 무제약).
- **회전/미러 변형 허용**: 같은 cell을 가로/세로로 눕혀 쓸 수 있고 `"variant"` 키로 표기
  (예: d_b2b — XD_b2b_m/m2=vertical, XD_b2b=horizontal).
- **파라미터 바인딩** `"params"`: instance가 쓰는 solver/UI 변수 또는 상수
  (XD_up {size:x1}, XClamp {size:x2}, XRDD {R:rdd(L), L:L}, RDL {R:0.1}, XResd(rmres) {R:500},
  I_ESD {I:I_sweep}, XVictim {topology:vTopo}; 2차 보호는 미바인딩 {}).
- 검증: `GET /api/schematic/mapping` — cell 존재·model 소속·바인딩 표를 반환하고
  위반을 issues로 보고한다. 레이아웃 수정 후 이 API로 확인.

## R15. 회로도 → 행렬 자동 변환 (netlist 추출)

**회로도가 netlist의 유일한 원천이다.** server/netlist.py:
- 연결 규칙: 배선은 축정렬 세그먼트, **등록점**(배선·소자 endpoints, dot, ground, FET anchor)이
  세그먼트 위에 있으면 그 net에 합류. 등록점 없는 교차는 미연결(표준 규약).
- 소자↔instance 결합: 소자 중점이 들어 있는 instance 상자(cell/model/params)로 귀속.
- open(회색) 소자·전류원은 G에 미조립. 시나리오는 (inject net, ground net, I)로 지정.
- model equation은 임의 placeholder(2026-07-27 사용자 허용): softplus diode(Von 0.7),
  양방향 clamp(트리거 4V), 선형 R(params.R 또는 rdd(L)), FET=접합 diode(bulk=source).
  크기 파라미터(x1/x2) 미반영 — 실측 모델로 교체 예정.
- API: GET /api/schematic/matrix?inject=IO&ground=VSS&i=1.33 (circuit 화면 §3.5).
- 검증: tests/test_netlist.py — net 소속 전수 15건 + KCL/직렬 보존/대칭/수렴 9건.
  레이아웃 수정 시 이 테스트가 topology 변화를 잡는다.
