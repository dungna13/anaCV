"""
core/graph.py — LangGraph State Machine cho CVHR AI Agent.

Kiến trúc pipeline:
  START → parse_cv → analyze_cv → rank_candidate → generate_questions
        → ask_question ↔ human (interrupt) ↔ [evaluate_answer → ask_question (loop) / final_evaluate]
        → cv_improve_subagent → generate_pdf → END

Tương tự services/main.py trong etax_kekhaithue:
  - CVHRState(TypedDict) thay vì CNKDState
  - interrupt() cho multi-turn interview
  - MemorySaver checkpoint
  - Conditional edges cho routing logic

Lớp phòng thủ bổ sung trong file này (so với bản nháp ban đầu):
  1. `_extract_json` loại bỏ thẻ <thought>...</thought> trước khi parse,
     đúng với định dạng output của các prompt theo chuẩn Prompt Engineer Master.
  2. `_safe_llm_json_call` — wrapper tự động RETRY khi LLM trả JSON sai
     định dạng / thiếu trường, và rơi về giá trị mặc định an toàn nếu vẫn
     lỗi sau khi hết số lần thử → graph KHÔNG BAO GIỜ crash giữa chừng vì lỗi parse.
  3. `_validate_answer` + `route_after_human` xử lý câu trả lời rỗng / quá
     ngắn / spam ký tự vô nghĩa bằng cách yêu cầu ứng viên trả lời lại
     (tối đa MAX_ANSWER_ATTEMPTS lần) trước khi để LLM chấm điểm.
"""

import json
import os
import re
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from typing_extensions import TypedDict

from config.settings import get_settings
from prompts.cv_analysis import (
    build_analyze_cv_prompt,
    build_expand_jd_prompt,
    build_extract_job_title_prompt,
    build_parse_cv_prompt,
)
from prompts.interview import (
    build_evaluate_answer_prompt,
    build_final_evaluate_prompt,
    build_generate_questions_prompt,
)
from prompts.cv_improvement import build_cv_improvement_prompt
from prompts.ranking import build_ranking_prompt
from services.tools.tool_api import scrape_jd_from_url, search_job_market, search_web_for_jd


settings = get_settings()

# ─────────────────────────────────────────────────────────────
# HẰNG SỐ CẤU HÌNH PHÒNG THỦ (Edge-case constants)
# ─────────────────────────────────────────────────────────────

# Số lần tối đa retry khi LLM trả JSON sai định dạng / thiếu trường bắt buộc.
MAX_JSON_RETRIES = 2

# Số ký tự tối thiểu để coi một câu trả lời là "có nội dung".
MIN_ANSWER_LENGTH = 3

# Số lần tối đa cho ứng viên trả lời lại MỘT câu hỏi nếu input không hợp lệ
# (trống / quá ngắn / spam). Sau số lần này, hệ thống vẫn chấp nhận câu trả
# lời (dù không hợp lệ) và để LLM tự chấm điểm thấp, tránh treo vòng lặp vô hạn.
MAX_ANSWER_ATTEMPTS = 3

# Các giá trị hợp lệ cho candidate_rank / final_verdict — dùng để tự soát lỗi
# (Layer 5 — Reflexion) khi LLM trả về giá trị nằm ngoài enum cho phép.
VALID_RANKS = {"fresher", "junior", "mid", "senior", "lead"}
VALID_VERDICTS = {"PASS", "CONSIDER", "FAIL"}


# ─────────────────────────────────────────────────────────────
# LANGFUSE SETUP (giống pattern etax)
# ─────────────────────────────────────────────────────────────

LANGFUSE_ENABLED = False
_langfuse_handler = None

if settings.langfuse.enabled:
    try:
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse.secret_key)
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse.public_key)
        if settings.langfuse.base_url:
            os.environ.setdefault("LANGFUSE_HOST", settings.langfuse.base_url)

        from langfuse.langchain import CallbackHandler as _LangfuseCallbackHandler
        _langfuse_handler = _LangfuseCallbackHandler()
        LANGFUSE_ENABLED = True
        print("[CVHR] ✅ Langfuse tracing enabled")
    except Exception as e:
        print(f"[CVHR] ⚠️ Langfuse init failed: {e}")


# ─────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────

def _get_llm() -> ChatGoogleGenerativeAI:
    """Tạo LLM instance (Gemini qua LangChain)."""
    return ChatGoogleGenerativeAI(
        model=settings.llm.model,
        google_api_key=settings.llm.google_api_key,
        temperature=settings.llm.temperature,
        max_output_tokens=settings.llm.max_tokens,
    )


# ─────────────────────────────────────────────────────────────
# TRÍCH XUẤT JSON TỪ PHẢN HỒI LLM
# ─────────────────────────────────────────────────────────────

