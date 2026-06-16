"""
tests/test_ranking.py — Unit tests cho logic xếp hạng ứng viên.
"""

import json
from prompts.ranking import build_ranking_prompt


def test_build_ranking_prompt(sample_cv_structured: dict, sample_jd_text: str):
    """Kiểm tra xem hàm build prompt ranking hoạt động đúng cấu trúc."""
    cv_str = json.dumps(sample_cv_structured, ensure_ascii=False)
    prompt = build_ranking_prompt(cv_structured=cv_str, jd_text=sample_jd_text)

    # Đảm bảo prompt chứa đầy đủ các thông tin cốt lõi
    assert "Bạn là Chuyên gia Kỹ nghệ Gợi ý" in prompt
    assert "Nguyễn Văn Minh" in prompt
    assert "Python Backend Developer" in prompt
    assert "KIẾN TRÚC CHỐNG ẢO TƯỞNG 5 LỚP" in prompt
