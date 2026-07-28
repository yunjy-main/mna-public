# -*- coding: utf-8 -*-
"""Device/SOA model — single source of truth (Python primary runtime, D4).

Faithful port of docs/two_device_complete_iv_soa_model.html with one deliberate
deviation: a single unified integration grid N for calibration AND curve
construction (the source HTML mixes n=1200/1000, causing ~6e-8 endpoint error).

tests/regression.py imports this module, so the golden checks guard exactly the
model the service serves.
"""
import math

N = 4000  # unified grid (calibration AND curve)


def sp(z):
    if z > 50:
        return z
    if z < -50:
        return math.exp(z)
    return math.log1p(math.exp(z))


def sg(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


D1 = {
    "id": "diode", "method": "exp",
    "par": lambda x: {"a1": 15.14 / x ** .08, "r1": .869 / x ** .826, "c1": 1.193 / x ** .0075,
                      "a2": 5.07 / x ** .0629, "r2": 27.48 / x ** 1.267, "c2": -7.18 / x ** -.0881},
    "m": [{"x": .64, "vp": 2.1145, "vn": -7.7309, "ip": .6002, "inn": -.01541},
          {"x": 1.344, "vp": 2.1779, "vn": -7.8437, "ip": 1.2137, "inn": -.0343},
          {"x": 2.56, "vp": 2.1802, "vn": -7.7251, "ip": 2.13426, "inn": -.0514632},
          {"x": 3.84, "vp": 2.15264, "vn": -7.8867, "ip": 2.91253, "inn": -.0957299}],
    "soa": {"vp": ["Vt2+", 1, 1.7052482326597274, .010814475389598174, 2.1338251606769485, 2.183514224890132],
            "vn": ["Vt2-", -1, 1.7052482326597274, .006758644201696505, 7.703915866993116, 7.856330403842027],
            "ip": ["It2+", 1, 1.7052482326597274, .8853326789209258, 1.4195543445506187, 1.4984574918281428],
            "inn": ["It2-", -1, 1.7052482326597274, .9679787370175855, .03472919025401326, .04363077033143844]},
    "range": (0.64, 3.84),
}

D2 = {
    "id": "clamp", "method": "late",
    "par": lambda x: {"a1": 829.4 / x ** .452, "r1": 5.462 / x ** .2865, "c1": .08357 / x ** -.207,
                      "a2": 30 / x ** -3.28e-29, "r2": 9.204 / x ** .3384, "c2": -.6568 / x ** .02765},
    "m": [{"x": 1415.232, "vp": 4.8121, "vn": -4.96245, "ip": 4.46711, "inn": -4.82594},
          {"x": 2021.76, "vp": 6.35918, "vn": -6.71245, "ip": 6.10259, "inn": -6.42855},
          {"x": 2628.288, "vp": 11.5124, "vn": -9.47609, "ip": 7.70351, "inn": -7.47626}],
    "soa": {"vp": ["Vt2+", 1, 1959.190790564251, 1.3726632026868713, 6.090603488345262, 7.691645019533501],
            "vn": ["Vt2-", -1, 1959.190790564251, 1.0334594160835273, 6.497875372967659, 6.994612508780857],
            "ip": ["It2+", 1, 1959.190790564251, .8799640088461418, 5.936085662066821, 5.948515095817292],
            "inn": ["It2-", -1, 1959.190790564251, .712730158253558, 6.063770015250391, 6.2861134455085015]},
    "range": (1415.232, 2628.288),
}

# ---- Capacitance spec (2026-07-28, 사용자 지시: radar 축용 spec equation) ----
# 실측 미제공 → 물리 기반 생성 모델(접합 C-V):
#     C(x, V) = C0 · (x/x0) / (1 − min(V, FC·Vbi)/Vbi)^mj
#   V = anode−cathode(순방향 양), 역방향(V<0)에서 감소, 순방향은 SPICE FC=0.5
#   관례로 Vbi/2 상한(발산 방지). 면적 선형 스케일(C ∝ x — I-V par와 동일 철학).
#   diode(D1): 기준 x=2.56에서 C0=250 fF (IO ESD diode급 zero-bias).
#   clamp(D2): drain 접합+gate 오버랩 ∝ W — 기준 x=1415.232에서 C0=2.1 pF.
# EM은 spec 대상에서 제외(사용자 지시). 실측 C 데이터가 오면 이 표만 교체.
CAP = {
    "diode": {"c0": 250e-15, "x0": 2.56, "vbi": 0.75, "mj": 0.45, "fc": 0.5},
    "clamp": {"c0": 2.1e-12, "x0": 1415.232, "vbi": 0.80, "mj": 0.40, "fc": 0.5},
}

# capLim: IO pad에서 바라본 총 capacitance 예산 (사용자 정의 2026-07-28 —
# "일반적인 GPIO에서 요구하는 IO단에서 바라본 spec, 작을수록 좋음").
# 관례: 범용 GPIO Cio max ≈ 5 pF (여유형 10 pF, 엄격형 3 pF; 고속 pad 0.5~1.5 pF).
# 판정은 소자 개별이 아니라 IO에 매달린 소자들의 합 ≤ IO_CAP_LIM.
IO_CAP_LIM = 5e-12

# I_ESD spec: HBM 레벨 ↔ 요구 전류 (사용자 지시 2026-07-28; 환산은 D9: 1 kV ↔ 1.33 A).
# 관례 레벨(JS-001 class 계열): 0.5 / 1 / 2 / 4 kV — 설계는 해당 전류까지 생존해야 한다.
A_PER_KV = 1.33
HBM_LEVELS_KV = (0.5, 1.0, 2.0, 4.0)
HBM_DEFAULT_KV = 1.0  # default spec 레벨 = HBM 1kV → 1.33A (사용자 지시 2026-07-28)


def hbm_current(kv):
    """HBM 레벨(kV) → 요구 주입 전류 [A] (D9 환산)."""
    return A_PER_KV * float(kv)


def cap_of(dev, x, v=0.0):
    """접합 capacitance C(x, V) [F] — dev는 D1/D2, x=size, v=양단 전압(순방향 양)."""
    p = CAP[dev["id"]]
    veff = min(v, p["fc"] * p["vbi"])
    return p["c0"] * (x / p["x0"]) / (1.0 - veff / p["vbi"]) ** p["mj"]


# D5: extrapolation window = measured split min/max +-50%
EXTRAP = 0.5


def xwindow(d):
    lo, hi = d["range"]
    return lo * (1 - EXTRAP), hi * (1 + EXTRAP)


def g0(v, x, d):
    p = d["par"](x)
    return sg(p["a1"] * (v - p["c1"])) / p["r1"] + sg(p["a2"] * (p["c2"] - v)) / p["r2"]


def mod(t, T, q, d):
    if d["method"] == "late":
        r = t / T
        if r <= .5:
            z = 0.0
        else:
            u = 2 * r - 1
            z = 3 * u * u - 2 * u * u * u
        return .35 + .65 / (1 + 2 * z ** 1.5)
    vd = .45 * T
    k = 10 / T
    z = (sp(k * (t - vd)) - sp(-k * vd)) / (sp(k * (T - vd)) - sp(-k * vd))
    return math.exp(-q * z * z)


def integ(x, d, T, q, s, neg, n=N):
    h = T / n
    a = 0.0
    for j in range(n + 1):
        t = j * h
        v = -t if neg else t
        y = g0(v, x, d) * mod(t, T, q, d) * s
        a += (1.0 if 0 < j < n else .5) * y
    return a * h


def corr(x, d, T, I, neg, n=N):
    if d["method"] == "late":
        return {"q": 2, "s": I / integ(x, d, T, 2, 1, neg, n)}
    l, h = -1.0, 1.0
    while integ(x, d, T, l, 1, neg, n) < I:
        l *= 2
    while integ(x, d, T, h, 1, neg, n) > I:
        h *= 2
    for _ in range(65):
        m2 = (l + h) / 2
        if integ(x, d, T, m2, 1, neg, n) > I:
            l = m2
        else:
            h = m2
    return {"q": (l + h) / 2, "s": 1}


def branch(x, d, T, c, neg, n=N):
    h = T / n
    V, I, G = [0.0], [0.0], []
    s = 0.0
    p = g0(0, x, d) * mod(0, T, c["q"], d) * c["s"]
    G.append(p)
    for j in range(1, n + 1):
        t = j * h
        v = -t if neg else t
        g = g0(v, x, d) * mod(t, T, c["q"], d) * c["s"]
        s += (p + g) * h / 2
        V.append(v)
        I.append(-s if neg else s)
        G.append(g)
        p = g
    return {"V": V, "I": I, "G": G}


def sv(a, x, c):
    return a[1] * (a[4] if c == "worst" else a[5]) * (x / a[2]) ** a[3]


def ep(d, x, c):
    return {"x": x, "vp": sv(d["soa"]["vp"], x, c), "vn": sv(d["soa"]["vn"], x, c),
            "ip": sv(d["soa"]["ip"], x, c), "inn": sv(d["soa"]["inn"], x, c)}


def calib(d, x, c, n=N):
    """n: 적분/곡선 격자 — 기본 N(정밀). optimizer loss 평가는 저해상도 n 허용."""
    e = ep(d, x, c)
    cp = corr(x, d, e["vp"], e["ip"], False, n)
    cn = corr(x, d, -e["vn"], -e["inn"], True, n)
    return {"e": e, "pos": branch(x, d, e["vp"], cp, False, n),
            "neg": branch(x, d, -e["vn"], cn, True, n), "cp": cp, "cn": cn}


def VofI(br, i):
    """Invert a monotone calibrated branch: current -> voltage (NaN beyond endpoint)."""
    I, V = br["I"], br["V"]
    n = len(I) - 1
    end_i = I[n]
    asc = end_i >= 0
    if (i > end_i) if asc else (i < end_i):
        return float("nan")
    lo, hi = 0, n
    while hi - lo > 1:
        m2 = (lo + hi) // 2
        if (I[m2] <= i) if asc else (I[m2] >= i):
            lo = m2
        else:
            hi = m2
    denom = (I[hi] - I[lo]) or 1
    f = (i - I[lo]) / denom
    return V[lo] + f * (V[hi] - V[lo])


# --- series path: IO port -Rio_rdl-> diode tap -D_up-> rail -RDD_un1-> clamp top
#     -clamp-> clamp bottom -RDD_dn1-> VSS rail(node A) -Rvss_rdl-> VSS port.
#   RDL 3종(고정 0.1Ω, 사용자 지시 2026-07-21): Rio_rdl, Rvdd_rdl(VDD port 분기 — 양(+)
#     IO->VSS 스트레스 무전류), Rvss_rdl.
#   DD(device-to-device) 금속 2종(0.5Ω/350µm 규칙, L 변수·공유 — D7; 사용자 지시 2026-07-27):
#     RDD_un1 = up diode ↔ nmos clamp 1stk (VDD rail), RDD_dn1 = down diode ↔ nmos clamp 1stk
#     (VSS rail). 양(+) 스트레스에서 둘 다 주 경로에 직렬.
RIO_RDL, RVDD_RDL, RVSS_RDL = 0.1, 0.1, 0.1
RIO = RIO_RDL  # 하위 호환 별칭
RDD_UN1 = 0.5  # up diode ↔ clamp 금속 (구 Rvdd; L=350 기준값, L 변수는 optimizer.rvdd_of)
RDD_DN1 = 0.5  # down diode ↔ clamp 금속 (동일 규칙·공유 L)


def series_vio(c1, c2, I, rio=RIO_RDL, rdd_un1=RDD_UN1, rdd_dn1=RDD_DN1, rvss=RVSS_RDL):
    return I * (rio + rdd_un1 + rdd_dn1 + rvss) + VofI(c1["pos"], I) + VofI(c2["pos"], I)


# --- victim probe: PMOS+NMOS inverter, drain node OUT reached from IO via Resd.
# Positive stress, dominant-path post-process (Resd=500 >> path R, victim current
# is mA-scale so it does not disturb the main path solve).
#   IO --Resd--> OUT ; PMOS drain-bulk junction OUT -> VDD_local (forward when
#   V_OUT > VDD_local + Von) ; NMOS drain junction OUT -> VSS (off below BV).
# NMOS drain stress = V_OUT - VSS_local(=0) ; victim current = (V_IO - V_OUT)/Resd.
VICTIM_RESD, VICTIM_VON, VICTIM_RONJ = 500.0, 0.7, 10.0


def victim_probe(vio, vdd_local, resd=VICTIM_RESD, von=VICTIM_VON, ronj=VICTIM_RONJ):
    """Return (v_out, i_v). Junction off -> v_out = vio, i_v = 0."""
    if vio - vdd_local - von <= 0:
        return vio, 0.0
    v_out = (ronj * vio + resd * (vdd_local + von)) / (ronj + resd)
    return v_out, (vio - v_out) / resd
