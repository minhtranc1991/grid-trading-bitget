"""Tạo results/report.html từ results/run.log + data/*.csv (một file HTML tự đủ, không cần mạng)."""
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import grid_optimizer as g

SYMS = ["BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT"]
TF = "15m"
OUT = Path(__file__).parent / "results" / "report.html"
TEMPLATE = Path(__file__).parent / "report_template.html"


LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) (?:\[(\d+)\] )?(.*)$")


def parse_log(text):
    """Tách theo PID nên hai lần chạy chồng nhau không lẫn dòng; log cũ (không có PID) coi là một luồng duy nhất.
    elapsed = từ dòng log liền trước (cùng PID) tới dòng B&H của cặp đó, tức là thời gian nạp/cache dữ liệu của cặp."""
    runs, cur, prev = [], {}, {}
    for line in text.splitlines():
        mt = LOG_LINE.match(line)
        if not mt:
            continue
        t, pid, msg = datetime.strptime(mt[1], "%Y-%m-%d %H:%M:%S,%f"), mt[2] or "-", mt[3]
        if msg.startswith("RUN"):
            cur[pid] = {"t": t.strftime("%Y-%m-%d %H:%M:%S"), "args": msg[9:], "pid": None if pid == "-" else int(pid), "syms": {}}
            runs.append(cur[pid])
        elif pid in cur:
            sym = msg.split(" ")[0]
            if sym in SYMS:
                d = cur[pid]["syms"].setdefault(sym, {"t0": prev.get(pid, t)})
                if (m := re.search(r"cache (\d+) -> (\d+) bars, fetched (\d+)", msg)):
                    d.update(cache_before=int(m[1]), cache_after=int(m[2]), fetched=int(m[3]))
                elif (m := re.search(r": (\d+) bars, (.+) -> (.+), gap=(\d+)", msg)):
                    d.update(bars=int(m[1]), start=m[2], end=m[3], gap=int(m[4]))
                elif "B&H" in msg:
                    d["elapsed"] = round((t - d["t0"]).total_seconds(), 2)
        prev[pid] = t
    for r in runs:
        for d in r["syms"].values():
            d.pop("t0", None)
    return runs


def load_sweep(s):
    p = g.LOG_PATH.parent / f"sweep_{s}.json"
    if not p.exists():
        return None
    j = json.loads(p.read_text(encoding="utf-8"))
    df = pd.DataFrame(j["rows"])
    pv = df[np.isclose(df.dl, df.dh)].pivot_table(index="dl", columns="n", values="sharpe", aggfunc="max")
    top = df.head(10)
    return {"window": j["window_days"], "fee": j["fee"], "combos": j["combos"], "passed": j["passed"], "bh": j["bh"],
            "top": top.round(4).to_dict("records"), "bottom": df.tail(5).round(4).to_dict("records"),
            "dl": [float(x) for x in pv.index], "n": [int(x) for x in pv.columns],
            "heat": [[None if pd.isna(v) else round(float(v), 2) for v in row] for row in pv.values],
            "beat": float((df["return"] > j["bh"]["return"]).mean() * 100), "median": float(df.sharpe.median()),
            "topwide": int((top.dh == df.dh.max()).sum()), "dhmax": float(df.dh.max())}


def load_wf(s):
    p = g.LOG_PATH.parent / f"{s}_folds.csv"
    if not p.exists():
        return None
    f = pd.read_csv(p)
    sp = g.space_for(s)
    return {"folds": f.round(4).to_dict("records"), "sum": {k: float(v) for k, v in g.wf_summary(f).items()},
            "stab": {"peak": g.stability(f, sp), "flat": g.stability(f, sp, "f_"), "stable": g.stability(f, sp, "s_")}, "dhmax": max(sp["dh"]), "default": g.DEFAULT_PICK}


def load_json(name):
    p = g.LOG_PATH.parent / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


ATR_N, REG_WIN, STRESS_Z = 14, 30, 1.5  # ATR(14) daily; STRESS khi |z| > 1.5 so với 30 ngày trước


def fold_schedule():
    """Lịch fold thực tế lấy từ results/{SYMBOL}_folds.csv của cặp đầu tiên có dữ liệu."""
    bar = g.BAR_MS[TF]
    for s in SYMS:
        p = g.LOG_PATH.parent / f"{s}_folds.csv"
        if not p.exists():
            continue
        f = pd.read_csv(p)
        if "is_start" not in f:  # file cũ: suy từ is_last_ts với IS mặc định
            f["is_start"] = f.is_last_ts - g.DAY_MS * 28 + bar
        day = lambda x: round(float(x) / g.DAY_MS, 1)
        r0 = f.iloc[0]
        cfg = {"is_days": day(r0.is_last_ts - r0.is_start + bar), "sel_days": day(r0.train_last_ts - r0.is_last_ts),
               "fwd_days": day(r0.test_end - r0.test_start + bar),
               "step_days": day(f.test_start.diff().dropna().median()) if len(f) > 1 else 0}
        cols = ["is_start", "is_last_ts", "train_last_ts", "test_start", "test_end"]
        return {"symbol": s, "cfg": cfg, "n": int(len(f)), "folds": f[cols].astype("int64").values.tolist()}
    return None


