from pathlib import Path
from uuid import uuid4
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.utils import ImageReader


INK = colors.HexColor("#F5F3EF")
MUTED = colors.HexColor("#A9A6B3")
GREEN = colors.HexColor("#A78BFA")
LIGHT_GREEN = colors.HexColor("#30284A")
BORDER = colors.HexColor("#464451")
PALE = colors.HexColor("#1E1E26")


def _logo_path() -> Path:
    configured = os.getenv("UPSERVE_LOGO_PATH")
    return Path(configured) if configured else Path(__file__).resolve().parents[1] / "assets" / "logo.png"


def _money(value: object) -> str:
    try:
        return f"INR {float(value):,.2f}"
    except (TypeError, ValueError):
        return "INR 0.00"


def _safe_text(value: object, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("quotation-body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=INK, spaceAfter=0),
        "muted": ParagraphStyle("quotation-muted", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=MUTED, spaceAfter=0),
        "small": ParagraphStyle("quotation-small", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=11, textColor=MUTED, spaceAfter=0),
        "label": ParagraphStyle("quotation-label", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=GREEN, spaceAfter=0),
        "title": ParagraphStyle("quotation-title", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=26, leading=30, textColor=INK, spaceAfter=0),
        "section": ParagraphStyle("quotation-section", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=GREEN, spaceBefore=0, spaceAfter=7),
        "right": ParagraphStyle("quotation-right", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=13, textColor=INK, alignment=TA_RIGHT, spaceAfter=0),
        "right_bold": ParagraphStyle("quotation-right-bold", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=INK, alignment=TA_RIGHT, spaceAfter=0),
    }


def _header_footer(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    margin = 18 * mm
    canvas.setFillColor(colors.HexColor("#101014"))
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#101014"))
    canvas.rect(0, height - 35 * mm, width, 35 * mm, fill=1, stroke=0)
    logo = _logo_path()
    if logo.exists():
        canvas.drawImage(ImageReader(str(logo)), margin, height - 31 * mm, width=27 * mm, height=27 * mm, mask="auto", preserveAspectRatio=True, anchor='sw')
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(margin, 12 * mm, "Build Digital Products That Scale")
    canvas.drawRightString(width - margin, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def generate_quotation_pdf(data: dict, save_dir: Path) -> str:
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"quotation_{uuid4().hex}.pdf"
    styles = _styles()
    margin = 18 * mm
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=A4,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=45 * mm,
        bottomMargin=22 * mm,
        title=f"Quotation {_safe_text(data.get('quotation_number'))}",
        author="Upserve",
    )
    width = A4[0] - (2 * margin)
    story = []

    metadata = [
        [Paragraph("QUOTATION", styles["label"]), Paragraph(_safe_text(data.get("quotation_number")), styles["right_bold"])],
        [Paragraph("DATE", styles["label"]), Paragraph(_safe_text(data.get("issued_on")), styles["right"])],
        [Paragraph("VALID FOR", styles["label"]), Paragraph(f"{_safe_text(data.get('validity'), '0')} days", styles["right"])],
    ]
    intro = Table([
        [Paragraph("Proposal for your next digital product", styles["title"]), Table(metadata, colWidths=[30 * mm, 38 * mm])],
        [Paragraph("Prepared by Upserve for a clear, collaborative engagement.", styles["muted"]), ""],
    ], colWidths=[width - 72 * mm, 72 * mm])
    intro.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("SPAN", (0, 1), (1, 1)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([intro, Spacer(1, 12 * mm)])

    client_table = Table([
        [Paragraph("PREPARED FOR", styles["label"]), Paragraph("PROJECT DETAILS", styles["label"])],
        [Paragraph(f"<b>{_safe_text(data.get('client_name'), 'Client')}</b><br/>{_safe_text(data.get('client_email'))}", styles["body"]), Paragraph(f"<b>{_safe_text(data.get('project_title'), 'Your project')}</b><br/>{_safe_text(data.get('timeline'), 'Timeline to be confirmed')}", styles["body"])],
    ], colWidths=[width / 2, width / 2])
    client_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.extend([client_table, Spacer(1, 12 * mm), Paragraph("SCOPE AND PRICING", styles["section"])])

    rows = [[Paragraph("SERVICE / DELIVERABLE", styles["label"]), Paragraph("DESCRIPTION", styles["label"]), Paragraph("QTY", styles["label"]), Paragraph("UNIT PRICE", styles["label"]), Paragraph("TOTAL", styles["label"])]]
    services = data.get("services", []) or []
    for index, item in enumerate(data.get("items", []) or []):
        rows.append([
            Paragraph(_safe_text(item.get("service") or (services[index] if index < len(services) else None), "Service"), styles["body"]),
            Paragraph(_safe_text(item.get("description")), styles["muted"]),
            Paragraph(_safe_text(item.get("quantity"), "1"), styles["right"]),
            Paragraph(_money(item.get("unitPrice")), styles["right"]),
            Paragraph(_money(item.get("total")), styles["right_bold"]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("Professional digital delivery", styles["body"]), Paragraph("As discussed with the Upserve team.", styles["muted"]), Paragraph("1", styles["right"]), Paragraph(_money(data.get("total_amount")), styles["right"]), Paragraph(_money(data.get("total_amount")), styles["right_bold"])])
    items_table = Table(rows, colWidths=[34 * mm, 66 * mm, 14 * mm, 28 * mm, 30 * mm], repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    story.extend([items_table, Spacer(1, 8 * mm)])

    total_table = Table([[Paragraph("TOTAL INVESTMENT", styles["label"]), Paragraph(_money(data.get("total_amount")), ParagraphStyle("total", parent=styles["right_bold"], fontSize=17, leading=20))]], colWidths=[width - 55 * mm, 55 * mm])
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(total_table)

    details = []
    if data.get("terms"):
        details.append([Paragraph("PAYMENT TERMS & CONDITIONS", styles["section"]), Paragraph(_safe_text(data.get("terms")), styles["body"])])
    if data.get("notes"):
        details.append([Paragraph("ADDITIONAL NOTES", styles["section"]), Paragraph(_safe_text(data.get("notes")), styles["body"])])
    if details:
        detail_table = Table(details, colWidths=[55 * mm, width - 55 * mm])
        detail_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.extend([Spacer(1, 8 * mm), detail_table])
    story.extend([Spacer(1, 8 * mm), Paragraph("This quotation is a proposal for discussion and is valid for the period shown above. We look forward to building something useful with you.", styles["small"])])

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return str(file_path)
