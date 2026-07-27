# mna 로드맵 — ESD Design Closure

> 목표: ESD verification을 PASS/FAIL에서 끝내지 않고, 미분가능한 회로 해석의 gradient로
> diode/clamp/metal 설계를 자동 수정하는 **GUI-독립 differentiable ESD solver framework**.
> (창립 대화 "HBM ESD 테스트 구조.html", issue #1/#2, 3-렌즈 비평 패널 검증 반영. 2026-07-21)

## 0. 배경 요약

- **창립 대화**: 문제 정의(pin-to-rail HBM, victim SOA) → 부등식/Pareto 문제화 →
  "Current-Sweep-Based SOA Feasible Region Extraction" 방법론 → MNA = inner solver →
  diode/clamp = shifted activation → **Differentiable MNA** (implicit layer, adjoint) →
  HTML prototype 공동개발(demo, interactive-1~5) → issue #1로 자기 평가.
- **issue #2**: 측정기반 two-device 모델 — diode(x1 0.64~3.84)/clamp(x2 1415~2628)의
  bidirectional Softplus I-V + 보정(β 이분법/scale) + SOA power-law envelope 8종(worst/best).
- **현재 상태**: Python FastAPI 서비스(/apps/mna, port 8807), 직렬 경로
  IO→Rio_rdl 0.1Ω→diode→RDD_un1 0.5Ω→clamp→RDD_dn1 0.5Ω→Rvss_rdl 0.1Ω→VSS, 회귀 골든 50건 + 창립 벤치마크 20건,
  화면 4종(models/circuit/spec/meta).

## 1. 확정 결정 (D1~D9 + 창립 스펙)

| # | 결정 |
|---|---|
| D1 | 로컬 `mna/`에서 작업 후 remote push (새 작업이 canonical) |
| D2 | down diode = **model1(diode) 미러** 사용 |
| D3 | SOA corner는 worst/best **양쪽 모두 평가**, 지표별 비관값 판정 |
| D4 | **Python 백엔드 + HTML frontend 서빙**. JSON 자산은 언어중립, JS는 교차검증용 |
| D5 | x extrapolation: 측정 split min/max **±50%** (diode [0.32, 5.76], clamp [707.6, 3942.4]) |
| D6 | 원시 측정 I-V 없음 → 모델 개정은 명명 정정 + 적응형 t_b(x)만 (재fit은 데이터 확보 시) |
| D7 | 금속은 **L만 설계변수**(W 고정) — R=0.5Ω·(L/350µm), EM 한계는 상수 |
| D8 | UI는 최소 범위로 시작, 증분 확장 |
| D9 | ESD spec 환산 **1 kV ↔ 1.33 A** |
| 창립 | **rule 비대칭**: A/C min=가혹 FAIL(projection 금지), max=cap/성능 준-rule, R min=공정한계/max=EM·Joule |
| 창립 | **3단계 해**: minimum(M≥1.0) / recommended(M≥1.2, PDK 채택점) / robust(M≥1.5, worst corner) |
| 창립 | **Top Cell port SOA**: 판정·loss는 wrapper port 경계에서만, 내부 primitive는 observe-only |
| 창립 | **2단계 loss**: feasibility check → SOA hard constraint 하 area 최소화 (단일 penalty 금지) |
| 창립 | stress case = {force_node, **ground_node(명시 필수)**, polarity}; per-case loss는 softmax |
| 창립 | gradient는 implicit differentiation(방식 B); solver core는 J_v와 J_x 모두 제공 |
| 창립 | backprop = **후보 탐색 가속기**; Stage 2(SPICE/PERC/transient sign-off)는 스코프 밖 |
| 창립 | snapback은 non-goal (모델이 monotonic 강제) |

## 2. Phase 계획

### Phase 0 — 기준선 (완료)
`tests/` 회귀 인프라(골든 50 + 창립 벤치마크 20, Python+JS 이중 러너), FastAPI 서비스 시드,
화면 4종, `_global` 서비스 등록. **완료 기준: 러너 전부 green — 달성.**

### Phase 1A — 모델 자산화 (1일)
- 상수·수식을 언어중립 JSON(파라미터 + β(x)/scale(x) **사전계산 테이블** + 허용오차·격자 정책)으로 분리.
- anchor 선정 절차(중앙 log-log residual min/max) 코드화 — 측정 데이터에서 16상수 재생성 가능하게.
- 수치 중립 정정만 포함: a2 지수 퇴화 → 상수 30 표기.
- HBM 환산(1kV=1.33A), D5 창, corner 정책을 JSON 스키마에 명시.
- 완료 기준: 라이브러리가 HTML과 등가(측정 7 split 전체 I-V 테이블 max|ΔI| < 5e-7, 격자 통일 후 1e-10로 강화).

### Phase 1B — 모델 개정 (1~2일, 1A 뒤 별도 게이트)
- clamp scale의 선형구간 왜곡 해소: **적응형 bending onset t_b(x) = min(0.5T, i0⁻¹(0.9·It2))** 재정식화
  (v=0 컨덕턴스 20% 불연속도 함께 해소).
- diode 음의 branch β<0 → "증폭" 명명 정정 (재fit은 원시 데이터 확보 시).
- 완료 기준: endpoint 통과 <1e-8 유지, min(dI/dV)>0 유지, 선형구간 기울기 보존 확인.

### Phase 2 — 직렬 solver 확장 (2~3일)
- down diode(model1 미러) 추가 — 음(−) 스트레스 지배 경로. 우회 경로 잔류 전류는 사후 단방향 검증.
- curve-endpoint SOA 의미론: usage_I = I/It2(x); **I>It2 C¹ 연장** V=Vt2+(I−It2)/g_end (infeasible loss 유한화).
- rule 비대칭 반영: A/C min=FAIL penalty(projection 금지), R window(공정/EM 기원 구분).
- 금속 L 변수화: R(L)=0.5·L/350µm.
- Ipass(first-fail) / M(x) / guardband 판정을 solver API로 정식화.
- 완료 기준: 고정 테스트 행렬(검증 수치 5건 + 무작위 M건 headless-vs-화면 교차, 허용오차 명시) green.

### Phase 3 — Gradient Closure (3~5일)
- **완전 미분 체인** (비평 검증 완료): dβ/dx는 endpoint 체인(T(x)가 적분상한·z 정규화·vd·k 4곳) +
  dIt2/dx 항 포함 — 누락 시 부호 반대·37배 오차. clamp는 ds/dx 몫미분. 1차는 중앙차분, FD 교차검증 게이트.
- **2단계 loss**: feasibility check(최대 보호 조건에서 violation>0이면 infeasible 판정·중단) →
  area 최소화. usage 기반 무차원화. cost 항(area/cap/leakage/routing) 승계.
- **multi-start 27점(min/mid/max³) + clustering + active-set 비교** — 단일해 편향 방지.
- sweep continuation(warm-start), 성능 게이트(41점 sweep 수 초 내 — 사전계산 테이블 전제).
- **integer projection/enumeration**: 연속해 → cost ceil → 주변 정수 후보 열거 → 검증 (단순 반올림 금지).
- 완료 기준: 창립 toy 벤치마크 재현(KKT 연속해, 정수해 3개) + 2A 전류-SOA FAIL을 x1 증가로 자동 해소 시연.

### Phase 4 — 병렬 경로와 MNA (1~2주)
- Newton 최초 필요 시점: up ∥ down ∥ VDD-VSS 직접 경로의 current sharing.
- 수치 전략(비평 정정 반영): ① off 소자는 gmin 안전망(잔류 전류 <1e-9·I 검증),
  ② 전류구동 dead-zone은 **branch 테이블 V(I) warm-start**, ③ 2~3 경로 분배는 **스칼라 이분법**(단조성으로 무조건 수렴).
- stress case 6종({force, ground, polarity}) 자동 생성, ground별(VSS/VDD) factorization,
  선형 pre-screen(±부호반전, unit-solve scale, multi-RHS).
- adjoint: A^T·λ 1회 solve, forward stamp 재사용(∂A/∂x = sparse gradient stamp).
- 규모 기준: 최소 참조 14×14(1차/2차 diode+clamp+victim series R) → rail 100분할 시 212×212 (Python ms 단위).
- 완료 기준: 직렬 특수해 = MNA 일반해 rel<1e-8 회귀, 41 sweep × case 전부 수동 튜닝 없이 수렴.

### Phase 5 — 계층·스키마·GUI (하위 단위 분할, 개별 산정)
- 5a. stress case 행렬 + per-case softmax loss + active-case 보고.
- 5b. subckt **flatten + hierarchy metadata** (deterministic naming, parent 추적) + **Top Cell port SOA**
  (내부 primitive는 observe-only) — Schur macro stamp는 후순위.
- 5c. **YAML/JSON problem schema** (SOA limit을 수식 문자열로, solver 결정론 요건 명시) + topology compiler.
- 5d. TopologyEditor GUI + victim SOA LUT(3키: victim_type, terminal_pair, pulse_condition) 지원.
- 완료 기준: 사전 지명한 계층 토폴로지 1건을 netlist-like 입력으로 풀고 top port SOA 판정.

### 최종 산출물 — RuleGenerator (개체 #21)
- **PDK table rule**: `HBM target | victim class | PAD class | Aup_min | Adown_min | Aclamp_min | Rpath_max`
- **formula rule** (pre-screen 전용, sign-off는 current-sweep/graph로).
- Pareto front에서 3단계 해(minimum/recommended/robust) 추출, recommended가 rule 채택점.

## 3. 개체 카탈로그 (21종)

구현 현황은 `/apps/mna/meta` 화면이 정본. 계층: A 모델(1 DeviceModel, 2 SOAEnvelope&Corner,
3 MetalModel, 4 VictimModel, 5 CalibrationPipeline) / B 문제기술(6 Netlist, 7 StressCase&Spec,
8 DesignVariableRegistry, 9 ProblemSchema) / C 수치(10 TopologyCompiler, 11 MNAAssembler,
12 NewtonSolver, 13 SensitivityEngine) / D 평가(14 LossFunction, 15 Optimizer, 16 PassFailEvaluator) /
E 결과(17 ResultStore, 18 TopologyEditor, 19 AnalysisReport) / F 인프라(20 RegressionHarness) /
산출물(21 RuleGenerator).

## 4. 검증 자산

- 골든 50건(`tests/golden.json`, N=4000 단일 격자, Python 주 러너 + JS 증인).
- 창립 벤치마크 20건(`tests/founding_benchmarks.py`): 3-node MNA(V_P=3.9V, ∂V_P/∂g=−0.25/−0.04/−1.0),
  A+C+W=10 toy(정수 global 3개, rounding trap, local trap (2,5,5), KKT (3.258, 3.990, 2.303)/9.551).
- 기준 구성(x1=2.56, x2=1415.232): worst Ifail=2.034A(diode, ≈HBM 3.05kV), victim 4V 도달
  worst 1.414A/best 1.273A (**corner 역전** — best-SOA가 victim 전압에 더 비관적).

## 5. 참고 문헌 앵커 (창립 대화 §연구 포지셔닝)

Circulax / spicex (JAX differentiable SPICE), GridNet (IR-drop sensitivity), graph-based ESD path
analysis (2008 TCAD), Calibre PERC + Solido (black-box 대비 white-box 차별화), 2023 ACM TODAES
ESD-CAD review. 빈 공간: "verification report를 gradient 기반 network-level corrective sizing으로
닫는 것". 리뷰어 공격 지점: toy model 한계 / local optimum·discrete 변수 / SOA=면적함수 가정
(→ 측정기반 envelope로 방어) / 상용 EDA 차별성.
