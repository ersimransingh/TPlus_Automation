import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

class EmailManager:
    def __init__(self, email_settings, security_manager):
        self.settings = email_settings
        self.security = security_manager

    def send_process_email(self, process_name, module_name, status, message, attachment_path=None, recipients=None):
        if not self.settings or not recipients:
            return

        host = self.settings.get("host")
        port = self.settings.get("port", 587)
        use_tls = self.settings.get("use_tls", True)
        username = self.settings.get("username")
        password_enc = self.settings.get("password_enc", "")
        from_email = self.settings.get("from_email", username)

        if not password_enc:
            print("⚠️ Email password not configured in activity.json. Skipping email.")
            return

        password = self.security.decode_base64(password_enc)

        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = f"Automation Alert: [{process_name}] {module_name} - {status}"

        status_color = "green" if status == "SUCCESS" else "red"
        body = f"""
        <html>
        <body>
            <h3>Automation Process Execution Report</h3>
            <p><b>Process Key:</b> {process_name}</p>
            <p><b>Module Name:</b> {module_name}</p>
            <p><b>Status:</b> <span style="color: {status_color}; font-weight: bold;">{status}</span></p>
            <p><b>Details:</b> {message}</p>
            <hr>
            <p><i>Automated NSDL DPM Bot Notification</i></p>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, "html"))

        # Attach file if provided
        if attachment_path and os.path.exists(attachment_path):
            try:
                with open(attachment_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename= {os.path.basename(attachment_path)}"
                )
                msg.attach(part)
            except Exception as e:
                print(f"⚠️ Failed to attach file {attachment_path}: {e}")

        try:
            server = smtplib.SMTP(host, port)
            if use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.sendmail(from_email, recipients, msg.as_string())
            server.quit()
            print(f"📧 Email notification sent successfully to: {recipients}")
        except Exception as e:
            print(f"❌ Failed to send email: {e}")