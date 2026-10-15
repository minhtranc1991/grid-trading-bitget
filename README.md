# grid-opt

> **Lịch sử sửa lỗi lõi (nhánh `fix/grid-pairing`):** bản đầu của `grid_equity` mua và bán cùng một line nên equity chỉ phụ thuộc giá hiện tại và số line đã cắt, dao động qua lại không sinh lãi theo chu kỳ; mọi kết luận "chưa có bằng chứng edge" ở bản đó là **hệ quả của mô hình sai** và đã bị thay thế. Lõi hiện tại (`grid_sim`) ghép cặp đúng: slot k mua ở L_k, bán ở L_{k+1}, có trễ, tính phí mỗi lệnh. Mọi số liệu bên dưới được chạy lại trên lõi mới.

Tối ưu tham số GRID TRADING SPOT cho Bitget (BTC, ETH, PAXG, XAUT /USDT).
Backtest + walk-forward out-of-sample, chỉ dùng dữ liệu công khai, không API key, không đặt lệnh thật.

**Mục tiêu:** tìm price range (low, high) và số lưới n tối đa hóa Sharpe, đánh giá OUT-OF-SAMPLE, cho từng cặp.

## Cách dùng

```
pip install -r requirements.txt
python grid_optimizer.py --symbols BTCUSDT ETHUSDT PAXGUSDT XAUTUSDT --tf 15m --days 540 --fee 0.001 --train 90 --test 30   # STEP 9: pipeline đầy đủ (~2 phút)
python grid_optimizer.py --sweep                          # STEP 4 cho cả 4 cặp, cửa sổ 90 ngày cuối
python grid_optimizer.py --symbols BTCUSDT --sweep --window 90 --fee 0.001   # chỉ một cặp
python grid_optimizer.py --walkforward                    # STEP 5: 4 cặp, train 90 / test 30 / step 30 -> results/{SYMBOL}_folds.csv
python grid_optimizer.py --stats                          # STEP 8: CI bootstrap + Deflated Sharpe -> results/stats_{SYMBOL}.json
python grid_optimizer.py --sensitivity                    # STEP 8: độ nhạy phí x0.5/1/2 và timeframe 5m/15m/1h (chậm, ~10 phút, tải nến 5m/1h)
python make_report.py                                     # cập nhật results/report.html
pytest
```

Không truyền cờ step nào (`--sweep/--walkforward/--stats/--sensitivity`) thì CLI chạy toàn bộ pipeline STEP 9 và ghi `results/summary.csv`, `results/equity_oos.png`, `results/oos_equity.json`. Từng step vẫn chạy riêng được bằng các cờ trên.
CLI tải/cache nến vào `data/{symbol}_{tf}.csv`, in số nến, khoảng thời gian, số gap và chỉ số buy&hold của từng cặp.
Lần sau chạy chỉ tải phần thiếu. CSV nằm trong `.gitignore`. Mọi lần chạy được ghi nối vào `results/run.log` (dùng `log.info` cho các step sau).

**Báo cáo trực quan:** `python make_report.py` đọc `results/run.log` + `data/*.csv` và ghi `results/report.html` (tự đủ, mở bằng trình duyệt).
Gồm tiến độ các step, giá chuẩn hóa, drawdown, vol 30d, phân phối lợi suất, scatter regime (Efficiency Ratio 30 ngày), chỉ số B&H, heatmap tháng, tương quan, lịch fold, kết quả sweep STEP 4 (top/bottom, heatmap, so với B&H cùng cửa sổ), lịch sử chạy. Mỗi step mới thêm một mục vào báo cáo. Tạo lại sau mỗi lần chạy mới.

