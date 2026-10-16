import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from grid_optimizer import dgt_equity, grid_equity


def test_equals_fixed_grid_when_never_breaks():
    rng = np.random.default_rng(0)
    P = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, 500)))
    dl = dh = 0.5  # biên rất rộng -> không bao giờ phá
    for mode in ("arithmetic", "geometric"):
        eq, resets = dgt_equity(P, dl, dh, 20, mode, 0.001, True)
        assert resets == 0
        assert np.allclose(eq, grid_equity(P, P[0] * (1 - dl), P[0] * (1 + dh), 20, mode, 0.001), atol=1e-12)


def test_resets_when_breaking_and_continuous():
    P = np.concatenate([np.linspace(100, 130, 200), np.linspace(130, 80, 300)])  # phá trên rồi phá dưới
    eq, resets = dgt_equity(P, 0.1, 0.1, 10, "arithmetic", 0.0, True)
    assert resets >= 2
    assert np.isfinite(eq).all() and eq[0] == 1.0
    assert np.abs(np.diff(eq) / eq[:-1]).max() < 0.1  # không nhảy bất thường khi reset (fee=0)


def test_fee_only_reduces_equity():
    P = np.concatenate([np.linspace(100, 130, 200), np.linspace(130, 80, 300)])
    free = dgt_equity(P, 0.1, 0.1, 10, "arithmetic", 0.0)
    paid = dgt_equity(P, 0.1, 0.1, 10, "arithmetic", 0.001)
    assert paid[-1] < free[-1]