# Các prompt trong prompts/ luôn yêu cầu LLM xuất:
#   <thought> ... chuỗi suy luận từng bước ... </thought>
#   ```json
#   { ... }
#   ```
# Vì vậy bước đầu tiên BẮT BUỘC là loại bỏ thẻ <thought> trước khi tìm JSON,
# để không bị nhiễu nội dung suy luận khi fallback parse trực tiếp.
_THOUGHT_TAG_RE = re.compile(r"<thought>.*?</thought>", re.DOTALL | re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_RAW_JSON_RE = re.compile(r"[\{\[].*[\}\]]", re.DOTALL)


def _extract_json(text: str) -> dict | list:
    """Trích xuất JSON từ response LLM.

    Thứ tự xử lý:
    1. Loại bỏ toàn bộ thẻ <thought>...</thought> (nếu LLM có sinh ra).
    2. Tìm JSON nằm trong code fence ```json ... ``` (chuẩn output mong đợi).
    3. Nếu không có code fence, thử tìm khối {...} hoặc [...] đầu tiên trong
       phần text còn lại (phòng trường hợp LLM quên bọc code fence).
    4. Nếu vẫn không tìm được, thử parse trực tiếp toàn bộ text đã làm sạch.

    Raises:
        json.JSONDecodeError: Nếu không có cách nào parse được JSON hợp lệ.
            Lỗi này được `_safe_llm_json_call` bắt và xử lý retry/fallback.
    """
    cleaned = _THOUGHT_TAG_RE.sub("", text or "").strip()

    fence_match = _JSON_FENCE_RE.search(cleaned)
    if fence_match:
        return json.loads(fence_match.group(1))

    raw_match = _RAW_JSON_RE.search(cleaned)
    if raw_match:
        return json.loads(raw_match.group(0))

    return json.loads(cleaned)


def _safe_llm_json_call(
    llm: ChatGoogleGenerativeAI,
    system_prompt: str,
    required_keys: list[str] | None,
    default_factory,
    label: str,
):
    """Gọi LLM và parse JSON với cơ chế tự retry + fallback an toàn.

    Đây là lớp bảo vệ trung tâm cho TẤT CẢ node có gọi LLM trong graph,
    giải quyết yêu cầu: "Thêm xử lý lỗi khi LLM trả về JSON sai định dạng,
    tự động thử lại hoặc gán giá trị mặc định an toàn để đồ thị không bị
    sập giữa chừng."

    Cơ chế:
    - Gọi LLM, thử parse JSON bằng `_extract_json`.
    - Nếu lỗi parse (JSONDecodeError) HOẶC JSON thiếu trường bắt buộc
      (`required_keys`) → gửi lại cho LLM kèm yêu cầu sửa, thử tối đa
      `MAX_JSON_RETRIES` lần.
    - Nếu vẫn lỗi sau khi hết số lần thử → trả về `default_factory()`
      (giá trị mặc định an toàn) để node gọi hàm này có thể tiếp tục chạy
      bình thường, KHÔNG làm crash toàn bộ graph.

    Args:
        llm: LLM instance dùng để gọi.
        system_prompt: Nội dung SystemMessage ban đầu (đã build từ prompts/).
        required_keys: Danh sách key bắt buộc nếu kết quả mong đợi là dict.
            Truyền None nếu kết quả mong đợi là list không rỗng (ví dụ:
            generate_questions trả về JSON array).
        default_factory: Hàm không tham số trả về giá trị mặc định an toàn.
        label: Tên node — chỉ dùng để log lỗi cho dễ debug.
    """
    messages: list = [SystemMessage(content=system_prompt)]

    for attempt in range(MAX_JSON_RETRIES + 1):
        response = llm.invoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        try:
            result = _extract_json(raw_text)

            if required_keys is not None:
                if not isinstance(result, dict):
                    raise ValueError("Kết quả không phải JSON object như mong đợi.")
                missing = [k for k in required_keys if k not in result]
                if missing:
                    raise ValueError(f"Thiếu các trường bắt buộc: {missing}")
            else:
                if not isinstance(result, list) or len(result) == 0:
                    raise ValueError("Kết quả phải là JSON array không rỗng.")

            return result

        except (json.JSONDecodeError, ValueError) as e:
            print(f"[CVHR] ⚠️ [{label}] Lỗi parse JSON (lần {attempt + 1}/{MAX_JSON_RETRIES + 1}): {e}")

            if attempt >= MAX_JSON_RETRIES:
                print(f"[CVHR] ❌ [{label}] Hết số lần thử lại — dùng giá trị mặc định an toàn.")
                return default_factory()

            # Đưa phản hồi lỗi vào lịch sử hội thoại + yêu cầu LLM sửa lại,
            # giúp model "thấy" lỗi của chính nó (self-correction).
            messages.append(AIMessage(content=raw_text))
            messages.append(
                HumanMessage(
                    content=(
                        "Phản hồi trên KHÔNG phải JSON hợp lệ hoặc thiếu trường bắt buộc. "
                        "Hãy xuất lại CHÍNH XÁC theo đúng JSON Schema đã yêu cầu, bọc trong "
                        "```json ... ```. Không thêm bất kỳ văn bản nào khác ngoài thẻ "
                        "<thought> và khối JSON."
                    )
                )
            )

    return default_factory()  # An toàn tuyệt đối — không bao giờ thực sự chạy tới đây.


# ─────────────────────────────────────────────────────────────
# KIỂM TRA CÂU TRẢ LỜI ỨNG VIÊN (Edge cases: trống / quá ngắn / spam)
# ─────────────────────────────────────────────────────────────

# Regex nhận diện chuỗi chỉ gồm ký tự không phải chữ cái (số, dấu câu, khoảng
# trắng...) — ví dụ "12345", "?????", "..." → coi là spam vô nghĩa.
_NON_ALPHA_ONLY_RE = re.compile(r"^[\W\d_]+$", re.UNICODE)


def _validate_answer(text: str | None) -> tuple[bool, str]:
    """Kiểm tra câu trả lời của ứng viên có hợp lệ tối thiểu hay không.

    Đây KHÔNG phải kiểm tra chất lượng câu trả lời (việc đó do LLM chấm ở
    node_evaluate_answer) — đây chỉ là tầng lọc nhanh, không tốn token LLM,
    để bắt các trường hợp rõ ràng không có nội dung:

    - Trống / chỉ có khoảng trắng.
    - Quá ngắn (dưới MIN_ANSWER_LENGTH ký tự).
    - Spam ký tự lặp lại (vd: "aaaaaa", "1111111").
    - Chỉ gồm ký tự không phải chữ cái (vd: "?????", "12345", "...").

    Returns:
        (is_valid, reason): `reason` chỉ có ý nghĩa khi is_valid=False,
        dùng để hiển thị cảnh báo thân thiện cho ứng viên.
    """
    if text is None:
        return False, "trống"

    stripped = text.strip()
    if not stripped:
        return False, "trống"

    if len(stripped) < MIN_ANSWER_LENGTH:
        return False, "quá ngắn"

    unique_ratio = len(set(stripped.lower())) / len(stripped)
    if unique_ratio < 0.15:
        return False, "có vẻ là spam ký tự lặp lại"

    if _NON_ALPHA_ONLY_RE.match(stripped):
        return False, "không chứa nội dung có nghĩa"

    return True, ""


# ─────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────

class CVHRState(TypedDict, total=False):
    """State của CVHR graph — lưu toàn bộ thông tin qua các node.

    Cấu trúc tương tự CNKDState trong etax:
    - messages: chat history (Annotated list với add_messages)
    - Các field khác: kết quả xử lý từng bước
    """

    # ─── Lịch sử hội thoại ───
    messages: Annotated[list, add_messages]

    # ─── Input ban đầu (set 1 lần khi start) ───
    cv_raw_text: str              # Nội dung text thô sau khi parse PDF
    jd_text: str                  # Mô tả công việc (Job Description)
    session_id: str               # UUID phiên

    # ─── Kết quả BƯỚC 1: Parse CV (node_parse_cv) ───
    parse_done: bool              # True sau khi parse xong
    cv_structured: dict           # CV đã được cấu trúc hóa (JSON)

    # ─── Kết quả BƯỚC 2: Phân tích CV (node_analyze_cv) ───
    analysis_done: bool
    strengths: list               # Điểm mạnh so với JD
    weaknesses: list               # Điểm yếu / thiếu sót so với JD
    skill_match_score: float      # 0.0 → 1.0 (tỷ lệ kỹ năng khớp)
    cv_improvements: list         # Đề xuất cải thiện CV

    # ─── Kết quả BƯỚC 3: Xếp hạng (node_rank_candidate) ───
    candidate_rank: str           # "fresher" | "junior" | "mid" | "senior" | "lead"
    rank_reasoning: str           # Lý do xếp hạng
    years_of_experience: float    # Số năm kinh nghiệm (ước tính)
    field_category: str           # "it" | "marketing" | "finance" | ...

    # ─── BƯỚC 4: Câu hỏi phỏng vấn (node_generate_questions) ───
    questions: list               # [{q, category, difficulty, expected_keywords, max_score}]
    current_q_index: int           # Câu hỏi đang hỏi (0-based)
    current_q_attempts: int       # Số lần đã hỏi câu hiện tại (phục vụ retry khi answer invalid)

    # ─── BƯỚC 5: Đánh giá câu trả lời (node_evaluate_answer) ───
    answer_scores: list            # [{q_index, score, feedback, follow_up_suggestion}]

    # ─── BƯỚC 6: Đánh giá chung (node_final_evaluate) ───
    overall_score: float          # Điểm tổng 0-100
    final_verdict: str            # "PASS" | "CONSIDER" | "FAIL"
    final_summary: str            # Đánh giá tổng kết dạng text

    # ─── BƯỚC 7: Subagent cải thiện CV ───
    cv_improve_report: str        # Báo cáo chi tiết cải thiện CV

    # ─── BƯỚC 8: Sinh PDF ───
    pdf_generated: bool
    pdf_path: str                 # Đường dẫn file PDF output

    # ─── Phase 3.5: JD Enrichment ───
    job_title: str               # Chức danh trích từ JD/CV
    jd_source: str               # "user_text" | "url_scraped" | "web_search" | "llm_generated"

    # ─── Phase 3.5: Salary Data ───
    market_salary_info: dict     # Từ search_job_market
    suggested_salary: dict       # {min, max, currency, rationale}


# ─────────────────────────────────────────────────────────────
# NODES
# ─────────────────────────────────────────────────────────────

def node_parse_cv(state: CVHRState) -> dict:
    """Node 1: Parse CV raw text → structured JSON bằng LLM.

    Tương tự node_setup_auto trong etax: chạy 1 lần ở đầu phiên,
    kết quả lưu vào state để các node sau dùng.
    """
    llm = _get_llm()
    cv_raw_text = state["cv_raw_text"]

    prompt = build_parse_cv_prompt(cv_raw_text)

    def _default_cv() -> dict:
        # Fallback an toàn: giữ lại raw_text để các bước sau (vốn cần
        # cv_structured) vẫn có dữ liệu tối thiểu để hoạt động, dù mất đi
        # phần cấu trúc hóa.
        return {
            "name": None,
            "email": None,
            "phone": None,
            "summary": None,
            "education": [],
            "experience": [],
            "skills": [],
            "certifications": [],
            "languages": [],
            "projects": [],
            "raw_text": cv_raw_text,
        }

    parsed = _safe_llm_json_call(
        llm,
        prompt,
        required_keys=["name", "skills", "experience"],
        default_factory=_default_cv,
        label="parse_cv",
    )

    # Đảm bảo raw_text được giữ
    if isinstance(parsed, dict) and not parsed.get("raw_text"):
        parsed["raw_text"] = cv_raw_text

    # Phát hiện field_category sơ bộ từ CV (sẽ được refine ở node_rank)
    skills_text = " ".join(parsed.get("skills", []) or []).lower()
    it_keywords = {"python", "java", "javascript", "react", "node", "docker",
                   "kubernetes", "aws", "devops", "backend", "frontend", "sql",
                   "api", "git", "linux", "c++", "golang", "rust", "flutter"}
    it_match = sum(1 for kw in it_keywords if kw in skills_text)
    detected_field = "it" if it_match >= 2 else "other"

    # Thông báo tiến trình qua messages
    name = parsed.get("name") or "Ứng viên"
    summary_msg = (
        f"✅ **Đã parse CV thành công!**\n"
        f"- Họ tên: {name}\n"
        f"- Số kinh nghiệm: {len(parsed.get('experience', []))} vị trí\n"
        f"- Kỹ năng: {', '.join(parsed.get('skills', [])[:8]) or 'N/A'}\n"
        f"- Lĩnh vực phát hiện: {detected_field.upper()}"
    )

    return {
        "cv_structured": parsed,
        "parse_done": True,
        "field_category": detected_field,
        "messages": [AIMessage(content=summary_msg)],
    }


def node_enrich_jd(state: CVHRState) -> dict:
    """Node 1.5: Giải quyết nguồn JD từ bất kỳ dạng input nào.

    Case A: jd_text là URL → scrape, fallback LLM expand.
    Case B: jd_text ngắn < 200 ký tự (keywords) → search_web → scrape → fallback LLM.
    Case C: jd_text rỗng → trích job_title từ CV → tương tự Case B.
    """
    llm = _get_llm()
    jd_text = (state.get("jd_text") or "").strip()
    cv_structured = state.get("cv_structured") or {}

    job_title = ""
    jd_source = "user_text"
    enriched_jd = jd_text

    # ── Case A: URL ──
    if jd_text.startswith(("http://", "https://")):
        scraped = scrape_jd_from_url.invoke({"url": jd_text})
        if not scraped.startswith("❌") and not scraped.startswith("⚠️") and len(scraped) >= 150:
            enriched_jd = scraped
            jd_source = "url_scraped"
        else:
            # Fallback: LLM expand từ URL domain
            prompt = build_expand_jd_prompt(json.dumps(cv_structured, ensure_ascii=False))
            result = _safe_llm_json_call(
                llm, prompt,
                required_keys=["job_title", "synthetic_jd"],
                default_factory=lambda: {"job_title": "", "synthetic_jd": jd_text},
                label="enrich_jd_url_fallback",
            )
            enriched_jd = result.get("synthetic_jd") or jd_text
            job_title = result.get("job_title") or ""
            jd_source = "llm_generated"

    # ── Case B: keywords (ngắn, không phải URL) ──
    elif jd_text and len(jd_text) < 200:
        keywords = jd_text
        urls = search_web_for_jd(keywords, max_results=3)
        scraped_ok = False
        for url in urls:
            scraped = scrape_jd_from_url.invoke({"url": url})
            if not scraped.startswith("❌") and not scraped.startswith("⚠️") and len(scraped) >= 150:
                enriched_jd = scraped
                jd_source = "web_search"
                scraped_ok = True
                break
        if not scraped_ok:
            prompt = build_expand_jd_prompt(json.dumps(cv_structured, ensure_ascii=False))
            result = _safe_llm_json_call(
                llm, prompt,
                required_keys=["job_title", "synthetic_jd"],
                default_factory=lambda: {"job_title": keywords, "synthetic_jd": jd_text},
                label="enrich_jd_keyword_fallback",
            )
            enriched_jd = result.get("synthetic_jd") or jd_text
            job_title = result.get("job_title") or keywords
            jd_source = "llm_generated"

    # ── Case C: rỗng → tự trích từ CV ──
    elif not jd_text:
        prompt = build_expand_jd_prompt(json.dumps(cv_structured, ensure_ascii=False))
        result = _safe_llm_json_call(
            llm, prompt,
            required_keys=["job_title", "synthetic_jd"],
            default_factory=lambda: {"job_title": "Chưa xác định", "synthetic_jd": ""},
            label="enrich_jd_from_cv",
        )
        enriched_jd = result.get("synthetic_jd") or ""
        job_title = result.get("job_title") or ""
        jd_source = "llm_generated"

    # Nếu có JD text đầy đủ (Case A user_text) → trích job_title từ JD
    if jd_source == "user_text" and enriched_jd:
        prompt = build_extract_job_title_prompt(enriched_jd[:3000])
        result = _safe_llm_json_call(
            llm, prompt,
            required_keys=["job_title"],
            default_factory=lambda: {"job_title": ""},
            label="extract_job_title",
        )
        job_title = result.get("job_title") or ""

    source_label = {
        "user_text": "nhập thủ công",
        "url_scraped": "cào từ URL",
        "web_search": "tìm kiếm web",
        "llm_generated": "AI tự sinh từ CV",
    }.get(jd_source, jd_source)

    msg = (
        f"📋 **JD đã sẵn sàng** (nguồn: {source_label})\n"
        f"- Chức danh: {job_title or 'N/A'}\n"
        f"- Độ dài JD: {len(enriched_jd)} ký tự"
    )

    return {
        "jd_text": enriched_jd,
        "job_title": job_title,
        "jd_source": jd_source,
        "messages": [AIMessage(content=msg)],
    }


def node_analyze_cv(state: CVHRState) -> dict:
    """Node 2: So sánh CV vs JD, đánh giá strengths/weaknesses."""
    llm = _get_llm()

    prompt = build_analyze_cv_prompt(
        cv_structured=json.dumps(state["cv_structured"], ensure_ascii=False, indent=2),
        jd_text=state["jd_text"],
    )

    def _default_analysis() -> dict:
        return {
            "strengths": [],
            "weaknesses": ["Hệ thống AI không thể phân tích tự động — cần HR xem xét thủ công."],
            "skill_match_score": 0.5,
            "cv_improvements": [],
        }

    result = _safe_llm_json_call(
        llm,
        prompt,
        required_keys=["strengths", "weaknesses", "skill_match_score", "cv_improvements"],
        default_factory=_default_analysis,
        label="analyze_cv",
    )

    # Tự soát lỗi (Layer 5): đảm bảo skill_match_score luôn nằm trong [0, 1]
    # dù LLM có trả về giá trị lệch chuẩn (vd: 75 thay vì 0.75, hoặc chuỗi).
    try:
        skill_match_score = max(0.0, min(1.0, float(result.get("skill_match_score", 0.5))))
    except (TypeError, ValueError):
        skill_match_score = 0.5

    strengths = result.get("strengths") or []
    weaknesses = result.get("weaknesses") or []
    cv_improvements = result.get("cv_improvements") or []

    summary_msg = (
        f"📊 **Kết quả phân tích CV vs JD:**\n"
        f"- Skill Match Score: **{skill_match_score:.0%}**\n"
        f"- Điểm mạnh: {len(strengths)} items\n"
        f"- Điểm yếu: {len(weaknesses)} items\n"
        f"- Đề xuất cải thiện: {len(cv_improvements)} items"
    )

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "skill_match_score": skill_match_score,
        "cv_improvements": cv_improvements,
        "analysis_done": True,
        "messages": [AIMessage(content=summary_msg)],
    }


