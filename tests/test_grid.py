import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from grid_optimizer import grid_equity, grid_sim

# lưới 90..110, n=20, bước 1. Tại P0=100.5: slot 10..19 giữ coin (mua tại 100.5), slot 0..9 dự trữ tiền 90..99.
CAP = 10 * 100.5 + sum(range(90, 100))  # = 1950


def test_equity0_is_one():
    assert grid_equity([100.5, 103.2, 98.1], 90, 110, 20, fee=0.001)[0] == 1.0


def test_flat_price_no_trades():
    eq, trades, _ = grid_sim([100.5] * 50, 90, 110, 20, fee=0)
    assert np.allclose(eq, 1.0) and trades == 0
    eq, trades, _ = grid_sim([100.5] * 50, 90, 110, 20, fee=0.01)
    assert trades == 0 and np.allclose(eq[1:], eq[1])  # chỉ còn phí mua coin lúc vào, không đổi nữa
    assert np.isclose(eq[1], 1 - 0.01 * 10 * 100.5 / CAP)


def test_oscillation_earns_one_step_per_cycle():
    # 100.5 -> 98.5 -> 100.5 lặp m lần: mỗi vòng slot 9 mua ở 99 rồi bán ở 100 = đúng 1 bước
    for m in (1, 3, 5):
        P = [100.5] + [98.5, 100.5] * m
        eq, trades, _ = grid_sim(P, 90, 110, 20, fee=0)
        assert np.isclose(eq[-1] - 1, m * 1.0 / CAP)
        assert trades == 2 * m
    # có phí: trừ phí mua lúc vào + 2 lệnh mỗi vòng (mua 99, bán 100)
    fee, m = 0.001, 5
    eq = grid_equity([100.5] + [98.5, 100.5] * m, 90, 110, 20, fee=fee)
    assert np.isclose(eq[-1] - 1, (m * 1.0 - fee * (10 * 100.5 + m * (99 + 100))) / CAP)


def test_up_down_k_lines_hand_computed():
    # lên qua 101,102,103 rồi xuống: bán 101,102,103 (+306), mua lại 102,101 (-203); coin 10 -> 9
    eq = grid_equity([100.5, 103.5, 100.5], 90, 110, 20, fee=0)
    assert np.isclose(eq[-1] - 1, (306 - 203 - 100.5) / CAP)
    # xuống qua 100(không mua: slot 10 đã giữ),99,98 rồi lên lại: 2 vòng khép kín = 2 bước
    eq = grid_equity([100.5, 97.5, 100.5], 90, 110, 20, fee=0)
    assert np.isclose(eq[-1] - 1, 2.0 / CAP)


def test_path_dependent():
    # cùng giá đầu và giá cuối, đường đi khác -> equity khác (có trễ)
    a = grid_equity([100.5, 100.6, 100.5], 90, 110, 20)[-1]
    b = grid_equity([100.5, 98.5, 100.5], 90, 110, 20)[-1]
    assert a == 1.0 and b > a


def _limit_order_sim(P, low, high, n, mode, fee):
    """Mô phỏng độc lập kiểu sổ lệnh limit: mỗi slot luôn có đúng một lệnh chờ (bán ở L_{k+1} hoặc mua ở L_k)."""
    L = (np.linspace if mode == "arithmetic" else np.geomspace)(low, high, n + 1)
    orders = {}
    cash = coins = 0.0
    for k in range(n):
        if L[k + 1] > P[0]:
            orders[k] = ("sell", L[k + 1])
            coins += 1
        else:
            orders[k] = ("buy", L[k])
            cash += L[k]
    cap = coins * P[0] + cash
    eq, prev, paid_entry = [1.0], P[0], False
    for p in P[1:]:
        for k, (side, x) in list(orders.items()):
            if side == "buy" and p < x <= prev:
                cash -= x * (1 + fee)
                coins += 1
                orders[k] = ("sell", L[k + 1])
            elif side == "sell" and prev < x <= p:
                cash += x * (1 - fee)
                coins -= 1
                orders[k] = ("buy", L[k])
        entry = fee * sum(1 for k in range(n) if L[k + 1] > P[0]) * P[0]
        eq.append((cash + coins * p - entry) / cap)
        prev = p
    return np.array(eq)


def test_matches_independent_limit_order_sim():
    rng = np.random.default_rng(0)
    for mode in ("arithmetic", "geometric"):
        for fee in (0.0, 0.001):
            P = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
            a = grid_equity(P, 90, 112, 12, mode, fee)
            b = _limit_order_sim(P, 90, 112, 12, mode, fee)
            assert np.abs(a - b).max() < 1e-9
