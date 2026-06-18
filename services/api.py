"""
services/api.py — FastAPI server cho CVHR AI Agent.

Endpoints:
  POST /api/session/start   — Upload CV + JD, bắt đầu phiên phỏng vấn (SSE stream)
  POST /api/session/message — Resume interrupt (ứng viên trả lời câu hỏi, SSE stream)
  GET  /api/session/{id}    — Lấy trạng thái phiên hiện tại
  GET  /health              — Health check

SSE streaming tương tự etax_kekhaithue: graph.stream() → yield event data qua EventSourceResponse.
"""

import json
import os
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from langgraph.types import Command
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config.settings import get_settings
from core.graph import build_graph, build_run_config
from core.parser import parse_pdf, parse_text_file
from memory.checkpointer import get_checkpointer

settings = get_settings()

app = FastAPI(
    title="CVHR AI Agent API",
    description="AI Agent Sơ vấn & Tối ưu CV Ứng viên",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton graph (dùng chung checkpointer cho tất cả sessions)
_checkpointer = get_checkpointer()
_graph = build_graph(checkpointer=_checkpointer)

# Serve static frontend — thư mục static/ nằm cùng cấp với services/
_STATIC_DIR = Path(__file__).parent.parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ─────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    session_id: str
    message: str


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _extract_text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    return str(content or "")


async def _stream_graph(
    graph_input: dict | Command,
    config: dict,
) -> AsyncGenerator[dict, None]:
    """Stream graph events thành SSE events.

    Mỗi event có dạng:
      {"type": "message", "content": "..."}   — AI message
      {"type": "interrupt", "content": "..."}  — interrupt (đợi user)
      {"type": "done", "state": {...}}          — graph kết thúc
      {"type": "error", "detail": "..."}        — lỗi
    """
    try:
        for chunk in _graph.stream(graph_input, config=config, stream_mode="values"):
            # chunk là snapshot state sau mỗi node
            # Lấy message mới nhất nếu có
            messages = chunk.get("messages") or []
            if messages:
                last = messages[-1]
                if isinstance(last, AIMessage):
                    text = _extract_text_from_content(last.content)
                    if text:
                        yield {"type": "message", "content": text}

        # Kiểm tra interrupt sau stream
        state = _graph.get_state(config)
        if state.next and state.tasks:
            for task in state.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_val = task.interrupts[0].value
                    prompt_text = _extract_text_from_content(interrupt_val)
                    yield {"type": "interrupt", "content": prompt_text}
                    return

        # Graph kết thúc bình thường
        final_state = state.values
        summary = {
            "session_id": config["configurable"]["thread_id"],
            "candidate_rank": final_state.get("candidate_rank"),
            "overall_score": final_state.get("overall_score"),
            "final_verdict": final_state.get("final_verdict"),
            "pdf_path": final_state.get("pdf_path"),
            "suggested_salary": final_state.get("suggested_salary"),
        }
        yield {"type": "done", "state": summary}

    except Exception as e:
        yield {"type": "error", "detail": str(e)}


def _sse_generator(graph_input: dict | Command, config: dict):
    """Wrap async generator thành SSE format (dùng cho /api/session/message)."""
    async def generator():
        async for event in _stream_graph(graph_input, config):
            yield {"data": json.dumps(event, ensure_ascii=False)}
    return generator()


# ─────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "CVHR AI Agent"}


@app.post("/api/session/start")
async def session_start(
    cv_file: UploadFile = File(..., description="File CV (PDF hoặc TXT)"),
    jd_text: str = Form(default="", description="Nội dung JD (có thể để trống)"),
    user_id: str = Form(default="anonymous"),
):
    """Upload CV + JD và bắt đầu phiên phỏng vấn.

    Stream SSE events trong quá trình graph chạy (parse → analyze → rank →
    generate_questions → câu hỏi đầu tiên).

    Returns SSE stream.
    """
    # Đọc file CV
    filename = cv_file.filename or ""
    content_bytes = await cv_file.read()

    try:
        import tempfile
        suffix = Path(filename).suffix.lower() if filename else ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content_bytes)
            tmp_path = tmp.name
        try:
            if suffix == ".pdf":
                cv_text = parse_pdf(tmp_path)
            else:
                cv_text = parse_text_file(tmp_path)
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không đọc được file CV: {e}")

    if not cv_text or len(cv_text.strip()) < 50:
        raise HTTPException(status_code=400, detail="File CV trống hoặc không có nội dung.")

    session_id = str(uuid.uuid4())
    config = build_run_config(session_id, user_id=user_id, run_name=f"api:{session_id[:8]}")

    graph_input = {
        "cv_raw_text": cv_text,
        "jd_text": jd_text.strip(),
        "session_id": session_id,
    }

    async def _generator_with_session_id():
        # Emit session_id ngay lập tức để frontend lưu lại trước khi stream bắt đầu
        yield {"data": json.dumps({"type": "session_start", "session_id": session_id}, ensure_ascii=False)}
        async for evt in _stream_graph(graph_input, config):
            yield {"data": json.dumps(evt, ensure_ascii=False)}

    return EventSourceResponse(_generator_with_session_id())


@app.post("/api/session/message")
async def session_message(req: MessageRequest):
    """Resume phiên phỏng vấn với câu trả lời của ứng viên.

    Gọi sau khi nhận event {"type": "interrupt"} từ /api/session/start
    hoặc lần gọi message trước.

    Returns SSE stream tiếp tục từ điểm interrupt.
    """
    if not req.session_id:
        raise HTTPException(status_code=400, detail="session_id là bắt buộc.")

    config = build_run_config(req.session_id, run_name=f"api:{req.session_id[:8]}")

    # Kiểm tra session tồn tại
    try:
        state = _graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy phiên '{req.session_id}'.")

    if not state.next:
        raise HTTPException(status_code=400, detail="Phiên đã kết thúc hoặc không ở trạng thái chờ input.")

    command = Command(resume=req.message)
    return EventSourceResponse(_sse_generator(command, config))


@app.get("/api/session/{session_id}")
async def session_status(session_id: str):
    """Lấy trạng thái hiện tại của phiên (không streaming)."""
    config = build_run_config(session_id)
    try:
        state = _graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy phiên '{session_id}'.")

    values = state.values
    return JSONResponse({
        "session_id": session_id,
        "is_waiting": bool(state.next),
        "next_nodes": list(state.next) if state.next else [],
        "candidate_rank": values.get("candidate_rank"),
        "current_q_index": values.get("current_q_index"),
        "questions_total": len(values.get("questions") or []),
        "overall_score": values.get("overall_score"),
        "final_verdict": values.get("final_verdict"),
        "pdf_path": values.get("pdf_path"),
        "suggested_salary": values.get("suggested_salary"),
        "jd_source": values.get("jd_source"),
    })


@app.get("/api/download")
async def download_pdf(path: str):
    """Tải file PDF đã sinh từ đường dẫn tuyệt đối."""
    abs_path = os.path.abspath(path)
    # Chỉ cho phép tải file trong thư mục data/reports
    allowed_dir = os.path.abspath("data/reports")
    if not abs_path.startswith(allowed_dir):
        raise HTTPException(status_code=403, detail="Không được phép truy cập file này.")
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="File PDF không tồn tại.")
    return FileResponse(
        abs_path,
        media_type="application/pdf",
        filename=os.path.basename(abs_path),
    )


@app.get("/")
async def serve_index():
    """Serve frontend SPA."""
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend chưa được build.")
    return FileResponse(str(index), media_type="text/html")
