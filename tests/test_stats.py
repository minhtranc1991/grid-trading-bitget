import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
import grid_optimizer as g


def test_bootstrap_ci_covers_point_and_true_sharpe():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, 20000)
    lo, pt, hi = g.block_bootstrap_sharpe(r, 35040, block=96, n=500)
    true = 0.0005 / 0.01 * np.sqrt(35040)
    assert lo < pt < hi
    assert lo < true < hi


def test_zero_mean_ci_contains_zero_and_wide_for_short_series():
    rng = np.random.default_rng(1)
    lo, pt, hi = g.block_bootstrap_sharpe(rng.normal(0, 0.01, 5000), 35040, n=500)
    assert lo < 0 < hi


def test_dsr_penalizes_more_trials():
    rng = np.random.default_rng(2)
    r = rng.normal(0.0004, 0.01, 20000)
    _, d_few, _ = g.deflated_sharpe(r, 2, 1e-6)
    _, d_many, _ = g.deflated_sharpe(r, 2000, 1e-6)
    assert d_many < d_few


def test_oos_returns_length_matches_folds():
    rng = np.random.default_rng(3)
    n = 240 * 96
    import pandas as pd
    df = pd.DataFrame({"ts": 1_700_000_000_000 + np.arange(n) * 900_000, "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))})
    sp = {"dl": [0.02, 0.05, 0.1], "dh": [0.02, 0.05, 0.1], "n": [4, 10], "mode": ["arithmetic", "geometric"]}
    f = g.walk_forward(df, "15m", "BTCUSDT", space=sp, with_dgt=False, min_dl=0, min_range=0, min_n=0)
    f["fee"] = 0.001
    gr, bh = g.oos_returns(df, f)
    assert len(gr) == len(bh) == len(f) * (7 * 96 - 1)  # mỗi fold forward 7 ngày = 672 bar -> 671 lợi suất
