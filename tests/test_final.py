import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import grid_optimizer as g


def test_run_final_summary_columns_and_consistency():
    rng = np.random.default_rng(5)
    n = 210 * 96  # 210 ngày -> 4 fold
    df = pd.DataFrame({"ts": 1_700_000_000_000 + np.arange(n) * 900_000, "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))})
    row, series = g.run_final("BTCUSDT", "15m", df, 0.001, 90, 30, 30, 90)
    for k in ("symbol", "oos_sharpe_median", "oos_return", "oos_mdd", "pct_fold_profit", "rec_dl", "rec_dh", "rec_n",
              "rec_step_pct", "rec_mode", "unstable", "edge"):
        assert k in row
    assert row["folds"] == 4 and row["oos_mdd"] <= 0 and 0 <= row["pct_fold_profit"] <= 100
    assert row["sharpe_ci_lo"] <= row["oos_sharpe_pooled"] <= row["sharpe_ci_hi"]
    assert len(series["t"]) == len(series["grid"]) == len(series["bh"])
    # bước khuyến nghị phải vượt ngưỡng phí 2·fee·hệ số an toàn
    assert row["rec_step_pct"] >= 2 * 0.001 * 2 - 1e-12
