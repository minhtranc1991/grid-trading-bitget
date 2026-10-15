import argparse
import json
import logging
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
URL = "https://api.bitget.com/api/v2/spot/market/history-candles"
GRAN = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}
BAR_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
PAGE = 200  # history-candles limit tối đa (đã thử: 1000 -> lỗi 40020)
LOG_PATH = Path(__file__).parent / "results" / "run.log"
log = logging.getLogger("grid")
COLS = ["ts", "open", "high", "low", "close", "base_vol", "quote_vol"]


def _get(symbol, tf, end_ms):
    q = f"?symbol={symbol}&granularity={GRAN[tf]}&limit={PAGE}&endTime={end_ms}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(URL + q, timeout=20) as r:
                d = json.load(r)
            if d["code"] == "00000":
                return d["data"]
            raise RuntimeError(d)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def _fetch_range(symbol, tf, start_ms, end_ms):
    """Phân trang lùi từ end_ms tới start_ms; trả list hàng thô."""
    rows, end = [], end_ms
    while True:
        b = _get(symbol, tf, end)
        if not b:
            break
        rows += b
        first = int(b[0][0])
        if first <= start_ms or first >= end:
            break
        end = first
        time.sleep(0.06)  # tránh chạm rate limit
    return rows


def _clean(rows, tf, now_ms=None):
    df = pd.DataFrame([r[:7] for r in rows], columns=COLS).astype(float)
    df["ts"] = df["ts"].astype("int64")
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if now_ms is not None:  # bỏ nến đang chạy dở
        df = df[df.ts + BAR_MS[tf] <= now_ms].reset_index(drop=True)
    return df


def load_ohlcv(symbol, tf="15m", days=540):
    path = DATA_DIR / f"{symbol}_{tf}.csv"
    now = int(time.time() * 1000)
    start = now - days * 86_400_000
    bar = BAR_MS[tf]
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=COLS)
    rows = old.values.tolist()
    if old.empty:
        rows += _fetch_range(symbol, tf, start, now)
    else:
        if int(old.ts.iloc[-1]) + bar < now:
            rows += _fetch_range(symbol, tf, int(old.ts.iloc[-1]), now)
        if int(old.ts.iloc[0]) > start + bar:
            rows += _fetch_range(symbol, tf, start, int(old.ts.iloc[0]))
    df = _clean(rows, tf, now)
    log.info("%s %s: cache %d -> %d bars, fetched %d raw rows", symbol, tf, len(old), len(df), len(rows) - len(old))
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(path, index=False)
    return df


def _cross(P, low, high, n, mode):
    lines = (np.linspace if mode == "arithmetic" else np.geomspace)(low, high, n + 1)
    return lines, np.searchsorted(lines, P, side="right")  # c = số line <= giá


def grid_equity(prices, low, high, n, mode="arithmetic", fee=0.0):
    """Equity chuẩn hóa (vốn đầu = 1) của grid n khoảng giữa low..high; fee = tỷ lệ mỗi chiều.
    Equity là hàm của (giá, số line đã cắt) nên không phụ thuộc đường đi, đúng với Chen et al."""
    P = np.asarray(prices, float)
    lines, c = _cross(P, low, high, n, mode)
    m = n + 1
    S = np.concatenate(([0.0], np.cumsum(lines)))
    c0 = c[0]
    Gv = 1.0 / ((m - c0) * P[0] + S[c0])
    Sc = S[c]
    fees = np.cumsum(fee * Gv * np.abs(np.diff(Sc, prepend=Sc[0])))
    return Gv * Sc + Gv * (m - c) * P - fees


def grid_stats(prices, low, high, n, mode="arithmetic"):
    """(số giao dịch = tổng |Δc|, turnover = tổng notional giao dịch / vốn đầu)."""
    P = np.asarray(prices, float)
    lines, c = _cross(P, low, high, n, mode)
    S = np.concatenate(([0.0], np.cumsum(lines)))
    c0 = c[0]
    Gv = 1.0 / ((n + 1 - c0) * P[0] + S[c0])
    return int(np.abs(np.diff(c)).sum()), float(Gv * np.abs(np.diff(S[c])).sum())