**Lõi mô phỏng (STEP 2):** `grid_sim(prices, low, high, n, mode, fee)` → (equity chuẩn hóa vốn đầu = 1, số lệnh khớp, turnover). n slot, mỗi slot 1 đơn vị coin; slot k mua ở L_k và bán ở L_{k+1}. Lúc vào, slot có line bán nằm trên giá đầu giữ coin (mua tại P0, tính phí), slot còn lại dự trữ tiền L_k. Giá cắt lên L_j thì slot j−1 bán nếu đang giữ; cắt xuống L_j thì slot j mua nếu đang không giữ. Duyệt theo **sự kiện cắt line** (không theo từng bar) nên sweep 2200 tổ hợp mất ~0.6 giây. Equity **phụ thuộc đường đi** (có trễ): dao động giữa hai line sinh đúng một bước lãi mỗi vòng khép kín.
Kiểm chứng: test tính tay (lên-xuống qua k line; mỗi vòng 100.5→98.5→100.5 lãi đúng 1 bước), và đối chiếu với một mô phỏng sổ lệnh limit viết độc lập, sai số < 1e-9 ở cả arithmetic lẫn geometric.

**Sweep (STEP 4, IN-SAMPLE):** `sweep(prices, space, fee)` quét dl, dh, n, mode theo `space_for(symbol)`; lọc bước% nhỏ nhất ≥ 2·fee·2, n ≤ `MAX_GRIDS` (cần xác minh), số lệnh khớp ≥ 20. Heatmap dl × n lấy lát cắt đối xứng dh = dl.
90 ngày cuối, Sharpe top-1 in-sample vs B&H cùng cửa sổ: BTC 4.49 vs 3.21; ETH 4.23 vs 2.49; PAXG 3.64 vs 0.91; XAUT 3.64 vs 0.88. Đây là in-sample trên cửa sổ tăng giá, chưa dùng để kết luận. Ghi `results/sweep_{SYMBOL}.json`, `results/heatmap_{BTC,ETH,PAXG,XAUT}.png`.

**Walk-forward (STEP 5, OUT-OF-SAMPLE):** `walk_forward(df, tf, symbol, ...)` chọn tham số trên 90 ngày train, áp tại giá đầu 30 ngày test, trượt 30 ngày (15 fold/cặp); so với B&H và lưới mặc định ±10%, n=20. Test chống rò rỉ: đổi giá từ ngày test trở đi thì tham số fold 0 không đổi.

**Tham số phẳng (STEP 6):** `smooth_pick` làm mượt Sharpe bằng trung bình lân cận 3×3 trên (dl, dh) với cùng (n, mode), chỉ xét ô có ≥ 5 ô hợp lệ quanh nó; `stability` báo median/IQR của dl, dh, bước% qua fold và cờ UNSTABLE (ngưỡng `UNSTABLE_IQR`, cần hiệu chỉnh).
**Mặc định = phẳng** (`DEFAULT_PICK`): Sharpe OOS trung vị trung bình 1.79 so với 1.27 của đỉnh nhọn, thắng 3/4 cặp. Cả 4 cặp bị cờ UNSTABLE với phẳng; với đỉnh nhọn thì BTC ổn định, 3 cặp còn lại UNSTABLE.

**DGT (STEP 7):** `dgt_equity(prices, dl, dh, n, mode, fee)` dựng lại lưới quanh giá mới khi giá phá low/high, vốn mới = equity hiện tại; phá trên thì đang toàn tiền mặt, phá dưới thì đang giữ toàn coin; trả phí tái cân bằng mỗi lần reset. Khi không bao giờ phá biên, DGT trùng khít grid thường (có test).

**Bảng OOS, Sharpe trung vị mỗi fold (annualized, 15 fold/cặp):**

| Chiến lược | BTC | ETH | PAXG | XAUT |
|---|---|---|---|---|
| Buy & Hold | −0.32 | −0.13 | −0.26 | −0.13 |
| Grid cố định mặc định (±10%, n=20) | 0.31 | 0.42 | 0.30 | 0.61 |
| Grid tối ưu: đỉnh nhọn | 1.26 | 1.56 | 1.17 | 1.10 |
| Grid tối ưu: phẳng | **1.66** | 1.43 | **2.08** | **1.99** |
| DGT (tham số phẳng) | 0.92 | 0.98 | −1.32 | −1.55 |
| DGT (lưới mặc định) | −1.25 | −1.05 | −1.17 | 0.04 |

