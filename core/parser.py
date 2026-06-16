"""
CV Parser — Parse PDF/DOCX files thành plain text.

Module này đảm nhiệm bước đầu tiên trong pipeline:
nhận file CV (PDF hoặc text) → trích xuất toàn bộ text thô.

Text thô sẽ được node_parse_cv gửi cho LLM để cấu trúc hóa
thành JSON (cv_structured).
"""

import io
from pathlib import Path


def parse_pdf(file_path: str | Path) -> str:
    """Đọc file PDF và trả về toàn bộ text.

    Sử dụng pdfplumber để extract text chính xác hơn pypdf,
    đặc biệt với các CV có layout phức tạp (bảng, cột).

    Args:
        file_path: Đường dẫn tới file PDF.

    Returns:
        Text thô trích xuất từ tất cả các trang.

    Raises:
        FileNotFoundError: Nếu file không tồn tại.
        ValueError: Nếu file không phải PDF hoặc không đọc được.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File không tồn tại: {file_path}")
    if file_path.suffix.lower() != ".pdf":
        raise ValueError(f"File không phải PDF: {file_path.suffix}")

    try:
        import pdfplumber
        pages_text = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            raise ValueError("PDF không chứa text (có thể là PDF dạng ảnh/scan).")
        return full_text

    except ImportError:
        # Fallback sang pypdf nếu pdfplumber chưa cài
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        pages_text = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            raise ValueError("PDF không chứa text (có thể là PDF dạng ảnh/scan).")
        return full_text


def parse_pdf_bytes(pdf_bytes: bytes) -> str:
    """Parse PDF từ bytes (cho trường hợp upload qua API).

    Args:
        pdf_bytes: Nội dung file PDF dạng bytes.

    Returns:
        Text thô trích xuất từ tất cả các trang.
    """
    try:
        import pdfplumber
        pages_text = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            raise ValueError("PDF không chứa text.")
        return full_text

    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            raise ValueError("PDF không chứa text.")
        return full_text


def parse_text_file(file_path: str | Path) -> str:
    """Đọc file text (.txt, .md) — dùng khi CV hoặc JD là plain text.

    Args:
        file_path: Đường dẫn tới file text.

    Returns:
        Nội dung text của file.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File không tồn tại: {file_path}")
    return file_path.read_text(encoding="utf-8")
