# Full model specification for `mna`

## 1. Raw bidirectional model

For device size `x`, the original project parameter functions are unchanged.

```text
F(v,x) = softplus(a1(x)(v-c1(x))) / (r1(x)a1(x))
       - softplus(a2(x)(c2(x)-v)) / (r2(x)a2(x))

I_raw(v,x) = F(v,x) - F(0,x)

g_raw(v,x) = dI_raw/dv
             = sigmoid(a1(x)(v-c1(x))) / r1(x)
             + sigmoid(a2(x)(c2(x)-v)) / r2(x) > 0
```

The original D1 and D2 parameter equations and all measured rows remain the source data in `server/model.py`.

## 2. SOA endpoint

The project runtime continues to use the existing worst/best power-law envelopes:

```text
SOA_k(x, corner) = sign_k * C_k(corner) * (x/x0_k)^p_k
```

Thus `ep(d, x, "worst")` and `ep(d, x, "best")` remain unchanged.

For review plots, the optional `measured_ep(d,x)` performs piecewise-linear interpolation through the original measured rows. It does not replace the runtime worst/best envelope.

## 3. Common saturation multiplier

Let `S(u)=3u^2-2u^3`, with `u` clipped to `[0,1]`.

```text
H_sat(u,p) = epsilon + (1-epsilon) * (1-S(u))^p
```

where `epsilon=0.02`.

Properties:

- `H_sat(0,p)=1`: the correction starts continuously from the raw model.
- `dH_sat/du=0` at the start and endpoint.
- `H_sat(1,p)=epsilon`: the endpoint slope is small but non-zero.
- `g_model = g_raw * H_sat > 0`: monotonic I-V is guaranteed.
- A non-zero endpoint slope keeps `calibtable.py`'s C1 extension finite.

The exponent `p` is solved by bisection so that integration reaches the selected SOA endpoint exactly.

## 4. Diode positive branch

The accepted start voltage is fixed at `1.6 V`.

```text
u(v) = clip((v-1.6)/(V_SOA-1.6), 0, 1)

g_model(v,x) = g_raw(v,x) * H_sat(u(v),p)
```

Therefore the diode positive branch is exactly raw through 1.6 V and gradually saturates afterward.

## 5. Diode negative branch

Define raw-current progress:

```text
q(v,x) = |I_raw(v,x)| / |I_raw(V_SOA,x)|
```

The nominal start is `q0=0.70`.

When the SOA endpoint current is below the raw endpoint current, the finite-floor saturation multiplier is used.

When the endpoint current is above raw, a local breakdown-like multiplier is used:

```text
u = clip((q-q0)/(1-q0), 0, 1)
H_boost = exp(beta * S(u))
g_model = g_raw * H_boost
```

`beta` is solved to hit the endpoint. This preserves positive differential conductance while allowing the large-size negative endpoint current to exceed the raw model only near SOA.

## 6. Clamp positive and negative branches

Both use current-progress gating with `q0=0.20`:

```text
u = clip((q-0.20)/0.80, 0, 1)
g_model = g_raw * H_sat(u,p)
```

Consequences:

- the first 20% of the raw current progression is exactly unchanged;
- no branch-wide `scale` is applied;
- larger clamp size retains its lower operating voltage;
- the SOA endpoint is matched by late conductance reduction.

At the far extrapolation edge only, if the envelope asks for more current than raw I-V, the same local exponential boost used above is selected automatically. This does not occur for clamp sizes inside the current optimization rule range.

## 7. Numerical branch construction

The project interface remains numerical and deterministic:

```text
I_model(v_j) = integral_0^v_j g_model(v,x) dv
```

using the existing unified trapezoidal grid `N`.

The return schema remains:

```python
{"V": [...], "I": [...], "G": [...]}
```

Additional raw diagnostic arrays are included without changing existing consumers.

## 8. MNA integration contract

No MNA equation changes are required.

- `calib()` still produces monotone branches.
- `VofI()` still inverts those branches.
- `series_vio()` still sums diode voltage, clamp voltage, and metal drops.
- `calibtable.py` still precomputes branch samples and log-size interpolation.
- optimizer numerical derivatives continue to observe the updated V(I,x) through the same table/API boundary.

Generated calibration tables and regression golden values must be rebuilt because the numerical V(I,x) values intentionally change.
