# Papers tham chiếu (bản sao cục bộ)

Tải từ arXiv ngày 2026-10-15, dùng làm tài liệu tham khảo cho dự án.

| File | Bài báo | Nguồn |
|---|---|---|
| `chen_2025_dynamic_grid_trading_2506.11921.pdf` | Chen, Chen, Jang. *Dynamic Grid Trading Strategy: From Zero Expectation to Market Outperformance* (2025) | https://arxiv.org/abs/2506.11921 |
| `yeh_2022_flexible_grid_trading_ann_sso_2211.12839.pdf` | Yeh, Hsieh, Huang. *Newly Developed Flexible Grid Trading Model Combined ANN and SSO algorithm* (2022) | https://arxiv.org/abs/2211.12839 |

Mã nguồn đi kèm bài Chen (chưa tải): https://github.com/colachenkc/Dynamic-Grid-Trading

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
