# HoYoLAB Multi-Account Toolkit

Ứng dụng web cục bộ giúp quản lý nhiều tài khoản HoYoverse (Genshin Impact, Honkai: Star Rail, Zenless Zone Zero):
- **Quản lý đa tài khoản:** Thêm/sửa/xóa tài khoản, tự động đọc UID, Level, số điểm HoYoLAB Mimo.
- **Nạp Giftcode tự động:** Tự động thu thập mã quà livestream/sự kiện mới nhất và nạp lần lượt vào game (chống rate-limit).
- **Đổi quà HoYoLAB Mimo:** Tự động gom quà trong shop Mimo (Primogem, Mora, Sách EXP, Khung avatar...).
- **Canh giờ Restock tài nguyên (Sniper Mode):** Tự động đếm ngược đến giờ mở bán, thức dậy trước 5s và giật quà ngay khi mở kho.

---

## Cách Khởi Chạy

Nhấp đúp chuột vào file:
👉 **`run_ui.bat`**

Trình duyệt sẽ tự động mở trang quản lý tại địa chỉ: `http://127.0.0.1:8000`

---

## Cấu Trúc Thư Mục

- `run_ui.bat`: File 1-click khởi động ứng dụng trên Windows.
- `app_ui.py`: Backend xử lý nghiệp vụ (FastAPI + Server-Sent Events).
- `web/index.html`: Giao diện người dùng Dark Mode (Tailwind CSS).
- `requirements.txt`: Các thư viện Python cần thiết (`genshin`, `fastapi`, `uvicorn`).
- `.gitignore`: Chặn commit các file chứa cookie nhạy cảm (`accounts.json`).
