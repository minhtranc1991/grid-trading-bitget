import argparse
import atexit
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
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


def _lines(low, high, n, mode):
    return (np.linspace if mode == "arithmetic" else np.geomspace)(low, high, n + 1)


def grid_sim(prices, low, high, n, mode="arithmetic", fee=0.0, entry_fee=True):
    """Mô phỏng lưới thật theo SỰ KIỆN cắt line. Trả (equity chuẩn hóa vốn=1, số lệnh khớp sau lúc vào, turnover).

    n slot; slot k mua ở L_k, bán ở L_{k+1} (mỗi slot 1 đơn vị coin). Lúc bắt đầu: slot có line bán nằm trên giá đầu
    giữ coin (mua tại P0), các slot còn lại dự trữ tiền L_k để mua. Giá cắt lên L_j: slot j-1 bán nếu đang giữ;
    cắt xuống L_j: slot j mua nếu đang không giữ. Phí fee tính cho mỗi lệnh (kể cả lệnh vào) và là hàm của đường đi.
    Vốn = coin ban đầu·P0 + tiền dự trữ."""
    P = np.asarray(prices, float)
    L = _lines(low, high, n, mode)
    Ll = L.tolist()
    p0 = P[0]
    hold = (L[1:] > p0).tolist()
    coins0 = sum(hold)
    cash0 = float(sum(Ll[k] for k in range(n) if not hold[k]))
    cap = coins0 * p0 + cash0
    c = np.searchsorted(L, P, side="right")  # số line <= giá
    dc = np.diff(c)
    ev = np.flatnonzero(dc)
    dcash = np.zeros(len(P))
    dcoin = np.zeros(len(P))
    trades, notional = 0, coins0 * p0
    for b in ev.tolist():
        d, c0 = int(dc[b]), int(c[b])
        if d > 0:  # cắt lên line c0..c0+d-1 (tăng dần): slot j-1 bán tại L_j
            for j in range(c0, c0 + d):
                if j >= 1 and hold[j - 1]:
                    hold[j - 1] = False
                    dcash[b + 1] += Ll[j] * (1 - fee)
                    dcoin[b + 1] -= 1
                    trades += 1
                    notional += Ll[j]
        else:  # cắt xuống line c0-1..c0+d (giảm dần): slot j mua tại L_j
            for j in range(c0 - 1, c0 + d - 1, -1):
                if j <= n - 1 and not hold[j]:
                    hold[j] = True
                    dcash[b + 1] -= Ll[j] * (1 + fee)
                    dcoin[b + 1] += 1
                    trades += 1
                    notional += Ll[j]
    eq = (cash0 + np.cumsum(dcash) + (coins0 + np.cumsum(dcoin)) * P) / cap
    if entry_fee:
        eq[1:] -= fee * coins0 * p0 / cap  # phí mua coin lúc vào lưới
    return eq, trades, float(notional / cap)


def grid_equity(prices, low, high, n, mode="arithmetic", fee=0.0, entry_fee=True):
    return grid_sim(prices, low, high, n, mode, fee, entry_fee)[0]


def grid_stats(prices, low, high, n, mode="arithmetic"):
    """(số lệnh khớp sau lúc vào, turnover = tổng notional giao dịch kể cả lúc vào / vốn đầu)."""
    return grid_sim(prices, low, high, n, mode)[1:]


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
                    if st < 2 * fee * safety:  # loại range hẹp + nhiều lưới: mọi lưới liền kề phải bù đủ phí khứ hồi
                        continue
                    eq, trades, turn = grid_sim(P, low, high, n, mode, fee)
                    if trades < min_trades:
                        continue
                    m = metrics(eq, bars_per_year, trades, turn)
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


def run_sweep(symbol, tf, df, window_days, fee, max_grids=MAX_GRIDS):
    t0 = time.time()
    n = window_days * 86_400_000 // BAR_MS[tf]
    P = df.close.values[-n:]
    res = sweep(P, space_for(symbol), fee, BARS_PER_YEAR[tf], max_grids=max_grids)
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
    T, eq, cap, start, resets, first = len(P), np.empty(len(P)), 1.0, 0, 0, True
    while True:
        p0 = P[start]
        low, high = p0 * (1 - dl), p0 * (1 + dh)
        out = (P[start:] < low) | (P[start:] > high)
        end = start + int(np.argmax(out)) if out.any() else T - 1
        e = grid_equity(P[start:end + 1], low, high, n, mode, fee, entry_fee=first)  # phí vào của lưới mới nằm ở bước tái cân bằng
        first = False
        eq[start:end + 1] = cap * e
        cap *= e[-1]
        if end == T - 1:
            break
        # tái cân bằng sang trạng thái đầu của lưới mới tại giá phá biên
        nxt = P[end]
        L = _lines(nxt * (1 - dl), nxt * (1 + dh), n, mode)
        h = L[1:] > nxt
        coin_frac = h.sum() * nxt / (h.sum() * nxt + L[:-1][~h].sum())
        was_cash = P[end] > high  # phá trên -> đang toàn tiền mặt
        cap *= 1 - fee * (coin_frac if was_cash else 1 - coin_frac)
        resets += 1
        start = end
    return (eq, resets) if return_resets else eq


