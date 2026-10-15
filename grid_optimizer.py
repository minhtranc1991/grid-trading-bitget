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


def grid_equity(prices, low, high, n, mode="arithmetic", fee=0.0):
    """Equity chuẩn hóa (vốn đầu = 1) của grid n khoảng giữa low..high; fee = tỷ lệ mỗi chiều.
    Equity là hàm của (giá, số line đã cắt) nên không phụ thuộc đường đi, đúng với Chen et al."""
    P = np.asarray(prices, float)
    space = np.linspace if mode == "arithmetic" else np.geomspace
    lines = space(low, high, n + 1)
    m = n + 1
    c = np.searchsorted(lines, P, side="right")
    S = np.concatenate(([0.0], np.cumsum(lines)))
    c0 = c[0]
    Gv = 1.0 / ((m - c0) * P[0] + S[c0])
    Sc = S[c]
    fees = np.cumsum(fee * Gv * np.abs(np.diff(Sc, prepend=Sc[0])))
    return Gv * Sc + Gv * (m - c) * P - fees


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
    a = ap.parse_args()
    LOG_PATH.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding="utf-8")])
    log.info("RUN args=%s", vars(a))
    for s in a.symbols:
        report(s, a.tf, load_ohlcv(s, a.tf, a.days))


if __name__ == "__main__":
    main()
