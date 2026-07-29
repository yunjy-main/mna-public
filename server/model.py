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
    # SOA-local 재보정 (이슈 #16): 원본 I-V·size 경향 보존, SOA 근방만 국소 보정.
    # pos: 1.6V까지 원본 그대로 → 이후 완만한 saturation으로 endpoint 도달.
    # neg: raw 진행률 70%까지 원본 → endpoint/raw 관계에 따라 국소 감쇠/breakdown 증가.
    "correction": {
        "pos": {"mode": "saturation_v", "v_start": 1.6},
        "neg": {"mode": "local_exp_q", "q_start": 0.70},
    },
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
    # SOA-local 재보정 (이슈 #16): 구 branch 전체 scale 제거 — raw 전류 진행률 20%까지
    # 원본 그대로(저전류 width 경향 보존), 이후 국소 saturation으로 endpoint 도달.
    # 창 밖 외삽에서 envelope가 raw보다 큰 전류를 요구하면 국소 exp boost로 자동 대체.
    "correction": {
        "pos": {"mode": "saturation_q", "q_start": 0.20},
        "neg": {"mode": "saturation_q", "q_start": 0.20},
    },
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

# capLim: IO pad에서 바라본 총 capacitance 예산 — 0.7 pF 이하
# (사용자 지시 2026-07-29 — 고속 pad급으로 강화; 판정은 contributor 합 ≤ IO_CAP_LIM).
IO_CAP_LIM = 0.7e-12

# I_ESD spec: HBM 레벨 ↔ 요구 전류 (사용자 지시 2026-07-28; 환산은 D9: 1 kV ↔ 1.33 A).
# 관례 레벨(JS-001 class 계열): 0.5 / 1 / 2 / 4 kV — 설계는 해당 전류까지 생존해야 한다.
A_PER_KV = 1.33
HBM_LEVELS_KV = (0.5, 1.0, 2.0, 4.0)
HBM_DEFAULT_KV = 1.0  # default spec 레벨 = HBM 1kV → 1.33A (사용자 지시 2026-07-28)

# 자유 파라미터 meta — 파라미터 '이름'은 schematic에서 발견(netlist.free_params)되고,
# 기본값·창은 모델 계층인 여기서 공급한다 (2-소자 시절 x1/x2 하드코딩 청산, 2026-07-28).
# dev가 있으면 창=xwindow(해당 device), 없으면 lo/hi 직접.
PARAM_META = {
    # 자유 파라미터 속성의 정본 (이슈 #11 §2.2) — rule: optimizer 탐색 창(비대칭 barrier,
    # 측정 유효창 xwindow와 구분·없으면 변수화 불가=강제 고정 E3), label/dec: 표시,
    # cost_w: loss 자원 cost 기본 가중치, freeze_default: 자물쇠 기본,
    # min_valid: API 값 하한(초과 필수, E5 — 기본 0)
    # rule 창 갱신 (사용자 지시 2026-07-29): x1 min 2.5, x2 max 3024, L max 350
    "x1": {"default": 2.56, "unit": "", "dev": "diode", "rule": (2.5, 3.84),
           "label": "x1 (diode size)", "dec": 3, "cost_w": 1.0, "freeze_default": False},
    "x2": {"default": 1415.232, "unit": "", "dev": "clamp", "rule": (1415.232, 3024.0),
           "label": "x2 (clamp size)", "dec": 1, "cost_w": 1.0, "freeze_default": False},
    "L": {"default": 350.0, "unit": "µm", "lo": 70.0, "hi": 1400.0, "rule": (70.0, 350.0),
          "label": "L (RDD 금속)", "dec": 1, "cost_w": 0.0, "freeze_default": True},
    # W: RDD 금속 폭 — rdd_r(L,W) 기준 5µm. rule 창 [1,12]µm (사용자 확정 2026-07-28)
    "W": {"default": 5.0, "unit": "µm", "rule": (1.0, 12.0),
          "label": "W (RDD 금속 폭)", "dec": 2, "cost_w": 0.0, "freeze_default": True},
}


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
    """Legacy 진단용 변조 함수 — API/문서 호환 보존 (이슈 #16).
    신 runtime branch는 corr()가 반환하는 correction 메타를 사용한다."""
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
    """Legacy 적분 — corr() 신경로 밖 호출자(문서·플롯)용 보존."""
    h = T / n
    a = 0.0
    for j in range(n + 1):
        t = j * h
        v = -t if neg else t
        y = g0(v, x, d) * mod(t, T, q, d) * s
        a += (1.0 if 0 < j < n else .5) * y
    return a * h