# --- STEP 6: tham số "phẳng" thay vì đỉnh nhọn ---
UNSTABLE_IQR = {"range_ratio": 0.35, "step_ratio": 1.0}  # cần hiệu chỉnh: IQR/khoảng của dl,dh; IQR/median của step%
# Kết quả walk-forward (xem README STEP 6): trung bình Sharpe OOS của "phẳng" -1.62 vs "đỉnh nhọn" -1.68 trên 4 cặp,
# thắng 2/4 cặp, chênh lệch nằm trong nhiễu (15 fold). Chọn "phẳng" làm mặc định vì ít nhạy với nhiễu, không vì có edge.
DEFAULT_PICK = "stable"  # xem README: IS 28d -> OOS 7d chọn tham số ổn định -> forward 7d
MIN_NEIGHBORS = 5  # ô được chọn phải có >= 5 ô hợp lệ trong lân cận 3x3 (kể cả chính nó)


def smooth_pick(res, space):
    """Chọn dòng có Sharpe trung bình lân cận 3x3 trên (dl,dh) cao nhất (cùng n, mode); chỉ ô có >= MIN_NEIGHBORS ô hợp lệ.
    Chỉ dùng numpy trong vòng lặp; pandas chỉ để lấy dòng thắng cuộc."""
    dli = {v: i for i, v in enumerate(space["dl"])}
    dhi = {v: i for i, v in enumerate(space["dh"])}
    shape = (len(dli), len(dhi))
    r = res.reset_index(drop=True)
    il, ih = r.dl.map(dli).values, r.dh.map(dhi).values
    sharpe = r.sharpe.values
    best_i, best_score, fb_i, fb_cnt, fb_avg = -1, -np.inf, -1, -1, -np.inf
    for idx in r.groupby(["n", "mode"]).indices.values():
        A = np.full(shape, np.nan)
        A[il[idx], ih[idx]] = sharpe[idx]
        M = np.full(shape, -1)
        M[il[idx], ih[idx]] = idx
        pad = np.pad(A, 1, constant_values=np.nan)
        win = np.stack([pad[i:i + shape[0], j:j + shape[1]] for i in range(3) for j in range(3)])
        valid = ~np.isnan(win)
        cnt = valid.sum(0)
        avg = np.where(cnt > 0, np.where(valid, win, 0).sum(0) / np.maximum(cnt, 1), np.nan)
        has = ~np.isnan(A)
        ok = has & (cnt >= MIN_NEIGHBORS)
        if ok.any():
            sc = np.where(ok, avg, -np.inf)
            p = np.unravel_index(np.argmax(sc), shape)
            if sc[p] > best_score:
                best_score, best_i = sc[p], M[p]
        # dự phòng nếu không ô nào đủ hàng xóm: ô có nhiều hàng xóm nhất, rồi trung bình cao nhất
        key = np.where(has, cnt * 1e6 + np.nan_to_num(avg, nan=-1e5), -np.inf)
        p = np.unravel_index(np.argmax(key), shape)
        if has[p] and (cnt[p] > fb_cnt or (cnt[p] == fb_cnt and avg[p] > fb_avg)):
            fb_i, fb_cnt, fb_avg = M[p], cnt[p], avg[p]
    i = best_i if best_i >= 0 else fb_i
    row = r.iloc[i].copy()
    row["smooth"] = best_score if best_i >= 0 else fb_avg
    return row


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
    eq, trades, turn = grid_sim(P, low, high, n, mode, fee)
    return metrics(eq, bpy, trades, turn)


SELECT_DAYS = 7  # độ dài cửa sổ OOS dùng để tìm tham số ổn định (chỉnh bằng --select)
TOP_K = 20  # số ứng viên lấy từ IS
PICK_PREFIX = {"peak": "", "flat": "f_", "stable": "s_"}


