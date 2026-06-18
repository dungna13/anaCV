"""
Tool definitions cho CVHR Agent (LangChain @tool).

Phase 3:
- search_job_market: Tìm kiếm mức lương thị trường (mock data)
- scrape_jd_from_url: Cào JD từ URL trang tuyển dụng (httpx + BeautifulSoup)
"""

import json
import re

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool


# ─────────────────────────────────────────────────────────────
# MOCK DATA — Thị trường lương IT Việt Nam 2024-2025
# ─────────────────────────────────────────────────────────────

_SALARY_DB: dict[str, dict[str, dict]] = {
    "it": {
        "fresher": {"min": 8_000_000,  "max": 15_000_000, "avg": 10_000_000, "unit": "VNĐ/tháng"},
        "junior":  {"min": 15_000_000, "max": 25_000_000, "avg": 18_000_000, "unit": "VNĐ/tháng"},
        "mid":     {"min": 25_000_000, "max": 45_000_000, "avg": 33_000_000, "unit": "VNĐ/tháng"},
        "senior":  {"min": 45_000_000, "max": 80_000_000, "avg": 60_000_000, "unit": "VNĐ/tháng"},
        "lead":    {"min": 70_000_000, "max": 150_000_000,"avg": 100_000_000,"unit": "VNĐ/tháng"},
    },
    "marketing": {
        "fresher": {"min": 7_000_000,  "max": 12_000_000, "avg": 9_000_000,  "unit": "VNĐ/tháng"},
        "junior":  {"min": 12_000_000, "max": 20_000_000, "avg": 15_000_000, "unit": "VNĐ/tháng"},
        "mid":     {"min": 20_000_000, "max": 35_000_000, "avg": 27_000_000, "unit": "VNĐ/tháng"},
        "senior":  {"min": 35_000_000, "max": 60_000_000, "avg": 45_000_000, "unit": "VNĐ/tháng"},
        "lead":    {"min": 55_000_000, "max": 100_000_000,"avg": 70_000_000, "unit": "VNĐ/tháng"},
    },
    "finance": {
        "fresher": {"min": 8_000_000,  "max": 13_000_000, "avg": 10_000_000, "unit": "VNĐ/tháng"},
        "junior":  {"min": 13_000_000, "max": 22_000_000, "avg": 17_000_000, "unit": "VNĐ/tháng"},
        "mid":     {"min": 22_000_000, "max": 40_000_000, "avg": 30_000_000, "unit": "VNĐ/tháng"},
        "senior":  {"min": 40_000_000, "max": 70_000_000, "avg": 55_000_000, "unit": "VNĐ/tháng"},
        "lead":    {"min": 60_000_000, "max": 120_000_000,"avg": 85_000_000, "unit": "VNĐ/tháng"},
    },
    "other": {
        "fresher": {"min": 7_000_000,  "max": 12_000_000, "avg": 9_000_000,  "unit": "VNĐ/tháng"},
        "junior":  {"min": 12_000_000, "max": 20_000_000, "avg": 15_000_000, "unit": "VNĐ/tháng"},
        "mid":     {"min": 20_000_000, "max": 35_000_000, "avg": 25_000_000, "unit": "VNĐ/tháng"},
        "senior":  {"min": 35_000_000, "max": 60_000_000, "avg": 45_000_000, "unit": "VNĐ/tháng"},
        "lead":    {"min": 50_000_000, "max": 100_000_000,"avg": 70_000_000, "unit": "VNĐ/tháng"},
    },
}


