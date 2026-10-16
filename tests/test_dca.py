import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import grid_optimizer as g


def _ms(s):
    return int(pd.Timestamp(s).value // 10**6)


def test_dca_plan_deposits_first_week_of_each_month():
    starts = [_ms(x) for x in ("2025-07-03", "2025-07-10", "2025-07-31", "2025-08-07", "2025-08-14", "2025-09-04")]
    dep, cum = g.dca_plan(starts, 50)
    assert dep == [50, 0, 0, 50, 0, 50] and cum == [50, 50, 50, 100, 100, 150]


def test_xirr_known_cases():
    # nạp 100 ngày 0, nhận 110 sau đúng 1 năm -> 10%
    assert np.isclose(g.xirr([0, 365], [-100, 110]), 0.10, atol=1e-6)
    assert np.isclose(g.xirr([0, 365], [-100, 100]), 0.0, atol=1e-6)


def test_dgt_down_only_ignores_upside_break():
    P = np.concatenate([np.linspace(100, 130, 200), np.linspace(130, 80, 300)])  # phá trên rồi phá dưới
    both, r_both = g.dgt_equity(P, 0.1, 0.1, 10, "arithmetic", 0.0, True)
    down, r_down = g.dgt_equity(P, 0.1, 0.1, 10, "arithmetic", 0.0, True, down_only=True)
    assert r_down < r_both and np.isfinite(down).all() and down[0] == 1.0
    up = np.linspace(100, 130, 200)  # chỉ đi lên: không có phá đáy -> trùng lưới thường
    eq, resets = g.dgt_equity(up, 0.1, 0.1, 10, "arithmetic", 0.001, True, down_only=True)
    assert resets == 0 and np.allclose(eq, g.grid_equity(up, 90, 110, 10, "arithmetic", 0.001))


def test_min_order_filters_dense_grids_for_small_capital():
    P = 100 + 5 * np.sin(np.linspace(0, 60, 3000))
    space = {"dl": [0.10], "dh": [0.05], "n": [10, 30, 60], "mode": ["arithmetic"]}
    big = g.sweep(P, space, 0.001, min_dl=0, min_range=0, min_n=0, capital=None)
    small = g.sweep(P, space, 0.001, min_dl=0, min_range=0, min_n=0, capital=50, min_order=2)
    assert set(big.n) >= set(small.n) and small.n.max() < big.n.max()  # vốn nhỏ không đủ cho lưới dày
    # lệnh nhỏ nhất của mọi cấu hình còn lại >= 2 USD
    for r in small.itertuples():
        L = g._lines(P[0] * (1 - r.dl), P[0] * (1 + r.dh), int(r.n), r.mode)
        h = L[1:] > P[0]
        assert 50 / (h.sum() * P[0] + L[:-1][~h].sum()) * L[0] >= 2 - 1e-9


def test_run_dca_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "RESULTS_DIR", tmp_path)
    for k in ("MIN_DL", "MIN_RANGE", "MIN_N"):
        monkeypatch.setattr(g, k, 0)
    rng = np.random.default_rng(7)
    n = 120 * 96
    df = pd.DataFrame({"ts": _ms("2025-01-01") + np.arange(n) * 900_000, "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))})
    out = g.run_dca("BTCUSDT", "15m", df, 0.001, 28, 7, 7)
    s = out["series"]
    assert len(s["t"]) == len(s["grid"]) == len(s["bh"]) == out["weeks"]
    assert np.isclose(s["invested"][-1], out["invested"]) and out["invested"] == 50 * out["deposits"]
    # DCA Buy & Hold: giá trị cuối = tổng coin mua được · giá cuối; ROI hợp lý
    assert out["bh"]["final"] > 0 and abs(out["bh"]["roi"]) < 1