def stable_pick(res, space, sel_px, fee, bpy, top_k=TOP_K, flat=None):
    """Tham số ổn định: ứng viên = top_k theo Sharpe IS + tham số phẳng của IS; chấm lại trên tuần OOS-select;
    chọn ứng viên có min(Sharpe IS, Sharpe OOS) cao nhất, tức là tốt ở cả hai nơi chứ không chỉ ở IS."""
    cands = [(r.dl, r.dh, int(r.n), r["mode"], r.sharpe, r.step_pct) for _, r in res.head(top_k).iterrows()]
    fl = smooth_pick(res, space) if flat is None else flat
    cands.append((fl.dl, fl.dh, int(fl.n), fl["mode"], fl.sharpe, fl.step_pct))
    best = None
    for dl, dh, n, mode, is_sh, st in cands:
        m = _grid_oos(sel_px, dl, dh, n, mode, fee, bpy)
        score = min(is_sh, m["sharpe"])
        if best is None or score > best["score"]:
            best = {"dl": dl, "dh": dh, "n": n, "mode": mode, "step_pct": st, "is_sharpe": is_sh, "sel_sharpe": m["sharpe"], "score": score}
    return best


_POOL = None


def _get_pool(jobs):
    """Pool dùng chung giữa các lần gọi (khởi tạo tiến trình con trên Windows tốn vài giây mỗi lần)."""
    global _POOL
    if _POOL is None or _POOL._max_workers != jobs:
        if _POOL is not None:
            _POOL.shutdown()
        _POOL = ProcessPoolExecutor(max_workers=jobs)
        atexit.register(_POOL.shutdown)
    return _POOL


JOBS = 1  # số tiến trình chạy song song các fold (CLI --jobs đặt mặc định 8); 1 = chạy tuần tự, không tạo pool


def _wf_fold(t):
    """Một fold độc lập (chạy được trong tiến trình con): IS -> OOS chọn tham số ổn định -> forward."""
    k, tr, sel, te, ts_bounds, symbol, tf, fee, space, safety, max_grids, with_dgt, top_k = t
    bpy = BARS_PER_YEAR[tf]
    res = sweep(tr, space, fee, bpy, safety, max_grids=max_grids)
    if res.empty:
        return k, None
    best = res.iloc[0]  # đỉnh in-sample
    fl = smooth_pick(res, space)
    st = stable_pick(res, space, sel, fee, bpy, top_k, flat=fl)
    oos = _grid_oos(te, best.dl, best.dh, int(best.n), best["mode"], fee, bpy)
    foos = _grid_oos(te, fl.dl, fl.dh, int(fl.n), fl["mode"], fee, bpy)
    soos = _grid_oos(te, st["dl"], st["dh"], st["n"], st["mode"], fee, bpy)
    dfl = _grid_oos(te, **DEFAULT_GRID, fee=fee, bpy=bpy)
    bh = metrics(buy_and_hold(te), bpy)
    if with_dgt:
        deq, dres = dgt_equity(te, st["dl"], st["dh"], st["n"], st["mode"], fee, True)
        dm = metrics(deq, bpy)
        deq2, dres2 = dgt_equity(te, **DEFAULT_GRID, fee=fee, return_resets=True)
        dm2 = metrics(deq2, bpy)
    else:
        dm = dm2 = {"sharpe": np.nan, "return": np.nan, "mdd": np.nan}
        dres = dres2 = np.nan
    is_last, sel_last, t_start, t_end = ts_bounds
    return k, {
        "fold": k, "is_last_ts": is_last, "train_last_ts": sel_last, "test_start": t_start, "test_end": t_end,
        "dgt_sharpe": dm["sharpe"], "dgt_return": dm["return"], "dgt_mdd": dm["mdd"], "dgt_resets": dres,
        "dgtdef_sharpe": dm2["sharpe"], "dgtdef_return": dm2["return"], "dgtdef_mdd": dm2["mdd"], "dgtdef_resets": dres2,
        "s_dl": st["dl"], "s_dh": st["dh"], "s_n": st["n"], "s_mode": st["mode"], "s_step_pct": st["step_pct"],
        "s_is_sharpe": st["is_sharpe"], "s_sel_sharpe": st["sel_sharpe"], "s_oos_sharpe": soos["sharpe"],
        "s_oos_return": soos["return"], "s_oos_mdd": soos["mdd"], "s_oos_trades": soos["trades"],
        "f_dl": fl.dl, "f_dh": fl.dh, "f_n": int(fl.n), "f_mode": fl["mode"], "f_step_pct": fl.step_pct,
        "f_is_sharpe": fl.sharpe, "f_smooth": fl.smooth, "f_oos_sharpe": foos["sharpe"], "f_oos_return": foos["return"],
        "f_oos_mdd": foos["mdd"], "f_oos_trades": foos["trades"],
        "dl": best.dl, "dh": best.dh, "n": int(best.n), "mode": best["mode"], "step_pct": best.step_pct,
        "is_sharpe": best.sharpe, "oos_sharpe": oos["sharpe"], "oos_return": oos["return"], "oos_mdd": oos["mdd"],
        "oos_trades": oos["trades"], "bh_sharpe": bh["sharpe"], "bh_return": bh["return"], "bh_mdd": bh["mdd"],
        "def_sharpe": dfl["sharpe"], "def_return": dfl["return"], "def_mdd": dfl["mdd"], "def_trades": dfl["trades"]}


