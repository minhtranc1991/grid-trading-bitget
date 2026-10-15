import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from grid_optimizer import grid_equity

LINES = np.linspace(90, 110, 21)  # bước 1


def test_equity0_is_one():
    eq = grid_equity([100.5, 103.2, 98.1], 90, 110, 20, fee=0.001)
    assert eq[0] == 1.0


def test_flat_price_no_change_no_fee():
    eq = grid_equity([100.5] * 50, 90, 110, 20, fee=0.01)
    assert np.allclose(eq, 1.0)


def test_up_down_k_lines_pays_only_fees():
    # Lên qua 3 line (101,102,103) rồi về chỗ cũ: equity gộp quay về 1 (grid là portfolio tĩnh,
    # không có lãi "k·bước" thực sự), chỉ còn phí = fee·Gv·2·(101+102+103).
    P = [100.5, 103.5, 100.5]
    fee = 0.001
    gross = grid_equity(P, 90, 110, 20, fee=0)
    assert np.isclose(gross[-1], 1.0)
    c0 = (LINES <= 100.5).sum()
    Gv = 1 / ((21 - c0) * 100.5 + LINES[:c0].sum())
    net = grid_equity(P, 90, 110, 20, fee=fee)
    assert np.isclose(net[-1], 1 - fee * Gv * 2 * (101 + 102 + 103))


def _loop_sim(P, low, high, n, mode, fee):
    lines = (np.linspace if mode == "arithmetic" else np.geomspace)(low, high, n + 1)
    held = [L > P[0] for L in lines]  # line phía trên giá đầu: đang giữ coin mua tại P0
    cash0 = sum(L for L, h in zip(lines, held) if not h)
    coins = sum(held)
    cap = cash0 + coins * P[0]
    cash, out, prev = cash0, [1.0], P[0]
    for p in P[1:]:
        if p > prev:  # bán tại các line bị cắt, tăng dần
            for L in lines:
                if prev < L <= p:
                    cash += L * (1 - fee); coins -= 1
        elif p < prev:  # mua tại các line bị cắt, giảm dần
            for L in lines[::-1]:
                if p < L <= prev:
                    cash -= L * (1 + fee); coins += 1
        out.append((cash + coins * p) / cap)
        prev = p
    return np.array(out)


def test_matches_python_loop():
    rng = np.random.default_rng(0)
    for mode in ("arithmetic", "geometric"):
        P = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
        a = grid_equity(P, 90, 112, 12, mode, fee=0.001)
        b = _loop_sim(P, 90, 112, 12, mode, 0.001)
        assert np.abs(a - b).max() < 1e-9
