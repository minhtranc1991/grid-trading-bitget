import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import make_report as m


def test_parse_log_separates_interleaved_runs_by_pid():
    log = "\n".join([
        "2026-10-15 10:00:00,000 [1] RUN args={'a': 1}",
        "2026-10-15 10:00:00,500 [2] RUN args={'b': 2}",
        "2026-10-15 10:00:01,000 [1] BTCUSDT 15m: cache 10 -> 12 bars, fetched 5 raw rows",
        "2026-10-15 10:00:01,100 [2] BTCUSDT 15m: cache 20 -> 20 bars, fetched 5 raw rows",
        "2026-10-15 10:00:03,000 [1] BTCUSDT B&H: sharpe=0.1 return=+1.0% mdd=-2.0%",
        "2026-10-15 10:00:09,100 [2] BTCUSDT B&H: sharpe=0.2 return=+2.0% mdd=-3.0%",
    ])
    runs = m.parse_log(log)
    assert len(runs) == 2
    r1, r2 = runs
    assert r1["pid"] == 1 and r2["pid"] == 2
    assert r1["syms"]["BTCUSDT"]["cache_after"] == 12 and r2["syms"]["BTCUSDT"]["cache_after"] == 20
    assert r1["syms"]["BTCUSDT"]["elapsed"] == 3.0   # 10:00:00 -> 10:00:03
    assert r2["syms"]["BTCUSDT"]["elapsed"] == 8.6   # 10:00:00.5 -> 10:00:09.1


def test_parse_log_accepts_old_lines_without_pid():
    log = "2026-10-15 10:00:00,000 RUN args={'a': 1}\n2026-10-15 10:00:02,000 ETHUSDT B&H: sharpe=0.1 return=+1.0% mdd=-2.0%"
    runs = m.parse_log(log)
    assert len(runs) == 1 and runs[0]["syms"]["ETHUSDT"]["elapsed"] == 2.0