def walk_forward(df, tf, symbol, fee=DEFAULT_FEE, train_days=28, test_days=7, step_days=7, space=None, safety=2.0,
                 with_dgt=True, max_grids=MAX_GRIDS, select_days=None, top_k=TOP_K, jobs=None):
    """Mỗi fold (trượt step_days):
      IS     [a, b)  : sweep, tìm tham số tối ưu (đỉnh nhọn và phẳng)
      OOS    [b, s)  : chấm các ứng viên của IS, chọn tham số ổn định (tốt ở cả IS và OOS)
      FORWARD[s, c)  : áp tham số tại giá đầu tuần, đo hiệu suất. Chưa từng dùng để chọn nên là phép thử sạch.
    Các fold độc lập nên chạy song song bằng jobs tiến trình (kết quả y hệt chạy tuần tự)."""
    select_days = SELECT_DAYS if select_days is None else select_days
    jobs = JOBS if jobs is None else jobs
    ts, px = df.ts.values, df.close.values
    space, tasks, k = space or space_for(symbol), [], 0
    while True:
        a = ts[0] + k * step_days * DAY_MS
        b = a + train_days * DAY_MS
        s_end = b + select_days * DAY_MS
        c = s_end + test_days * DAY_MS
        if c > ts[-1] + BAR_MS[tf]:
            break
        i0, i1, i2, i3 = np.searchsorted(ts, [a, b, s_end, c])
        bounds = (int(ts[i1 - 1]), int(ts[i2 - 1]), int(ts[i2]), int(ts[i3 - 1]))
        tasks.append((k, px[i0:i1], px[i1:i2], px[i2:i3], bounds, symbol, tf, fee, space, safety, max_grids, with_dgt, top_k))
        k += 1
    if jobs > 1 and len(tasks) > 1:
        out = list(_get_pool(jobs).map(_wf_fold, tasks))
    else:
        out = [_wf_fold(t) for t in tasks]
    rows = []
    for k, row in out:
        if row is None:
            log.info("WF %s fold %d: không có tổ hợp qua lọc, bỏ qua", symbol, k)
        else:
            rows.append(row)
    return pd.DataFrame(rows)


def wf_summary(f):
    med = lambda c: float(f[c].median())
    pp = lambda c: float((f[c] > 0).mean() * 100)
    return {"folds": len(f), "bh_sharpe_median": med("bh_sharpe"), "def_sharpe_median": med("def_sharpe"),
            "bh_return_median": med("bh_return"), "def_return_median": med("def_return"),
            "bh_pct_profit": pp("bh_return"), "def_pct_profit": pp("def_return"),
            # đỉnh nhọn (IS top-1)
            "oos_sharpe_median": med("oos_sharpe"), "is_sharpe_median": med("is_sharpe"), "pct_profit": pp("oos_return"),
            "pct_beat_bh": float((f.oos_return > f.bh_return).mean() * 100), "oos_return_median": med("oos_return"),
            # phẳng (smooth IS)
            "f_oos_sharpe_median": med("f_oos_sharpe"), "f_is_sharpe_median": med("f_is_sharpe"), "f_pct_profit": pp("f_oos_return"),
            "f_pct_beat_bh": float((f.f_oos_return > f.bh_return).mean() * 100), "f_oos_return_median": med("f_oos_return"),
            # ổn định (IS -> OOS)
            "s_oos_sharpe_median": med("s_oos_sharpe"), "s_is_sharpe_median": med("s_is_sharpe"), "s_sel_sharpe_median": med("s_sel_sharpe"),
            "s_pct_profit": pp("s_oos_return"), "s_pct_beat_bh": float((f.s_oos_return > f.bh_return).mean() * 100),
            "s_oos_return_median": med("s_oos_return"),
            # DGT trên tham số ổn định
            "dgt_sharpe_median": med("dgt_sharpe"), "dgt_return_median": med("dgt_return"), "dgt_pct_profit": pp("dgt_return"),
            "dgt_pct_beat_bh": float((f.dgt_return > f.bh_return).mean() * 100), "dgt_resets_median": med("dgt_resets"),
            "dgtdef_sharpe_median": med("dgtdef_sharpe"), "dgtdef_return_median": med("dgtdef_return")}


