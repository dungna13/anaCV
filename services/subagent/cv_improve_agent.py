"""
Subagent cải thiện CV — Phân tích CV chuyên sâu và đề xuất roadmap cải thiện.

Tương tự services/subagent/occupation_classify_agent.py trong etax:
- Có thể hoạt động như graph con riêng (Phase 3+)
- Phase 1: chạy đơn giản qua 1 LLM call trong node_cv_improve_subagent
"""

# Phase 1: Logic subagent nằm trực tiếp trong node_cv_improve_subagent (core/graph.py)
# Phase 3: Sẽ tách thành graph con riêng với state riêng

# Placeholder cho Phase 3:
# from langgraph.graph import StateGraph, END, START
# from typing_extensions import TypedDict
#
# class CVImproveState(TypedDict, total=False):
#     cv_structured: dict
#     jd_text: str
#     candidate_rank: str
#     weaknesses: list
#     answer_scores: list
#     improvement_report: str
#     done: bool
#
# def build_cv_improve_graph():
#     builder = StateGraph(CVImproveState)
#     # ... add nodes and edges
#     return builder.compile()
