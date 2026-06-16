"""
tests/conftest.py — Cấu hình pytest fixtures cho CVHR.
"""

import os
import pytest

# Thiết lập môi trường test giả lập để không bị thiếu biến môi trường bắt buộc
os.environ["GOOGLE_API_KEY"] = "mock-key-for-testing"
os.environ["API_HOST"] = "127.0.0.1"
os.environ["API_PORT"] = "8000"


@pytest.fixture
def sample_cv_text() -> str:
    """Fixture cung cấp nội dung CV mẫu dạng text thô."""
    return """
    HỌ TÊN: Nguyễn Văn Minh
    EMAIL: minh.nguyen@email.com
    SĐT: 0987654321
    HỌC VẤN: Đại học Công nghệ - ĐHQGHN (2020 - 2024), GPA: 3.6/4
    KINH NGHIỆM:
    - Công ty AI Tech (06/2023 - 06/2024): Vị trí Backend Developer Intern.
      + Phát triển hệ thống API sử dụng Python, FastAPI và PostgreSQL.
      + Dockerize ứng dụng để triển khai lên môi trường staging.
    KỸ NĂNG: Python, FastAPI, SQL, Docker, Git.
    DỰ ÁN:
    - E-commerce App: Xây dựng giỏ hàng và thanh toán bằng Node.js và MongoDB.
    """


@pytest.fixture
def sample_jd_text() -> str:
    """Fixture cung cấp mô tả công việc (JD) mẫu."""
    return """
    VỊ TRÍ: Python Backend Developer (Junior)
    MÔ TẢ CÔNG VIỆC:
    - Phát triển API backend hiệu năng cao bằng Python (FastAPI/Django).
    - Thiết kế và tối ưu hóa cơ sở dữ liệu PostgreSQL.
    YÊU CẦU:
    - Có tối thiểu 1 năm kinh nghiệm làm việc với Python.
    - Hiểu biết về Docker và hệ thống CI/CD là lợi thế.
    - Biết sử dụng Git để làm việc nhóm.
    """


@pytest.fixture
def sample_cv_structured() -> dict:
    """Fixture cung cấp dữ liệu CV đã được cấu trúc hóa."""
    return {
        "name": "Nguyễn Văn Minh",
        "email": "minh.nguyen@email.com",
        "phone": "0987654321",
        "summary": None,
        "education": [
            {
                "school": "Đại học Công nghệ - ĐHQGHN",
                "degree": "Cử nhân",
                "year_start": 2020,
                "year_end": 2024,
                "gpa": 3.6
            }
        ],
        "experience": [
            {
                "company": "Công ty AI Tech",
                "title": "Backend Developer Intern",
                "year_start": 2023,
                "year_end": 2024,
                "duration_months": 12,
                "description": "Phát triển hệ thống API sử dụng Python, FastAPI và PostgreSQL.",
                "technologies": ["Python", "FastAPI", "PostgreSQL", "Docker"]
            }
        ],
        "skills": ["Python", "FastAPI", "SQL", "Docker", "Git"],
        "certifications": [],
        "languages": [],
        "projects": [
            {
                "name": "E-commerce App",
                "description": "Xây dựng giỏ hàng và thanh toán.",
                "technologies": ["Node.js", "MongoDB"],
                "role": "Backend Developer"
            }
        ]
    }
