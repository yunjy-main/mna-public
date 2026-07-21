# Regression harness (Phase 0)

로드맵의 검증 백본. 모든 phase는 이 골든 수치를 깨지 않아야 한다.

아키텍처(결정 D4 개정): **Python이 주 런타임**(solver/모델/백엔드), HTML은 frontend 서빙 전용.
JS 러너는 언어 간 등가성 증인으로 유지 — 두 러너가 같은 golden.json을 통과해야 한다.
서비스는 `../_global/config/services/8807.mna.yaml`로 등록됨 (FastAPI, /apps/mna, Phase 2 산출물).

## 실행

```
python tests/regression.py            # 주 러너: golden.json 대비 검사 (PASS/FAIL, exit code)
node tests/regression.js              # 교차검증 러너 (동일 golden.json)
python tests/founding_benchmarks.py   # 창립 해석 벤치마크 (3-node MNA + 다중해 toy, 20건)
python tests/regression.py --emit     # golden.json 재생성 (모델 의도 변경 시에만)
```

`tests/regression.py`는 `server/model.py`를 import하므로 골든이 서빙 모델 그 자체를 검증한다.
`founding_benchmarks.py`는 창립 대화의 손검증 값(3-node V_P=3.9V, ∂V_P/∂g=−0.25/−0.04/−1.0;
A+C+W=10 toy의 global 정수해 3개·rounding trap·local trap·KKT 연속해)을 고정한다 —
Phase 3(gradient)·Phase 4(MNA) 구현의 검증 앵커.

## 커버리지 (50개 골든 항목)

1. **포팅 충실도** — 측정 7개 split의 ± branch endpoint 재현 (rel < 1e-9)
2. **SOA envelope** — worst It2+ 7건 (해석식, rel < 1e-12)
3. **캘리브레이션 핀** — diode β±(x), clamp scale+(x), min(dI/dV) (rel < 1e-6)
4. **기준 구성 직렬 경로** — x1=2.56, x2=1415.232, Rio=0.1Ω, Rvdd=0.5Ω:
   Ifail, V_IO(0.5/1.0/1.33A) worst + V_IO(1.33A) best (**corner 역전 증인**: best > worst)
5. **검증점** — V_IO(2A; x1=2.56, x2=2021.76, worst) = 5.431V (x2 규약 명시 핀)
6. **해석 최소 크기** — 2A worst 생존 x1_min = 2.5116
7. **음의 스트레스** — diode It2−(2.56) = −51.46mA, 기준 구성 V_IO ≈ −8.32V
8. **구조 불변량** — 전체 G > 0 (단조성), I0(0) = 0

## 수치 규약

- **격자 정책**: 캘리브레이션(corr/integ)과 곡선(branch) 모두 **N=4000 단일 격자**.
  원본 docs HTML은 1200/1000 혼용으로 endpoint 오차 ~6e-8이 있어 의도적으로 통일함.
- 골든 항목은 (x1, x2, corner, R) 규약을 key에 명시 — 규약 없는 수치 비교는 가짜 회귀 실패를 만든다.
- SOA corner는 worst/best 양쪽 평가(결정 D3). 기타 결정 사항 D1–D9는 프로젝트 노트 참조.
