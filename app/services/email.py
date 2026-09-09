import base64
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
import os
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
import resend

from app.config import ALERT_RECEIVER_EMAIL, RESEND_API_KEY, RESEND_FROM_EMAIL
from app.exceptions import AppException


@dataclass(frozen=True)
class EmailSendResult:
    status_code: int
    id: str | None = None


class EmailDeliveryError(AppException):
    def __init__(self, message: str = "Email delivery is temporarily unavailable."):
        super().__init__(message, status_code=503, error_code="EMAIL_DELIVERY_ERROR")


def _sender_address() -> str:
    return RESEND_FROM_EMAIL or "hello@upserve.in"


def format_currency(value: object) -> str:
    try:
        return f"INR {float(value):,.2f}"
    except (TypeError, ValueError):
        return "INR 0.00"


def format_date(value: object, fallback: str = "-") -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    text = str(value or "").strip()
    if not text or text in {"N/A", "None", "null", "undefined"}:
        return fallback
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return text


def format_status(value: object, fallback: str = "Unpaid") -> str:
    text = str(value or "").replace("_", " ").strip()
    return text.title() if text else fallback


def _send_email(payload: dict) -> EmailSendResult:
    if not RESEND_API_KEY:
        raise EmailDeliveryError("Missing Resend configuration.")
    resend.api_key = RESEND_API_KEY
    try:
        response = resend.Emails.send(payload)
    except Exception as exc:
        raise EmailDeliveryError("Resend email delivery failed.") from exc
    response_id = getattr(response, "id", None)
    if response_id is None and isinstance(response, dict):
        response_id = response.get("id")
    return EmailSendResult(status_code=202, id=response_id)


def _raise_for_resend(response: EmailSendResult, purpose: str) -> None:
    if not 200 <= response.status_code < 300:
        raise EmailDeliveryError(f"Resend rejected {purpose}.")


def _workspace_url(path: str = "/app") -> str:
    return f"{os.getenv('FRONTEND_URL', 'https://upserve.in').rstrip('/')}{path}"


def _logo_data_uri() -> str:
    configured = os.getenv("UPSERVE_LOGO_PATH")
    logo_path = Path(configured) if configured else Path(__file__).resolve().parents[1] / "assets" / "logo.png"
    try:
        return f"data:image/png;base64,{base64.b64encode(logo_path.read_bytes()).decode('ascii')}"
    except OSError:
        return ""


def _rows(rows: list[tuple[str, object]]) -> str:
    return "".join(f'<p style="margin:4px 0"><strong style="color:#f5f3ef">{escape(label)}:</strong> {escape(str(value))}</p>' for label, value in rows if value not in (None, "", "-"))


def _email_layout(heading: str, body_html: str, footer_note: str, cta_text: str | None = None, cta_url: str | None = None, preheader: str | None = None) -> str:
    cta = f'<p style="margin:28px 0"><a href="{escape(cta_url)}" style="display:inline-block;padding:13px 18px;border-radius:8px;background:#a78bfa;color:#15131d;text-decoration:none;font-weight:700">{escape(cta_text)} →</a></p>' if cta_text and cta_url else ""
    hidden = f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(preheader)}</div>' if preheader else ""
    logo_url = _logo_data_uri()
    return f'''<!doctype html><html><body style="margin:0;background:transparent;color:#f5f3ef;font-family:Arial,sans-serif">{hidden}<div style="padding:32px 16px;background:transparent"><div style="max-width:600px;margin:auto;background:#1e1e26;border:1px solid #393744;border-radius:16px;padding:32px"><div><img src="{escape(logo_url)}" width="36" height="36" alt="Upserve logo" style="display:block;width:36px;height:36px;object-fit:contain;margin-bottom:10px"><div style="font-weight:700;letter-spacing:2px;color:#a78bfa;font-size:14px">UPSERVE</div><div style="margin-top:6px;color:#a7a3b6;font-size:12px">Build Digital Products That Scale</div></div><h1 style="font-size:28px;line-height:1.12;margin:32px 0 20px;color:#f5f3ef">{escape(heading)}</h1><div style="font-size:15px;line-height:1.7;color:#c2becd">{body_html}</div>{cta}<div style="border-top:1px solid #393744;margin-top:32px;padding-top:18px;color:#a7a3b6;font-size:12px;line-height:1.6">{escape(footer_note)}<br>Thoughtful software, delivered clearly.</div></div></div></body></html>'''