def node_rank_candidate(state: CVHRState) -> dict:
    """Node 3: Xếp hạng level ứng viên (Fresher/Junior/Mid/Senior/Lead)."""
    llm = _get_llm()

    prompt = build_ranking_prompt(
        cv_structured=json.dumps(state["cv_structured"], ensure_ascii=False, indent=2),
        jd_text=state["jd_text"],
    )

    def _default_rank() -> dict:
        # "junior" được chọn làm mặc định an toàn (không quá khắt khe, không
        # quá ưu ái) khi hệ thống không thể tự xếp hạng.
        return {
            "candidate_rank": "junior",
            "years_of_experience": 0.0,
            "rank_reasoning": "Không thể xác định tự động do lỗi hệ thống — cần HR đánh giá lại.",
            "field_category": state.get("field_category", "other"),
        }

    result = _safe_llm_json_call(
        llm,
        prompt,
        required_keys=["candidate_rank", "years_of_experience", "rank_reasoning"],
        default_factory=_default_rank,
        label="rank_candidate",
    )

    rank = result.get("candidate_rank", "junior")
    reasoning = result.get("rank_reasoning", "")
    if rank not in VALID_RANKS:
        # Tự soát lỗi (Layer 5): LLM trả về rank ngoài enum cho phép.
        reasoning = f"{reasoning} (Lưu ý: rank gốc '{rank}' không hợp lệ, đã quy về 'junior')".strip()
        rank = "junior"

    try:
        years = max(0.0, float(result.get("years_of_experience", 0.0)))
    except (TypeError, ValueError):
        years = 0.0

    field = result.get("field_category") or state.get("field_category", "other")

    rank_emoji = {
        "fresher": "🌱", "junior": "🌿", "mid": "🌳",
        "senior": "🏆", "lead": "👑",
    }
    emoji = rank_emoji.get(rank, "📋")

    summary_msg = (
        f"{emoji} **Xếp hạng ứng viên: {rank.upper()}**\n"
        f"- Số năm kinh nghiệm: ~{years:.1f} năm\n"
        f"- Lĩnh vực: {field}\n"
        f"- Lý do: {reasoning}"
    )

    # Lấy market salary data
    job_title = state.get("job_title") or ""
    try:
        market_json = search_job_market.invoke({
            "job_title": job_title or rank,
            "candidate_rank": rank,
            "field_category": field,
        })
        market_salary_info = json.loads(market_json)
        salary_display = market_salary_info.get("salary_display", "N/A")
        summary_msg += f"\n- Lương thị trường: {salary_display}"
    except Exception as e:
        print(f"[CVHR] ⚠️ [rank_candidate] search_job_market lỗi: {e}")
        market_salary_info = {}

    return {
        "candidate_rank": rank,
        "rank_reasoning": reasoning,
        "years_of_experience": years,
        "field_category": field,
        "market_salary_info": market_salary_info,
        "messages": [AIMessage(content=summary_msg)],
    }


