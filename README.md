# 🤖 CVHR — AI Agent Sơ vấn & Tối ưu CV Ứng viên

**CVHR** là hệ thống AI Agent tuyển dụng thông minh được xây dựng bằng kiến trúc **LangGraph State Machine** (tương tự đồ thị luồng xử lý của dự án `etax_kekhaithue`). Hệ thống tự động hóa toàn bộ quy trình: Parse thông tin CV thô $\rightarrow$ Đánh giá tương khớp CV vs JD $\rightarrow$ Xếp hạng level ứng viên $\rightarrow$ Phỏng vấn sơ vấn multi-turn (hỏi đáp) qua CLI $\rightarrow$ Chấm điểm chi tiết $\rightarrow$ Đề xuất lộ trình 6 tháng cải thiện CV.

Dự án này được thiết kế như một giáo trình thực tế giúp lập trình viên học tập và làm chủ các công cụ **LangGraph, Langfuse, và LangSmith**.

---

## 🚀 Tính năng nổi bật

### 1. LangGraph State Machine (Đồ thị Trạng thái)
Quản lý luồng tương tác thông minh qua 10 Nodes chuyên biệt và các Cạnh điều hướng có điều kiện (Conditional Edges). Trạng thái phiên phỏng vấn được lưu trữ liên tục (state persistence) thông qua `MemorySaver` checkpointer, hỗ trợ ngắt luồng (`interrupt`) chờ ứng viên trả lời và khôi phục (`resume`) cực kỳ mượt mà.

