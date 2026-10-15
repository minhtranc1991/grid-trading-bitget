# grid-opt

> **Lịch sử sửa lỗi lõi (nhánh `fix/grid-pairing`):** bản đầu của `grid_equity` mua và bán cùng một line nên equity chỉ phụ thuộc giá hiện tại và số line đã cắt, dao động qua lại không sinh lãi theo chu kỳ; mọi kết luận "chưa có bằng chứng edge" ở bản đó là **hệ quả của mô hình sai** và đã bị thay thế. Lõi hiện tại (`grid_sim`) ghép cặp đúng: slot k mua ở L_k, bán ở L_{k+1}, có trễ, tính phí mỗi lệnh. Mọi số liệu bên dưới được chạy lại trên lõi mới.

Tối ưu tham số GRID TRADING SPOT cho Bitget (BTC, ETH, PAXG, XAUT /USDT).
Backtest + walk-forward out-of-sample, chỉ dùng dữ liệu công khai, không API key, không đặt lệnh thật.

**Mục tiêu:** tìm price range (low, high) và số lưới n tối đa hóa Sharpe, đánh giá OUT-OF-SAMPLE, cho từng cặp.

## Cách dùng

```
pip install -r requirements.txt
python grid_optimizer.py --symbols BTCUSDT ETHUSDT PAXGUSDT XAUTUSDT --tf 15m --days 540 --fee 0.001 --train 28 --select 7 --test 7 --step 7 --jobs 8   # STEP 9: pipeline đầy đủ (~25 giây với 8 tiến trình)
python grid_optimizer.py --sweep                          # STEP 4 cho cả 4 cặp, cửa sổ 90 ngày cuối
python grid_optimizer.py --symbols BTCUSDT --sweep --window 90 --fee 0.001   # chỉ một cặp
python grid_optimizer.py --walkforward                    # STEP 5: IS 28 / OOS 7 / forward 7 / step 7 -> results/{SYMBOL}_folds.csv
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

**IS / OOS / forward (STEP 5, rolling hàng tuần):** `walk_forward(df, tf, symbol, ...)`, mỗi fold trượt 1 tuần:

| Giai đoạn | Độ dài | Việc làm |
|---|---|---|
| IS | 4 tuần (`--train 28`) | sweep, tìm tham số tối ưu; lấy top 20 và tham số "phẳng" làm ứng viên |
| OOS | 1 tuần kế tiếp (`--select 7`) | chấm lại các ứng viên, chọn **tham số ổn định** = ứng viên có `min(Sharpe IS, Sharpe OOS)` cao nhất (`stable_pick`) |
| Forward | 1 tuần kế tiếp nữa (`--test 7`) | áp tham số tại giá đầu tuần và đo hiệu suất; chưa từng dùng để chọn nên là phép thử sạch |

540 ngày dữ liệu cho **72 fold/cặp** (trước đây 15). So sánh trên cùng tuần forward: tham số ổn định, tham số phẳng, đỉnh nhọn (IS top-1), lưới mặc định ±10%/n=20, B&H, và DGT. Test chống rò rỉ: đổi giá từ tuần forward trở đi thì tham số fold 0 không đổi; đổi giá trong tuần OOS thì tham số ổn định có thể đổi còn đỉnh nhọn thì không.

**Tham số phẳng (STEP 6):** `smooth_pick` làm mượt Sharpe bằng trung bình lân cận 3×3 trên (dl, dh) với cùng (n, mode), chỉ xét ô có ≥ 5 ô hợp lệ quanh nó; `stability` báo median/IQR của dl, dh, bước% qua fold và cờ UNSTABLE (ngưỡng `UNSTABLE_IQR`, cần hiệu chỉnh). `DEFAULT_PICK = "stable"`.

**DGT (STEP 7):** `dgt_equity(prices, dl, dh, n, mode, fee)` dựng lại lưới quanh giá mới khi giá phá low/high, vốn mới = equity hiện tại; phá trên thì đang toàn tiền mặt, phá dưới thì đang giữ toàn coin; trả phí tái cân bằng mỗi lần reset. Khi không bao giờ phá biên, DGT trùng khít grid thường (có test).

**Bảng forward, Sharpe trung vị mỗi tuần (annualized, 72 fold/cặp):**

| Chiến lược | BTC | ETH | PAXG | XAUT |
|---|---|---|---|---|
| Buy & Hold | −0.67 | 0.29 | 1.63 | 1.89 |
| Grid cố định mặc định (±10%, n=20) | 0.31 | 1.22 | 2.10 | 2.17 |
| Grid đỉnh nhọn (IS top-1) | 2.43 | 1.73 | 2.75 | 2.65 |
| Grid phẳng | 2.15 | 2.13 | 3.31 | 3.24 |
| **Grid ổn định (IS → OOS)** | **2.62** | 1.80 | 3.11 | 2.99 |
| DGT (tham số ổn định) | −0.06 | 0.08 | 0.34 | 0.27 |

Sharpe IS của tham số ổn định 3.1–3.3 giảm còn 1.8–3.1 ở tuần forward (mức lạc quan của in-sample). Tỷ lệ tuần lãi (ổn định / B&H): BTC 61% / 47%, ETH 65% / 50%, PAXG 69% / 61%, XAUT 68% / 61%. Tham số ổn định không hơn phẳng ở ETH/PAXG/XAUT; chênh lệch nằm trong nhiễu. DGT thua grid cố định vì reset khóa vị thế ở giá phá biên và trả thêm phí.

**Thống kê (STEP 8):** `block_bootstrap_sharpe` (khối 1 ngày, 2000 lần) cho CI 95% của Sharpe OOS gộp các tuần forward; `deflated_sharpe` trả PSR(0) và DSR theo số tổ hợp thử (2200 crypto, 1408 vàng) và phương sai Sharpe giữa các thử nghiệm.
Sharpe gộp (tham số ổn định) [CI 95%] vs B&H: BTC −0.66 [−2.31, 1.01] vs −0.34; ETH +0.12 [−1.50, 1.86] vs +0.23; PAXG −0.14 [−1.55, 1.31] vs +0.73; XAUT −0.26 [−1.72, 1.23] vs +0.74. CI của hiệu grid − B&H chứa 0 ở cả 4 cặp (vàng sát biên: [−2.85, 0.25] và [−2.99, 0.20]). PSR(0) 0.22–0.56; DSR 0.00–0.07.
**Sharpe gộp (≈ 0) thấp hơn nhiều so với trung vị tuần (1.8–3.1):** đa số tuần lãi nhỏ (return trung vị +0.1%) nhưng vài tuần lỗ lớn (thấp nhất −7% đến −8%); phân phối lệch âm nên trung vị không phản ánh phần đuôi.
Độ nhạy (Sharpe forward trung vị, tham số ổn định):

| Cấu hình | BTC | ETH | PAXG | XAUT |
|---|---|---|---|---|
| Phí 0.5× | 2.99 | 2.01 | 3.73 | 3.26 |
| Phí 1× | 2.62 | 1.80 | 3.11 | 2.99 |
| Phí 2× | 2.01 | 1.35 | 1.25 (60 fold) | 1.42 (61 fold) |
| 5m | 3.44 | 2.54 | 2.85 | 2.97 |
| 15m | 2.62 | 1.80 | 3.11 | 2.99 |
| 1h | 1.78 | 1.31 | 1.77 | 1.50 |

Phí cao làm giảm ở mọi cặp, mạnh nhất ở vàng (phí 2× đòi bước ≥ 0.8% nên 11–12 tuần không còn tổ hợp nào qua bộ lọc và bị bỏ qua). Nến thưa hơn làm giảm Sharpe ở crypto (5m > 15m > 1h), phù hợp với việc dùng giá close bỏ sót các lần cắt line trong nến. Không cấu hình nào đảo kết luận chung.

**Tóm tắt cuối (STEP 9, `results/summary.csv`)**: IS 28d / OOS 7d / forward 7d, phí 0.1%, 72 fold/cặp, tham số ổn định.

| Cặp | Sharpe gộp [CI 95%] | Return gộp | B&H | MDD | MDD B&H | Tuần lãi | Khuyến nghị dl / dh / n / bước% / mode | Cờ |
|---|---|---|---|---|---|---|---|---|
| BTC | −0.66 [−2.31, 1.01] | −17.8% | −26.9% | −34.0% | −55.7% | 61% | 5% / 8% / 8 / 1.62% / geometric | UNSTABLE |
| ETH | +0.12 [−1.50, 1.86] | −1.2% | −6.0% | −36.3% | −71.4% | 65% | 25% / 5% / 20 / 1.70% / geometric | UNSTABLE |
| PAXG | −0.14 [−1.55, 1.31] | −4.6% | +23.9% | −20.7% | −30.8% | 69% | 8% / 0.25% / 8 / 1.08% / geometric | UNSTABLE |
| XAUT | −0.26 [−1.72, 1.23] | −6.5% | +23.6% | −19.5% | −30.5% | 68% | 8% / 0.25% / 8 / 1.08% / geometric | UNSTABLE |

**Kết luận (trên lõi đã sửa):**
- Grid **giảm drawdown rõ rệt** (MDD forward thấp hơn B&H ở cả 4 cặp) và **lãi ở đa số tuần** (61–69% so với 47–61% của B&H).
- Trong giai đoạn thị trường giảm (BTC/ETH) grid lỗ ít hơn B&H; trong giai đoạn vàng tăng (+24%) grid **thua B&H nhiều** vì bán sớm khi giá lên.
- **Chưa có bằng chứng thống kê về edge:** CI 95% của Sharpe gộp chứa 0 ở cả 4 cặp, CI của hiệu so với B&H cũng chứa 0; DSR thấp.
- **Range bị tối ưu lệch rất mạnh:** `dh` trung vị chỉ 1.3–2% trong khi `dl` 5–25% (khuyến nghị vàng là `dh` = 0.25%, giá trị nhỏ nhất của không gian tìm kiếm). Lưới chủ yếu mua khi giá giảm và bán nhanh khi giá nhích lên, nên bỏ lỡ đà tăng. Bộ lọc bước chưa chặn kiểu range này (chưa có ràng buộc độ rộng/dh tối thiểu).
- Tham số khuyến nghị chỉ để thử nghiệm: cờ UNSTABLE, tham số đổi nhiều giữa các tuần.

**Trần số lưới:** `--max-grids N` (mặc định `MAX_GRIDS = 100`, cần xác minh trong app Bitget) lọc `n ≤ N` ở mọi bước (sweep, walk-forward, stats, pipeline cuối). Không gian tìm kiếm quét `n ∈ {4, 6, 8, 10, 15, 20, 30, 40, 60, 80, 100}`; `n` khuyến nghị hiện là 6–20, nên trần 100 không phải ràng buộc đang cắn.

**Hàm lõi:** `load_ohlcv`, `grid_sim` / `grid_equity` / `grid_stats`, `metrics`, `buy_and_hold`, `sweep`, `smooth_pick`, `stable_pick`, `walk_forward`, `dgt_equity`, `block_bootstrap_sharpe`, `deflated_sharpe`.

**Chạy song song:** các fold độc lập nên `walk_forward` chạy bằng `ProcessPoolExecutor` (`--jobs N`, mặc định `min(8, số lõi)`, tối đa 8; `--jobs 1` chạy tuần tự). Kết quả y hệt tuần tự (có test). Walk-forward 72 fold của một cặp: 66 giây → 8 giây, trong đó phần lớn tăng tốc đến từ việc viết lại `smooth_pick` bằng NumPy (23.6 giây trên 1 tiến trình).

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
- [x] **STEP 5** Walk-forward: IS 28d tìm tham số tối ưu → OOS 7d chọn tham số ổn định → forward 7d đo hiệu suất, trượt 7d (72 fold); `results/{symbol}_folds.csv`; test không rò rỉ
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
- **Ràng buộc thiết kế:** dự án không mô hình hành vi riêng của bot khi range hẹp + nhiều lưới. Thay vào đó, tối ưu chỉ xét cấu hình có **bước nhỏ nhất ≥ 2·fee·hệ số an toàn** (mặc định 0.4% với phí 0.1%), áp ở mọi đường (sweep, walk-forward, DGT, khuyến nghị cuối); range hẹp chỉ qua được khi có ít lưới (bước = range / n), nên không có cấu hình hẹp-và-dày nào được tối ưu.
- Position Grid: hệ thống tự chọn số lưới và range, không chỉnh tay (bot khác với bot ở đây).

## Giới hạn của kết quả

- Dùng giá close → số lần cắt lưới bị ước lượng thấp (bảo thủ); dùng high/low sẽ lạc quan. Không mô hình queue/slippage/độ trễ.
- Grid thuần không có kỳ vọng dương trên random walk (Chen et al.); kết quả tốt trên một giai đoạn có thể chỉ là drift/regime. Với 15 fold và một giai đoạn, CI rộng.
- Lệnh khớp được mô phỏng ở đúng giá line khi giá close cắt qua; không có trượt giá, queue hay độ trễ.
- PAXG, XAUT là token neo vàng: biến động thấp, phí/spread chi phối; cần kiểm tra thanh khoản thật. Không đòn bẩy.
- Phí Bitget và giới hạn số lưới là giả định cần xác minh.