Tỷ lệ fold lãi (phẳng / B&H): BTC 67% / 40%, ETH 73% / 47%, PAXG 60% / 40%, XAUT 67% / 40%. DGT thua grid cố định vì reset liên tục (trung vị 2–7 lần/fold) khóa vị thế ở giá phá biên và trả thêm phí.

**Thống kê (STEP 8):** `block_bootstrap_sharpe` (khối 1 ngày, 2000 lần) cho CI 95% của Sharpe OOS gộp các fold; `deflated_sharpe` trả PSR(0) và DSR theo số tổ hợp thử (2200 crypto, 1408 vàng) và phương sai Sharpe giữa các thử nghiệm.
Sharpe OOS gộp (grid phẳng) [CI 95%] vs B&H: BTC −0.37 [−2.02, 1.33] vs −0.48; ETH −0.44 [−2.02, 1.24] vs −0.24; PAXG −0.10 [−1.69, 1.52] vs +0.79; XAUT +0.06 [−1.45, 1.67] vs +0.81. CI của hiệu grid − B&H chứa 0 ở cả 4 cặp. PSR(0) 0.31–0.53; DSR 0.00–0.10.
**Sharpe gộp (≈ 0) thấp hơn nhiều so với trung vị fold (1.4–2.1):** phần lớn fold lãi nhỏ nhưng vài fold lỗ lớn (phân phối lệch âm: trung bình return fold < trung vị, ví dụ ETH có fold −23%, khi giá phá biên dưới và lưới giữ coin giảm giá). Trung vị fold không phản ánh phần đuôi này.
Độ nhạy (Sharpe OOS trung vị, phẳng): phí 0.5× / 1× / 2× → BTC 1.55 / 1.66 / 1.54; ETH 1.46 / 1.43 / 1.37; PAXG 2.24 / 2.08 / 0.98; XAUT 2.25 / 1.99 / 0.54 (vàng nhạy phí hơn crypto). Timeframe 5m / 15m / 1h → BTC 1.93 / 1.66 / 0.92; ETH 1.34 / 1.43 / 1.35; PAXG 1.03 / 2.08 / 2.25; XAUT 1.00 / 1.99 / 2.64. Không timeframe/phí nào đảo dấu kết luận; chênh lệch giữa các timeframe nằm trong nhiễu với 15 fold.

**Tóm tắt cuối (STEP 9, `results/summary.csv`)**: walk-forward 90/30/30, phí 0.1%, 15 fold/cặp, grid phẳng.

| Cặp | Sharpe OOS gộp [CI 95%] | Return OOS gộp | B&H | MDD OOS | MDD B&H | Fold lãi | Khuyến nghị dl/dh/n/bước%/mode | Cờ |
|---|---|---|---|---|---|---|---|---|
| BTC | −0.37 [−2.02, 1.33] | −11.7% | −30.6% | −30.9% | −54.5% | 67% | 5% / 50% / 15 / 2.44% / arithmetic | UNSTABLE |
| ETH | −0.44 [−2.02, 1.24] | −24.0% | −34.0% | −49.3% | −69.9% | 73% | 35% / 50% / 20 / 2.83% / arithmetic | UNSTABLE |
| PAXG | −0.10 [−1.69, 1.52] | −3.9% | +24.1% | −19.2% | −29.5% | 60% | 3% / 8% / 8 / 1.35% / geometric | UNSTABLE |
| XAUT | +0.06 [−1.45, 1.67] | −0.4% | +24.3% | −18.3% | −29.3% | 67% | 2% / 5% / 6 / 1.16% / geometric | UNSTABLE |

**Kết luận (trên lõi đã sửa):**
- Grid **giảm drawdown rõ rệt** (MDD OOS thấp hơn B&H ở cả 4 cặp) và **lãi ở đa số fold** (60–73% so với 40–47% của B&H), vì nó giữ ít coin hơn khi giá giảm.
- Trong giai đoạn thị trường giảm (BTC/ETH) grid lỗ ít hơn B&H; trong giai đoạn vàng tăng (+24%) grid **thua B&H nhiều** vì bán sớm khi giá lên.
- **Chưa có bằng chứng thống kê về edge:** CI 95% của Sharpe OOS gộp chứa 0 ở cả 4 cặp và CI của hiệu so với B&H cũng chứa 0; DSR thấp. Với 15 fold và một giai đoạn thị trường, không thể phân biệt edge thật với may mắn.
- Tham số khuyến nghị chỉ để thử nghiệm: cờ UNSTABLE, tham số đổi nhiều giữa các fold.

