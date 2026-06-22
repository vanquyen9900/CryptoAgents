# CryptoAgents: AI-Powered Multi-Agent Crypto & Stock Trading Framework

CryptoAgents là một framework giao dịch tài chính đa tác nhân (Multi-Agent) sử dụng LLM được xây dựng trên **LangGraph** và **Typer**. Hệ thống mô phỏng quy trình hoạt động của một quỹ đầu tư thực tế, nơi các tác nhân chuyên biệt phối hợp phân tích thị trường, nghiên cứu xu hướng, quản lý rủi ro và đưa ra quyết định giao dịch cuối cùng.

## Kiến trúc hệ thống (Core Architecture)

Hệ thống phân rã các tác vụ phức tạp thành nhiều vai trò chuyên biệt:
*   **Analyst Team (Nhóm phân tích):** 
    *   *Fundamentals Analyst:* Đánh giá chỉ số tài chính doanh nghiệp (tự động bỏ qua đối với Crypto).
    *   *Technical Analyst:* Phân tích các chỉ báo kỹ thuật (MACD, RSI, EMA...) để dự đoán chuyển động giá.
    *   *News Analyst:* Theo dõi tin tức vĩ mô toàn cầu và sự kiện kinh tế.
    *   *Sentiment Analyst:* Tổng hợp tâm lý thị trường từ Tin tức, Reddit và StockTwits.
*   **Researcher Team (Nhóm nghiên cứu):** Gồm *Bull Researcher* (tối ưu xu hướng tăng) và *Bear Researcher* (đánh giá rủi ro giảm giá) tranh biện và phản biện dưới sự điều phối của *Research Manager*.
*   **Trader Agent:** Tổng hợp dữ liệu từ các nhà phân tích và nghiên cứu để đề xuất lệnh giao dịch chi tiết.
*   **Risk & Portfolio Management (Quản lý danh mục & Rủi ro):** Đánh giá rủi ro danh mục và phê duyệt/từ chối giao dịch cuối cùng.

Hệ thống tích hợp các mô hình học sâu **TensorFlow** (Autoencoder phát hiện bất thường và LSTM dự báo xu hướng) đóng vai trò là tầng định lượng hỗ trợ các tác nhân LLM đưa ra quyết định chính xác hơn.

---

## Hướng dẫn cài đặt (Installation)

### Yêu cầu hệ thống:
*   Python từ 3.10 trở lên.
*   Hệ điều hành: Windows, macOS, hoặc Linux.

### Các bước cài đặt:
1.  **Tạo môi trường ảo (Virtual Environment):**
    ```bash
    python -m venv venv
    ```
2.  **Kích hoạt môi trường ảo:**
    *   Trên Windows (PowerShell):
        ```powershell
        .\venv\Scripts\Activate.ps1
        ```
    *   Trên macOS/Linux:
        ```bash
        source venv/bin/activate
        ```
3.  **Cài đặt các gói phụ thuộc:**
    ```bash
    pip install -e .
    ```

---

## Cấu hình (Configuration)

Tạo file `.env` ở thư mục gốc của dự án (sử dụng file `.env.example` làm mẫu) và điền API Key của nhà cung cấp LLM bạn sử dụng:

```env
# LLM Providers (Gán khóa API của nhà cung cấp bạn muốn dùng)
GOOGLE_API_KEY=AIzaSy...
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Cấu hình nguồn dữ liệu phụ trợ (Không bắt buộc, mặc định sử dụng Yahoo Finance miễn phí)
ALPHA_VANTAGE_API_KEY=
```

---

## Cách chạy dự án (Usage)

### 1. Giao diện Dòng lệnh Tương tác (Interactive CLI)
Đây là cách chạy trực quan nhất, cho phép bạn lựa chọn cấu hình phân tích trực tiếp:
```bash
python -m cli.main
```
Hoặc chạy trực tiếp bằng lệnh:
```bash
tradingagents
```

### 2. Chạy Programmatic Script (`main.py`)
Bạn có thể tự định nghĩa một script phân tích tự động bằng cách chỉnh sửa và chạy file `main.py`:
```bash
python main.py
```

### 3. Chạy qua Docker
Dự án được cấu hình sẵn môi trường Docker:
```bash
docker compose run --rm tradingagents
```

---

## Kiểm thử (Testing)
Chạy bộ kiểm thử để đảm bảo mọi luồng dữ liệu hoạt động bình thường:
```bash
pytest tests/
```
Hoặc kiểm tra kết nối dữ liệu:
```bash
python check_all_dataflows.py
```
