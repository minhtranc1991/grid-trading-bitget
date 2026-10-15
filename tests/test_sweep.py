import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
import grid_optimizer as g


def test_step_pct():
    assert np.isclose(g.step_pct(90, 110, 20, "arithmetic"), 1 / 110)  # bước 1 trên line cao nhất
    assert np.isclose(g.step_pct(100, 121, 2, "geometric"), 0.1)


def test_sweep_filters_and_sorted():
    P = 100 + 5 * np.sin(np.linspace(0, 60, 3000))
    fee = 0.001
    space = {"dl": [0.02, 0.05, 0.1], "dh": [0.02, 0.05, 0.1], "n": [4, 10, 40, 500], "mode": ["arithmetic", "geometric"]}
    r = g.sweep(P, space, fee, safety=2, min_trades=20, max_grids=100)
    assert len(r) > 0
    assert r.sharpe.is_monotonic_decreasing
    assert (r.step_pct >= 2 * fee * 2 - 1e-12).all()  # lọc bước% >= 2·fee·hệ số an toàn
    assert (r.trades >= 20).all()
    assert (r.n <= 100).all()  # n=500 bị loại bởi MAX_GRIDS


def test_space_for_gold_vs_crypto():
    assert max(g.space_for("PAXGUSDT")["dl"]) == 0.08
    assert max(g.space_for("BTCUSDT")["dl"]) == 0.50