### 2. Kỹ nghệ Gợi ý Cao cấp (Prompt Engineering)
Toàn bộ hệ thống prompt được tối ưu hóa theo tiêu chuẩn **Prompt Engineer Master** (chỉ dẫn [SKILL.md](file:///C:/Projects/SKILL.md)):
*   **Dual Process Theory (Lập luận chậm):** Ép buộc mô hình suy nghĩ logic, đối chiếu dữ liệu trong thẻ `<thought>` trước khi đưa ra kết quả.
*   **Kiến trúc chống ảo tưởng 5 lớp (Layered Anti-Hallucination):** Giới hạn tri thức nghiêm ngặt trong CV/JD, bắt buộc trích dẫn nguồn bằng chứng trực tiếp từ CV gốc (Layer 2), gán giá trị mặc định khi thiếu thông tin (Layer 3), và tự soát lỗi (Layer 5).
*   **Phòng thủ đối kháng (Adversarial Defense):** Chống tấn công override chỉ thị (jailbreak) chèn ẩn trong tệp tin CV hoặc trong câu trả lời của ứng viên.

### 3. Đánh giá & Chấm điểm động (Dynamic Scoring)
*   **Cá nhân hóa câu hỏi:** Bộ câu hỏi (5-7 câu) được thiết kế riêng biệt dựa trên khoảng trống kỹ năng (weaknesses) của ứng viên so với JD.
*   **Chỉnh điểm theo Rank:** Cùng một đáp án lý thuyết cơ bản, ứng viên Fresher có thể đạt 7-8/10 nhưng Senior chỉ đạt 4-5/10 (vì kỳ vọng đối với Senior cần bao gồm phân tích trade-offs và kinh nghiệm thực tiễn).
*   **Chấm điểm ngữ nghĩa (Semantic matching):** LLM tự động suy luận để đối chiếu câu trả lời với `expected_keywords` thay vì so khớp ký tự cứng nhắc.

---

## 📂 Cấu trúc thư mục dự án

```text
C:\Projects\CVHR\
├── config/
│   └── settings.py          # Quản lý cấu hình bằng Pydantic Settings V2 (chống warnings)
├── core/
│   ├── parser.py            # Trích xuất văn bản thô từ file CV PDF (pdfplumber) hoặc TXT
│   └── graph.py             # Định nghĩa Graph: State, 10 Nodes, Edges, luồng validation & exception
├── prompts/
│   ├── cv_analysis.py       # Prompt phân tích CV vs JD & Trích xuất cấu trúc CV (JSON)
│   ├── interview.py         # Prompt sinh câu hỏi phỏng vấn & chấm điểm từng câu
│   ├── cv_improvement.py    # Prompt của Subagent Career Coach viết roadmap cải thiện CV
│   └── ranking.py           # Prompt xếp hạng trình độ ứng viên (IT & Non-IT)
├── memory/
│   └── checkpointer.py      # Bộ lưu trữ trạng thái phiên (MemorySaver)
├── services/
│   ├── subagent/            # Chứa subagent chuyên sâu (Phase 3)
│   └── tools/               # Chứa các tool xuất PDF, cào thông tin (Phase 3)
├── tests/
│   ├── conftest.py          # Cấu hình môi trường mock test và dữ liệu mẫu
│   ├── test_parser.py       # Test bộ trích xuất PDF/TXT
│   ├── test_ranking.py      # Test hàm build prompt xếp hạng
│   └── test_graph_flow.py   # Test logic điều hướng, xử lý chuỗi và validate input của Graph
├── data/
│   ├── sample_cvs/          # CV mẫu dạng text để chạy thử
│   └── sample_jds/          # JD mẫu dạng text để đối chiếu
├── README.md                # Tài liệu hướng dẫn sử dụng dự án
├── requirements.txt         # Thư viện phụ thuộc
└── main.py                  # Entrypoint: Giao diện Terminal CLI tương tác từng bước
```

---

## 🛠 Hướng dẫn cài đặt & Chạy thử nghiệm

### 1. Cài đặt môi trường
Yêu cầu hệ thống cài đặt sẵn Python 3.10 trở lên.
```bash
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo (Windows)
.venv\Scripts\activate

# Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

### 2. Cấu hình biến môi trường
Tạo file `.env` từ file `.env.example` và thiết lập các API key:
```ini
# Gemini API Key (Bắt buộc để chạy thật)
GOOGLE_API_KEY=AIzaSy...

# Cấu hình tracing Langfuse (Tùy chọn)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# Cấu hình tracing LangSmith (Tùy chọn)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=cvhr-agent
```

### 3. Chạy tương tác phỏng vấn sơ vấn qua Terminal CLI
Chạy lệnh khởi động giao diện CLI và tương tác từng bước:
```bash
python main.py
```
*   **Bước 1:** Kéo thả trực tiếp file CV (PDF/TXT) hoặc nhập đường dẫn file CV (ví dụ: `data\sample_cvs\cv_nguyen_van_minh.txt`) vào terminal và nhấn Enter.
*   **Bước 2:** Nhập đường dẫn file JD (PDF/TXT) bằng cách kéo thả file JD vào terminal, hoặc bạn có thể dán trực tiếp nội dung văn bản JD (nhấn Enter 2 lần để kết thúc nhận văn bản).
*   **Bước 3:** AI sẽ tự động phân tích CV, phân loại lĩnh vực, xếp hạng level và sinh bộ câu hỏi.
*   **Bước 4:** Trả lời trực tiếp từng câu hỏi hiển thị trên console. Hệ thống tự chấm điểm và đưa ra nhận xét động.
*   **Bước 5:** Nhận tổng kết quyết định tuyển dụng (PASS/CONSIDER/FAIL) và báo cáo tối ưu hóa CV.

### 4. Chạy bộ kiểm thử (Unit Tests)
Dự án được tích hợp sẵn 10 test cases giả lập môi trường giúp kiểm tra nhanh cấu trúc đồ thị, tính năng lọc câu trả lời spam/rỗng, bóc tách JSON và các hàm nghiệp vụ khác mà không tốn tokens API:
```bash
pytest tests/ -v
```

---

## 📈 Kế hoạch phát triển tiếp theo (Phase 3 & 4)
*   **Phase 3:** Triển khai subagent độc lập `cv_improve_agent` để phân tích sâu kỹ năng; tích hợp thư viện `reportlab` trong `pdf_generator.py` xuất báo cáo chuyên nghiệp gửi về email cho HR; viết công cụ cào thông tin JD từ link URL.
*   **Phase 4:** Phát triển FastAPI server và các API Endpoint SSE (Server-Sent Events) để phát trực tiếp luồng stream chat về giao diện Web Client (React/Next.js).
