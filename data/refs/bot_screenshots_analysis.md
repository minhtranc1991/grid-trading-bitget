# Phân tích 10 ảnh bot Bitget thật (chụp 2026-10-16 09:36)

5 bot grid spot đang chạy, mỗi bot 2 màn hình (Tổng quan, Thông số). Các số dưới đây đọc trực tiếp từ ảnh; phần "tính" là suy ra từ tham số trong ảnh.

## Dữ liệu từ ảnh

| Bot | Vốn | Giá bắt đầu | Phạm vi | Số lưới | Coin mỗi lưới | Lệnh mở | Phí dự trữ (USDT) | Lưới | Chưa ghép | Tổng | Chạy |
|---|---|---|---|---|---|---|---|---|---|---|---|
| XAUT #1 | 75 | 4,116.98 | 3,978 – 4,448 | 27 | 0.0006 | 27 | 0.644 | +2.63 (+3.51%) | −2.13 (−2.84%) | +0.51 | 72 ngày |
| ETH | 225 | 2,315.15 | 2,258 – 2,580 | 14 | 0.0062 | 14 | 1.721 | +31.27 (+13.89%) | −34.27 (−15.24%) | −3.00 | 160 ngày |
| BTC | 225 | 80,222.96 | 73,392 – 92,739 | 34 | 0.000082 | 34 | 0.753 | +18.26 (+8.11%) | −4.12 (−1.84%) | +14.14 | 160 ngày |
| XAUT #2 | 75 | 4,699.80 | 3,918 – 4,448 | 31 | 0.0005 | 31 | 0.633 | +3.88 (+5.18%) | −8.80 (−11.73%) | −4.91 | 160 ngày |
| PAXG | 150 | 4,705.80 | 3,932 – 4,441 | 30 | 0.0011 | 30 | 0.812 | +8.01 (+5.34%) | −11.06 (−7.37%) | −3.04 | 160 ngày |

Tất cả: chế độ đặt lệnh "Hình học" (geometric), không trượt giá, không chốt lời/cắt lỗ, không điều kiện chấm dứt, HODL tắt, tự chuyển lợi nhuận bật, sau khi chấm dứt "bán cho tôi".

## Điều ảnh xác nhận về cơ chế

1. **Số lệnh mở bằng đúng số lưới** (27/27, 14/14, 34/34, 31/31, 30/30): mỗi slot có đúng một lệnh chờ, mua nếu nằm dưới giá, bán nếu nằm trên giá. Đây chính là mô hình slot trong `grid_sim`.
2. **Mỗi lưới cùng một lượng coin cố định** ("Số tiền mua mỗi lưới").
3. **Tổng lợi nhuận = lợi nhuận lưới + lợi nhuận chưa ghép** (2.63 − 2.13 = 0.50; 31.27 − 34.27 = −3.00; 18.26 − 4.12 = 14.14; 3.88 − 8.80 = −4.92; 8.01 − 11.06 = −3.05). Đây đúng là phép tách lưới/vị thế trong báo cáo.
4. **Bước lưới thực tế** (geometric, tính từ phạm vi và số lưới): XAUT 0.41%, ETH 0.96%, BTC 0.69%, PAXG 0.41%, nghĩa là bot vàng chạy sát ngưỡng lọc 0.4% của dự án.

## Bot không dùng hết USDT: USDT để lại làm gì

Cách chia vốn (tính từ giá bắt đầu và tham số, mô hình slot):

| Bot | Slot giữ coin lúc vào | Slot dự trữ USDT | Tỷ lệ vốn đã triển khai | Phần để lại |
|---|---|---|---|---|
| XAUT #1 | 19 | 8 | 88% | ~12% |
| ETH | 12 | 2 | 89% | ~11% |
| BTC | 22 | 12 | 98% | ~2% |
| XAUT #2, PAXG | không tính được: phạm vi hiện tại nằm dưới giá bắt đầu (xem dưới) | | | |

Có ba lớp "để lại":

1. **USDT được khóa sẵn cho lệnh mua ở mọi vạch dưới giá.** Bot chỉ mua coin ngay cho các slot nằm trên giá; phần còn lại giữ USDT, mỗi slot dưới giá có sẵn tiền ở vạch mua của nó. Nhờ vậy, khi giá sập xuyên lưới, từng vạch bị chạm khớp lệnh mua đã có tiền chứ không cần "mở thêm" lệnh. Tỷ lệ USDT trong "Vị thế hiện tại" là 43–63% khi giá nằm giữa phạm vi.
2. **Phí dự trữ** 0.3–0.9% vốn bằng USDT, cộng một lượng nhỏ coin (0.0001 XAUT, 0.0006 ETH, 0.000009 BTC) để trả phí hai chiều.
3. **Phần dư không phân bổ:** lượng coin mỗi lưới bị làm tròn xuống theo bước lot (n × lượng × giá bắt đầu chỉ bằng 89–104% vốn), nên lúc tạo bot triển khai khoảng 88–98% vốn; số dư và lãi giữ lại ở dạng USDT.

## Khi giá sập qua đáy lưới

- Đến đáy thì hết lệnh mua: bot đã mua đủ n slot, nằm giữ coin, USDT còn lại chỉ là phần dư (phí dự trữ, làm tròn, lãi), không đủ để mua thêm nhiều.
- **Muốn thêm lưới phía dưới phải sửa phạm vi/số lưới bằng tay** (nút bút chì trong "Thông số bot"). Hai bot vàng cho thấy điều này: giá bắt đầu 4,699.8 và 4,705.8 nhưng phạm vi hiện tại là 3,918 – 4,448 và 3,932 – 4,441, đỉnh phạm vi thấp hơn giá bắt đầu 5–6%, tức phạm vi đã được dời xuống sau khi giá giảm.
- Không có cắt lỗ: phần vị thế chưa ghép chịu toàn bộ đà giảm (XAUT #2 −11.7%, PAXG −7.4%, ETH −15.2% trên vốn).

## So với mô phỏng của dự án

| | Bot thật | Mô phỏng (tham số ổn định) |
|---|---|---|
| Lợi nhuận lưới / tuần (trên vốn) | 0.23% – 0.61% | 0.15% – 0.58% |
| Lợi nhuận chưa ghép / tuần | −0.08% đến −0.67% | −0.37% đến −1.28% |
| Số lưới | 14 – 34 | trung vị 6 (4 – 8) |
| Bước lưới | 0.41% – 0.96% | 1% – 2% |
| Độ rộng phạm vi | 12% – 26% | 3% – 14% |
| Chu kỳ khép kín / ngày | 1.6 – 2.0 (từ số lệnh trong ảnh lịch sử) | 0.14 – 0.29 (lưới mặc định ±10%, n=20: 0.8 – 1.6) |

Ghi chú: mô hình khớp bậc độ lớn của lợi nhuận lưới thật; nhưng tối ưu của dự án chọn lưới **thưa và hẹp** hơn hẳn các bot thật, và khớp ít hơn 5–10 lần.