def build():
    close, high, low = {}, {}, {}
    for s in SYMS:
        df = pd.read_csv(g.DATA_DIR / f"{s}_{TF}.csv")
        df.index = pd.to_datetime(df.ts, unit="ms")
        close[s], high[s], low[s] = df.close, df.high, df.low
    C, Hh, Ll = pd.DataFrame(close), pd.DataFrame(high), pd.DataFrame(low)
    r4 = lambda x: [None if pd.isna(v) else round(float(v), 3) for v in x]

    h4 = C.resample("4h").last().dropna()
    idx4 = h4 / h4.iloc[0] * 100
    dd4 = (h4 / h4.cummax() - 1) * 100
    day = C.resample("1D").last().dropna()
    ret = day.pct_change(fill_method=None)
    # ATR(14) daily, làm mượt kiểu Wilder, biểu diễn theo % giá close
    dH, dL = Hh.resample("1D").max().reindex(day.index), Ll.resample("1D").min().reindex(day.index)
    prev = day.shift(1)
    tr = np.maximum(np.maximum(dH - dL, (dH - prev).abs()), (dL - prev).abs())
    atr = tr.ewm(alpha=1 / ATR_N, adjust=False, min_periods=ATR_N).mean()
    atr_pct = atr / day * 100
    # regime theo ngày: STRESS nếu lợi suất ngày lệch quá STRESS_Z độ lệch chuẩn so với 30 ngày trước đó
    z = (ret - ret.rolling(REG_WIN).mean().shift(1)) / ret.rolling(REG_WIN).std().shift(1)
    me = day.resample("ME").last()
    mret = me / pd.concat([day.iloc[:1], me.iloc[:-1]]).values - 1
    months = [f"{d:%Y-%m}" + ("*" if i in (0, len(me) - 1) else "") for i, d in enumerate(me.index)]
    bpy = g.BARS_PER_YEAR[TF]
    met = {}
    for s in SYMS:
        m = g.metrics(g.buy_and_hold(C[s].values), bpy)
        m["vol"] = float(C[s].pct_change(fill_method=None).std() * np.sqrt(bpy))
        m["first"], m["last"] = float(C[s].iloc[0]), float(C[s].iloc[-1])
        m["bars"] = int(C[s].size)
        met[s] = m
    ms = lambda ix: [int(x.value // 10**6) for x in ix]
    hist, dstat, reg = {}, {}, {}
    erf = np.vectorize(math.erf)
    for s in SYMS:
        r = ret[s].dropna()
        mu, sd = float(r.mean()), float(r.std())
        lim = max(abs(r.quantile(0.005)), abs(r.quantile(0.995))) * 100
        edges = np.linspace(-lim, lim, 41)
        cnt = np.histogram(r * 100, bins=edges)[0]
        cdf = 0.5 * (1 + erf((edges / 100 - mu) / (sd * math.sqrt(2))))
        r15 = C[s].pct_change(fill_method=None).dropna().abs()
        dstat[s] = {"mean": mu * 100, "std": sd * 100, "skew": float(r.skew()), "kurt": float(r.kurt()),
                    "min": float(r.min() * 100), "max": float(r.max() * 100),
                    "tail2": float((abs(r - mu) > 2 * sd).mean() * 100),
                    "med15": float(r15.median() * 100), "p15_01": float((r15 > 0.001).mean() * 100),
                    "p15_02": float((r15 > 0.002).mean() * 100), "p15_04": float((r15 > 0.004).mean() * 100)}
        hist[s] = {"edges": edges.round(3).tolist(), "pct": (cnt / len(r) * 100).round(3).tolist(),
                   "norm": (np.diff(cdf) * 100).round(3).tolist()}
        ok = z[s].notna()
        st = (z[s][ok].abs() > STRESS_Z)
        reg[s] = {"t": ms(day.index[ok]), "r": r4(ret[s][ok] * 100), "z": r4(z[s][ok]), "s": [int(v) for v in st],
                  "n": int(ok.sum()), "n_stress": int(st.sum())}
    return {
        "syms": SYMS, "tf": TF,
        "span": [int(C.index[0].value // 10**6), int(C.index[-1].value // 10**6)],
        "t4": ms(idx4.index), "px": {s: r4(idx4[s]) for s in SYMS}, "dd": {s: r4(dd4[s]) for s in SYMS},
        "td": ms(day.index), "atr": {s: r4(atr_pct[s]) for s in SYMS}, "atr_n": ATR_N,
        "months": months, "mret": {s: r4(mret[s] * 100) for s in SYMS},
        "corr": ret.corr().round(3).values.tolist(),
        "hist": hist, "dstat": dstat, "regime": reg, "stress_z": STRESS_Z, "reg_win": REG_WIN, "fold_sched": fold_schedule(), "met": met, "sweep": {s: load_sweep(s) for s in SYMS}, "wf": {s: load_wf(s) for s in SYMS}, "stats": {s: load_json(f"stats_{s}.json") for s in SYMS}, "sens": {s: load_json(f"sens_{s}.json") for s in SYMS}, "summary": (pd.read_csv(g.LOG_PATH.parent / "summary.csv").to_dict("records") if (g.LOG_PATH.parent / "summary.csv").exists() else None), "oos_eq": load_json("oos_equity.json"), "ab": {s: load_json(f"ab_{s}.json") for s in SYMS}, "runs": parse_log(g.LOG_PATH.read_text(encoding="utf-8")),
        "rawlog": g.LOG_PATH.read_text(encoding="utf-8"),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def generate():
    """Tạo results/report.html từ log, dữ liệu và kết quả mới nhất. Trả đường dẫn file."""
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(build()))
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    out = generate()
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
