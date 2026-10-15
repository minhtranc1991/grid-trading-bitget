import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import grid_optimizer as g

SYMS = ["BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT"]


def test_clean_dedup_sort_dropforming():
    rows = [[str(t), "1", "2", "0.5", "1.5", "3", "4", "4"] for t in (1800000, 0, 900000, 900000, 2700000)]
    df = g._clean(rows, "15m", now_ms=2_700_000 + 100)  # nến 2700000 chưa đóng
    assert df.ts.tolist() == [0, 900000, 1800000]


@pytest.mark.parametrize("sym", SYMS)
def test_cached_csv(sym):
    p = g.DATA_DIR / f"{sym}_15m.csv"
    if not p.exists():
        pytest.skip("chưa tải dữ liệu")
    df = g.pd.read_csv(p)
    assert df.ts.is_monotonic_increasing and df.ts.is_unique
    assert not df.isna().any().any()
