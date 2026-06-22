# Nhật ký thay đổi (Changelog)

Tất cả các thay đổi đáng chú ý đối với dự án **CryptoAgents** sẽ được ghi nhận tại đây.

Định dạng dựa trên [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), và dự án tuân thủ [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-06-18

### Khởi tạo dự án độc lập (Initial Release)
- Đổi tên dự án từ framework gốc sang **CryptoAgents**.
- Gỡ bỏ toàn bộ thương hiệu cũ, liên kết mã nguồn và hình ảnh liên quan đến tổ chức ban đầu.
- Cấu hình lại các biến môi trường và tối ưu hóa hỗ trợ trực tiếp Google Gemini API Key thông qua `GOOGLE_API_KEY`.
- Cố định và sửa đổi các lỗi kiểm thử unit test (`pytest tests/`) liên quan đến cách ly cấu hình và các kiểm tra luồng định lượng TensorFlow.
- Xác minh và bảo trì thành công toàn bộ 11 luồng dữ liệu (Yahoo Finance, TensorFlow Anomaly, LSTM Trend, News...).
