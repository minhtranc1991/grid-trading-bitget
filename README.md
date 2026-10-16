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

**Báo cáo trực quan:** `results/report.html` (tự đủ, mở bằng trình duyệt) được **tự động tạo lại sau mỗi lần chạy `grid_optimizer.py`** (tắt bằng `--no-report`); cũng có thể chạy riêng `python make_report.py`.
Các mục: 1 giá chuẩn hóa, 2 drawdown, 3 ATR(14) daily (% giá close), 4 phân phối lợi suất, 5 scatter regime theo ngày (NORMAL/STRESS: ngày lệch quá 1.5σ so với 30 ngày trước), 6 chỉ số B&H, 7 lợi suất theo tháng, 8 tương quan, 9 lịch fold thực tế (IS/OOS/forward), 10 tóm tắt tối ưu + walk-forward, 11 ý nghĩa thống kê và độ nhạy (giải thích dễ hiểu, thanh khoảng tin cậy), 12 kết luận và tham số khuyến nghị theo từng cặp, 13 lịch sử chạy.

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

**Mục tiêu tối ưu (`--objective`, mặc định `return`):** lợi suất thuần quy về một tuần (`ret_wk`) để so cửa sổ IS 4 tuần với OOS 1 tuần. Sharpe, Sortino, Calmar chỉ để tham khảo; có thể đổi sang `sharpe|sortino|calmar`. Xếp hạng trong sweep, tham số phẳng và tham số ổn định (`min(score IS, score OOS)`) đều theo mục tiêu này.

**Bảng forward, lợi suất trung vị mỗi tuần (72 fold/cặp, mục tiêu = lợi suất):**

| Chiến lược | BTC | ETH | PAXG | XAUT |
|---|---|---|---|---|
| Buy & Hold | −0.62% | +0.10% | **+0.77%** | **+0.71%** |
| Grid cố định mặc định (±10%, n=20) | +0.09% | **+0.49%** | +0.41% | +0.37% |
| Grid đỉnh nhọn (IS top-1) | +0.08% | +0.14% | +0.12% | +0.09% |
| Grid phẳng | +0.08% | +0.20% | +0.19% | +0.16% |
| Grid ổn định (IS → OOS) | +0.06% | +0.14% | +0.12% | +0.12% |
| DGT (tham số ổn định) | +0.02% | −0.07% | +0.03% | −0.01% |

Sharpe forward trung vị: ổn định 2.12 / 1.58 / 3.20 / 2.65, đỉnh nhọn 2.23 / 1.45 / 2.98 / 2.35, B&H −0.67 / 0.29 / 1.63 / 1.89. Tỷ lệ tuần lãi (ổn định): 62% / 61% / 65% / 65%.

**Phát hiện quan trọng: tối ưu lợi suất bị overfit nặng.** Lợi suất tuần trung vị của tham số ổn định ở IS là +1.03% / +1.92% / +0.67% / +0.61% nhưng chỉ còn +0.06% / +0.14% / +0.12% / +0.12% ở tuần forward (suy giảm ~80–95%). Đáng chú ý hơn, **lưới mặc định ±10%, n=20 không tối ưu còn cho lợi suất tuần cao hơn các cách chọn tối ưu** ở ETH, PAXG và XAUT. Tức là bước tối ưu hiện tại chưa tạo giá trị ngoài mẫu; cần cách chọn tham số bền vững hơn (xem `data/refs/papers/README.md`: PBO, vùng ổn định + cliff veto, tỷ lệ chống chịu OOS/IS).

So với lần chạy mục tiêu Sharpe: lợi suất gộp BTC −17.8% → −40.1%, ETH −1.2% → −28.4%, PAXG −4.6% → +3.6%, XAUT −6.5% → +2.2%. Mục tiêu lợi suất làm kết quả crypto **xấu đi** (chọn lưới giữ nhiều coin rồi gặp thị trường giảm), vàng nhỉnh hơn nhưng vẫn thua B&H rất xa.

**Thống kê (STEP 8):** `block_bootstrap_sharpe` (khối 1 ngày, 2000 lần) cho CI 95% của Sharpe gộp các tuần forward; `deflated_sharpe` trả PSR(0) và DSR theo số tổ hợp thử (2200 crypto, 1408 vàng).
Sharpe gộp (tham số ổn định) [CI 95%]: BTC −1.22 [−2.80, 0.46]; ETH −0.36 [−2.05, 1.40]; PAXG +0.23 [−1.25, 1.76]; XAUT +0.18 [−1.35, 1.75]. CI của hiệu grid − B&H chứa 0 ở cả 4 cặp (BTC [−2.33, 0.83], ETH [−2.47, 1.00], PAXG [−2.56, 0.45], XAUT [−2.68, 0.33]). Độ nhạy phí và khung nến xem mục 11 của báo cáo.

**Tóm tắt cuối (STEP 9, `results/summary.csv`)**: IS 28d / OOS 7d / forward 7d, phí 0.1%, 72 fold/cặp, mục tiêu lợi suất, tham số ổn định.

| Cặp | Return gộp | B&H | MDD | MDD B&H | Sharpe gộp [CI 95%] | Sortino (grid / B&H) | Calmar (grid / B&H) | Tuần lãi | Khuyến nghị dl / dh / n / bước% / mode |
|---|---|---|---|---|---|---|---|---|---|
| BTC | −40.1% | −26.9% | −48.6% | −55.7% | −1.22 [−2.80, 0.46] | −1.69 / −0.48 | −0.60 / −0.35 | 62% | 2% / 18% / 8 / 2.35% / geometric |
| ETH | −28.4% | −6.0% | −53.9% | −71.4% | −0.36 [−2.05, 1.40] | −0.51 / +0.34 | −0.38 / −0.06 | 61% | 5% / 12% / 8 / 1.90% / arithmetic |
| PAXG | +3.6% | +23.9% | −20.6% | −30.8% | +0.23 [−1.25, 1.76] | +0.32 / +1.00 | +0.13 / +0.56 | 65% | 8% / 0.5% / 8 / 1.11% / geometric |
| XAUT | +2.2% | +23.6% | −21.1% | −30.5% | +0.18 [−1.35, 1.75] | +0.24 / +1.02 | +0.08 / +0.56 | 65% | 8% / 0.5% / 10 / 0.89% / geometric |

**Kết luận (trên lõi đã sửa, mục tiêu lợi suất):**
- **Grid không vượt giữ coin về lợi nhuận ở cả 4 cặp**; ở BTC và ETH còn lỗ nhiều hơn B&H. Chỉ còn lợi thế là drawdown nhỏ hơn (MDD giảm ~7–18 điểm %).
- **Chưa có bằng chứng thống kê về edge:** CI 95% của Sharpe gộp chứa 0 ở cả 4 cặp, CI của hiệu so với B&H cũng chứa 0.
- **Vấn đề nằm ở bước chọn tham số**, không ở mô phỏng: tham số tối ưu theo lợi suất suy giảm ~80–95% từ IS sang forward và kém cả lưới mặc định chưa tối ưu.
- Range khuyến nghị cho vàng vẫn rất lệch (`dh` = 0.5%); tham số cờ UNSTABLE ở cả 4 cặp. Chỉ để thử nghiệm.

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