def send_contact_alert(name: str, email: str, message: str) -> None:
    if not ALERT_RECEIVER_EMAIL:
        raise EmailDeliveryError("Missing alert receiver email configuration.")
    text = f"Name: {name}\nEmail: {email}\n\nMessage:\n{message}"
    response = _send_email({"from": f"Upserve <{_sender_address()}>", "to": [ALERT_RECEIVER_EMAIL], "subject": f"New website enquiry from {name}", "text": text, "html": _email_layout("New website enquiry", f"<p>{escape(text).replace(chr(10), '<br>')}</p>", "New website enquiry received.")})
    _raise_for_resend(response, "contact alert")


def send_welcome_email(name: str, email: str, password: str, role: str) -> None:
    role_name = "sub-admin" if role == "sub_admin" else "client"
    text = f"Hello {name},\n\nYour Upserve {role_name} workspace has been created. Use it to review quotations, track invoices and follow your project's progress.\n\nLogin email: {email}\nTemporary password: {password}\n\nFor your security, please change your password immediately after signing in, and keep these credentials private.\n\nRegards,\nUpserve"
    html = f"<p>Hello {escape(name)},</p><p>Your Upserve {role_name} workspace has been created. Use it to review quotations, track invoices and follow your project's progress.</p>{_rows([('Login email', email), ('Temporary password', password)])}<p>For your security, please change your password immediately after signing in, and keep these credentials private.</p>"
    payload = {"from": f"Upserve <{_sender_address()}>", "to": [email], "subject": "Welcome to Upserve — your client workspace is ready", "text": text, "html": _email_layout(f"Welcome to Upserve, {name}", html, "Sign in with the credentials above and change your password after your first login.", "Sign In to Your Workspace", _workspace_url("/login"))}
    _raise_for_resend(_send_email(payload), "welcome email")


def send_existing_client_access_email(name: str, email: str) -> None:
    message = f"Hello {name},\n\nYour existing Upserve client account has been linked to a new business enquiry. No new account or password was created.\n\nSign-in email: {email}\n\nRegards,\nUpserve"
    payload = {"from": f"Upserve <{_sender_address()}>", "to": [email], "subject": "Your Upserve account is ready for the next step", "text": message, "html": _email_layout("Your Upserve workspace is ready", f"<p>{escape(message).replace(chr(10), '<br>')}</p>", "Sign in with your existing password to continue.", "Sign In to Your Workspace", _workspace_url("/login"))}
    _raise_for_resend(_send_email(payload), "existing client access email")


def send_quotation_email(name: str, email: str, quotation_number: str, total_amount: float, timeline: str | None, validity: int | None, items: list[dict] | None = None, terms: str | None = None, notes: str | None = None, file_path: str | None = None, project_name: str = "your project") -> None:
    rows = [("Quotation", quotation_number), ("Total investment", format_currency(total_amount)), ("Estimated timeline", timeline), ("Valid for", f"{validity} days" if validity is not None else None)]
    text = f"Hello {name},\n\nA quotation has been prepared for {project_name}.\n\n" + "\n".join(f"{label}: {value}" for label, value in rows if value) + "\n\nThe detailed quotation is attached as a PDF. Sign in to your workspace to review the complete proposal and respond.\n\nRegards,\nUpserve"
    html = f"<p>Hello {escape(name)},</p><p>A quotation has been prepared for {escape(project_name)}.</p>{_rows(rows)}<p>The detailed quotation is attached as a PDF. Sign in to your workspace to review the complete proposal and respond.</p>"
    payload = {"from": f"Upserve <{_sender_address()}>", "to": [email], "subject": f"Your quotation {quotation_number} is ready", "text": text, "html": _email_layout("Your quotation is ready", html, "Please sign in to review the complete proposal and respond.", "Review Proposal", _workspace_url("/app/quotations"))}
    if file_path and os.path.exists(file_path):
        with open(file_path, "rb") as file:
            payload["attachments"] = [{"filename": f"{quotation_number}.pdf", "content": base64.b64encode(file.read()).decode("ascii")}]
    _raise_for_resend(_send_email(payload), "quotation email")


