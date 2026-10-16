import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from grid_optimizer import buy_and_hold, grid_stats, metrics


def test_sharpe_known_series():
    eq = np.cumprod([1, 1.02, 1.0, 1.02, 1.0])  # r = .02, 0, .02, 0
    r = np.array([0.02, 0, 0.02, 0])
    exp = r.mean() / r.std(ddof=1) * np.sqrt(100)
    assert np.isclose(metrics(eq, 100)["sharpe"], exp)
    assert np.isclose(metrics(eq, 100)["sharpe"], 0.01 / np.sqrt(4 * 1e-4 / 3) * 10)


def test_return_and_mdd():
    m = metrics([1, 1.2, 0.9, 1.0], 1)
    assert np.isclose(m["return"], 0.0) and np.isclose(m["mdd"], -0.25)


def test_buy_and_hold_and_trades():
    assert np.allclose(buy_and_hold([50, 100, 25]), [1, 2, 0.5])
    t, turn = grid_stats([100.5, 103.5, 100.5], 90, 110, 20)  # 3 bán + 2 mua lại = 5 lệnh khớp
    assert t == 5 and turn > 0


def test_sortino_calmar_retwk_known_series():
    # 4 bar: +2%, -1%, +2%, -1%; bars_per_year = 52 * 4 để 1 tuần = 4 bar
    eq = np.cumprod([1, 1.02, 0.99, 1.02, 0.99])
    r = np.array([0.02, -0.01, 0.02, -0.01])
    m = metrics(eq, 52 * 4)
    dd = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
    assert np.isclose(m["sortino"], r.mean() / dd * np.sqrt(52 * 4))
    assert np.isclose(m["ret_wk"], m["return"])  # cửa sổ đúng 1 tuần
    assert np.isclose(m["calmar"], m["return"] * 52 / abs(m["mdd"]))