@tool
def search_job_market(
    job_title: str,
    candidate_rank: str = "junior",
    field_category: str = "it",
    location: str = "Vietnam",
) -> str:
    """Tra cứu thông tin thị trường tuyển dụng và mức lương cho một vị trí.

    Sử dụng mock data dựa trên field_category và candidate_rank để trả về
    thông tin tham khảo về mức lương thị trường tại Việt Nam (2024-2025).

    Args:
        job_title: Chức danh công việc (vd: "Backend Developer", "Marketing Manager").
        candidate_rank: Level ứng viên — "fresher" | "junior" | "mid" | "senior" | "lead".
        field_category: Lĩnh vực — "it" | "marketing" | "finance" | "other".
        location: Địa điểm (hiện tại chỉ hỗ trợ "Vietnam").

    Returns:
        Chuỗi JSON chứa thông tin thị trường và mức lương tham khảo.
    """
    field = field_category.lower() if field_category else "other"
    if field not in _SALARY_DB:
        field = "other"

    rank = candidate_rank.lower() if candidate_rank else "junior"
    if rank not in _SALARY_DB[field]:
        rank = "junior"

    salary = _SALARY_DB[field][rank]

    result = {
        "job_title": job_title,
        "location": location,
        "field": field,
        "level": rank,
        "salary_range": {
            "min": salary["min"],
            "max": salary["max"],
            "avg": salary["avg"],
            "unit": salary["unit"],
        },
        "salary_display": (
            f"{salary['min'] // 1_000_000}M – {salary['max'] // 1_000_000}M VNĐ/tháng "
            f"(trung bình ~{salary['avg'] // 1_000_000}M VNĐ/tháng)"
        ),
        "source": "Mock data — Thị trường IT Việt Nam 2024-2025 (tổng hợp từ IT Viec, TopCV, VietnamWorks)",
        "note": "Mức lương thực tế có thể dao động tùy công ty, kỹ năng chuyên sâu và location (HCM/HN thường cao hơn tỉnh ~20-30%).",
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
# SCRAPER TOOL — Cào JD từ URL
# ─────────────────────────────────────────────────────────────

_SCRAPER_TIMEOUT = 15  # giây

# Các selector CSS ưu tiên cho các trang tuyển dụng phổ biến
_JD_SELECTORS = [
    "article.job-description",
    "div.job-description",
    "div.job-detail__description",
    "div[class*='job-description']",
    "div[class*='job_description']",
    "div[class*='jd-content']",
    "section[class*='description']",
    "div[data-automation='jobDescription']",
    "div.description",
    "main article",
    "article",
    "main",
]


def _clean_text(text: str) -> str:
    """Làm sạch text cào từ HTML: bỏ khoảng trắng thừa, dòng trống liên tiếp."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@tool
def scrape_jd_from_url(url: str) -> str:
    """Cào nội dung Job Description từ URL trang tuyển dụng.

    Hỗ trợ: TopCV, IT Viec, VietnamWorks, LinkedIn, và hầu hết trang HTML thông thường.
    Sử dụng BeautifulSoup để trích xuất phần nội dung JD chính từ trang web,
    bỏ qua navigation, footer, quảng cáo.

    Args:
        url: URL đầy đủ của trang tuyển dụng
             (vd: "https://itviec.com/it-jobs/backend-python-abc-123").

    Returns:
        Nội dung JD dạng plain text, hoặc thông báo lỗi nếu không cào được.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "❌ URL không hợp lệ. Vui lòng cung cấp URL đầy đủ (bắt đầu bằng http:// hoặc https://)."

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        }
        response = httpx.get(url, headers=headers, timeout=_SCRAPER_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
    except httpx.TimeoutException:
        return f"❌ Timeout khi tải trang {url}. Trang có thể không phản hồi hoặc chặn bot."
    except httpx.HTTPStatusError as e:
        return f"❌ Lỗi HTTP {e.response.status_code} khi tải trang {url}."
    except Exception as e:
        return f"❌ Không thể tải trang {url}: {e}"

    soup = BeautifulSoup(response.text, "lxml")

    # Loại bỏ script, style, nav, footer
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()

    # Thử lần lượt các selector đặc thù cho các trang tuyển dụng
    jd_element = None
    for selector in _JD_SELECTORS:
        jd_element = soup.select_one(selector)
        if jd_element:
            break

    if jd_element:
        raw_text = jd_element.get_text(separator="\n")
    else:
        # Fallback: lấy body text
        body = soup.find("body")
        raw_text = body.get_text(separator="\n") if body else soup.get_text(separator="\n")

    text = _clean_text(raw_text)

    if len(text) < 100:
        return (
            f"⚠️ Không trích xuất được nội dung JD từ {url}. "
            "Trang có thể yêu cầu đăng nhập, render bằng JavaScript, hoặc chặn bot. "
            "Vui lòng paste nội dung JD trực tiếp."
        )

    # Giới hạn 8000 ký tự để tránh quá dài cho LLM
    if len(text) > 8000:
        text = text[:8000] + "\n\n[... nội dung được cắt bớt để tiết kiệm tokens ...]"

    return f"[JD từ {url}]\n\n{text}"


ALL_TOOLS = [search_job_market, scrape_jd_from_url]


# ─────────────────────────────────────────────────────────────
# HELPER — Tìm kiếm JD từ DuckDuckGo HTML (không cần API key)
# ─────────────────────────────────────────────────────────────

_DDG_URL = "https://html.duckduckgo.com/html/"
_DDG_TIMEOUT = 12

# Trang tuyển dụng phổ biến ưu tiên trong kết quả search
_JOB_SITE_PRIORITY = (
    "itviec.com", "topcv.vn", "vietnamworks.com",
    "linkedin.com/jobs", "careerbuilder.vn", "mywork.com.vn",
)


def search_web_for_jd(keywords: str, max_results: int = 5) -> list[str]:
    """Tìm kiếm các URL JD liên quan từ DuckDuckGo HTML (không cần API key).

    Tự động thêm site filter ưu tiên các trang tuyển dụng VN để kết quả
    sát thực tế hơn.

    Args:
        keywords: Từ khóa tìm kiếm (vd: "Backend Python Developer tuyển dụng").
        max_results: Số URL tối đa trả về.

    Returns:
        Danh sách URL từ kết quả tìm kiếm (có thể rỗng nếu lỗi mạng/bị chặn).
    """
    query = f"{keywords} tuyển dụng việc làm"
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        }
        resp = httpx.post(
            _DDG_URL,
            data={"q": query, "kl": "vn-vi"},
            headers=headers,
            timeout=_DDG_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    anchors = soup.select("a.result__a")

    urls: list[str] = []
    priority_urls: list[str] = []
    other_urls: list[str] = []

    for a in anchors:
        href = a.get("href", "")
        if not href.startswith("http"):
            continue
        if any(site in href for site in _JOB_SITE_PRIORITY):
            priority_urls.append(href)
        else:
            other_urls.append(href)

    urls = priority_urls + other_urls
    return urls[:max_results]