def node_generate_questions(state: CVHRState) -> dict:
    """Node 4: Sinh bộ câu hỏi phỏng vấn dựa trên CV + JD + level."""
    llm = _get_llm()

    prompt = build_generate_questions_prompt(
        cv_structured=json.dumps(state["cv_structured"], ensure_ascii=False, indent=2),
        jd_text=state["jd_text"],
        candidate_rank=state["candidate_rank"],
        rank_reasoning=state["rank_reasoning"],
        weaknesses=json.dumps(state["weaknesses"], ensure_ascii=False),
    )

    def _fallback_questions() -> list:
        # Bộ câu hỏi tổng quát, an toàn cho mọi level — dùng khi LLM không
        # thể sinh câu hỏi hợp lệ sau khi đã retry, để buổi phỏng vấn vẫn
        # có thể tiếp tục thay vì graph bị treo/crash.
        return [
            {
                "q": "Bạn hãy giới thiệu ngắn gọn về bản thân và kinh nghiệm liên quan đến vị trí ứng tuyển?",
                "category": "soft_skill", "difficulty": "easy",
                "expected_keywords": [], "max_score": 10,
            },
            {
                "q": "Theo bạn, kỹ năng/công nghệ nào trong CV của bạn phù hợp nhất với JD này? Vì sao?",
                "category": "technical", "difficulty": "easy",
                "expected_keywords": [], "max_score": 10,
            },
            {
                "q": "Hãy kể về một khó khăn bạn từng gặp trong công việc/học tập và cách bạn giải quyết.",
                "category": "situational", "difficulty": "easy",
                "expected_keywords": [], "max_score": 10,
            },
        ]

    raw_questions = _safe_llm_json_call(
        llm,
        prompt,
        required_keys=None,
        default_factory=_fallback_questions,
        label="generate_questions",
    )

    # Lọc các câu hỏi thiếu trường "q" (phòng LLM trả JSON array nhưng item lỗi).
    questions = [q for q in raw_questions if isinstance(q, dict) and q.get("q")]
    if not questions:
        questions = _fallback_questions()

    summary_msg = (
        f"📝 **Đã sinh {len(questions)} câu hỏi phỏng vấn!**\n"
        f"Bắt đầu sơ vấn...\n\n"
        f"---"
    )

    return {
        "questions": questions,
        "current_q_index": 0,
        "current_q_attempts": 0,
        "answer_scores": [],
        "messages": [AIMessage(content=summary_msg)],
    }


