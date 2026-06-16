"""
tests/test_graph_flow.py — Unit tests cho cấu trúc LangGraph và hàm phụ trợ.
"""

from core.graph import (
    build_graph,
    build_run_config,
    route_after_human,
    route_after_evaluate,
    _validate_answer,
    _extract_json,
)


def test_validate_answer():
    """Kiểm tra tầng lọc câu trả lời (input validation) không tốn token."""
    # Hợp lệ
    is_valid, _ = _validate_answer("Tôi đã dùng Docker để tối ưu hóa việc phân phối ứng dụng trong dự án E-commerce.")
    assert is_valid is True

    # Trống / None
    is_valid, reason = _validate_answer("")
    assert is_valid is False
    assert reason == "trống"

    is_valid, _ = _validate_answer("    ")
    assert is_valid is False

    # Quá ngắn
    is_valid, reason = _validate_answer("ab")
    assert is_valid is False
    assert "ngắn" in reason

    # Ký tự đặc biệt spam
    is_valid, reason = _validate_answer("?????????")
    assert is_valid is False
    assert "spam" in reason or "nghĩa" in reason


def test_extract_json_with_thought():
    """Kiểm tra hàm trích xuất JSON khi LLM trả về có kèm thẻ <thought>."""
    response_text = """
    <thought>
    - Trích xuất thông tin học vấn và kinh nghiệm.
    - Đã kiểm tra lớp chống ảo tưởng.
    </thought>
    ```json
    {
      "name": "Nguyễn Văn Minh",
      "email": "minh.nguyen@email.com"
    }
    ```
    """
    data = _extract_json(response_text)
    assert isinstance(data, dict)
    assert data["name"] == "Nguyễn Văn Minh"
    assert data["email"] == "minh.nguyen@email.com"


def test_build_run_config():
    """Kiểm tra khởi tạo config luồng chính xác."""
    config = build_run_config(session_id="test-session-123", user_id="user-456")
    assert config["configurable"]["thread_id"] == "test-session-123"


def test_route_after_human():
    """Kiểm tra điều hướng rẽ nhánh sau khi nhận input từ con người."""
    from langchain_core.messages import HumanMessage
    
    # Khi câu trả lời hợp lệ
    state_valid = {
        "messages": [HumanMessage(content="Tôi đã làm việc với Python được 2 năm.")],
        "current_q_attempts": 1
    }
    next_node = route_after_human(state_valid)
    assert next_node == "evaluate_answer"

    # Khi câu trả lời không hợp lệ (trống) và còn lượt thử
    state_invalid = {
        "messages": [HumanMessage(content="")],
        "current_q_attempts": 1
    }
    next_node = route_after_human(state_invalid)
    assert next_node == "ask_question"



def test_route_after_evaluate():
    """Kiểm tra điều hướng rẽ nhánh lặp câu hỏi phỏng vấn."""
    # Còn câu hỏi tiếp theo
    state_has_more = {
        "current_q_index": 2,
        "questions": [1, 2, 3, 4, 5]
    }
    next_node = route_after_evaluate(state_has_more)
    assert next_node == "ask_question"

    # Đã hỏi hết tất cả các câu hỏi
    state_finished = {
        "current_q_index": 5,
        "questions": [1, 2, 3, 4, 5]
    }
    next_node = route_after_evaluate(state_finished)
    assert next_node == "final_evaluate"


def test_graph_compile():
    """Kiểm tra đồ thị LangGraph build và compile thành công."""
    graph = build_graph()
    assert graph is not None
    # Kiểm tra các node cốt lõi đã được add vào graph
    node_names = graph.nodes.keys()
    assert "parse_cv" in node_names
    assert "analyze_cv" in node_names
    assert "rank_candidate" in node_names
    assert "human" in node_names
