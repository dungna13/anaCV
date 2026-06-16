"""
Checkpointer Factory — Tạo checkpointer cho LangGraph.

Phase 1: Sử dụng MemorySaver (RAM) — đơn giản, không cần DB.
Phase 5+: Có thể upgrade lên MySQL/PostgreSQL checkpointer.
"""

from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer():
    """Trả về checkpointer instance.

    Hiện tại dùng MemorySaver (in-memory). Dữ liệu mất khi restart server.
    Upgrade: thay bằng SqliteSaver hoặc AsyncMySQLCheckpointer khi cần persist.
    """
    return MemorySaver()
