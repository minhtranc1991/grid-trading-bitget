import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import grid_optimizer as g

SPACE = {"dl": [0.02, 0.05, 0.1], "dh": [0.02, 0.05, 0.1], "n": [4, 10, 20], "mode": ["arithmetic", "geometric"]}


def _df(seed=0, days=240):
    rng = np.random.default_rng(seed)
    n = days * 96
    ts = 1_700_000_000_000 + np.arange(n) * 900_000
    return pd.DataFrame({"ts": ts, "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))})


def test_no_leakage_by_timestamp():
    df = _df()
    f = g.walk_forward(df, "15m", "BTCUSDT", space=SPACE)
    assert len(f) >= 4
    assert (f.train_last_ts < f.test_start).all()  # train kết thúc trước khi test bắt đầu
    assert (f.test_start.diff().dropna() == 30 * g.DAY_MS).all()  # trượt đúng 30 ngày
    # đổi toàn bộ giá từ test_start của fold 0 trở đi: tham số fold 0 phải y nguyên
    t = f.test_start.iloc[0]
    df2 = df.copy()
    df2.loc[df2.ts >= t, "close"] *= np.random.default_rng(1).uniform(0.5, 2, (df2.ts >= t).sum())
    f2 = g.walk_forward(df2, "15m", "BTCUSDT", space=SPACE)
    cols = ["dl", "dh", "n", "mode", "is_sharpe"]
    assert f.loc[0, cols].tolist() == f2.loc[0, cols].tolist()


def test_summary_keys():
    f = g.walk_forward(_df(1), "15m", "BTCUSDT", space=SPACE)
    s = g.wf_summary(f)
    assert s["folds"] == len(f) and 0 <= s["pct_profit"] <= 100


def test_max_grids_caps_n_in_walk_forward():
    sp = {"dl": [0.02, 0.05, 0.1], "dh": [0.02, 0.05, 0.1], "n": [4, 10, 20, 40], "mode": ["arithmetic", "geometric"]}
    f = g.walk_forward(_df(), "15m", "BTCUSDT", space=sp, with_dgt=False, max_grids=10)
    assert (f.n <= 10).all() and (f.f_n <= 10).all()