def node_ask_question(state: CVHRState) -> dict:
    """Node 5: Đặt câu hỏi hiện tại cho ứng viên.

    Lấy câu hỏi tại index current_q_index, format và gửi qua messages.
    Nếu node này được gọi lại do câu trả lời trước KHÔNG hợp lệ (xem
    `route_after_human`), hiển thị thêm cảnh báo nhắc ứng viên trả lời
    chi tiết hơn, kèm số lần thử còn lại.
    """
    idx = state["current_q_index"]
    questions = state["questions"]
    total = len(questions)
    q = questions[idx]

    attempts = state.get("current_q_attempts", 0)

    warning = ""
    if attempts >= 1:
        last_human = next(
            (m for m in reversed(state["messages"])
             if isinstance(m, HumanMessage) and m.content is not None),
            None,
        )
        _, reason = _validate_answer(last_human.content if last_human else None)
        warning = (
            f"⚠️ **Câu trả lời trước {reason or 'không hợp lệ'}.** "
            f"Vui lòng trả lời chi tiết hơn (lần thử {attempts + 1}/{MAX_ANSWER_ATTEMPTS}).\n\n"
        )

    text = (
        f"{warning}"
        f"**Câu hỏi {idx + 1}/{total}** "
        f"({q['category']} — {q['difficulty']})\n\n"
        f"{q['q']}"
    )
    return {
        "current_q_attempts": attempts + 1,
        "messages": [AIMessage(content=text)],
    }