def run_wf(symbol, tf, df, train, test, step, fee, max_grids=MAX_GRIDS):
    t0 = time.time()
    f = walk_forward(df, tf, symbol, fee, train, test, step, max_grids=max_grids)
    out = Path(__file__).parent / "results" / f"{symbol}_folds.csv"
    out.parent.mkdir(exist_ok=True)
    f.to_csv(out, index=False)
    s = wf_summary(f)
    sp = space_for(symbol)
    st = stability(f, sp, "s_")
    log.info("WF %s IS=%dd OOS-select=%dd forward=%dd step=%dd: %d fold, %.1fs", symbol, train, SELECT_DAYS, test, step, s["folds"], time.time() - t0)
    log.info("WF %s Sharpe median (forward): stable=%.2f flat=%.2f peak=%.2f default=%.2f B&H=%.2f DGT=%.2f; %%fold lãi stable=%.0f%% (B&H %.0f%%), "
             "%%fold hơn B&H=%.0f%%; in-sample(stable)=%.2f, OOS-select(stable)=%.2f; %s", symbol, s["s_oos_sharpe_median"],
             s["f_oos_sharpe_median"], s["oos_sharpe_median"], s["def_sharpe_median"], s["bh_sharpe_median"], s["dgt_sharpe_median"],
             s["s_pct_profit"], s["bh_pct_profit"], s["s_pct_beat_bh"], s["s_is_sharpe_median"], s["s_sel_sharpe_median"],
             "UNSTABLE" if st["unstable"] else "stable")
    return f


# --- STEP 8: đánh giá thống kê & độ nhạy ---
def oos_returns(df, folds, prefix=None, with_ts=False):
    """Lợi suất từng bar, nối các fold OOS: (grid theo tham số chọn ở fold, B&H cùng cửa sổ)."""
    prefix = PICK_PREFIX[DEFAULT_PICK] if prefix is None else prefix
    ts, px = df.ts.values, df.close.values
    gr, bh, tt = [], [], []
    for r in folds.to_dict("records"):
        i1, i2 = np.searchsorted(ts, r["test_start"]), np.searchsorted(ts, r["test_end"], side="right")
        te = px[i1:i2]
        eq = grid_equity(te, te[0] * (1 - r[prefix + "dl"]), te[0] * (1 + r[prefix + "dh"]), int(r[prefix + "n"]), r[prefix + "mode"], r["fee"])
        gr.append(np.diff(eq) / eq[:-1])
        bh.append(np.diff(te) / te[:-1])
        tt.append(ts[i1 + 1:i2])
    out = (np.concatenate(gr), np.concatenate(bh))
    return out + (np.concatenate(tt),) if with_ts else out


def block_bootstrap_sharpe(r, bpy, block=96, n=2000, seed=0):
    """Khoảng tin cậy 95% của Sharpe annualized bằng bootstrap theo khối (mặc định 1 ngày 15m)."""
    r = np.asarray(r, float)
    nb = int(np.ceil(len(r) / block))
    pad = nb * block - len(r)
    x = np.concatenate([r, np.zeros(pad)]).reshape(nb, block)
    L = np.full(nb, block)
    L[-1] -= pad
    s1, s2 = x.sum(1), (x ** 2).sum(1)
    idx = np.random.default_rng(seed).integers(0, nb, (n, nb))
    cnt = L[idx].sum(1)
    mean = s1[idx].sum(1) / cnt
    var = (s2[idx].sum(1) - cnt * mean ** 2) / (cnt - 1)
    sh = mean / np.sqrt(var) * np.sqrt(bpy)
    pt = r.mean() / r.std(ddof=1) * np.sqrt(bpy)
    return float(np.percentile(sh, 2.5)), float(pt), float(np.percentile(sh, 97.5))


