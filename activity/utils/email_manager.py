import base64
import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class EmailManager:
    def __init__(self, email_settings, security_manager=None):
        self.settings = email_settings or {}
        self.security = security_manager

    def _resolve_password(self):
        password_enc = self.settings.get("password_enc", "")
        if password_enc:
            if self.security and hasattr(self.security, "decode_base64"):
                try:
                    return self.security.decode_base64(password_enc)
                except Exception:
                    pass
            try:
                padded = str(password_enc).strip()
                missing = len(padded) % 4
                if missing:
                    padded += "=" * (4 - missing)
                return base64.b64decode(padded).decode("utf-8")
            except Exception:
                return password_enc
        return self.settings.get("password", "")

    def send_process_email(
        self,
        process_name,
        module_name,
        status,
        message,
        attachment_path=None,
        recipients=None,
        file_name=None,
        folder_path=None,
        file_size_kb=None,
    ):
        target_recipients = recipients or self.settings.get("recipients", [])
        if isinstance(target_recipients, str):
            target_recipients = [r.strip() for r in target_recipients.split(",") if r.strip()]

        if not self.settings or not target_recipients:
            print("[EMAIL] Skipped: 'email_settings' or 'recipients' missing in activity.json.")
            return False

        host = self.settings.get("host")
        port = int(self.settings.get("port") or 587)
        use_tls = bool(self.settings.get("use_tls", True))
        username = self.settings.get("username")
        from_email = self.settings.get("from_email", username)
        password = self._resolve_password()

        if not host or not password:
            print("[EMAIL] Skipped: SMTP 'host' or 'password_enc' missing in activity.json.")
            return False

        clean_status = str(status).strip().upper()
        is_success = clean_status == "SUCCESS"
        status_color = "#1b7e3c" if is_success else "#c62828"
        timestamp_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S")

        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = ", ".join(target_recipients)
        msg["Subject"] = f"NSDL Automation [{clean_status}] - {module_name} ({process_name})"

        screenshot_attached = False
        if attachment_path and os.path.isfile(attachment_path):
            try:
                with open(attachment_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={os.path.basename(attachment_path)}",
                )
                msg.attach(part)
                screenshot_attached = True
            except Exception as e:
                print(f"[EMAIL] Warning: Failed to attach screenshot {attachment_path}: {e}")

        file_row = (
            f"<tr><td><b>Downloaded File</b></td><td>{file_name if is_success and file_name else 'Not Downloaded'}</td></tr>"
        )
        size_row = (
            f"<tr><td><b>File Size</b></td><td>{file_size_kb} KB</td></tr>"
            if is_success and file_size_kb is not None
            else ""
        )
        folder_row = (
            f"<tr><td><b>Target Folder</b></td><td>{folder_path}</td></tr>"
            if folder_path
            else ""
        )
        shot_row = (
            f"<tr><td><b>Screenshot</b></td><td>Attached ({os.path.basename(attachment_path)})</td></tr>"
            if screenshot_attached
            else "<tr><td><b>Screenshot</b></td><td>Not Available</td></tr>"
        )

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #222;">
            <h3 style="margin-bottom: 8px;">NSDL DPM Automation Execution Report</h3>
            <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; border-color: #ccc;">
                <tr><td><b>Process Key</b></td><td>{process_name}</td></tr>
                <tr><td><b>Module Name</b></td><td>{module_name}</td></tr>
                <tr><td><b>Status</b></td><td><span style="color: {status_color}; font-weight: bold;">{clean_status}</span></td></tr>
                {file_row}
                {size_row}
                {folder_row}
                {shot_row}
                <tr><td><b>Timestamp</b></td><td>{timestamp_str}</td></tr>
                <tr><td><b>Details</b></td><td>{message}</td></tr>
            </table>
            <p style="font-size: 12px; color: #666; margin-top: 12px;">Automated NSDL DPM Notification</p>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, "html"))

        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=30)
            else:
                server = smtplib.SMTP(host, port, timeout=30)
                if use_tls:
                    server.starttls()

            if username and password:
                server.login(username, password)
            server.sendmail(from_email, target_recipients, msg.as_string())
            server.quit()
            print(f"[EMAIL] {clean_status} report sent to: {target_recipients}")
            return True
        except Exception as e:
            print(f"[EMAIL] Failed to send {clean_status} email: {e}")
            return False