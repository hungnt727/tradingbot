# 📉 Chiến Lược Giao Dịch SonicR (SHORT Optimized)

## 1. Tổng Quan
Chiến lược SonicR tối ưu hóa cho vị thế **SHORT** (Bán khống) dựa trên sự kết hợp giữa các đường trung bình động hàm mũ (EMA) đa khung thời gian và chỉ báo sức mạnh tương đối (RSI) để xác định điểm đảo chiều xu hướng.

---

## 2. Thiết Lập Kỹ Thuật (Indicators)
- **EMA Stack (Xu hướng):** 
    - EMA 34, EMA 89, EMA 200, EMA 610.
- **RSI (Sức mạnh):**
    - RSI chu kỳ 14.
    - **EMA của RSI:** EMA 5, EMA 10, EMA 20 (Tính trên giá trị của đường RSI).
- **ATR (Biến động):**
    - Sử dụng để tính toán độ lớn nến và lọc nhiễu (Spike Filter).

---

## 3. Điều Kiện Vào Lệnh (SHORT Entry)
Một tín hiệu SHORT được kích hoạt khi:
1. **Xếp chồng EMA (Xu hướng Giảm):** 
    - `EMA 34 < EMA 89 < EMA 200 < EMA 610`.
2. **Xác nhận RSI (Động lực Giảm):**
    - `EMA_RSI 5 < EMA_RSI 10` VÀ `EMA_RSI 5 < EMA_RSI 20`.
3. **Bộ lọc Biến động (Spike Filter):**
    - Độ lớn cây nến (High - Low) phải nhỏ hơn **2.0 lần ATR**. Nếu nến quá dài (Spike), Bot sẽ bỏ qua để tránh rủi ro "đu đỉnh".
4. **Phát hiện Giao Cắt (Signal Trigger):**
    - Trạng thái (1) và (2) vừa chuyển từ **False** sang **True** trong vòng 5 nến gần nhất.
    - *Lưu ý: Chỉ bắn 1 lệnh duy nhất cho mỗi điểm giao cắt vật lý và mỗi cây nến 15 phút.*

---

## 4. Quản Lý Rủi Ro & Chốt Lời (Risk Management)
- **Cấu hình mặc định:**
    - **Stop Loss (SL):** 2.0% từ giá vào lệnh.
    - **Take Profit (TP):**
        - **TP1:** 2.0% (Chốt 50% khối lượng).
        - **TP2:** 4.0% (Chốt 50% khối lượng còn lại).
- **Dời Stop Loss:** 
    - Ngay khi **TP1** được khớp, Stop Loss của phần còn lại sẽ được dời về **điểm vào lệnh (Breakeven)**.

---

## 5. Cơ Chế Thoát Lệnh Đặc Biệt (Holding & Timeout)
- **Timeout (MAX_HOLDING):** 100 nến (tương đương 25 giờ trên khung 15m).
- **Quy tắc đóng lệnh:**
    - **Nếu đang LÃI (PnL > 0):** Đóng lệnh ngay lập tức sau 100 nến (`TIMEOUT_PROFIT`).
    - **Nếu đang LỖ (PnL < 0):** KHÔNG đóng lệnh. Tiếp tục giữ cho đến khi chạm SL, TP hoặc kịch khung dữ liệu (`Gồng lỗ có kiểm soát`).

---

## 6. Hiệu Suất Kỳ Vọng (Backtest Top 300 Coin)
- **Win Rate:** ~63% - 67%.
- **Tổng PnL:** ~700% - 1100% (trên 1000 nến khung 15m).
- **Đặc tính:** Tận dụng tốt các đợt sụt giảm mạnh của Altcoin, bảo vệ vốn cực tốt nhờ cơ chế Breakeven.