def deflated_sharpe(r, n_trials, trial_var):
    """(PSR so với 0, DSR, SR0) theo Bailey & López de Prado; Sharpe tính theo từng bar, trial_var = phương sai Sharpe/bar giữa các thử nghiệm."""
    from statistics import NormalDist
    from scipy.stats import kurtosis, skew  # scipy đi kèm pandas stack; nếu thiếu thì pip install scipy
    r = np.asarray(r, float)
    T, nd = len(r), NormalDist()
    sr = r.mean() / r.std(ddof=1)
    sk, ku = skew(r), kurtosis(r, fisher=False)
    den = np.sqrt(max(1e-12, 1 - sk * sr + (ku - 1) / 4 * sr ** 2))
    gam = 0.5772156649
    sr0 = np.sqrt(trial_var) * ((1 - gam) * nd.inv_cdf(1 - 1 / n_trials) + gam * nd.inv_cdf(1 - 1 / (n_trials * np.e)))
    return nd.cdf(sr * np.sqrt(T - 1) / den), nd.cdf((sr - sr0) * np.sqrt(T - 1) / den), float(sr0)


def run_stats(symbol, tf, df, fee, train=28, test=7, step=7, window=90, max_grids=MAX_GRIDS):
    bpy = BARS_PER_YEAR[tf]
    f = walk_forward(df, tf, symbol, fee, train, test, step, with_dgt=False, max_grids=max_grids)
    f["fee"] = fee
    gr, bh = oos_returns(df, f)
    ci_g, ci_b, ci_d = block_bootstrap_sharpe(gr, bpy), block_bootstrap_sharpe(bh, bpy), block_bootstrap_sharpe(gr - bh, bpy)
    sp = space_for(symbol)
    ntr = len(sp["dl"]) * len(sp["dh"]) * len(sp["n"]) * len(sp["mode"])
    nbar = window * 86_400_000 // BAR_MS[tf]
    sweep_sh = sweep(df.close.values[-nbar:], sp, fee, bpy, max_grids=max_grids).sharpe.values / np.sqrt(bpy)  # Sharpe/bar của các thử nghiệm
    psr, dsr, sr0 = deflated_sharpe(gr, ntr, float(np.var(sweep_sh, ddof=1)))
    zero_in = ci_g[0] <= 0 <= ci_g[2]
    verdict = ("chưa có bằng chứng edge (CI 95% của Sharpe OOS chứa 0)" if zero_in else
               ("Sharpe OOS âm có ý nghĩa thống kê" if ci_g[2] < 0 else "Sharpe OOS dương có ý nghĩa, cần kiểm tra DSR"))
    out = {"symbol": symbol, "tf": tf, "fee": fee, "folds": len(f), "bars": int(len(gr)), "n_trials": ntr,
           "grid_ci": ci_g, "bh_ci": ci_b, "diff_ci": ci_d, "psr0": psr, "dsr": dsr, "sr0_bar": sr0,
           "sr0_annual": sr0 * np.sqrt(bpy), "verdict": verdict}
    path = Path(__file__).parent / "results" / f"stats_{symbol}.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    log.info("STATS %s: Sharpe OOS %.2f [%.2f, %.2f], B&H %.2f [%.2f, %.2f], hiệu %.2f [%.2f, %.2f]; PSR(0)=%.3f DSR=%.3f, %d tổ hợp; %s",
             symbol, ci_g[1], ci_g[0], ci_g[2], ci_b[1], ci_b[0], ci_b[2], ci_d[1], ci_d[0], ci_d[2], psr, dsr, ntr, verdict)
    return out


