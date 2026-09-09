from pathlib import Path
from uuid import uuid4
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
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


def _display_date(value: object) -> str:
    text = str(value or "").strip()
    if not text or text in {"N/A", "None", "null"}:
        return "-"
    try:
        from datetime import datetime
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return text


def _text(c: canvas.Canvas, value: object, x: float, y: float, size: float = 10, color=INK, bold=False) -> None:
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, str(value))


def _right_text(c: canvas.Canvas, value: object, x: float, y: float, size: float = 10, color=INK, bold=False) -> None:
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawRightString(x, y, str(value))


def _paragraph(c: canvas.Canvas, value: str, x: float, y: float, width: float, size: float = 9.5, color=INK, leading: float = 14) -> float:
    style = ParagraphStyle("invoice-copy", fontName="Helvetica", fontSize=size, leading=leading, textColor=color, spaceAfter=0)
    paragraph = Paragraph(str(value or "-"), style)
    _, height = paragraph.wrap(width, 100 * mm)
    paragraph.drawOn(c, x, y - height)
    return height


def _line(c: canvas.Canvas, x1: float, y: float, x2: float, color=BORDER, thickness: float = 0.8) -> None:
    c.setStrokeColor(color)
    c.setLineWidth(thickness)
    c.line(x1, y, x2, y)


def generate_invoice_pdf(data: dict, save_dir: Path) -> str:
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"invoice_{uuid4().hex}.pdf"
    file_path = save_dir / filename

    c = canvas.Canvas(str(file_path), pagesize=A4)
    width, height = A4
    margin = 22 * mm
    right = width - margin
    content_width = right - margin

    c.setFillColor(colors.HexColor("#101014"))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#101014"))
    c.rect(0, height - 48 * mm, width, 48 * mm, fill=1, stroke=0)
    logo = _logo_path()
    if logo.exists():
        c.drawImage(ImageReader(str(logo)), margin, height - 43 * mm, width=32 * mm, height=32 * mm, mask="auto", preserveAspectRatio=True, anchor='sw')
    _right_text(c, "INVOICE", right, height - 18 * mm, 25, colors.white, True)
    _right_text(c, f"#{data['invoice_number']}", right, height - 27 * mm, 10, colors.HexColor("#C9D8CE"))

    y = height - 65 * mm
    _text(c, "BILL TO", margin, y, 8, GREEN, True)
    _text(c, data.get("client_name", "Client"), margin, y - 7 * mm, 13, INK, True)
    _text(c, data.get("client_email", ""), margin, y - 13 * mm, 9.5, MUTED)

    meta_x = width - 83 * mm
    _text(c, "ISSUE DATE", meta_x, y, 8, MUTED, True)
    _right_text(c, _display_date(data.get("generated_on")), right, y, 10, INK, True)
    _text(c, "DUE DATE", meta_x, y - 8 * mm, 8, MUTED, True)
    _right_text(c, _display_date(data.get("deadline")), right, y - 8 * mm, 10, INK, True)
    _text(c, "STATUS", meta_x, y - 16 * mm, 8, MUTED, True)
    status = str(data.get("status", "issued")).replace("_", " ").title()
    _right_text(c, status, right, y - 16 * mm, 10, GREEN, True)
    stage = str(data.get("stage", "final")).replace("_", " ").title()
    percentage = data.get("percentage", 100)
    _text(c, "PAYMENT STAGE", meta_x, y - 24 * mm, 8, MUTED, True)
    _right_text(c, f"{stage} · {percentage}%", right, y - 24 * mm, 10, INK, True)

    y -= 31 * mm
    _line(c, margin, y, right)
    y -= 12 * mm
    _text(c, "PROJECT SUMMARY", margin, y, 8, GREEN, True)
    _text(c, data.get("title", "Project"), margin, y - 8 * mm, 16, INK, True)
    description = str(data.get("description") or "Professional project delivery services")
    _paragraph(c, description, margin, y - 12 * mm, content_width, 9.5, MUTED, 14)
    y -= 30 * mm

    c.setFillColor(PALE)
    c.roundRect(margin, y - 18 * mm, content_width, 18 * mm, 5, fill=1, stroke=0)
    _text(c, "SERVICE / PROJECT DELIVERY", margin + 7 * mm, y - 7 * mm, 9.5, INK, True)
    _text(c, "As agreed in the accepted quotation", margin + 7 * mm, y - 13 * mm, 8.5, MUTED)
    _right_text(c, f"{data['currency']} {float(data['amount']):,.2f}", right - 7 * mm, y - 9 * mm, 12, INK, True)
    y -= 32 * mm

    c.setFillColor(LIGHT_GREEN)
    c.roundRect(margin, y - 27 * mm, content_width, 27 * mm, 6, fill=1, stroke=0)
    paid = bool(data.get("is_paid"))
    _text(c, "TOTAL AMOUNT PAID" if paid else "TOTAL AMOUNT DUE", margin + 8 * mm, y - 10 * mm, 8.5, GREEN, True)
    _text(c, "Payment received and recorded." if paid else "Payment is due by the date shown above.", margin + 8 * mm, y - 17 * mm, 8.5, MUTED)
    _right_text(c, f"{data['currency']} {float(data['amount']):,.2f}", right - 8 * mm, y - 14 * mm, 19, INK, True)
    y -= 42 * mm

    _line(c, margin, y, right)
    y -= 10 * mm
    _text(c, "PAYMENT INFORMATION", margin, y, 8, GREEN, True)
    _text(c, "Payment status", margin, y - 9 * mm, 9, MUTED)
    payment_status = "Paid" if data.get("is_paid") else "Unpaid"
    _text(c, payment_status, margin, y - 15 * mm, 10, INK, True)
    _text(c, "Reference", margin + 65 * mm, y - 9 * mm, 9, MUTED)
    _text(c, str(data.get("payment_reference") or data["invoice_number"]), margin + 65 * mm, y - 15 * mm, 10, INK, True)

    footer_y = 18 * mm
    _line(c, margin, footer_y + 8 * mm, right)
    _text(c, "Thank you for choosing Upserve.", margin, footer_y, 8.5, MUTED)
    _right_text(c, "Generated from Upserve project workspace", right, footer_y, 8, MUTED)
    _text(c, "Build Digital Products That Scale", margin, footer_y - 5 * mm, 7.5, MUTED)
    c.setTitle(f"Invoice {data['invoice_number']}")
    c.setAuthor("Upserve")
    c.save()
    return str(file_path)
