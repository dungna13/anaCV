"""
main.py — Entry point cho CVHR AI Agent.

Chạy bằng lệnh:
    python main.py              # Interactive terminal mode
    python main.py --api        # FastAPI server mode (Phase 4)

Terminal mode tương tự run_terminal() trong etax_kekhaithue:
- Upload CV (path) + nhập JD text
- Tự động parse, phân tích, xếp hạng
- Phỏng vấn multi-turn qua interrupt()
- In kết quả đánh giá + báo cáo cải thiện CV
"""

import os
import sys
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from core.graph import build_graph, build_run_config
from core.parser import parse_pdf, parse_text_file
from memory.checkpointer import get_checkpointer


# ─────────────────────────────────────────────────────────────
# TIỆN ÍCH HIỂN THỊ TERMINAL (màu sắc + định dạng)
# ─────────────────────────────────────────────────────────────
# Không thêm dependency mới (vd: colorama/rich) — chỉ dùng mã màu ANSI thuần,
# được hỗ trợ sẵn trên Windows Terminal / VSCode terminal. Với cmd.exe cũ,
# `_enable_windows_ansi()` bật chế độ Virtual Terminal Processing.

class _C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"


def _enable_windows_ansi() -> None:
    """Bật hỗ trợ mã màu ANSI trên cmd.exe/PowerShell cũ của Windows.

    `os.system("")` là một mẹo quen thuộc để Windows kích hoạt chế độ xử lý
    Virtual Terminal — không ảnh hưởng tới các terminal đã hỗ trợ ANSI sẵn
    (Windows Terminal, VSCode integrated terminal).
    """
    if sys.platform == "win32":
        os.system("")


def _print_header(title: str) -> None:
    line = "=" * 60
    print(f"{_C.CYAN}{_C.BOLD}{line}\n{title}\n{line}{_C.RESET}")


def _print_ai(text: str) -> None:
    print(f"\n{_C.CYAN}🤖 AI:{_C.RESET} {text}\n")


def _print_success(text: str) -> None:
    print(f"{_C.GREEN}{text}{_C.RESET}")


def _print_error(text: str) -> None:
    print(f"{_C.RED}{text}{_C.RESET}")


def _print_warning(text: str) -> None:
    print(f"{_C.YELLOW}{text}{_C.RESET}")


def _verdict_color(verdict: str) -> str:
    return {"PASS": _C.GREEN, "CONSIDER": _C.YELLOW, "FAIL": _C.RED}.get(verdict, _C.RESET)


