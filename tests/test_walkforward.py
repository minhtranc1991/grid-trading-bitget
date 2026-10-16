import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import grid_optimizer as g

SPACE = {"dl": [0.02, 0.05, 0.1], "dh": [0.02, 0.05, 0.1], "n": [4, 10, 20], "mode": ["arithmetic", "geometric"]}
WIN = dict(train_days=28, test_days=7, step_days=7, select_days=7, min_dl=0, min_range=0, min_n=0)  # tắt ràng buộc rộng/dày cho không gian nhỏ  # IS 4 tuần, OOS 1 tuần, forward 1 tuần


def _df(seed=0, days=150):
    rng = np.random.default_rng(seed)
    n = days * 96
    ts = 1_700_000_000_000 + np.arange(n) * 900_000
    return pd.DataFrame({"ts": ts, "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))})


def test_window_layout_and_no_leakage_by_timestamp():
    df = _df()
    f = g.walk_forward(df, "15m", "BTCUSDT", space=SPACE, **WIN)
    assert len(f) >= 10
    assert (f.is_last_ts < f.train_last_ts).all()  # IS kết thúc trước, rồi tới OOS-select
    assert (f.train_last_ts < f.test_start).all()  # mọi dữ liệu dùng để chọn đều trước tuần forward
    assert (f.test_start.diff().dropna() == 7 * g.DAY_MS).all()  # trượt đúng 1 tuần
    # đổi toàn bộ giá từ tuần forward của fold 0 trở đi: tham số cả ba cách chọn của fold 0 phải y nguyên
    t = f.test_start.iloc[0]
    df2 = df.copy()
    m = df2.ts >= t
    df2.loc[m, "close"] *= np.random.default_rng(1).uniform(0.5, 2, m.sum())
    f2 = g.walk_forward(df2, "15m", "BTCUSDT", space=SPACE, **WIN)
    cols = ["dl", "dh", "n", "mode", "f_dl", "f_dh", "f_n", "s_dl", "s_dh", "s_n", "s_mode", "s_is_sharpe", "s_sel_sharpe"]
    assert f.loc[0, cols].tolist() == f2.loc[0, cols].tolist()


def test_stable_params_depend_on_oos_select_window():
    # đổi giá TRONG tuần OOS-select (trước forward) thì tham số ổn định có thể đổi, nhưng IS-only (đỉnh nhọn) thì không
    df = _df(2)
    f = g.walk_forward(df, "15m", "BTCUSDT", space=SPACE, **WIN)
    sel_start = f.is_last_ts.iloc[0] + 900_000
    df2 = df.copy()
    m = (df2.ts >= sel_start) & (df2.ts <= f.train_last_ts.iloc[0])
    df2.loc[m, "close"] *= np.random.default_rng(3).uniform(0.7, 1.4, m.sum())
    f2 = g.walk_forward(df2, "15m", "BTCUSDT", space=SPACE, **WIN)
    assert f.loc[0, ["dl", "dh", "n", "mode"]].tolist() == f2.loc[0, ["dl", "dh", "n", "mode"]].tolist()
    assert f.loc[0, "s_sel_sharpe"] != f2.loc[0, "s_sel_sharpe"]


def test_stable_pick_is_good_in_both_windows():
    # ứng viên có Sharpe IS cao nhất nhưng tệ ở OOS phải bị bỏ khi có ứng viên đều tốt ở cả hai
    P_is = 100 + 5 * np.sin(np.linspace(0, 60, 2688))
    P_sel = 100 + 5 * np.sin(np.linspace(0, 20, 672))
    res = g.sweep(P_is, SPACE, 0.001, min_dl=0, min_range=0, min_n=0)
    st = g.stable_pick(res, SPACE, P_sel, 0.001, g.BARS_PER_YEAR["15m"])
    assert st["score"] == min(st["is_score"], st["sel_score"])  # score = lợi suất quy về tuần (mục tiêu mặc định)
    top = res.iloc[0]
    top_oos = g.objective_value(g._grid_oos(P_sel, top.dl, top.dh, int(top.n), top["mode"], 0.001, g.BARS_PER_YEAR["15m"]))
    assert st["score"] >= min(top.score, top_oos) - 1e-12  # không kém ứng viên đỉnh nhọn theo tiêu chí min()


def test_summary_keys():
    f = g.walk_forward(_df(1), "15m", "BTCUSDT", space=SPACE, **WIN)
    s = g.wf_summary(f)
    assert s["folds"] == len(f) and 0 <= s["s_pct_profit"] <= 100


def test_max_grids_caps_n_in_walk_forward():
    sp = {"dl": [0.02, 0.05, 0.1], "dh": [0.02, 0.05, 0.1], "n": [4, 10, 20, 40], "mode": ["arithmetic", "geometric"]}
    f = g.walk_forward(_df(), "15m", "BTCUSDT", space=sp, with_dgt=False, max_grids=10, **WIN)
    assert (f.n <= 10).all() and (f.f_n <= 10).all() and (f.s_n <= 10).all()


def test_chosen_configs_respect_min_step():
    # mọi cấu hình được chọn (đỉnh nhọn, phẳng, ổn định) phải có bước nhỏ nhất >= 2·fee·hệ số an toàn
    fee = 0.001
    f = g.walk_forward(_df(), "15m", "BTCUSDT", fee=fee, space=SPACE, with_dgt=False, **WIN)
    for c in ("step_pct", "f_step_pct", "s_step_pct"):
        assert (f[c] >= 2 * fee * 2 - 1e-12).all()


def test_parallel_equals_serial():
    df = _df(4, days=100)
    a = g.walk_forward(df, "15m", "BTCUSDT", space=SPACE, jobs=1, **WIN)
    b = g.walk_forward(df, "15m", "BTCUSDT", space=SPACE, jobs=2, **WIN)
    pd.testing.assert_frame_equal(a, b)


def test_constraints_respected_in_walk_forward():
    sp = {"dl": [0.05, 0.10, 0.15], "dh": [0.02, 0.05, 0.10], "n": [6, 14, 20], "mode": ["arithmetic", "geometric"]}
    f = g.walk_forward(_df(), "15m", "BTCUSDT", space=sp, with_dgt=False, train_days=28, test_days=7, step_days=7, select_days=7,
                       min_dl=0.10, min_range=0.15, min_n=14)
    assert len(f) > 5
    for pre in ("", "f_", "s_"):
        assert (f[pre + "dl"] >= 0.10 - 1e-12).all() and ((f[pre + "dl"] + f[pre + "dh"]) >= 0.15 - 1e-12).all() and (f[pre + "n"] >= 14).all()
    assert {"s_oos_brk", "def_brk"} <= set(f.columns)
