"""
tests/test_cv_analysis.py — Unit tests cho prompts phân tích CV và API tools.
"""

import json
import pytest
from prompts.cv_analysis import (
    build_parse_cv_prompt,
    build_analyze_cv_prompt,
    build_expand_jd_prompt,
    build_extract_job_title_prompt,
)
from prompts.interview import build_final_evaluate_prompt
from services.tools.tool_api import scrape_jd_from_url


# ─────────────────────────────────────────────────────────────
# Prompts structure tests (không gọi LLM)
# ─────────────────────────────────────────────────────────────

def test_build_parse_cv_prompt(sample_cv_text: str):
    prompt = build_parse_cv_prompt(sample_cv_text)
    assert "Nguyễn Văn Minh" in prompt
    assert "KIẾN TRÚC CHỐNG ẢO TƯỞNG 5 LỚP" in prompt
    assert "raw_text" in prompt


def test_build_analyze_cv_prompt(sample_cv_structured: dict, sample_jd_text: str):
    cv_str = json.dumps(sample_cv_structured, ensure_ascii=False)
    prompt = build_analyze_cv_prompt(cv_structured=cv_str, jd_text=sample_jd_text)
    assert "strengths" in prompt
    assert "weaknesses" in prompt
    assert "skill_match_score" in prompt
    assert "Python Backend Developer" in prompt


def test_build_expand_jd_prompt(sample_cv_structured: dict):
    cv_str = json.dumps(sample_cv_structured, ensure_ascii=False)
    prompt = build_expand_jd_prompt(cv_str)
    assert "synthetic_jd" in prompt
    assert "job_title" in prompt


def test_build_extract_job_title_prompt(sample_jd_text: str):
    prompt = build_extract_job_title_prompt(sample_jd_text)
    assert "job_title" in prompt
    assert "Python Backend Developer" in prompt


def test_build_final_evaluate_prompt_with_market_data():
    """Kiểm tra prompt final_evaluate có nhúng market_salary_info."""
    market = json.dumps({"salary_display": "25M – 45M VNĐ/tháng"}, ensure_ascii=False)
    prompt = build_final_evaluate_prompt(
        candidate_rank="junior",
        skill_match_score=0.7,
        field_category="it",
        answer_scores_summary="- Câu 1: 7/10",
        market_salary_info=market,
    )
    assert "suggested_salary" in prompt
    assert "25M" in prompt
    assert "junior" in prompt


def test_build_final_evaluate_prompt_default_market():
    """market_salary_info có default = '{}' nên không crash khi bỏ qua."""
    prompt = build_final_evaluate_prompt(
        candidate_rank="mid",
        skill_match_score=0.8,
        field_category="it",
        answer_scores_summary="- Câu 1: 8/10",
    )
    assert "overall_score" in prompt


# ─────────────────────────────────────────────────────────────
# scrape_jd_from_url — kiểm tra xử lý URL không hợp lệ (không cần mạng)
# ─────────────────────────────────────────────────────────────

def test_scrape_jd_invalid_url():
    result = scrape_jd_from_url.invoke({"url": "not-a-url"})
    assert result.startswith("❌")


def test_scrape_jd_empty_url():
    result = scrape_jd_from_url.invoke({"url": ""})
    assert result.startswith("❌")