def run_sensitivity(symbol, days, fee, fees=(0.5, 1.0, 2.0), tfs=("5m", "15m", "1h"), max_grids=MAX_GRIDS):
    """Sharpe OOS trung vị (phẳng, đỉnh nhọn, B&H) theo phí (x0.5/1/2 ở 15m) và theo timeframe (phí 1x)."""
    rows, base = [], None
    df15 = load_ohlcv(symbol, "15m", days)
    for m in fees:
        s = wf_summary(walk_forward(df15, "15m", symbol, fee * m, with_dgt=False, max_grids=max_grids))
        base = s if m == 1.0 else base
        rows.append({"kind": "fee", "label": f"{m:g}x ({fee * m:.4f})", **{k: s[k] for k in ("s_oos_sharpe_median", "f_oos_sharpe_median", "oos_sharpe_median", "bh_sharpe_median", "s_pct_profit", "folds")}})
        log.info("SENS %s fee x%g: stable=%.2f flat=%.2f peak=%.2f B&H=%.2f", symbol, m, s["s_oos_sharpe_median"], s["f_oos_sharpe_median"], s["oos_sharpe_median"], s["bh_sharpe_median"])
    for tf in tfs:
        s = base if tf == "15m" and base else wf_summary(walk_forward(load_ohlcv(symbol, tf, days), tf, symbol, fee, with_dgt=False, max_grids=max_grids))
        rows.append({"kind": "tf", "label": tf, **{k: s[k] for k in ("s_oos_sharpe_median", "f_oos_sharpe_median", "oos_sharpe_median", "bh_sharpe_median", "s_pct_profit", "folds")}})
        log.info("SENS %s tf %s: stable=%.2f flat=%.2f peak=%.2f B&H=%.2f", symbol, tf, s["s_oos_sharpe_median"], s["f_oos_sharpe_median"], s["oos_sharpe_median"], s["bh_sharpe_median"])
    (Path(__file__).parent / "results" / f"sens_{symbol}.json").write_text(json.dumps(rows), encoding="utf-8")
    return rows


