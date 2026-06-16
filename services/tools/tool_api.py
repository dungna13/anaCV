"""
Tool definitions cho CVHR Agent (LangChain @tool).

Phase 3: Sẽ định nghĩa các tools:
- search_job_market: Tìm kiếm mức lương thị trường
- scrape_jd_from_url: Cào JD từ URL trang tuyển dụng
"""

# Phase 1: Chưa cần tools (graph chạy thuần LLM + state)
# Phase 3: Uncomment và implement

# from langchain_core.tools import tool
#
# @tool
# def search_job_market(job_title: str, location: str = "Vietnam") -> str:
#     """Tìm kiếm thông tin thị trường tuyển dụng cho vị trí cụ thể."""
#     # TODO: Implement với Tavily Search hoặc mock data
#     pass
#
# @tool
# def scrape_jd_from_url(url: str) -> str:
#     """Cào nội dung JD từ URL trang tuyển dụng."""
#     # TODO: Implement với httpx + BeautifulSoup
#     pass
#
# ALL_TOOLS = [search_job_market, scrape_jd_from_url]
