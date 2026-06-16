"""
tests/test_parser.py — Unit tests cho module core/parser.py.
"""

from pathlib import Path
import pytest
from core.parser import parse_text_file, parse_pdf


def test_parse_text_file(tmp_path: Path):
    """Kiểm tra đọc file text bình thường."""
    test_file = tmp_path / "test_cv.txt"
    content = "Họ tên: Nguyễn Văn Minh\nKỹ năng: Python"
    test_file.write_text(content, encoding="utf-8")

    parsed = parse_text_file(test_file)
    assert "Nguyễn Văn Minh" in parsed
    assert "Python" in parsed


def test_parse_text_file_not_found():
    """Kiểm tra báo lỗi khi file không tồn tại."""
    with pytest.raises(FileNotFoundError):
        parse_text_file("duong/dan/khong/ton/tai.txt")


def test_parse_pdf_invalid_extension(tmp_path: Path):
    """Kiểm tra báo lỗi khi file không phải đuôi .pdf."""
    invalid_file = tmp_path / "cv_file.docx"
    invalid_file.write_text("dummy", encoding="utf-8")
    with pytest.raises(ValueError, match="File không phải PDF"):
        parse_pdf(invalid_file)