**Trần số lưới:** `--max-grids N` (mặc định `MAX_GRIDS = 100`, cần xác minh trong app Bitget) lọc `n ≤ N` ở mọi bước (sweep, walk-forward, stats, pipeline cuối). Không gian tìm kiếm quét `n ∈ {4, 6, 8, 10, 15, 20, 30, 40, 60, 80, 100}`; `n` khuyến nghị hiện là 6–20, nên trần 100 không phải ràng buộc đang cắn.

**Hàm lõi:** `load_ohlcv`, `grid_sim` / `grid_equity` / `grid_stats`, `metrics`, `buy_and_hold`, `sweep`, `walk_forward`, `dgt_equity`, `block_bootstrap_sharpe`, `deflated_sharpe`.

**B&H 15m (2025-04-21 → 2026-10-15):** BTC Sharpe 0.07 / −8.2% / MDD −53.8%; ETH 0.71 / +44.5% / −69.3%; PAXG 0.61 / +20.2% / −29.7%; XAUT 0.62 / +20.1% / −29.4%.

## Quy trình làm việc

- Mỗi feature/step rẽ nhánh riêng (`feature/stepN-...`) từ nhánh step trước, không code trên `main`.
- Chỉ làm một step mỗi lượt, mỗi step để lại ít nhất một test chạy được; step sau không được làm hỏng test step trước.
- Ưu tiên một file `grid_optimizer.py`; chỉ tách file khi >400 dòng.
- Giả định chưa xác minh (phí, giới hạn lưới) là tham số có chú thích "cần xác minh".
- Update nhỏ chỉ commit trên nhánh hiện tại; chỉ rẽ nhánh mới cho step/feature thật.
- Trước mỗi lần push: cập nhật README (checklist, thông tin, giới hạn) theo thay đổi của dự án.
- Commit theo từng feature nhỏ (một commit một việc: code step, test, báo cáo, README...), không gộp tất cả vào một commit.

## Checklist

- [x] **STEP 0** Khung dự án: `grid_optimizer.py` (`main()`), `requirements.txt`, `tests/`, `data/`, `results/`, README
- [x] **STEP 1** Tải & cache dữ liệu (`load_ohlcv`): 4 cặp × 15m, ~52000 nến, 0 gap, test ts tăng/không trùng/không NaN
- [x] **STEP 2** Grid backtest lõi `grid_sim` (slot ghép cặp, theo sự kiện cắt line) + test: equity[0]=1, giá đứng yên, lãi mỗi vòng = 1 bước, tính tay, khớp mô phỏng sổ lệnh limit độc lập (đã sửa sau lỗi mô hình)
- [x] **STEP 3** Chỉ số: `metrics` (Sharpe annualized, return, MDD, số giao dịch, turnover) + `buy_and_hold`
- [x] **STEP 4** Quét tham số trên một cửa sổ (`sweep`), lọc bước% ≥ 2·fee·hệ số, n ≤ giới hạn lưới, trades ≥ 20; heatmap `results/heatmap_BTC.png`. Ghi chú in-sample
- [x] **STEP 5** Walk-forward: train 90d → test 30d, trượt 30d; `results/{symbol}_folds.csv`; test không rò rỉ
- [x] **STEP 6** Tham số "phẳng" (làm mượt Sharpe 3×3) vs đỉnh nhọn; báo cáo ổn định median/IQR, cờ UNSTABLE
- [x] **STEP 7** Baseline DGT (reset lưới khi phá biên) + bảng OOS B&H vs grid cố định vs tối ưu vs DGT
- [x] **STEP 8** Đánh giá thống kê: số tổ hợp đã thử, Deflated Sharpe / block bootstrap, độ nhạy phí (0.5×/1×/2×) và timeframe (5m/15m/1h)
- [x] **STEP 9** CLI đầy đủ + `results/summary.csv` + equity OOS vs B&H + README giới hạn; end-to-end < vài phút, pytest pass