# ---- SOA-local 재보정 core (이슈 #16) ----
# 원본 softplus I-V(raw)와 실측 SOA source를 유지하고, SOA 근방에서만 컨덕턴스를
# 국소 보정한다. H_sat(u,p) = ε + (1−ε)(1−S(u))^p — 시작에서 연속(H=1, dH/du=0),
# endpoint에서 기울기 ε>0 유지(calibtable C1 확장 유한성). g_model = g_raw·H > 0.
SATURATION_FLOOR = 0.02


def _smoothstep(u):
    u = max(0.0, min(1.0, u))
    return 3.0 * u * u - 2.0 * u * u * u


def _raw_grid(x, d, T, neg, n):
    h = T / n
    V, Iabs, G, TT = [0.0], [0.0], [g0(0.0, x, d)], [0.0]
    acc = 0.0
    prev = G[0]
    for j in range(1, n + 1):
        t = j * h
        v = -t if neg else t
        cur = g0(v, x, d)
        acc += (prev + cur) * h / 2.0
        V.append(v)
        Iabs.append(acc)
        G.append(cur)
        TT.append(t)
        prev = cur
    return V, Iabs, G, TT


def _integrate_scaled(G, TT, mult):
    acc = 0.0
    for j in range(1, len(TT)):
        h = TT[j] - TT[j - 1]
        acc += (G[j - 1] * mult[j - 1] + G[j] * mult[j]) * h / 2.0
    return acc


def _sat_multiplier(shape, power):
    base = max(0.0, 1.0 - shape)
    return SATURATION_FLOOR + (1.0 - SATURATION_FLOOR) * base ** power


def _bisect_monotone(fn, target, lo, hi, increasing, iterations=80):
    vlo, vhi = fn(lo), fn(hi)
    lower, upper = (vlo, vhi) if increasing else (vhi, vlo)
    if target < lower - 1e-12 or target > upper + 1e-12:
        raise ValueError("target {} outside correction range [{}, {}]".format(
            target, lower, upper))
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        value = fn(mid)
        if (value < target) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _shape_from_config(cfg, TT, Iraw, T):
    mode = cfg["mode"]
    if mode == "saturation_v":
        start = cfg["v_start"]
        if not 0.0 < start < T:
            raise ValueError("v_start must lie inside branch: {} vs {}".format(start, T))
        return [_smoothstep((t - start) / (T - start)) if t > start else 0.0
                for t in TT]
    start = cfg["q_start"]
    raw_end = Iraw[-1]
    if not 0.0 <= start < 1.0:
        raise ValueError("q_start must be in [0,1)")
    return [_smoothstep((q - start) / (1.0 - start)) if q > start else 0.0
            for q in (value / raw_end for value in Iraw)]


def corr(x, d, T, I, neg, n=N):
    """branch 보정 계수 산출 — 전역 scale 없이 SOA-local 보정 (이슈 #16).

    계약 호환: signature 불변, 반환에 q·s 호환 필드 포함(regression/calibtable),
    branch()가 반환 dict를 그대로 수용. endpoint는 이분법으로 정확히 도달."""
    target = abs(I)
    if target <= 0.0:
        raise ValueError("endpoint current must be non-zero")
    _, Iraw, Graw, TT = _raw_grid(x, d, T, neg, n)
    raw_end = Iraw[-1]
    side = "neg" if neg else "pos"
    cfg = d["correction"][side]
    shape = _shape_from_config(cfg, TT, Iraw, T)
    requested_mode = cfg["mode"]

    if requested_mode.startswith("saturation") and target <= raw_end * (1.0 + 1e-12):
        def endpoint(power):
            mult = [_sat_multiplier(z, power) for z in shape]
            return _integrate_scaled(Graw, TT, mult)

        try:
            power = _bisect_monotone(endpoint, target, 0.0, 512.0, False)
            return {"mode": requested_mode, "power": power,
                    "v_start": cfg.get("v_start"), "q_start": cfg.get("q_start"),
                    "raw_end": raw_end, "target": target,
                    "q": power, "s": target / raw_end}
        except ValueError:
            pass  # gate/floor로 도달 불가 — adaptive q_start fallback (PR#17 리뷰 2)

    q_start = cfg.get("q_start", 0.70)
    ratio = target / raw_end
    if ratio < 1.0 and ratio <= q_start + 0.02:
        q_start = max(0.05, ratio - 0.05)

    # fallback/boost 경로는 branch()가 사용할 q-shape로 fitting을 통일한다
    # (PR#17 리뷰 1: v-shape로 fitting 후 q-shape branch를 만드는 불일치 제거)
    cfg_local = {"mode": "local_exp_q", "q_start": q_start}
    shape = _shape_from_config(cfg_local, TT, Iraw, T)

    if target <= raw_end * (1.0 + 1e-12):
        def endpoint_reduce(power):
            mult = [_sat_multiplier(z, power) for z in shape]
            return _integrate_scaled(Graw, TT, mult)

        power = _bisect_monotone(endpoint_reduce, target, 0.0, 512.0, False)
        # 반환 mode는 fitting에 쓴 shape와 동일한 q-기반으로 고정 (shape 정합)
        return {"mode": "saturation_q", "power": power,
                "v_start": cfg.get("v_start"), "q_start": q_start,
                "raw_end": raw_end, "target": target,
                "q": power, "s": target / raw_end,
                "fallback_from": (requested_mode
                                  if requested_mode != "saturation_q" else None)}

    def endpoint_boost(beta):
        mult = [math.exp(beta * z) for z in shape]
        return _integrate_scaled(Graw, TT, mult)

    beta = _bisect_monotone(endpoint_boost, target, 0.0, 120.0, True)
    return {"mode": "local_exp_q", "beta": beta, "q_start": q_start,
            "raw_end": raw_end, "target": target,
            "q": beta, "s": target / raw_end,
            "fallback_from": (requested_mode if requested_mode != "local_exp_q" else None)}