def node_human(state: CVHRState) -> dict:
    """Node 6: Interrupt — đợi ứng viên nhập câu trả lời.

    Giống node_human trong etax: gọi interrupt() để tạm dừng graph,
    đợi user gửi input qua Command(resume=...).

    Việc kiểm tra hợp lệ (trống/quá ngắn/spam) được xử lý ở
    `route_after_human` ngay sau node này — node_human chỉ có một trách
    nhiệm duy nhất là thu thập input thô.
    """
    last_ai = next(
        (m for m in reversed(state["messages"])
         if isinstance(m, AIMessage) and m.content),
        None,
    )
    prompt_text = last_ai.content if last_ai else "Vui lòng trả lời:"
    user_input = interrupt(prompt_text)

    # Phòng thủ kiểu dữ liệu: Command(resume=...) về lý thuyết có thể mang
    # bất kỳ giá trị nào, ép về str để các bước sau (vốn luôn xử lý str) an toàn.
    if not isinstance(user_input, str):
        user_input = str(user_input) if user_input is not None else ""

    return {"messages": [HumanMessage(content=user_input)]}


def node_evaluate_answer(state: CVHRState) -> dict:
    """Node 7: Chấm điểm câu trả lời hiện tại."""
    llm = _get_llm()
    idx = state["current_q_index"]
    q = state["questions"][idx]

    # Lấy câu trả lời cuối cùng của user
    last_human = next(
        (m for m in reversed(state["messages"])
         if isinstance(m, HumanMessage) and m.content is not None),
        None,
    )
    answer_text = last_human.content if last_human else ""

    prompt = build_evaluate_answer_prompt(
        question=q["q"],
        expected_keywords=json.dumps(q.get("expected_keywords", []), ensure_ascii=False),
        answer=answer_text,
        candidate_rank=state["candidate_rank"],
    )

    def _default_evaluation() -> dict:
        return {
            "score": 0,
            "feedback": "Không thể đánh giá tự động câu trả lời này do lỗi hệ thống AI. HR vui lòng xem xét thủ công.",
            "follow_up_suggestion": None,
        }

    result = _safe_llm_json_call(
        llm,
        prompt,
        required_keys=["score", "feedback"],
        default_factory=_default_evaluation,
        label="evaluate_answer",
    )

    # Tự soát lỗi (Layer 5): score phải là số nguyên trong [0, 10].
    try:
        score = int(round(float(result.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(10, score))

    feedback = result.get("feedback") or "Không có nhận xét."

    # Thêm vào answer_scores
    score_entry = {
        "q_index": idx,
        "question": q["q"],
        "category": q["category"],
        "answer": answer_text,
        "score": score,
        "feedback": feedback,
    }
    new_scores = list(state.get("answer_scores", []))
    new_scores.append(score_entry)

    # Feedback cho ứng viên
    feedback_msg = (
        f"📋 **Đánh giá câu {idx + 1}:** {score}/10\n"
        f"💬 {feedback}\n\n---"
    )

    return {
        "answer_scores": new_scores,
        "current_q_index": idx + 1,    # Chuyển sang câu tiếp
        "current_q_attempts": 0,       # Reset bộ đếm retry cho câu hỏi kế tiếp
        "messages": [AIMessage(content=feedback_msg)],
    }


def node_final_evaluate(state: CVHRState) -> dict:
    """Node 8: Tổng kết đánh giá toàn bộ buổi phỏng vấn."""
    llm = _get_llm()

    answer_scores = state.get("answer_scores", [])
    skill_match_score = state.get("skill_match_score", 0.5)

    # Build summary từ answer_scores
    scores_summary = "\n".join([
        f"- Câu {s['q_index']+1} ({s['category']}): {s['score']}/10 — {s['feedback']}"
        for s in answer_scores
    ]) or "(Không có câu trả lời nào được ghi nhận.)"

    market_salary_info = state.get("market_salary_info") or {}

    prompt = build_final_evaluate_prompt(
        candidate_rank=state["candidate_rank"],
        skill_match_score=skill_match_score,
        field_category=state["field_category"],
        answer_scores_summary=scores_summary,
        market_salary_info=json.dumps(market_salary_info, ensure_ascii=False),
    )

    def _default_final_evaluate() -> dict:
        # Fallback: tự tính overall_score theo ĐÚNG công thức trọng số đã
        # định nghĩa trong prompts/interview.py (60% phỏng vấn + 30% skill
        # match + 0% bonus, vì không có LLM để đánh giá định tính phần bonus).
        avg_score = (
            sum(s["score"] for s in answer_scores) / len(answer_scores)
            if answer_scores else 0.0
        )
        overall = round(avg_score * 10 * 0.6 + skill_match_score * 100 * 0.3, 1)
        overall = max(0.0, min(100.0, overall))
        verdict = "PASS" if overall >= 70 else "CONSIDER" if overall >= 50 else "FAIL"
        return {
            "overall_score": overall,
            "final_verdict": verdict,
            "final_summary": (
                "Hệ thống AI gặp lỗi khi tổng hợp đánh giá định tính. Đây là kết quả "
                "tính toán dự phòng dựa trên công thức trọng số chuẩn (60% điểm phỏng "
                "vấn + 30% skill match). Vui lòng HR xem xét thủ công thêm trước khi quyết định."
            ),
        }

    result = _safe_llm_json_call(
        llm,
        prompt,
        required_keys=["overall_score", "final_verdict", "final_summary"],
        default_factory=_default_final_evaluate,
        label="final_evaluate",
    )

    try:
        overall_score = max(0.0, min(100.0, float(result.get("overall_score", 0.0))))
    except (TypeError, ValueError):
        overall_score = 0.0

    verdict = result.get("final_verdict", "CONSIDER")
    if verdict not in VALID_VERDICTS:
        verdict = "PASS" if overall_score >= 70 else "CONSIDER" if overall_score >= 50 else "FAIL"

    final_summary = result.get("final_summary") or "Không có nhận xét tổng kết."
    suggested_salary = result.get("suggested_salary") or {}

    verdict_emoji = {"PASS": "✅", "CONSIDER": "🤔", "FAIL": "❌"}
    emoji = verdict_emoji.get(verdict, "📋")

    salary_line = ""
    if suggested_salary and suggested_salary.get("min"):
        try:
            s_min = int(suggested_salary["min"]) // 1_000_000
            s_max = int(suggested_salary["max"]) // 1_000_000
            salary_line = f"\n- **Đề xuất lương:** {s_min}M – {s_max}M VNĐ/tháng"
        except Exception:
            pass

    summary_msg = (
        f"\n{'='*50}\n"
        f"{emoji} **KẾT QUẢ ĐÁNH GIÁ TỔNG KẾT**\n"
        f"{'='*50}\n\n"
        f"- **Điểm tổng:** {overall_score}/100\n"
        f"- **Kết luận:** {verdict}"
        f"{salary_line}\n\n"
        f"**Nhận xét:**\n{final_summary}"
    )

    return {
        "overall_score": overall_score,
        "final_verdict": verdict,
        "final_summary": final_summary,
        "suggested_salary": suggested_salary,
        "messages": [AIMessage(content=summary_msg)],
    }


def node_cv_improve_subagent(state: CVHRState) -> dict:
    """Node 9: Subagent chuyên sâu phân tích và đề xuất cải thiện CV.

    Tương tự node_tax_subagent trong etax:
    - Nhận toàn bộ context (CV, JD, kết quả phỏng vấn)
    - Tạo báo cáo "CV Improvement Roadmap" chi tiết
    """
    llm = _get_llm()

    prompt = build_cv_improvement_prompt(
        cv_structured=json.dumps(state["cv_structured"], ensure_ascii=False, indent=2),
        jd_text=state["jd_text"],
        candidate_rank=state["candidate_rank"],
        answer_scores=json.dumps(state.get("answer_scores", []), ensure_ascii=False, indent=2),
        weaknesses=json.dumps(state.get("weaknesses", []), ensure_ascii=False),
    )

    try:
        response = llm.invoke([SystemMessage(content=prompt)])
        report = response.content if isinstance(response.content, str) else str(response.content)
    except Exception as e:
        # Node này trả về văn bản tự do (không phải JSON) nên không dùng
        # _safe_llm_json_call được — vẫn cần bọc try/except để một lỗi gọi
        # LLM (vd: timeout/quota) không làm sập graph ở bước gần cuối cùng.
        print(f"[CVHR] ⚠️ [cv_improve_subagent] Lỗi gọi LLM: {e}")
        report = (
            "Không thể sinh báo cáo cải thiện CV tự động do lỗi hệ thống. "
            "Vui lòng tham khảo phần 'Điểm yếu' và 'Đề xuất cải thiện' ở bước phân tích CV ở trên."
        )

    summary_msg = (
        f"\n{'='*50}\n"
        f"📈 **BÁO CÁO CẢI THIỆN CV**\n"
        f"{'='*50}\n\n"
        f"{report}"
    )

    return {
        "cv_improve_report": report,
        "messages": [AIMessage(content=summary_msg)],
    }


def node_generate_pdf(state: CVHRState) -> dict:
    """Node 10: Sinh file PDF Evaluation Report bằng reportlab."""
    from services.tools.pdf_generator import generate_evaluation_pdf

    name = (state.get("cv_structured") or {}).get("name") or "ứng viên"

    try:
        pdf_path = generate_evaluation_pdf(dict(state), output_dir="data/reports")
        summary_msg = (
            f"\n🎉 **Hoàn tất đánh giá cho {name}!**\n\n"
            f"📄 Báo cáo PDF đã được xuất:\n`{pdf_path}`\n\n"
            f"Cảm ơn bạn đã tham gia sơ vấn!"
        )
        return {
            "pdf_generated": True,
            "pdf_path": pdf_path,
            "messages": [AIMessage(content=summary_msg)],
        }
    except Exception as e:
        print(f"[CVHR] ⚠️ [generate_pdf] Lỗi sinh PDF: {e}")
        summary_msg = (
            f"\n🎉 **Hoàn tất đánh giá cho {name}!**\n\n"
            f"⚠️ Không thể sinh file PDF tự động: {e}\n"
            f"Cảm ơn bạn đã tham gia sơ vấn!"
        )
        return {
            "pdf_generated": False,
            "pdf_path": "",
            "messages": [AIMessage(content=summary_msg)],
        }


# ─────────────────────────────────────────────────────────────
# ROUTING FUNCTIONS (Conditional Edges)
# ─────────────────────────────────────────────────────────────

def route_after_human(state: CVHRState) -> Literal["ask_question", "evaluate_answer"]:
    """Sau khi ứng viên nhập câu trả lời (qua interrupt ở node_human):

    - Nếu câu trả lời KHÔNG hợp lệ (trống / quá ngắn / spam ký tự vô nghĩa)
      VÀ chưa hết số lần thử (`MAX_ANSWER_ATTEMPTS`) → quay lại `ask_question`
      để hỏi lại CÙNG câu hỏi đó (current_q_index không đổi), kèm cảnh báo.
    - Nếu câu trả lời hợp lệ, HOẶC đã hết số lần thử lại (tránh treo vòng
      lặp vô hạn với ứng viên cố tình spam) → chuyển sang `evaluate_answer`
      để LLM chấm điểm (câu trả lời tệ vẫn sẽ tự nhiên bị chấm điểm thấp
      theo Layer 3 của prompt EVALUATE_ANSWER_PROMPT).
    """
    last_human = next(
        (m for m in reversed(state["messages"])
         if isinstance(m, HumanMessage) and m.content is not None),
        None,
    )
    answer_text = last_human.content if last_human else ""
    is_valid, _reason = _validate_answer(answer_text)

    attempts = state.get("current_q_attempts", 1)
    if not is_valid and attempts < MAX_ANSWER_ATTEMPTS:
        return "ask_question"
    return "evaluate_answer"


def route_after_evaluate(state: CVHRState) -> Literal["ask_question", "final_evaluate"]:
    """Sau khi chấm 1 câu:
    - Còn câu hỏi chưa hỏi → quay lại ask_question (loop)
    - Đã hỏi hết → chuyển sang đánh giá tổng
    """
    if state["current_q_index"] < len(state["questions"]):
        return "ask_question"
    return "final_evaluate"


# ─────────────────────────────────────────────────────────────
# BUILD GRAPH
# ─────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    """Xây dựng và compile LangGraph State Machine.

    Flow:
      START → parse_cv → analyze_cv → rank_candidate → generate_questions
            → ask_question → human (interrupt)
            → [answer không hợp lệ & còn lượt thử → ask_question (loop) /
               answer hợp lệ hoặc hết lượt thử → evaluate_answer]
            → [còn câu hỏi → ask_question (loop) / hết câu hỏi → final_evaluate]
            → cv_improve_subagent → generate_pdf → END
    """
    builder = StateGraph(CVHRState)

    # ── Đăng ký Nodes ──
    builder.add_node("parse_cv", node_parse_cv)
    builder.add_node("enrich_jd", node_enrich_jd)
    builder.add_node("analyze_cv", node_analyze_cv)
    builder.add_node("rank_candidate", node_rank_candidate)
    builder.add_node("generate_questions", node_generate_questions)
    builder.add_node("ask_question", node_ask_question)
    builder.add_node("human", node_human)
    builder.add_node("evaluate_answer", node_evaluate_answer)
    builder.add_node("final_evaluate", node_final_evaluate)
    builder.add_node("cv_improve_subagent", node_cv_improve_subagent)
    builder.add_node("generate_pdf", node_generate_pdf)

    # ── Normal Edges (đường thẳng, không điều kiện) ──
    builder.add_edge(START, "parse_cv")
    builder.add_edge("parse_cv", "enrich_jd")
    builder.add_edge("enrich_jd", "analyze_cv")
    builder.add_edge("analyze_cv", "rank_candidate")
    builder.add_edge("rank_candidate", "generate_questions")
    builder.add_edge("generate_questions", "ask_question")
    builder.add_edge("ask_question", "human")
    builder.add_edge("final_evaluate", "cv_improve_subagent")
    builder.add_edge("cv_improve_subagent", "generate_pdf")
    builder.add_edge("generate_pdf", END)

    # ── Conditional Edges (có điều kiện, phân nhánh) ──
    builder.add_conditional_edges(
        "human",
        route_after_human,
        {
            "ask_question": "ask_question",
            "evaluate_answer": "evaluate_answer",
        },
    )
    builder.add_conditional_edges(
        "evaluate_answer",
        route_after_evaluate,
        {
            "ask_question": "ask_question",
            "final_evaluate": "final_evaluate",
        },
    )

    return builder.compile(checkpointer=checkpointer)


# ─────────────────────────────────────────────────────────────
# BUILD RUN CONFIG (Langfuse integration)
# ─────────────────────────────────────────────────────────────

def build_run_config(
    session_id: str,
    user_id: str = "anonymous",
    *,
    run_name: str | None = None,
) -> dict:
    """Tạo config truyền vào graph.invoke / astream.

    - configurable.thread_id = session_id → LangGraph checkpoint multi-turn
    - callbacks chứa Langfuse handler (nếu enabled)
    - metadata cho Langfuse trace tagging

    Giống build_run_config() trong etax.
    """
    config: dict = {"configurable": {"thread_id": session_id}}
    if LANGFUSE_ENABLED and _langfuse_handler is not None:
        config["callbacks"] = [_langfuse_handler]
        config["metadata"] = {
            "langfuse_user_id": user_id,
            "langfuse_session_id": session_id,
        }
        if run_name:
            config["run_name"] = run_name
    return config
