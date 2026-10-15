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


def parse_log(text):
    runs, prev, cur = [], None, None
    for line in text.splitlines():
        if len(line) < 25:
            continue
        t = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f")
        msg = line[24:]
        if msg.startswith("RUN"):
            cur = {"t": t.strftime("%Y-%m-%d %H:%M:%S"), "args": msg[9:], "syms": {}}
            runs.append(cur)
        elif cur is not None:
            sym = msg.split(" ")[0]
            if sym not in SYMS:
                continue
            d = cur["syms"].setdefault(sym, {"t0": prev})
            if (m := re.search(r"cache (\d+) -> (\d+) bars, fetched (\d+)", msg)):
                d.update(cache_before=int(m[1]), cache_after=int(m[2]), fetched=int(m[3]))
            elif (m := re.search(r": (\d+) bars, (.+) -> (.+), gap=(\d+)", msg)):
                d.update(bars=int(m[1]), start=m[2], end=m[3], gap=int(m[4]))
            elif "B&H" in msg:
                d["elapsed"] = round((t - d["t0"]).total_seconds(), 2)
            d["t_last"] = t
        prev = t
    for r in runs:
        for d in r["syms"].values():
            d.pop("t0", None)
            d.pop("t_last", None)
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
            "beat": float((df.sharpe > j["bh"]["sharpe"]).mean() * 100), "median": float(df.sharpe.median()),
            "topwide": int((top.dh == df.dh.max()).sum()), "dhmax": float(df.dh.max())}


def load_wf(s):
    p = g.LOG_PATH.parent / f"{s}_folds.csv"
    if not p.exists():
        return None
    f = pd.read_csv(p)
    return {"folds": f.round(4).to_dict("records"), "sum": {k: float(v) for k, v in g.wf_summary(f).items()}}


def progress():
    txt = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")
    return [{"done": d == "x", "n": int(n), "text": t.strip()} for d, n, t in re.findall(r"- \[( |x)\] \*\*STEP (\d+)\*\* (.+)", txt)]


def build():
    close = {}
    for s in SYMS:
        df = pd.read_csv(g.DATA_DIR / f"{s}_{TF}.csv")
        df.index = pd.to_datetime(df.ts, unit="ms")
        close[s] = df.close
    C = pd.DataFrame(close)
    r4 = lambda x: [None if pd.isna(v) else round(float(v), 3) for v in x]

    h4 = C.resample("4h").last().dropna()
    idx4 = h4 / h4.iloc[0] * 100
    dd4 = (h4 / h4.cummax() - 1) * 100
    day = C.resample("1D").last().dropna()
    ret = day.pct_change()
    vol = ret.rolling(30).std() * np.sqrt(365) * 100
    me = day.resample("ME").last()
    mret = me / pd.concat([day.iloc[:1], me.iloc[:-1]]).values - 1
    months = [f"{d:%Y-%m}" + ("*" if i in (0, len(me) - 1) else "") for i, d in enumerate(me.index)]
    bpy = g.BARS_PER_YEAR[TF]
    met = {}
    for s in SYMS:
        m = g.metrics(g.buy_and_hold(C[s].values), bpy)
        m["vol"] = float(C[s].pct_change().std() * np.sqrt(bpy))
        m["first"], m["last"] = float(C[s].iloc[0]), float(C[s].iloc[-1])
        m["bars"] = int(C[s].size)
        met[s] = m
    ms = lambda ix: [int(x.value // 10**6) for x in ix]
    ER_TH = 0.3  # ER 30 ngày > 0.3 ~ gấp đôi mức random walk (~0.15) => trend
    hist, dstat, reg = {}, {}, {}
    erf = np.vectorize(math.erf)
    for s in SYMS:
        r = ret[s].dropna()
        mu, sd = float(r.mean()), float(r.std())
        lim = max(abs(r.quantile(0.005)), abs(r.quantile(0.995))) * 100
        edges = np.linspace(-lim, lim, 41)
        cnt = np.histogram(r * 100, bins=edges)[0]
        cdf = 0.5 * (1 + erf((edges / 100 - mu) / (sd * math.sqrt(2))))
        r15 = C[s].pct_change().dropna().abs()
        dstat[s] = {"mean": mu * 100, "std": sd * 100, "skew": float(r.skew()), "kurt": float(r.kurt()),
                    "min": float(r.min() * 100), "max": float(r.max() * 100),
                    "tail2": float((abs(r - mu) > 2 * sd).mean() * 100),
                    "med15": float(r15.median() * 100), "p15_01": float((r15 > 0.001).mean() * 100),
                    "p15_02": float((r15 > 0.002).mean() * 100), "p15_04": float((r15 > 0.004).mean() * 100)}
        hist[s] = {"edges": edges.round(3).tolist(), "pct": (cnt / len(r) * 100).round(3).tolist(),
                   "norm": (np.diff(cdf) * 100).round(3).tolist()}
        net = day[s].pct_change(30) * 100
        path = day[s].diff().abs().rolling(30).sum()
        er = (day[s] - day[s].shift(30)).abs() / path
        ok = net.notna() & er.notna() & vol[s].notna()
        reg[s] = {"t": ms(day.index[ok]), "x": r4(net[ok]), "y": r4(vol[s][ok]), "er": r4(er[ok]),
                  "up": [bool(v) for v in (net[ok] > 0)]}
    return {
        "syms": SYMS, "tf": TF,
        "span": [int(C.index[0].value // 10**6), int(C.index[-1].value // 10**6)],
        "t4": ms(idx4.index), "px": {s: r4(idx4[s]) for s in SYMS}, "dd": {s: r4(dd4[s]) for s in SYMS},
        "td": ms(vol.index), "vol": {s: r4(vol[s]) for s in SYMS},
        "months": months, "mret": {s: r4(mret[s] * 100) for s in SYMS},
        "corr": ret.corr().round(3).values.tolist(),
        "hist": hist, "dstat": dstat, "reg": reg, "erth": ER_TH, "met": met, "sweep": {s: load_sweep(s) for s in SYMS}, "wf": {s: load_wf(s) for s in SYMS}, "progress": progress(), "runs": parse_log(g.LOG_PATH.read_text(encoding="utf-8")),
        "rawlog": g.LOG_PATH.read_text(encoding="utf-8"),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


if __name__ == "__main__":
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(build()))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html) // 1024} KB)")
