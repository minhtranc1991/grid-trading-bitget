# grid-opt

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

**Sweep (STEP 4, IN-SAMPLE):** `sweep(prices, space, fee)` quét dl, dh, n, mode theo `space_for(symbol)`; lọc bước% nhỏ nhất ≥ 2·fee·2, n ≤ `MAX_GRIDS` (cần xác minh), trades ≥ 20. Heatmap dl × n lấy lát cắt đối xứng dh = dl.
Kết quả BTC 90 ngày cuối: 1622/2200 tổ hợp qua lọc, 0.6 giây; Sharpe top-1 3.45 so với B&H cùng cửa sổ 3.22 (+29%). Các top đều có dh = 50%, tức là gần như giữ coin: lợi nhuận là drift, không phải edge của grid. Chưa dùng để kết luận; xem STEP 5.
Cả 4 cặp (90 ngày): sweep ghi `results/sweep_{SYMBOL}.json` và `results/heatmap_{BTC,ETH,PAXG,XAUT}.png`. PAXG/XAUT: Sharpe top-1 (0.26–0.30) thấp hơn B&H cùng cửa sổ (0.80–0.83).

**Walk-forward (STEP 5, OUT-OF-SAMPLE):** `walk_forward(df, tf, symbol, ...)` chọn tham số đỉnh in-sample trên 90 ngày train, áp tại giá đầu 30 ngày test, trượt 30 ngày (15 fold/cặp); so với B&H và lưới mặc định ±10%, n=20. Test chống rò rỉ: đổi giá từ ngày test trở đi thì tham số fold 0 không đổi.
Kết quả (Sharpe trung vị OOS / B&H / lưới mặc định): BTC −2.00 / −0.32 / −0.69; ETH −1.06 / −0.13 / −1.25; PAXG −1.99 / −0.26 / −1.70; XAUT −1.65 / −0.13 / −1.50. Grid chọn từ train không vượt B&H ở cả 4 cặp; tỷ lệ fold lãi 27–40%. Chưa có bằng chứng edge; tham số đỉnh in-sample không giữ được ngoài mẫu (STEP 6 thử tham số phẳng).

**Tham số phẳng (STEP 6):** `smooth_pick` làm mượt Sharpe bằng trung bình lân cận 3×3 trên (dl, dh) với cùng (n, mode), chỉ xét ô có ≥ 5 ô hợp lệ quanh nó; `stability` báo median/IQR của dl, dh, bước% qua fold và cờ UNSTABLE (ngưỡng `UNSTABLE_IQR`, cần hiệu chỉnh).
So sánh Sharpe OOS trung vị, đỉnh nhọn vs phẳng: BTC −2.00 vs −1.42; ETH −1.06 vs −1.03; PAXG −1.99 vs −2.00; XAUT −1.65 vs −2.03; trung bình −1.68 vs −1.62.
**Mặc định = phẳng** (`DEFAULT_PICK`): trung bình nhỉnh hơn và ít nhạy nhiễu, nhưng chênh lệch nằm trong nhiễu (thắng 2/4 cặp, 15 fold) và cả hai đều kém B&H, nên đây không phải bằng chứng edge. Cả 4 cặp, cả hai cách chọn, đều bị cờ UNSTABLE; dh median nằm ở biên trên của không gian tìm kiếm (BTC/ETH 50%/35%, vàng 8%), tức là bộ tối ưu luôn đẩy dh lên mức tối đa.

**DGT (STEP 7):** `dgt_equity(prices, dl, dh, n, mode, fee)` dựng lại lưới quanh giá mới khi giá phá low/high, vốn mới = equity hiện tại; phá trên thì đang toàn tiền mặt, phá dưới thì đang giữ toàn coin; trả phí tái cân bằng mỗi lần reset. Khi không bao giờ phá biên, DGT trùng khít grid thường (có test).
Bảng OOS trung vị Sharpe (15 fold/cặp) — BTC / ETH / PAXG / XAUT:

| Chiến lược | BTC | ETH | PAXG | XAUT |
|---|---|---|---|---|
| Buy & Hold | −0.32 | −0.13 | −0.26 | −0.13 |
| Grid cố định mặc định (±10%, n=20) | −0.69 | −1.25 | −1.70 | −1.50 |
| Grid tối ưu: đỉnh nhọn | −2.00 | −1.06 | −1.99 | −1.65 |
| Grid tối ưu: phẳng | −1.42 | −1.03 | −2.00 | −2.03 |
| DGT (tham số phẳng) | −2.60 | −2.25 | −3.39 | −3.33 |
| DGT (lưới mặc định) | −2.92 | −3.15 | −2.63 | −1.58 |

DGT không cải thiện: reset liên tục (trung vị 3–4 lần/fold) khóa lỗ và trả thêm phí. Không có chiến lược grid nào vượt B&H ở cả 4 cặp.