def branch(x, d, T, c, neg, n=N):
    """보정 branch 생성 — 반환 스키마(V/I/G) 불변, raw 진단 배열은 additive.
    correction 메타 없는 c(legacy q/s dict)는 구 경로로 처리(호환)."""
    if "mode" not in c:
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

    V, Iraw, Graw, TT = _raw_grid(x, d, T, neg, n)
    if c["mode"].startswith("saturation"):
        if c["mode"] == "saturation_v":
            shape_cfg = {"mode": "saturation_v", "v_start": c["v_start"]}
        else:
            shape_cfg = {"mode": "saturation_q", "q_start": c["q_start"]}
        shape = _shape_from_config(shape_cfg, TT, Iraw, T)
        mult = [_sat_multiplier(z, c["power"]) for z in shape]
    else:
        local_cfg = {"mode": "local_exp_q", "q_start": c["q_start"]}
        shape = _shape_from_config(local_cfg, TT, Iraw, T)
        mult = [math.exp(c["beta"] * z) for z in shape]
    G = [g * m for g, m in zip(Graw, mult)]
    Iabs = [0.0]
    acc = 0.0
    for j in range(1, len(TT)):
        h = TT[j] - TT[j - 1]
        acc += (G[j - 1] + G[j]) * h / 2.0
        Iabs.append(acc)
    I = [-value for value in Iabs] if neg else Iabs
    return {"V": V, "I": I, "G": G,
            "I_raw": ([-value for value in Iraw] if neg else Iraw),
            "G_raw": Graw, "multiplier": mult}


def sv(a, x, c):
    return a[1] * (a[4] if c == "worst" else a[5]) * (x / a[2]) ** a[3]


def ep(d, x, c):
    return {"x": x, "vp": sv(d["soa"]["vp"], x, c), "vn": sv(d["soa"]["vn"], x, c),
            "ip": sv(d["soa"]["ip"], x, c), "inn": sv(d["soa"]["inn"], x, c)}


def measured_ep(d, x):
    """실측 row 구간선형 보간 endpoint — 검토·플롯용 (이슈 #16 MODEL_SPEC §2).
    runtime 정본은 worst/best 멱법칙 envelope(ep) 그대로다."""
    rows = d["m"]
    lo, hi = rows[0], rows[1]
    for a, b in zip(rows, rows[1:]):
        lo, hi = a, b
        if x <= b["x"]:
            break
    f = (x - lo["x"]) / (hi["x"] - lo["x"])
    out = {"x": x}
    for k in ("vp", "vn", "ip", "inn"):
        out[k] = lo[k] + f * (hi[k] - lo[k])
    return out


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
RDD_W0 = 5.0   # 금속 기준 폭 [µm] — 0.5Ω/350µm는 W=5µm 기준 (사용자 지시 2026-07-28)


def rdd_r(L, W=RDD_W0):
    """RDD 금속 저항 [Ω] — sheet 스케일: 0.5Ω × (L/350µm) × (5µm/W)."""
    return RDD_UN1 * (float(L) / 350.0) * (RDD_W0 / float(W))


# 바인딩 함수 레지스트리 (이슈 #11 §2.2) — schematic의 func_expr(예: "rdd(L,W)")
# 함수명 → 물리 함수. 새 물리식은 여기 등록하면 파서(발견=평가)가 자동 연결.
BINDING_FUNCS = {"rdd": rdd_r}


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