# --- STEP 9: pipeline đầy đủ ---
def run_final(symbol, tf, df, fee, train, test, step, window, max_grids=MAX_GRIDS):
    """Walk-forward + CI + tham số khuyến nghị cho một cặp. Trả (dòng summary, chuỗi equity OOS)."""
    bpy, sp = BARS_PER_YEAR[tf], space_for(symbol)
    f = walk_forward(df, tf, symbol, fee, train, test, step, max_grids=max_grids)
    out = Path(__file__).parent / "results" / f"{symbol}_folds.csv"
    out.parent.mkdir(exist_ok=True)
    f.to_csv(out, index=False)
    f["fee"] = fee
    pre = PICK_PREFIX[DEFAULT_PICK]
    gr, bh, tt = oos_returns(df, f, pre, with_ts=True)
    eq_g, eq_b = np.concatenate([[1.0], np.cumprod(1 + gr)]), np.concatenate([[1.0], np.cumprod(1 + bh)])
    mg, mb = metrics(eq_g, bpy), metrics(eq_b, bpy)
    lo, pt, hi = block_bootstrap_sharpe(gr, bpy)
    # tham số khuyến nghị: cùng quy trình như mỗi fold, trên dữ liệu mới nhất (IS ngay trước tuần OOS-select cuối), tương đối theo giá hiện tại
    nsel = SELECT_DAYS * 86_400_000 // BAR_MS[tf]
    nis = train * 86_400_000 // BAR_MS[tf]
    px_all = df.close.values
    res = sweep(px_all[-(nsel + nis):-nsel], sp, fee, bpy, max_grids=max_grids)
    if DEFAULT_PICK == "stable":
        rec = pd.Series(stable_pick(res, sp, px_all[-nsel:], fee, bpy))
    else:
        rec = smooth_pick(res, sp) if DEFAULT_PICK == "flat" else res.iloc[0]
    st = stability(f, sp, pre)
    last = float(df.close.iloc[-1])
    row = {"symbol": symbol, "tf": tf, "fee": fee, "folds": len(f), "oos_sharpe_median": f[pre + "oos_sharpe"].median(),
           "oos_sharpe_pooled": pt, "sharpe_ci_lo": lo, "sharpe_ci_hi": hi, "oos_return": mg["return"], "oos_mdd": mg["mdd"],
           "pct_fold_profit": float((f[pre + "oos_return"] > 0).mean() * 100), "bh_sharpe_pooled": mb["sharpe"],
           "bh_return": mb["return"], "bh_mdd": mb["mdd"], "rec_dl": rec.dl, "rec_dh": rec.dh, "rec_n": int(rec.n),
           "rec_step_pct": rec.step_pct, "rec_mode": rec["mode"], "rec_low": last * (1 - rec.dl), "rec_high": last * (1 + rec.dh),
           "unstable": "UNSTABLE" if st["unstable"] else "stable",
           "edge": "no evidence of edge" if lo <= 0 <= hi else ("negative" if hi < 0 else "positive, verify DSR")}
    k = max(1, len(tt) // 3000)  # lấy mẫu để file nhỏ
    series = {"t": [int(x) for x in tt[::k]], "grid": [round(float(x), 5) for x in eq_g[1::k]], "bh": [round(float(x), 5) for x in eq_b[1::k]]}
    log.info("FINAL %s: OOS Sharpe pooled %.2f [%.2f, %.2f] (median fold %.2f), return %+.1f%% vs B&H %+.1f%%, MDD %.1f%%, %s, %s; "
             "khuyến nghị dl=%.2f%% dh=%.2f%% n=%d bước=%.2f%% %s", symbol, pt, lo, hi, row["oos_sharpe_median"], 100 * mg["return"],
             100 * mb["return"], 100 * mg["mdd"], row["unstable"], row["edge"], 100 * rec.dl, 100 * rec.dh, int(rec.n), 100 * rec.step_pct, rec["mode"])
    return row, series


def write_final(rows, series):
    d = Path(__file__).parent / "results"
    pd.DataFrame(rows).to_csv(d / "summary.csv", index=False)
    (d / "oos_equity.json").write_text(json.dumps(series), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(2, 2, figsize=(12, 7), sharex=False)
    for ax, (sym, sr) in zip(axs.ravel(), series.items()):
        x = pd.to_datetime(sr["t"], unit="ms")
        ax.plot(x, sr["grid"], label="Grid OOS (nối các fold)", lw=1.6)
        ax.plot(x, sr["bh"], label="Buy & Hold", lw=1.6, color="gray")
        ax.axhline(1, color="k", lw=0.5, ls=":")
        ax.set_title(sym)
        ax.legend(fontsize=8)
    fig.suptitle("Equity OOS nối các fold vs Buy & Hold (vốn đầu = 1)")
    fig.tight_layout()
    fig.savefig(d / "equity_oos.png", dpi=110)
    plt.close(fig)


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
    ap.add_argument("--max-grids", type=int, default=MAX_GRIDS, help="trần số lưới n (cần xác minh trong app Bitget)")
    ap.add_argument("--walkforward", action="store_true", help="STEP 5: walk-forward OOS")
    ap.add_argument("--stats", action="store_true", help="STEP 8: CI bootstrap + Deflated Sharpe")
    ap.add_argument("--sensitivity", action="store_true", help="STEP 8: độ nhạy theo phí và timeframe (chậm)")
    ap.add_argument("--train", type=int, default=28, help="độ dài IS (ngày): tìm tham số tối ưu")
    ap.add_argument("--select", type=int, default=SELECT_DAYS, help="độ dài OOS (ngày): tìm tham số ổn định")
    ap.add_argument("--test", type=int, default=7, help="độ dài tuần forward (ngày): đo hiệu suất")
    ap.add_argument("--step", type=int, default=7, help="bước trượt (ngày)")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1), help="số tiến trình song song cho các fold (tối đa 8)")
    a = ap.parse_args()
    globals()["SELECT_DAYS"] = a.select
    globals()["JOBS"] = max(1, min(a.jobs, 8))
    LOG_PATH.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(process)d] %(message)s",  # PID để tách các lần chạy chồng nhau
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding="utf-8")])
    log.info("RUN args=%s", vars(a))
    final = not (a.sweep or a.walkforward or a.stats or a.sensitivity)
    rows, series = [], {}
    for s in a.symbols:
        df = load_ohlcv(s, a.tf, a.days)
        report(s, a.tf, df)
        m = metrics(buy_and_hold(df.close.values), BARS_PER_YEAR[a.tf])
        log.info("%s B&H: sharpe=%.2f return=%+.1f%% mdd=%.1f%%", s, m["sharpe"], 100 * m["return"], 100 * m["mdd"])
        if a.sweep:
            run_sweep(s, a.tf, df, a.window, a.fee, a.max_grids)
        if a.walkforward:
            run_wf(s, a.tf, df, a.train, a.test, a.step, a.fee, a.max_grids)
        if a.stats:
            run_stats(s, a.tf, df, a.fee, a.train, a.test, a.step, a.window, a.max_grids)
        if a.sensitivity:
            run_sensitivity(s, a.days, a.fee, max_grids=a.max_grids)
        if final:
            row, series[s] = run_final(s, a.tf, df, a.fee, a.train, a.test, a.step, a.window, a.max_grids)
            rows.append(row)
    if final:
        write_final(rows, series)
        cols = ["symbol", "oos_sharpe_median", "oos_sharpe_pooled", "oos_return", "oos_mdd", "pct_fold_profit", "bh_return",
                "rec_dl", "rec_dh", "rec_n", "rec_step_pct", "rec_mode", "unstable", "edge"]
        print(pd.DataFrame(rows)[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