**Thống kê (STEP 8):** `block_bootstrap_sharpe` (khối 1 ngày, 2000 lần) cho CI 95% của Sharpe OOS gộp các fold; `deflated_sharpe` trả PSR(0) và DSR theo số tổ hợp thử (2200 crypto, 1408 vàng) và phương sai Sharpe giữa các thử nghiệm.
Sharpe OOS gộp (grid phẳng) [CI 95%] vs B&H: BTC −1.28 [−2.98, 0.31] vs −0.48; ETH −1.20 [−2.79, 0.44] vs −0.24; PAXG −1.08 [−2.67, 0.48] vs +0.79; XAUT −1.13 [−2.69, 0.42] vs +0.81. DSR ≈ 0 ở cả 4 cặp.
**Kết luận: chưa có bằng chứng edge** (CI chứa 0 ở cả 4 cặp); ở PAXG/XAUT grid kém B&H có ý nghĩa thống kê (CI hiệu [−4.45, −1.18] / [−4.81, −1.31]).
Độ nhạy (Sharpe OOS trung vị, phẳng): phí 0.5×/1×/2× → BTC −1.49/−1.42/−2.16; ETH −0.90/−1.03/−1.13; PAXG −1.21/−2.00/−2.49; XAUT −0.92/−2.03/−2.33. Phí cao hơn làm kém đi ở mọi cặp; không có cấu hình timeframe nào (5m/15m/1h) vượt B&H. 1h tốt nhất cho ETH/PAXG/XAUT, nhưng chênh lệch giữa các timeframe nằm trong nhiễu (B&H trung vị của ETH dao động −0.13 đến +0.57 chỉ vì lấy mẫu).

**Tóm tắt cuối (STEP 9, `results/summary.csv`)**: walk-forward 90/30/30, phí 0.1%, 15 fold/cặp.

| Cặp | Sharpe OOS gộp [CI 95%] | Return OOS | B&H | MDD OOS | Fold lãi | Khuyến nghị dl/dh/n/bước%/mode | Cờ |
|---|---|---|---|---|---|---|---|
| BTC | −1.28 [−2.98, 0.31] | −48.1% | −30.6% | −56.6% | 33% | 12% / 50% / 6 / 6.89% / arithmetic | UNSTABLE |
| ETH | −1.20 [−2.79, 0.44] | −58.0% | −34.0% | −71.0% | 27% | 3% / 50% / 10 / 3.53% / arithmetic | UNSTABLE |
| PAXG | −1.08 [−2.67, 0.48] | −23.9% | +24.1% | −28.5% | 40% | 2% / 8% / 4 / 2.31% / arithmetic | UNSTABLE |
| XAUT | −1.13 [−2.69, 0.42] | −24.2% | +24.3% | −29.4% | 40% | 3% / 8% / 4 / 2.55% / arithmetic | UNSTABLE |

**Kết luận: chưa có bằng chứng edge** cho grid spot trên cả 4 cặp trong giai đoạn 2025-04 → 2026-10. Equity OOS nối các fold nằm dưới B&H, và đi ngang từng đoạn dài (lưới bị giá phá biên, đứng yên toàn coin hoặc toàn tiền mặt). Tham số khuyến nghị chỉ để thử nghiệm: tất cả đều UNSTABLE và `dh` chạm biên trên của không gian tìm kiếm (lưới gần như giữ coin). Khuyến nghị được chọn bằng cách "phẳng" trên 90 ngày cuối, tương đối theo giá hiện tại (`rec_low`/`rec_high` trong summary.csv là mức giá tuyệt đối tương ứng).

**Trần số lưới:** `--max-grids N` (mặc định `MAX_GRIDS = 100`, cần xác minh trong app Bitget) lọc `n ≤ N` ở mọi bước (sweep, walk-forward, stats, pipeline cuối). Không gian tìm kiếm quét `n ∈ {4, 6, 8, 10, 15, 20, 30, 40, 60, 80, 100}`; `n` khuyến nghị hiện là 4–10, nên trần 100 không phải ràng buộc đang cắn.

**Hàm lõi:** `load_ohlcv`, `grid_equity` (equity chuẩn hóa, vốn đầu = 1), `grid_stats` (số giao dịch, turnover), `metrics`, `buy_and_hold`.

**Lưu ý lý thuyết:** equity của grid chỉ phụ thuộc giá hiện tại và số line đã cắt, không phụ thuộc đường đi. Giá đi lên-xuống rồi về chỗ cũ thì equity gộp = 1, chỉ còn trừ phí. Lãi chỉ có khi giá kết thúc ở chỗ khác chỗ bắt đầu (drift/regime).

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
- [x] **STEP 2** Grid backtest lõi `grid_equity(prices, low, high, n, mode, fee)` vector hóa + 4 test (equity[0]=1, giá đứng yên, k line, khớp vòng lặp thuần Python sai số <1e-9)
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
- Grid thuần không có kỳ vọng dương (Chen et al.); kết quả tốt trên một giai đoạn có thể chỉ là drift/regime.
- PAXG, XAUT là token neo vàng: biến động thấp, phí/spread chi phối; cần kiểm tra thanh khoản thật. Không đòn bẩy.
- Phí Bitget và giới hạn số lưới là giả định cần xác minh.
