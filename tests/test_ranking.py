"""
tests/test_ranking.py — Unit tests cho logic xếp hạng ứng viên và salary tools.
"""

import json
import pytest
from prompts.ranking import build_ranking_prompt
from services.tools.tool_api import search_job_market, search_web_for_jd


def test_build_ranking_prompt(sample_cv_structured: dict, sample_jd_text: str):
    """Kiểm tra xem hàm build prompt ranking hoạt động đúng cấu trúc."""
    cv_str = json.dumps(sample_cv_structured, ensure_ascii=False)
    prompt = build_ranking_prompt(cv_structured=cv_str, jd_text=sample_jd_text)

    assert "Bạn là Chuyên gia Kỹ nghệ Gợi ý" in prompt
    assert "Nguyễn Văn Minh" in prompt
    assert "Python Backend Developer" in prompt
    assert "KIẾN TRÚC CHỐNG ẢO TƯỞNG 5 LỚP" in prompt


@pytest.mark.parametrize("rank,field", [
    ("fresher", "it"),
    ("junior", "it"),
    ("mid", "marketing"),
    ("senior", "finance"),
    ("lead", "other"),
])
def test_search_job_market_valid(rank: str, field: str):
    """Kiểm tra search_job_market trả về JSON hợp lệ cho mọi rank/field."""
    result_json = search_job_market.invoke({
        "job_title": "Developer",
        "candidate_rank": rank,
        "field_category": field,
    })
    result = json.loads(result_json)
    assert "salary_range" in result
    assert result["salary_range"]["min"] > 0
    assert result["salary_range"]["max"] >= result["salary_range"]["min"]
    assert result["level"] == rank
    assert result["field"] == field


def test_search_job_market_invalid_rank():
    """Rank không hợp lệ → fallback về 'junior'."""
    result_json = search_job_market.invoke({
        "job_title": "Test",
        "candidate_rank": "không_tồn_tại",
        "field_category": "it",
    })
    result = json.loads(result_json)
    assert result["level"] == "junior"


def test_search_job_market_invalid_field():
    """Field không hợp lệ → fallback về 'other'."""
    result_json = search_job_market.invoke({
        "job_title": "Test",
        "candidate_rank": "mid",
        "field_category": "ngành_lạ",
    })
    result = json.loads(result_json)
    assert result["field"] == "other"


def test_search_web_for_jd_returns_list():
    """search_web_for_jd luôn trả về list (kể cả khi mạng lỗi)."""
    result = search_web_for_jd("python developer", max_results=3)
    assert isinstance(result, list)
    # Không assert len > 0 vì có thể DDG chặn trong CI