def _extract_text(content) -> str:
    """Trích text từ content (có thể là str hoặc list parts từ Gemini)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "")


def run_terminal() -> None:
    """Chạy CVHR qua terminal — interactive mode.

    Flow:
    1. Nhập đường dẫn file CV (PDF hoặc TXT)
    2. Nhập JD (paste trực tiếp, kết thúc bằng dòng trống)
    3. Hệ thống tự chạy: parse → analyze → rank → sinh câu hỏi
    4. Phỏng vấn multi-turn (interrupt → resume bằng Command(resume=...))
    5. In kết quả đánh giá + cải thiện CV

    Các lỗi không mong muốn (vd: LLM API lỗi mạng/hết quota) được bắt ở
    tầng `graph.invoke` để phiên dừng lại một cách thân thiện, KHÔNG làm
    crash chương trình với traceback khó hiểu cho ứng viên.
    """
    _enable_windows_ansi()

    _print_header("🤖 CVHR — AI Agent Sơ vấn & Tối ưu CV Ứng viên")
    print()

    # ── Bước 1: Nhập CV ──
    cv_path = input("📄 Nhập đường dẫn file CV (PDF/TXT): ").strip().strip('"')
    if not cv_path:
        _print_error("❌ Đường dẫn CV không được để trống!")
        return

    try:
        if cv_path.lower().endswith(".pdf"):
            cv_text = parse_pdf(cv_path)
        else:
            cv_text = parse_text_file(cv_path)
        _print_success(f"✅ Đã đọc CV: {len(cv_text)} ký tự\n")
    except (FileNotFoundError, ValueError) as e:
        _print_error(f"❌ Lỗi đọc CV: {e}")
        return
    except Exception as e:
        # Bắt mọi lỗi không lường trước được khi parse PDF (vd: file PDF
        # hỏng, lỗi thư viện đọc PDF) — không để chương trình crash thô.
        _print_error(f"❌ Lỗi không mong muốn khi đọc CV: {e}")
        return

    # ── Bước 2: Nhập JD ──
    print("📋 Nhập Job Description (JD):")
    print("   (Paste nội dung JD, nhấn Enter 2 lần để kết thúc)")
    print("-" * 40)

    jd_lines = []
    empty_count = 0
    while True:
        line = input()
        if line.strip() == "":
            empty_count += 1
            if empty_count >= 2:
                break
            jd_lines.append("")
        else:
            empty_count = 0
            jd_lines.append(line)

    jd_text = "\n".join(jd_lines).strip()
    if not jd_text:
        _print_error("❌ JD không được để trống!")
        return

    _print_success(f"\n✅ Đã nhận JD: {len(jd_text)} ký tự\n")

    # ── Bước 3: Khởi tạo graph ──
    thread_id = str(uuid.uuid4())
    memory = get_checkpointer()
    graph = build_graph(checkpointer=memory)
    config = build_run_config(thread_id, run_name=f"terminal:{thread_id[:8]}")

    print(f"{_C.DIM}[Phiên: {thread_id[:8]}...]{_C.RESET}\n")
    print("🚀 Bắt đầu phân tích...\n")

    # ── Bước 4: Chạy graph ──
    current_input = {
        "messages": [HumanMessage(content="Bắt đầu sơ vấn ứng viên")],
        "cv_raw_text": cv_text,
        "jd_text": jd_text,
        "session_id": thread_id,
    }

    while True:
        try:
            result = graph.invoke(current_input, config=config)
        except Exception as e:
            # Lớp bảo vệ cuối cùng: nếu graph crash vì lý do không lường
            # trước (mạng, quota API, bug...), dừng phiên một cách rõ ràng
            # thay vì để traceback đè lên trải nghiệm của ứng viên.
            _print_error(f"\n❌ Lỗi hệ thống không mong muốn: {e}")
            _print_error("Phiên làm việc đã bị dừng. Vui lòng thử lại sau.")
            return

        # Kiểm tra interrupt (đợi ứng viên trả lời)
        interrupts = result.get("__interrupt__")
        if interrupts:
            prompt_text = interrupts[0].value
            _print_ai(_extract_text(prompt_text))
            user_input = input(f"{_C.YELLOW}👤 Bạn:{_C.RESET} ").strip()

            if user_input.lower() in {"exit", "quit", "thoát", "q"}:
                print(f"\n{_C.MAGENTA}👋 Đã thoát phiên. Cảm ơn bạn!{_C.RESET}")
                return

            # Lưu ý: ứng viên có thể gửi chuỗi rỗng/quá ngắn/spam — graph tự
            # xử lý các trường hợp này (xem route_after_human trong
            # core/graph.py) bằng cách hỏi lại tối đa MAX_ANSWER_ATTEMPTS lần,
            # main.py không cần validate lại ở đây.
            current_input = Command(resume=user_input)
            continue

        # Graph kết thúc — in message cuối
        last = result["messages"][-1]
        if isinstance(last, AIMessage):
            text = _extract_text(last.content)
            if text:
                _print_ai(text)

        _print_header("🎉 [Phiên kết thúc]")

        # In tổng kết nhanh
        if result.get("final_verdict"):
            verdict = result["final_verdict"]
            score = result.get("overall_score", 0)
            rank = result.get("candidate_rank", "N/A")
            color = _verdict_color(verdict)
            print(f"\n📊 {_C.BOLD}Tóm tắt:{_C.RESET}")
            print(f"   - Level: {rank.upper()}")
            print(f"   - Điểm tổng: {score}/100")
            print(f"   - Kết luận: {color}{_C.BOLD}{verdict}{_C.RESET}")

        return


if __name__ == "__main__":
    if "--api" in sys.argv:
        # Phase 4: Start FastAPI server
        print("API mode chưa được triển khai (Phase 4).")
        print("Sử dụng: python main.py  (terminal mode)")
    else:
        run_terminal()
