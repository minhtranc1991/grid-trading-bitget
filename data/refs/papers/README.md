# Papers tham chiếu (bản sao cục bộ)

Tải từ arXiv và trang cá nhân của tác giả ngày 2026-10-15/16, dùng làm tài liệu đối chiếu cho dự án. Mỗi file đã mở kiểm tra tiêu đề trang đầu.

## Về grid trading

| File | Bài báo | Nguồn |
|---|---|---|
| `chen_2025_dynamic_grid_trading_2506.11921.pdf` | Chen, Chen, Jang. *Dynamic Grid Trading Strategy: From Zero Expectation to Market Outperformance* (2025) | https://arxiv.org/abs/2506.11921 |
| `yeh_2022_flexible_grid_trading_ann_sso_2211.12839.pdf` | Yeh, Hsieh, Huang. *Newly Developed Flexible Grid Trading Model Combined ANN and SSO algorithm* (2022) | https://arxiv.org/abs/2211.12839 |

Mã nguồn đi kèm bài Chen (chưa tải): https://github.com/colachenkc/Dynamic-Grid-Trading

## Về chọn tham số và chống overfit (IS/OOS)

| File | Bài báo | Nguồn | Dùng cho |
|---|---|---|---|
| `bailey_2017_probability_of_backtest_overfitting.pdf` | Bailey, Borwein, López de Prado, Zhu. *The Probability of Backtest Overfitting* (J. Computational Finance, 2017) | https://papers.ssrn.com/abstract=2326253 | PBO qua CSCV, độ suy giảm hiệu suất, xác suất lỗ, trội ngẫu nhiên |
| `bailey_lopezdeprado_2014_deflated_sharpe_ratio.pdf` | Bailey, López de Prado. *The Deflated Sharpe Ratio* (2014) | https://papers.ssrn.com/abstract=2460551 | PSR, DSR (đã dùng ở STEP 8) |
| `nguyen_2026_algoxpert_is_wfa_oos_protocol_2603.09219.pdf` | Nguyen, Nguyen, Pham. *AlgoXpert Alpha Research Framework: A Rigorous IS–WFA–OOS Protocol for Mitigating Overfitting in Quantitative Strategies* (2026) | https://arxiv.org/abs/2603.09219 | Vùng ổn định (≥ 90% tốt nhất), cliff veto, xếp hạng bằng Calmar, tỷ lệ chống chịu η |
| `jacquier_muhlekarbe_mulligan_2025_overfitting_signals_2501.03938.pdf` | Jacquier, Muhle-Karbe, Mulligan. *In-Sample and Out-of-Sample Sharpe Ratios for Linear Predictive Models* (2025) | https://arxiv.org/abs/2501.03938 | Mức suy giảm Sharpe IS → OOS theo số tín hiệu và độ dài dữ liệu |

Chưa tải được (không công khai): Wu, Lin, Huang, Wu. *On the design of searching algorithm for parameter plateau in quantitative trading strategies using particle swarm optimization*, Knowledge-Based Systems 293 (2024) 111630, https://www.sciencedirect.com/science/article/abs/pii/S095070512400265X (plateau score; bài báo trả phí).

## Chỉ số và cách chọn tham số trong từng bài (đọc từ bản PDF/HTML)

**Chen et al. 2025**
- Chỉ số: IRR (lợi suất năm hóa) là chính, thêm MDD khi so với buy & hold. Không dùng Sharpe/Sortino/Calmar.
- Tham số: không tối ưu theo một hàm mục tiêu; quét tổ hợp (grid size k, grid numbers half) rồi vẽ heatmap IRR. Không tách train/test.
- Phí 0.0008 (OKX maker). Dữ liệu 1 phút Binance, BTC và ETH, 2021-01 đến 2024-07.
- Tác giả lưu ý IRR cao phần lớn nhờ đà tăng giá crypto trong giai đoạn đó.

**Yeh et al. 2022**
- Hàm mục tiêu của SSO (mục 3.3.1, Eq. 15): tối đa hóa lợi suất đầu tư (giá trị cuối kỳ của coin + tiền).
- Ràng buộc: Eq. 16 `g_{i+1} − g_i > h·g_{i+1}`; Eq. 17–19: biên trên `P0·105% < Gul < P0·130%` (thí nghiệm 2: 150%), biên dưới `P0·70% < Gll < P0·95%` (thí nghiệm 2: 50%), số lưới mỗi phía từ 10. Tức là **cả hai phía đều có tối thiểu 5%**, để tránh range hẹp và overfit.
- Chỉ số đánh giá: ROI, MDD, volatility, Sharpe ratio.
- Nhận xét của tác giả: phương pháp có ROI lớn hơn thì MDD cũng cao hơn.

**Bailey et al. 2017 (PBO)**
- CSCV: chia dữ liệu thành S phần, xét mọi cách chọn S/2 phần làm IS; với mỗi cách, lấy cấu hình tốt nhất ở IS, đo thứ hạng tương đối ω của nó ở OOS, logit λ = ln(ω / (1 − ω)).
- **PBO = tỷ lệ các cách chia có λ < 0** (cấu hình IS-tốt-nhất kém hơn trung vị OOS).
- Chẩn đoán đi kèm: suy giảm hiệu suất (hồi quy OOS theo IS), xác suất lỗ Prob[R_OOS < 0], trội ngẫu nhiên bậc 1 so với chọn ngẫu nhiên.

**AlgoXpert 2026** (đọc qua tóm tắt công cụ, một phần văn bản gốc; cần đối chiếu PDF khi dùng)
- Vùng ổn định `Ω = {θ : SR(θ) ≥ 0.9·SR_opt}`; xếp hạng trong vùng bằng Calmar, recovery factor, mức lỗ tệ nhất theo cửa sổ (không bằng Sharpe).
- Cliff veto: loại cấu hình mà láng giềng ±1 bước kém hơn nhiều (CliffSR, CliffDD).
- Chẩn đoán IS → OOS: ΔSR = SR_test − SR_train và η = SR_test / SR_train.
- Hướng tới chiến lược có trạng thái/phụ thuộc đường đi (grid, trailing, inventory).