BARS_PER_YEAR = {"1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520, "1h": 8760, "4h": 2190}  # crypto 24/7


def metrics(equity, bars_per_year, trades=0, turnover=0.0):
    eq = np.asarray(equity, float)
    r = np.diff(eq) / eq[:-1]
    sd = r.std(ddof=1)
    return {
        "sharpe": float(r.mean() / sd * np.sqrt(bars_per_year)) if sd > 0 else 0.0,
        "return": float(eq[-1] / eq[0] - 1),
        "mdd": float((eq / np.maximum.accumulate(eq) - 1).min()),
        "trades": trades,
        "turnover": turnover,
    }


def buy_and_hold(prices):
    return np.asarray(prices, float) / prices[0]


# --- STEP 4: quét tham số trên một cửa sổ (IN-SAMPLE, chưa dùng để kết luận) ---
MAX_GRIDS = 100  # cần xác minh: docs Bitget không nêu giới hạn số lưới (xem UI từng cặp)
DEFAULT_FEE = 0.001  # cần xác minh: 0.1%/chiều theo ảnh app 2026-10-15
N_LIST = [4, 6, 8, 10, 15, 20, 30, 40, 60, 80, 100]
D_CRYPTO = [0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.50]
D_GOLD = [0.0025, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.08]
GOLD = ("PAXGUSDT", "XAUTUSDT")


def space_for(symbol):
    d = D_GOLD if symbol in GOLD else D_CRYPTO
    return {"dl": d, "dh": d, "n": N_LIST, "mode": ["arithmetic", "geometric"]}


def step_pct(low, high, n, mode):
    """Bước tương đối nhỏ nhất giữa 2 line (Yeh Eq.16: g_{i+1}-g_i > h*g_{i+1})."""
    if mode == "arithmetic":
        return (high - low) / n / high
    return (high / low) ** (1 / n) - 1


def sweep(prices, space, fee, bars_per_year=BARS_PER_YEAR["15m"], safety=2.0, min_trades=20, max_grids=MAX_GRIDS):
    """Quét lưới tham số, trả DataFrame sắp theo Sharpe giảm dần. IN-SAMPLE."""
    P = np.asarray(prices, float)
    p0, rows = P[0], []
    for dl in space["dl"]:
        for dh in space["dh"]:
            low, high = p0 * (1 - dl), p0 * (1 + dh)
            for n in space["n"]:
                if n > max_grids:
                    continue
                for mode in space["mode"]:
                    st = step_pct(low, high, n, mode)
                    if st < 2 * fee * safety:
                        continue
                    trades, turn = grid_stats(P, low, high, n, mode)
                    if trades < min_trades:
                        continue
                    m = metrics(grid_equity(P, low, high, n, mode, fee), bars_per_year, trades, turn)
                    rows.append({"dl": dl, "dh": dh, "n": n, "mode": mode, "step_pct": st, **m})
    cols = ["dl", "dh", "n", "mode", "step_pct", "sharpe", "return", "mdd", "trades", "turnover"]
    return pd.DataFrame(rows, columns=cols).sort_values("sharpe", ascending=False).reset_index(drop=True)


def heatmap(df, path, title):
    """Sharpe tốt nhất theo (dl, n) trên lát cắt đối xứng dh = dl, max trên mode."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    pv = df[np.isclose(df.dl, df.dh)].pivot_table(index="dl", columns="n", values="sharpe", aggfunc="max")
    v = pv.values
    lim = max(abs(np.nanmin(v)), abs(np.nanmax(v)), 1e-9)
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(v, cmap="RdBu", norm=TwoSlopeNorm(0, -lim, lim), aspect="auto", origin="lower")
    ax.set_xticks(range(len(pv.columns)), pv.columns)
    ax.set_yticks(range(len(pv.index)), [f"{x * 100:g}%" for x in pv.index])
    for (i, j), val in np.ndenumerate(v):
        if not np.isnan(val):
            ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8)
    ax.set_xlabel("n (số khoảng lưới)")
    ax.set_ylabel("dl (low = P0·(1-dl))")
    ax.set_title(title + "\nIN-SAMPLE: không dùng để kết luận (dh = dl, max trên mode)")
    fig.colorbar(im, label="Sharpe")
    Path(path).parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def run_sweep(symbol, tf, df, window_days, fee):
    t0 = time.time()
    n = window_days * 86_400_000 // BAR_MS[tf]
    P = df.close.values[-n:]
    res = sweep(P, space_for(symbol), fee, BARS_PER_YEAR[tf])
    bh = metrics(buy_and_hold(P), BARS_PER_YEAR[tf])
    total = len(space_for(symbol)["dl"]) * len(space_for(symbol)["dh"]) * len(N_LIST) * 2
    log.info("SWEEP %s %dd: %d/%d tổ hợp qua bộ lọc, %.1fs. IN-SAMPLE, chưa dùng để kết luận", symbol, window_days, len(res), total, time.time() - t0)
    fmt = {"dl": "{:.2%}".format, "dh": "{:.2%}".format, "step_pct": "{:.2%}".format, "sharpe": "{:.2f}".format,
           "return": "{:+.1%}".format, "mdd": "{:.1%}".format, "turnover": "{:.1f}".format}
    print(f"\n== {symbol} sweep {window_days}d (IN-SAMPLE, chưa dùng để kết luận) ==\nTOP 10")
    print(res.head(10).to_string(formatters=fmt))
    print(f"B&H cùng cửa sổ: sharpe={bh['sharpe']:.2f} return={bh['return']:+.1%} mdd={bh['mdd']:.1%}")
    print("BOTTOM 5")
    print(res.tail(5).to_string(formatters=fmt))
    out = Path(__file__).parent / "results" / f"heatmap_{symbol[:-4]}.png"
    meta = {"window_days": window_days, "fee": fee, "combos": total, "passed": len(res), "bh": bh,
            "rows": res.to_dict("records")}
    (out.parent / f"sweep_{symbol}.json").write_text(json.dumps(meta), encoding="utf-8")  # cho make_report.py
    heatmap(res, out, f"{symbol} Sharpe: dl x n ({window_days}d)")
    log.info("SWEEP %s B&H cửa sổ: sharpe=%.2f return=%+.1f%%; top1 sharpe=%.2f", symbol, bh["sharpe"], 100 * bh["return"], res.sharpe.iloc[0])
    log.info("SWEEP %s heatmap -> %s", symbol, out)
    return res


# --- STEP 5: walk-forward (train -> test, trượt) ---
DAY_MS = 86_400_000
DEFAULT_GRID = {"dl": 0.10, "dh": 0.10, "n": 20, "mode": "arithmetic"}  # lưới mặc định để so sánh


# --- STEP 7: baseline DGT (reset lưới khi giá phá biên, Chen et al.) ---
def dgt_equity(prices, dl, dh, n, mode="arithmetic", fee=0.0, return_resets=False):
    """Lưới tương đối (dl, dh, n) đặt tại giá đầu; khi giá phá low/high thì dựng lại quanh giá mới với vốn = equity hiện tại.
    Phá trên: lưới đã bán hết -> toàn tiền mặt, tái đầu tư vào lưới mới. Phá dưới: lưới đang giữ toàn coin, vốn mới = giá trị coin + tiền.
    Phí tái cân bằng = fee · phần vốn phải mua/bán để chuyển sang trạng thái ban đầu của lưới mới."""
    P = np.asarray(prices, float)
    T, eq, cap, start, resets = len(P), np.empty(len(P)), 1.0, 0, 0
    while True:
        p0 = P[start]
        low, high = p0 * (1 - dl), p0 * (1 + dh)
        out = (P[start:] < low) | (P[start:] > high)
        end = start + int(np.argmax(out)) if out.any() else T - 1
        e = grid_equity(P[start:end + 1], low, high, n, mode, fee)
        eq[start:end + 1] = cap * e
        cap *= e[-1]
        if end == T - 1:
            break
        # tái cân bằng sang trạng thái đầu của lưới mới tại giá phá biên
        nxt = P[end]
        lines, c = _cross(np.array([nxt]), nxt * (1 - dl), nxt * (1 + dh), n, mode)
        coin_frac = (n + 1 - c[0]) * nxt / ((n + 1 - c[0]) * nxt + lines[: c[0]].sum())
        was_cash = P[end] > high  # phá trên -> đang toàn tiền mặt
        cap *= 1 - fee * (coin_frac if was_cash else 1 - coin_frac)
        resets += 1
        start = end
    return (eq, resets) if return_resets else eq


# --- STEP 6: tham số "phẳng" thay vì đỉnh nhọn ---
UNSTABLE_IQR = {"range_ratio": 0.35, "step_ratio": 1.0}  # cần hiệu chỉnh: IQR/khoảng của dl,dh; IQR/median của step%
# Kết quả walk-forward (xem README STEP 6): trung bình Sharpe OOS của "phẳng" -1.62 vs "đỉnh nhọn" -1.68 trên 4 cặp,
# thắng 2/4 cặp, chênh lệch nằm trong nhiễu (15 fold). Chọn "phẳng" làm mặc định vì ít nhạy với nhiễu, không vì có edge.
DEFAULT_PICK = "flat"
MIN_NEIGHBORS = 5  # ô được chọn phải có >= 5 ô hợp lệ trong lân cận 3x3 (kể cả chính nó)


def smooth_pick(res, space):
    """Chọn dòng có Sharpe trung bình lân cận 3x3 trên (dl,dh) cao nhất (cùng n, mode); chỉ ô có >= MIN_NEIGHBORS ô hợp lệ."""
    dls, dhs = list(space["dl"]), list(space["dh"])
    best, best_score, fallback = None, -np.inf, (None, -1)
    for (n, mode), g in res.groupby(["n", "mode"]):
        A = np.full((len(dls), len(dhs)), np.nan)
        for r in g.itertuples():
            A[dls.index(r.dl), dhs.index(r.dh)] = r.sharpe
        pad = np.pad(A, 1, constant_values=np.nan)
        win = np.stack([pad[i:i + A.shape[0], j:j + A.shape[1]] for i in range(3) for j in range(3)])
        cnt = (~np.isnan(win)).sum(0)
        avg = np.where(cnt > 0, np.nansum(win, 0) / np.maximum(cnt, 1), np.nan)
        for i, j in zip(*np.where(~np.isnan(A))):
            row = g[(g.dl == dls[i]) & (g.dh == dhs[j])].iloc[0].copy()
            row["smooth"] = avg[i, j]
            if cnt[i, j] >= MIN_NEIGHBORS and avg[i, j] > best_score:
                best, best_score = row, avg[i, j]
            if cnt[i, j] > fallback[1] or (cnt[i, j] == fallback[1] and fallback[0] is not None and avg[i, j] > fallback[0]["smooth"]):
                fallback = (row, cnt[i, j])
    return best if best is not None else fallback[0]


def stability(f, space, prefix=""):
    """Median/IQR của dl, dh, step% qua các fold; cờ UNSTABLE nếu IQR vượt ngưỡng cấu hình."""
    out, flag = {}, False
    for c, rng in (("dl", max(space["dl"]) - min(space["dl"])), ("dh", max(space["dh"]) - min(space["dh"])), ("step_pct", None)):
        v = f[prefix + c]
        q1, med, q3 = v.quantile([0.25, 0.5, 0.75])
        out[c + "_median"], out[c + "_iqr"] = float(med), float(q3 - q1)
        ratio = (q3 - q1) / rng if rng else (q3 - q1) / med
        flag |= ratio > (UNSTABLE_IQR["range_ratio"] if rng else UNSTABLE_IQR["step_ratio"])
    out["unstable"] = bool(flag)
    return out


def _grid_oos(P, dl, dh, n, mode, fee, bpy):
    """Đặt lưới tại giá đầu của P (tham số tương đối) rồi đo hiệu suất trên P."""
    low, high = P[0] * (1 - dl), P[0] * (1 + dh)
    trades, turn = grid_stats(P, low, high, n, mode)
    return metrics(grid_equity(P, low, high, n, mode, fee), bpy, trades, turn)


def walk_forward(df, tf, symbol, fee=DEFAULT_FEE, train_days=90, test_days=30, step_days=30, space=None, safety=2.0):
    """Mỗi fold: sweep trên train [a,b), chọn tham số tốt nhất, áp tại giá đầu test [b,c). Chỉ dùng dữ liệu < b để chọn."""
    ts, px = df.ts.values, df.close.values
    bpy, space, rows, k = BARS_PER_YEAR[tf], space or space_for(symbol), [], 0
    while True:
        a = ts[0] + k * step_days * DAY_MS
        b, c = a + train_days * DAY_MS, a + (train_days + test_days) * DAY_MS
        if c > ts[-1] + BAR_MS[tf]:
            break
        i0, i1, i2 = np.searchsorted(ts, [a, b, c])
        tr, te = px[i0:i1], px[i1:i2]
        res = sweep(tr, space, fee, bpy, safety)
        if res.empty:
            log.info("WF %s fold %d: không có tổ hợp qua lọc, bỏ qua", symbol, k)
            k += 1
            continue
        best = res.iloc[0]  # đỉnh in-sample (STEP 6 sẽ thay bằng tham số phẳng)
        oos = _grid_oos(te, best.dl, best.dh, int(best.n), best["mode"], fee, bpy)
        dfl = _grid_oos(te, **DEFAULT_GRID, fee=fee, bpy=bpy)
        bh = metrics(buy_and_hold(te), bpy)
        fl = smooth_pick(res, space)
        deq, dres = dgt_equity(te, fl.dl, fl.dh, int(fl.n), fl["mode"], fee, True)
        dm = metrics(deq, bpy)
        deq2, dres2 = dgt_equity(te, **DEFAULT_GRID, fee=fee, return_resets=True)
        dm2 = metrics(deq2, bpy)
        foos = _grid_oos(te, fl.dl, fl.dh, int(fl.n), fl["mode"], fee, bpy)
        rows.append({"dgt_sharpe": dm["sharpe"], "dgt_return": dm["return"], "dgt_mdd": dm["mdd"], "dgt_resets": dres,
                     "dgtdef_sharpe": dm2["sharpe"], "dgtdef_return": dm2["return"], "dgtdef_mdd": dm2["mdd"], "dgtdef_resets": dres2,
                     "f_dl": fl.dl, "f_dh": fl.dh, "f_n": int(fl.n), "f_mode": fl["mode"], "f_step_pct": fl.step_pct,
                     "f_is_sharpe": fl.sharpe, "f_smooth": fl.smooth, "f_oos_sharpe": foos["sharpe"], "f_oos_return": foos["return"],
                     "f_oos_mdd": foos["mdd"], "f_oos_trades": foos["trades"],
"fold": k, "train_last_ts": int(ts[i1 - 1]), "test_start": int(ts[i1]), "test_end": int(ts[i2 - 1]),
                     "dl": best.dl, "dh": best.dh, "n": int(best.n), "mode": best["mode"], "step_pct": best.step_pct,
                     "is_sharpe": best.sharpe, "oos_sharpe": oos["sharpe"], "oos_return": oos["return"], "oos_mdd": oos["mdd"],
                     "oos_trades": oos["trades"], "bh_sharpe": bh["sharpe"], "bh_return": bh["return"], "bh_mdd": bh["mdd"],
                     "def_sharpe": dfl["sharpe"], "def_return": dfl["return"], "def_mdd": dfl["mdd"], "def_trades": dfl["trades"]})
        k += 1
    return pd.DataFrame(rows)


def wf_summary(f):
    return {"folds": len(f), "oos_sharpe_median": f.oos_sharpe.median(), "bh_sharpe_median": f.bh_sharpe.median(),
            "def_sharpe_median": f.def_sharpe.median(), "is_sharpe_median": f.is_sharpe.median(),
            "pct_profit": float((f.oos_return > 0).mean() * 100), "pct_beat_bh": float((f.oos_return > f.bh_return).mean() * 100),
            "oos_return_median": f.oos_return.median(), "bh_return_median": f.bh_return.median(),
            "f_oos_sharpe_median": f.f_oos_sharpe.median(), "f_is_sharpe_median": f.f_is_sharpe.median(),
            "f_pct_profit": float((f.f_oos_return > 0).mean() * 100), "f_pct_beat_bh": float((f.f_oos_return > f.bh_return).mean() * 100),
            "f_oos_return_median": f.f_oos_return.median(),
            "dgt_sharpe_median": f.dgt_sharpe.median(), "dgt_return_median": f.dgt_return.median(),
            "dgt_pct_profit": float((f.dgt_return > 0).mean() * 100), "dgt_pct_beat_bh": float((f.dgt_return > f.bh_return).mean() * 100),
            "dgt_resets_median": f.dgt_resets.median(),
            "dgtdef_sharpe_median": f.dgtdef_sharpe.median(), "dgtdef_return_median": f.dgtdef_return.median(),
            "def_return_median": f.def_return.median(), "def_pct_profit": float((f.def_return > 0).mean() * 100),
            "bh_pct_profit": float((f.bh_return > 0).mean() * 100)}


def run_wf(symbol, tf, df, train, test, step, fee):
    t0 = time.time()
    f = walk_forward(df, tf, symbol, fee, train, test, step)
    out = Path(__file__).parent / "results" / f"{symbol}_folds.csv"
    out.parent.mkdir(exist_ok=True)
    f.to_csv(out, index=False)
    s = wf_summary(f)
    sp = space_for(symbol)
    st_p, st_f = stability(f, sp), stability(f, sp, "f_")
    log.info("WF %s DGT: OOS Sharpe median=%.2f (flat grid %.2f, B&H %.2f, DGT default %.2f), resets median=%.0f, %%fold lãi=%.0f%%",
             symbol, s["dgt_sharpe_median"], s["f_oos_sharpe_median"], s["bh_sharpe_median"], s["dgtdef_sharpe_median"],
             s["dgt_resets_median"], s["dgt_pct_profit"])
    log.info("WF %s flat: OOS Sharpe median=%.2f (peak %.2f); %%fold lãi=%.0f%%; peak %s, flat %s", symbol, s["f_oos_sharpe_median"],
             s["oos_sharpe_median"], s["f_pct_profit"], "UNSTABLE" if st_p["unstable"] else "stable", "UNSTABLE" if st_f["unstable"] else "stable")
    log.info("WF %s train=%dd test=%dd step=%dd: %d folds, %.1fs. OOS Sharpe median=%.2f (B&H %.2f, default %.2f, in-sample %.2f); "
             "%%fold lãi=%.0f%%, %%fold hơn B&H=%.0f%%", symbol, train, test, step, s["folds"], time.time() - t0, s["oos_sharpe_median"],
             s["bh_sharpe_median"], s["def_sharpe_median"], s["is_sharpe_median"], s["pct_profit"], s["pct_beat_bh"])
    return f


def report(symbol, tf, df):
    bar = BAR_MS[tf]
    gaps = int(((df.ts.diff().dropna() // bar) - 1).clip(lower=0).sum())
    f = lambda t: pd.to_datetime(t, unit="ms").strftime("%Y-%m-%d %H:%M")
    log.info("%s %s: %d bars, %s -> %s, gap=%d missing bars", symbol, tf, len(df), f(df.ts.iloc[0]), f(df.ts.iloc[-1]), gaps)


def main():
    ap = argparse.ArgumentParser(description="Grid trading parameter optimizer for Bitget spot (backtest only).")
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT"])
    ap.add_argument("--tf", default="15m", choices=list(GRAN))
    ap.add_argument("--days", type=int, default=540)
    ap.add_argument("--sweep", action="store_true", help="STEP 4: quét tham số trên cửa sổ cuối (in-sample)")
    ap.add_argument("--window", type=int, default=90, help="số ngày của cửa sổ sweep")
    ap.add_argument("--fee", type=float, default=DEFAULT_FEE)
    ap.add_argument("--walkforward", action="store_true", help="STEP 5: walk-forward OOS")
    ap.add_argument("--train", type=int, default=90)
    ap.add_argument("--test", type=int, default=30)
    ap.add_argument("--step", type=int, default=30)
    a = ap.parse_args()
    LOG_PATH.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding="utf-8")])
    log.info("RUN args=%s", vars(a))
    for s in a.symbols:
        df = load_ohlcv(s, a.tf, a.days)
        report(s, a.tf, df)
        m = metrics(buy_and_hold(df.close.values), BARS_PER_YEAR[a.tf])
        log.info("%s B&H: sharpe=%.2f return=%+.1f%% mdd=%.1f%%", s, m["sharpe"], 100 * m["return"], 100 * m["mdd"])
        if a.sweep:
            run_sweep(s, a.tf, df, a.window, a.fee)
        if a.walkforward:
            run_wf(s, a.tf, df, a.train, a.test, a.step, a.fee)


if __name__ == "__main__":
    main()