## Thông tin nền

**Nghiên cứu**
- Chen–Chen–Jang 2025 (arXiv 2506.11921): grid có biên trên random walk 50/50, không phí → kỳ vọng 0; sau phí âm. Grid không có edge nội tại; lãi đến từ mean reversion thật / drift / chọn đúng regime. DGT (reset lưới khi phá biên) là baseline.
- Yeh–Hsieh–Huang 2022 (arXiv 2211.12839): ROI in-sample (60–127%) rớt còn vài % khi validation → bắt buộc out-of-sample. Ràng buộc phí (Eq.16): g_{i+1} − g_i > h·g_{i+1}.

**Phí giao dịch (từ ảnh app Bitget trong `data/refs/`, chụp 2026-10-15)**
- **0.1% mỗi chiều** (mua/bán), giống nhau cho BTC, ETH, PAXG, XAUT; round-trip 0.2%. Không thấy chiết khấu BGB/VIP.
- Lệnh mua trừ phí bằng coin (base), lệnh bán trừ bằng USDT; giá trị tương đương nên `fee·|ΔS|` vẫn đúng.
- Lãi mỗi lưới hiển thị đã trừ phí cả hai chiều.
- Bước lưới bot thật (arithmetic): ETH ≈0.94%, BTC ≈0.69%, PAXG/XAUT ≈0.41% → lãi ròng/chu kỳ ≈0.74% / 0.49% / 0.21%. PAXG/XAUT bị phí ăn gần nửa lãi gộp.
- Mặc định `fee=0.001`, là tham số (cần xác minh nếu tài khoản đổi mức phí).

**API dữ liệu (đã xác minh bằng gọi thử)**
- `GET /api/v2/spot/market/history-candles?symbol=&granularity=&limit=&endTime=`: `limit` tối đa **200** (1000 → lỗi 40020), phân trang lùi bằng `endTime`, trả tăng dần theo ts.
- `.../candles` cho tối đa 1000 nến nhưng chỉ gần đây.
- Hàng: `[ts_ms, open, high, low, close, base_vol, quote_vol, quote_vol]`. Granularity: `5min`, `15min`, `1h`, ...

**Giới hạn của Bitget (docs help-center, đã đọc 5 bài)**
- Tối đa 50 bot/tài khoản (mọi loại).
- **Docs KHÔNG nêu** số lưới tối thiểu/tối đa, bước % tối thiểu, lãi/lưới tối thiểu, vốn tối thiểu, hay giới hạn theo cặp. Minimum Investment chỉ hiện trong UI theo cặp và tham số. → `MAX_GRIDS` là tham số "cần xác minh"; cách xác minh: mở màn hình tạo bot trong app, đọc Min Investment và số lưới tối đa của từng cặp.
- Bot chỉ mở lệnh khi lãi lưới > phí; ở range hẹp + nhiều lưới dùng "interval matching" (ghép lệnh cách vài lưới) nên bot thật khác mô hình lưới thuần.
- Position Grid: hệ thống tự chọn số lưới và range, không chỉnh tay (bot khác với bot ở đây).

## Giới hạn của kết quả

- Dùng giá close → số lần cắt lưới bị ước lượng thấp (bảo thủ); dùng high/low sẽ lạc quan. Không mô hình queue/slippage/độ trễ/interval matching.
- Grid thuần không có kỳ vọng dương trên random walk (Chen et al.); kết quả tốt trên một giai đoạn có thể chỉ là drift/regime. Với 15 fold và một giai đoạn, CI rộng.
- Lệnh khớp được mô phỏng ở đúng giá line khi giá close cắt qua; không có trượt giá, queue, độ trễ, hay "interval matching" của bot Bitget.
- PAXG, XAUT là token neo vàng: biến động thấp, phí/spread chi phối; cần kiểm tra thanh khoản thật. Không đòn bẩy.
- Phí Bitget và giới hạn số lưới là giả định cần xác minh.
