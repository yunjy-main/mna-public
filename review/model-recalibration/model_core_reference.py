# Reference fragment inserted into the existing mna/server/model.py.
# This file is not standalone; use tools/apply_model_recalibration.py.

D1_CORRECTION = r'''
    "correction": {
        # Positive: preserve exact raw I-V through 1.6 V, then gently saturate.
        "pos": {"mode": "saturation_v", "v_start": 1.6},
        # Negative: preserve raw size trend until 70% of raw endpoint current;
        # then locally increase/decrease conductance to reach the SOA endpoint.
        "neg": {"mode": "local_exp_q", "q_start": 0.70},
    },
'''

D2_CORRECTION = r'''
    "correction": {
        # Both polarities retain the raw width trend at low current and reduce
        # conductance only near SOA. Outside the supported size range, if an
        # envelope requires more current than raw I-V, corr() uses a local
        # exponential fallback rather than a global scale.
        "pos": {"mode": "saturation_q", "q_start": 0.20},
        "neg": {"mode": "saturation_q", "q_start": 0.20},
    },
'''

# Replacement for def mod(...) through immediately before def sv(...):


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
    # A non-zero floor keeps calibtable's C1 extension finite and smooth.
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


def mod(t, T, q, d):
    """Legacy diagnostic modifier retained for API compatibility.

    New runtime branches use correction metadata returned by corr(). Keeping
    this function avoids breaking docs/main code that imports or plots it.
    """
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
    """Legacy integral retained for callers outside the new corr() path."""
    h = T / n
    a = 0.0
    for j in range(n + 1):
        t = j * h
        v = -t if neg else t
        y = g0(v, x, d) * mod(t, T, q, d) * s
        a += (1.0 if 0 < j < n else .5) * y
    return a * h


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
    """Calibrate one branch without a global conductance scale.

    Contract compatibility:
    - signature is unchanged;
    - result always includes q and s for regression/calibtable callers;
    - branch() accepts the returned dictionary directly.
    """
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

        power = _bisect_monotone(endpoint, target, 0.0, 512.0, False)
        return {"mode": requested_mode, "power": power,
                "v_start": cfg.get("v_start"), "q_start": cfg.get("q_start"),
                "raw_end": raw_end, "target": target,
                "q": power, "s": target / raw_end}

    q_start = cfg.get("q_start", 0.70)
    ratio = target / raw_end
    if ratio < 1.0 and ratio <= q_start + 0.02:
        q_start = max(0.05, ratio - 0.05)

    if requested_mode != "saturation_v":
        cfg_local = {"mode": "local_exp_q", "q_start": q_start}
        shape = _shape_from_config(cfg_local, TT, Iraw, T)

    if target <= raw_end * (1.0 + 1e-12):
        def endpoint_reduce(power):
            mult = [_sat_multiplier(z, power) for z in shape]
            return _integrate_scaled(Graw, TT, mult)

        power = _bisect_monotone(endpoint_reduce, target, 0.0, 512.0, False)
        mode = "saturation_v" if requested_mode == "saturation_v" else "saturation_q"
        return {"mode": mode, "power": power,
                "v_start": cfg.get("v_start"), "q_start": q_start,
                "raw_end": raw_end, "target": target,
                "q": power, "s": target / raw_end,
                "fallback_from": (requested_mode if requested_mode != mode else None)}

    def endpoint_boost(beta):
        mult = [math.exp(beta * z) for z in shape]
        return _integrate_scaled(Graw, TT, mult)

    beta = _bisect_monotone(endpoint_boost, target, 0.0, 120.0, True)
    return {"mode": "local_exp_q", "beta": beta, "q_start": q_start,
            "raw_end": raw_end, "target": target,
            "q": beta, "s": target / raw_end,
            "fallback_from": (requested_mode if requested_mode != "local_exp_q" else None)}


def branch(x, d, T, c, neg, n=N):
    """Build a corrected branch with the original project return schema."""
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