def send_mass_email(subject: str, body: str, recipients: list[str], attachment: Optional[UploadFile] = None):
    payload = {"from": f"Upserve <{_sender_address()}>", "to": recipients, "subject": subject, "text": body, "html": _email_layout(subject, f"<p>{escape(body).replace(chr(10), '<br>')}</p>", subject)}
    if attachment:
        payload["attachments"] = [{"filename": attachment.filename or "attachment", "content": base64.b64encode(attachment.file.read()).decode("ascii")}]
    return _send_email(payload)


def send_invoice_email(to_email: str, subject: str, body: str, file_path: str, invoice_number: str | None = None):
    with open(file_path, "rb") as file:
        attachment = {"filename": f"invoice_{invoice_number}.pdf" if invoice_number else os.path.basename(file_path), "content": base64.b64encode(file.read()).decode("ascii")}
    response = _send_email({"from": f"Upserve <{_sender_address()}>", "to": [to_email], "subject": subject, "text": body, "html": _email_layout(subject, f"<p>{escape(body).replace(chr(10), '<br>')}</p>", "The invoice PDF is attached for your records.", "View Invoice in Workspace", _workspace_url("/app/projects")), "attachments": [attachment]})
    _raise_for_resend(response, "invoice email")
    return response


def send_payment_confirmation_email(to_email: str, client_name: str, invoice_number: str, amount: float, reference: str, method: str, file_path: str | None = None) -> None:
    readable_method = method if method and not method.strip().startswith(("id_", "ObjectId(")) else "Bank transfer"
    text = f"Hello {client_name},\n\nWe have received and recorded your payment for invoice {invoice_number}.\n\nAmount received: {format_currency(amount)}\nPayment reference: {reference or '-'}\nPayment method: {readable_method}\n\nThank you for keeping your project account up to date.\n\nRegards,\nUpserve Accounts"
    html = f"<p>Hello {escape(client_name)},</p><p>We have received and recorded your payment for invoice {escape(invoice_number)}.</p>{_rows([('Amount received', format_currency(amount)), ('Payment reference', reference or '-'), ('Payment method', readable_method)])}<p>Thank you for keeping your project account up to date.</p>"
    payload = {"from": f"Upserve Accounts <{_sender_address()}>", "to": [to_email], "subject": f"Payment received · {invoice_number}", "text": text, "html": _email_layout("Payment received", html, "Your payment has been recorded successfully.")}
    if file_path and os.path.exists(file_path):
        with open(file_path, "rb") as file:
            payload["attachments"] = [{"filename": f"invoice_{invoice_number}.pdf", "content": base64.b64encode(file.read()).decode("ascii")}]
    _raise_for_resend(_send_email(payload), "payment confirmation email")


def send_project_completion_email(to_email: str, client_name: str, project_title: str, project_value: float, paid_amount: float, deliverable_count: int) -> None:
    text = f"Hello {client_name},\n\nThank you for choosing Upserve. We're pleased to confirm that {project_title} has been completed.\n\nProject summary\nProject value: {format_currency(project_value)}\nAmount received: {format_currency(paid_amount)}\nDeliverables completed: {deliverable_count}\nProject status: Completed\n\nWe appreciate the opportunity to work with you. If you need improvements, maintenance, a new feature or another digital product, reply to this email and our team will be glad to help.\n\nRegards,\nUpserve"
    html = f"<p>Hello {escape(client_name)},</p><p>Thank you for choosing Upserve. We're pleased to confirm that {escape(project_title)} has been completed.</p><h2 style=\"font-size:17px\">Project summary</h2>{_rows([('Project value', format_currency(project_value)), ('Amount received', format_currency(paid_amount)), ('Deliverables completed', deliverable_count), ('Project status', 'Completed')])}<p>We appreciate the opportunity to work with you. If you need improvements, maintenance, a new feature or another digital product, reply to this email and our team will be glad to help.</p>"
    response = _send_email({"from": f"Upserve <{_sender_address()}>", "to": [to_email], "subject": f"Project completed · {project_title}", "text": text, "html": _email_layout("Project completed", html, "Generated from your Upserve project workspace.")})
    _raise_for_resend(response, "project completion email")
