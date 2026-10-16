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
    r = g.sweep(P, space, fee, safety=2, min_trades=20, max_grids=100, min_dl=0, min_range=0, min_n=0)
    assert len(r) > 0
    assert r.score.is_monotonic_decreasing  # mặc định sắp theo lợi nhuận lưới (mục tiêu)
    assert np.allclose(r.score, r.grid_wk)  # mặc định tối ưu lợi nhuận lưới
    assert (r.step_pct >= 2 * fee * 2 - 1e-12).all()  # lọc bước% >= 2·fee·hệ số an toàn
    assert (r.trades >= 20).all()
    assert (r.n <= 100).all()  # n=500 bị loại bởi MAX_GRIDS


def test_space_for_gold_vs_crypto():
    assert max(g.space_for("PAXGUSDT")["dl"]) == 0.20  # mở rộng để đủ cho ràng buộc dl >= 10%
    assert max(g.space_for("BTCUSDT")["dl"]) == 0.50


def test_smooth_pick_prefers_plateau_over_spike():
    import pandas as pd

    d = [0.01, 0.02, 0.03]
    sh = {(i, j): 1.0 for i in range(3) for j in range(3)}
    sh[(0, 0)], sh[(0, 1)], sh[(1, 0)] = 5.0, -3.0, -3.0  # đỉnh nhọn ở góc, hàng xóm tệ
    res = pd.DataFrame([{"dl": d[i], "dh": d[j], "n": 10, "mode": "arithmetic", "step_pct": 0.01, "sharpe": v}
                        for (i, j), v in sh.items()]).sort_values("sharpe", ascending=False)
    space = {"dl": d, "dh": d}
    assert res.iloc[0].dl == 0.01 and res.iloc[0].dh == 0.01  # đỉnh nhọn
    pick = g.smooth_pick(res, space)
    assert (pick.dl, pick.dh) == (0.02, 0.02)  # ô giữa: lân cận 3x3 đầy đủ


def test_stability_flags_wide_iqr():
    import pandas as pd

    sp = {"dl": [0.01, 0.5], "dh": [0.01, 0.5]}
    wide = pd.DataFrame({"dl": [0.01, 0.5, 0.01, 0.5], "dh": [0.25] * 4, "step_pct": [0.01] * 4})
    tight = pd.DataFrame({"dl": [0.2] * 4, "dh": [0.25] * 4, "step_pct": [0.01] * 4})
    assert g.stability(wide, sp)["unstable"] and not g.stability(tight, sp)["unstable"]


def test_objective_selects_top_by_that_metric():
    P = 100 + 5 * np.sin(np.linspace(0, 60, 3000))
    space = {"dl": [0.02, 0.05, 0.1], "dh": [0.02, 0.05, 0.1], "n": [4, 10, 20], "mode": ["arithmetic", "geometric"]}
    for obj, col in (("grid", "grid_wk"), ("return", "return"), ("sharpe", "sharpe"), ("sortino", "sortino"), ("calmar", "calmar")):
        r = g.sweep(P, space, 0.001, objective=obj, min_dl=0, min_range=0, min_n=0)
        assert r.iloc[0][col] == r[col].max()


def test_wide_dense_constraints_filter_combinations():
    P = 100 + 5 * np.sin(np.linspace(0, 60, 3000))
    space = {"dl": [0.02, 0.05, 0.10, 0.15], "dh": [0.02, 0.05, 0.10], "n": [4, 10, 15, 20], "mode": ["arithmetic", "geometric"]}
    r = g.sweep(P, space, 0.001, min_dl=0.10, min_range=0.15, min_n=14)
    assert len(r) > 0
    assert (r.dl >= 0.10 - 1e-12).all() and ((r.dl + r.dh) >= 0.15 - 1e-12).all() and (r.n >= 14).all()
    free = g.sweep(P, space, 0.001, min_dl=0, min_range=0, min_n=0)
    assert len(free) > len(r)
