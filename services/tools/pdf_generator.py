"""
PDF Generator — Xuất Evaluation Report PDF bằng reportlab.

Tạo file PDF "Candidate Evaluation Report" chứa:
- Thông tin ứng viên (từ cv_structured)
- Kết quả phân tích CV vs JD (strengths/weaknesses/skill_match_score)
- Level xếp hạng (candidate_rank)
- Điểm từng câu phỏng vấn (answer_scores)
- Đánh giá tổng kết (overall_score, final_verdict, final_summary)
- Báo cáo cải thiện CV (cv_improve_report)
"""

import os
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ─────────────────────────────────────────────────────────────
# MÀU SẮC & STYLE
# ─────────────────────────────────────────────────────────────

_PRIMARY = colors.HexColor("#1E40AF")    # Xanh đậm
_SUCCESS = colors.HexColor("#15803D")   # Xanh lá
_DANGER  = colors.HexColor("#B91C1C")   # Đỏ
_WARNING = colors.HexColor("#B45309")   # Cam/vàng
_LIGHT   = colors.HexColor("#EFF6FF")   # Nền xanh nhạt
_GRAY    = colors.HexColor("#6B7280")   # Xám

_VERDICT_COLOR = {
    "PASS":      _SUCCESS,
    "CONSIDER":  _WARNING,
    "FAIL":      _DANGER,
}


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle(
        "title", parent=base["Title"],
        textColor=_PRIMARY, fontSize=18, spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    styles["section"] = ParagraphStyle(
        "section", parent=base["Heading2"],
        textColor=_PRIMARY, fontSize=13, spaceBefore=14, spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    styles["body"] = ParagraphStyle(
        "body", parent=base["Normal"],
        fontSize=10, leading=15, spaceAfter=4,
        fontName="Helvetica",
    )
    styles["small"] = ParagraphStyle(
        "small", parent=base["Normal"],
        fontSize=9, textColor=_GRAY, leading=13,
        fontName="Helvetica",
    )
    styles["bullet"] = ParagraphStyle(
        "bullet", parent=base["Normal"],
        fontSize=10, leading=15, leftIndent=12, spaceAfter=2,
        fontName="Helvetica",
    )
    styles["verdict"] = ParagraphStyle(
        "verdict", parent=base["Normal"],
        fontSize=20, fontName="Helvetica-Bold", alignment=1,
    )
    return styles


def _hr(styles):
    return HRFlowable(width="100%", thickness=1, color=_PRIMARY, spaceAfter=6, spaceBefore=6)


def _section_header(text: str, styles: dict):
    return Paragraph(f"▌ {text}", styles["section"])


def _bullet_items(items: list[str], styles: dict, prefix: str = "•") -> list:
    return [Paragraph(f"{prefix} {item}", styles["bullet"]) for item in items if item]


# ─────────────────────────────────────────────────────────────
# BUILD NỘI DUNG PDF
# ─────────────────────────────────────────────────────────────

def _build_content(state: dict, styles: dict) -> list:
    elements = []

    cv = state.get("cv_structured") or {}
    name = cv.get("name") or "N/A"
    email = cv.get("email") or "N/A"
    phone = cv.get("phone") or "N/A"
    rank = state.get("candidate_rank", "N/A").upper()
    years = state.get("years_of_experience", 0)
    field = state.get("field_category", "N/A").upper()
    verdict = state.get("final_verdict", "N/A")
    overall_score = state.get("overall_score", 0)
    skill_match = state.get("skill_match_score", 0)
    final_summary = state.get("final_summary") or ""
    strengths = state.get("strengths") or []
    weaknesses = state.get("weaknesses") or []
    cv_improvements = state.get("cv_improvements") or []
    answer_scores = state.get("answer_scores") or []
    cv_improve_report = state.get("cv_improve_report") or ""
    rank_reasoning = state.get("rank_reasoning") or ""
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ── Tiêu đề ──
    elements.append(Paragraph("CANDIDATE EVALUATION REPORT", styles["title"]))
    elements.append(Paragraph(
        f"<font color='#6B7280' size='9'>Sinh bởi CVHR AI Agent — {generated_at}</font>",
        styles["small"],
    ))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(_hr(styles))

    # ── Thông tin ứng viên ──
    elements.append(_section_header("THÔNG TIN ỨNG VIÊN", styles))
    info_data = [
        ["Họ tên:", name, "Email:", email],
        ["Điện thoại:", phone, "Lĩnh vực:", field],
        ["Level:", rank, "Kinh nghiệm:", f"~{years:.1f} năm"],
    ]
    info_table = Table(info_data, colWidths=[3 * cm, 7 * cm, 3 * cm, 7 * cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TEXTCOLOR", (0, 0), (0, -1), _PRIMARY),
        ("TEXTCOLOR", (2, 0), (2, -1), _PRIMARY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.2 * cm))

    if rank_reasoning:
        elements.append(Paragraph(f"<i>Lý do xếp hạng: {rank_reasoning}</i>", styles["small"]))

    elements.append(Spacer(1, 0.3 * cm))
    elements.append(_hr(styles))

    # ── Kết quả tổng kết ──
    elements.append(_section_header("KẾT QUẢ ĐÁNH GIÁ", styles))

    verdict_color = _VERDICT_COLOR.get(verdict, _GRAY)
    score_data = [
        ["Điểm tổng:", f"{overall_score:.1f}/100",
         "Skill Match:", f"{skill_match:.0%}"],
        ["Kết luận:", verdict, "", ""],
    ]
    score_table = Table(score_data, colWidths=[3.5 * cm, 6.5 * cm, 3.5 * cm, 6.5 * cm])
    score_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTSIZE", (1, 1), (1, 1), 14),
        ("TEXTCOLOR", (0, 0), (0, -1), _PRIMARY),
        ("TEXTCOLOR", (2, 0), (2, -1), _PRIMARY),
        ("TEXTCOLOR", (1, 1), (1, 1), verdict_color),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("SPAN", (1, 1), (3, 1)),
    ]))
    elements.append(score_table)

    if final_summary:
        elements.append(Spacer(1, 0.2 * cm))
        elements.append(Paragraph("<b>Nhận xét tổng kết:</b>", styles["body"]))
        elements.append(Paragraph(final_summary, styles["body"]))

    elements.append(Spacer(1, 0.3 * cm))
    elements.append(_hr(styles))

    # ── Phân tích CV vs JD ──
    elements.append(_section_header("PHÂN TÍCH CV vs JD", styles))

    if strengths:
        elements.append(Paragraph("<b>✅ Điểm mạnh:</b>", styles["body"]))
        elements.extend(_bullet_items(strengths, styles, "✓"))
        elements.append(Spacer(1, 0.15 * cm))

    if weaknesses:
        elements.append(Paragraph("<b>⚠️ Điểm yếu / Thiếu sót:</b>", styles["body"]))
        elements.extend(_bullet_items(weaknesses, styles, "✗"))
        elements.append(Spacer(1, 0.15 * cm))

    if cv_improvements:
        elements.append(Paragraph("<b>💡 Đề xuất cải thiện CV:</b>", styles["body"]))
        elements.extend(_bullet_items(cv_improvements, styles, "→"))

    elements.append(Spacer(1, 0.3 * cm))
    elements.append(_hr(styles))

    # ── Điểm phỏng vấn từng câu ──
    if answer_scores:
        elements.append(_section_header("CHI TIẾT ĐIỂM PHỎNG VẤN", styles))

        table_data = [["#", "Câu hỏi", "Loại", "Điểm", "Nhận xét"]]
        for s in answer_scores:
            q_text = (s.get("question") or "")[:80]
            if len(s.get("question") or "") > 80:
                q_text += "..."
            feedback = (s.get("feedback") or "")[:120]
            if len(s.get("feedback") or "") > 120:
                feedback += "..."
            score_val = s.get("score", 0)
            table_data.append([
                str(s.get("q_index", 0) + 1),
                Paragraph(q_text, styles["small"]),
                s.get("category", ""),
                f"{score_val}/10",
                Paragraph(feedback, styles["small"]),
            ])

        score_table = Table(
            table_data,
            colWidths=[0.8 * cm, 5.5 * cm, 2 * cm, 1.5 * cm, 7 * cm],
            repeatRows=1,
        )
        score_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (3, 0), (3, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(score_table)
        elements.append(Spacer(1, 0.3 * cm))
        elements.append(_hr(styles))

    # ── Đề xuất lương & Benchmark thị trường ──
    market_salary_info = state.get("market_salary_info") or {}
    suggested_salary = state.get("suggested_salary") or {}
    if market_salary_info or suggested_salary:
        elements.append(_section_header("ĐỀ XUẤT LƯƠNG & BENCHMARK THỊ TRƯỜNG", styles))
        salary_data = []
        if market_salary_info.get("salary_display"):
            salary_data.append(["Lương thị trường:", market_salary_info["salary_display"]])
        if suggested_salary.get("min") and suggested_salary.get("max"):
            try:
                s_min = int(suggested_salary["min"]) // 1_000_000
                s_max = int(suggested_salary["max"]) // 1_000_000
                currency = suggested_salary.get("currency", "VNĐ/tháng")
                salary_data.append(["Đề xuất cho ứng viên:", f"{s_min}M – {s_max}M {currency}"])
            except Exception:
                pass
        if salary_data:
            sal_table = Table(salary_data, colWidths=[5 * cm, 15 * cm])
            sal_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), _PRIMARY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ]))
            elements.append(sal_table)
        rationale = suggested_salary.get("rationale") or market_salary_info.get("note") or ""
        if rationale:
            elements.append(Spacer(1, 0.15 * cm))
            elements.append(Paragraph(f"<i>{rationale}</i>", styles["small"]))
        elements.append(Spacer(1, 0.3 * cm))
        elements.append(_hr(styles))

    # ── Báo cáo cải thiện CV ──
    if cv_improve_report:
        elements.append(_section_header("BÁO CÁO CẢI THIỆN CV (CV IMPROVEMENT ROADMAP)", styles))
        # Split theo dòng để giữ định dạng
        for line in cv_improve_report.splitlines():
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 0.1 * cm))
                continue
            if line.startswith("##"):
                elements.append(Paragraph(f"<b>{line.lstrip('#').strip()}</b>", styles["body"]))
            elif line.startswith("#"):
                elements.append(Paragraph(f"<b><u>{line.lstrip('#').strip()}</u></b>", styles["body"]))
            elif line.startswith(("- ", "• ", "* ")):
                elements.append(Paragraph(f"• {line[2:]}", styles["bullet"]))
            else:
                elements.append(Paragraph(line, styles["body"]))

    return elements


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

def generate_evaluation_pdf(state: dict, output_dir: str = "data/reports") -> str:
    """Sinh file PDF Evaluation Report từ state của CVHR graph.

    Args:
        state: Toàn bộ state từ graph (CVHRState dict).
        output_dir: Thư mục lưu file PDF output.

    Returns:
        Đường dẫn tuyệt đối đến file PDF đã sinh.

    Raises:
        OSError: Nếu không tạo được thư mục hoặc ghi file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    cv = state.get("cv_structured") or {}
    name_raw = (cv.get("name") or "candidate").lower()
    safe_name = "".join(c if c.isalnum() else "_" for c in name_raw).strip("_")[:30]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"eval_{safe_name}_{timestamp}.pdf"
    output_path = str(Path(output_dir) / filename)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = _build_styles()
    elements = _build_content(state, styles)
    doc.build(elements)

    return os.path.abspath(output_path)
