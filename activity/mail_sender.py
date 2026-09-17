"""
mail_sender.py

Sends per-import-batch email reports containing HTML status summaries 
and inline error/confirmation screenshots.
"""

import os
import sys
import smtplib
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

try:
    from logger_config import setup_logger
except ImportError:
    from activity.logger_config import setup_logger

logger = setup_logger()


def resolve_password_value(val):
    """Decodes Base64 if valid; returns plain text as-is if not."""
    if not val or not isinstance(val, str):
        return str(val) if val is not None else ""
    clean_val = val.strip()
    if len(clean_val) % 4 != 0 or len(clean_val) < 4:
        return clean_val
    try:
        decoded_bytes = base64.b64decode(clean_val, validate=True)
        decoded_str = decoded_bytes.decode('utf-8')
        if decoded_str.isprintable():
            return decoded_str
        return clean_val
    except Exception:
        return clean_val


def send_batch_report_email(smtp_config, mail_config, table_rows, screenshot_path=None,
                            default_subject="Import Batch Report"):
    """
    Sends execution status email reports containing HTML summaries and inline screenshots.
    """
    if not smtp_config:
        logger.info("No 'email_settings' defined in JSON; skipping email send.")
        return
    if not mail_config or not mail_config.get("to"):
        logger.info("No 'mail' block (or no 'to' address) defined for this process; skipping email send.")
        return

    subject = mail_config.get("subject") or default_subject
    to_addr = mail_config["to"]
    cc_addr = mail_config.get("cc", "")
    from_addr = (
        smtp_config.get("from_email") or 
        smtp_config.get("username") or 
        smtp_config.get("from")
    )

    raw_pwd = (
        smtp_config.get("password_enc") or 
        smtp_config.get("PASSWORD_ENC") or 
        smtp_config.get("password") or 
        smtp_config.get("PASSWORD", "")
    )
    smtp_password = resolve_password_value(raw_pwd)

    # Root MIMEMultipart container ('related' required for inline HTML images)
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    if cc_addr:
        msg["Cc"] = cc_addr

    rows_html = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px;border:1px solid #ccc;font-weight:bold;background:#f5f5f5;'>{label}</td>"
        f"<td style='padding:6px 12px;border:1px solid #ccc;'>{value}</td>"
        f"</tr>"
        for label, value in table_rows
    )

    has_valid_screenshot = screenshot_path and os.path.exists(screenshot_path)

    screenshot_html = ""
    if has_valid_screenshot:
        screenshot_html = (
            "<br/><p><b>Execution Screenshot:</b></p>"
            "<p><img src='cid:batch_screenshot' style='max-width:800px;border:1px solid #ccc;'/></p>"
        )

    html_body = f"""
    <html>
      <body style="font-family:Arial, sans-serif;">
        <p>The following import batch execution status update was generated:</p>
        <table style="border-collapse:collapse;width:100%;max-width:600px;">
          {rows_html}
        </table>
        {screenshot_html}
      </body>
    </html>
    """

    # Attach HTML Body
    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(html_body, "html"))
    msg.attach(msg_alt)

    # Attach Inline Screenshot Image with explicit CID headers
    if has_valid_screenshot:
        try:
            with open(screenshot_path, "rb") as f:
                img_data = f.read()
                
            img_part = MIMEImage(img_data, _subtype="png")
            img_part.add_header("Content-ID", "<batch_screenshot>")
            img_part.add_header("Content-Disposition", "inline", filename=os.path.basename(screenshot_path))
            msg.attach(img_part)
            logger.info(f"📎 Attached screenshot inline to email payload -> {screenshot_path}")
        except Exception as img_err:
            logger.warning(f"⚠️ Failed attaching screenshot to email: {img_err}")
    else:
        logger.warning(f"⚠️ Screenshot path not found or invalid: {screenshot_path}")

    recipients = [to_addr] + ([cc_addr] if cc_addr else [])

    # Ensure smtp_host is never None or empty
    smtp_host = (
        smtp_config.get("host") or 
        smtp_config.get("smtp_server") or 
        smtp_config.get("HOST") or 
        "smtp.gmail.com"
    ).strip()

    try:
        smtp_port = int(smtp_config.get("port") or smtp_config.get("smtp_port") or 587)
    except (ValueError, TypeError):
        smtp_port = 587

    use_tls = smtp_config.get("use_tls", True)

    try:
        logger.info(f"Connecting to SMTP Server: {smtp_host}:{smtp_port}...")
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if smtp_config.get("username"):
                server.login(smtp_config["username"], smtp_password)
            server.sendmail(from_addr, recipients, msg.as_string())
        logger.info(f"Batch report email sent successfully to '{to_addr}'" + (f", cc '{cc_addr}'" if cc_addr else ""))
    except Exception as e:
        logger.error(f"Failed to send batch report email: {e}", exc_info=True)
