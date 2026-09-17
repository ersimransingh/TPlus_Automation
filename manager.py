import json
import os
import time
import subprocess
import sys
import smtplib
import threading
import copy
import re
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

# Screen Recording Dependencies
import cv2
import pyautogui
import numpy as np
from PIL import ImageGrab
import schedule
import xml.etree.ElementTree as ET
import requests

# Force UTF-8 encoding for Windows Consoles
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Resolves base execution folder (whether running raw script or compiled EXE)
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
ACTIVITY_DIR = os.path.join(BASE_DIR, "activity")
SCHEDULER_LOGS_DIR = os.path.join(ACTIVITY_DIR, "schedule_log")

def get_cli_arg(param_name, default_val=None):
    if param_name in sys.argv:
        idx = sys.argv.index(param_name)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return default_val

# Resolve Config File Locations Dynamically
SCHEDULER_PATH = get_cli_arg("--config") or os.path.join(BASE_DIR, "scheduler.json")
CUSTOM_ACTIVITY_JSON = get_cli_arg("--activity")

def resolve_activity_json_path():
    if CUSTOM_ACTIVITY_JSON and os.path.exists(CUSTOM_ACTIVITY_JSON):
        return CUSTOM_ACTIVITY_JSON
    local_path = os.path.join(ACTIVITY_DIR, "activity.json")
    if os.path.exists(local_path):
        return local_path
    local_action = os.path.join(ACTIVITY_DIR, "Action.json")
    if os.path.exists(local_action):
        return local_action
    return os.path.join(BASE_DIR, "activity.json")

ACTIVITY_PATH = resolve_activity_json_path()
SCHEDULER_LOGS_DIR = os.path.join(ACTIVITY_DIR, "schedule_log")
RECORDINGS_BASE_DIR = os.path.join(ACTIVITY_DIR, "recordings")

def log_message(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] [{level}] {message}"
    try:
        print(formatted_msg)
    except Exception:
        print(formatted_msg.encode('ascii', 'ignore').decode('ascii'))
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_dir = os.path.join(SCHEDULER_LOGS_DIR, date_str)
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "scheduler_execution.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")

def get_client_dp_ids():
    cdsl_id = ""
    nsdl_id = ""
    try:
        if os.path.exists(ACTIVITY_PATH):
            with open(ACTIVITY_PATH, 'r', encoding='utf-8') as f:
                act_data = json.load(f)
                
            global_settings = act_data.get("global_app_settings") or act_data.get("GLOBAL_APP_SETTINGS", {})
            cdsl_id = str(global_settings.get("dp_rta_id") or global_settings.get("CDSLDPID") or act_data.get("CDSLDPID") or "").strip()
            nsdl_id = str(global_settings.get("NSDLDPID") or global_settings.get("nsdl_dp_id") or act_data.get("NSDLDPID") or "").strip()
            
            if not cdsl_id and not nsdl_id:
                for k, v in act_data.items():
                    if isinstance(v, dict):
                        if "CDSLDPID" in v: cdsl_id = str(v["CDSLDPID"]).strip()
                        if "NSDLDPID" in v: nsdl_id = str(v["NSDLDPID"]).strip()
                        if "dp_rta_id" in v: cdsl_id = str(v["dp_rta_id"]).strip()
    except Exception as e:
        log_message(f"⚠️ Warning extracting DP IDs from activity.json: {e}", "WARNING")
        
    return cdsl_id, nsdl_id

def send_license_alert_email(cdsl_id, nsdl_id, status_type, strValidUpdt, grace_remaining=0):
    """
    Dispatches a plain-text email report for license Grace Period or Terminated state,
    dynamically deriving the system name from app_path (root or global_app_settings).
    """
    try:
        if not os.path.exists(ACTIVITY_PATH):
            log_message("⚠️ Cannot send license status email: activity.json missing.", "WARNING")
            return

        with open(ACTIVITY_PATH, 'r', encoding='utf-8') as f:
            act_data = json.load(f)

        global_settings = act_data.get("global_app_settings") or act_data.get("GLOBAL_APP_SETTINGS", {})
        app_path_raw = (
            act_data.get("app_path") or 
            act_data.get("APP_PATH") or 
            global_settings.get("app_path") or 
            global_settings.get("APP_PATH") or 
            ""
        )
        
        if app_path_raw:
            exe_name = os.path.basename(app_path_raw)
            system_title = os.path.splitext(exe_name)[0].upper()
        else:
            system_title = "AUTOMATION"

        email_cfg = act_data.get("email_settings") or act_data.get("EMAIL_SETTINGS", {})
        if not email_cfg:
            log_message("⚠️ No 'email_settings' found in activity.json; skipping license email.", "WARNING")
            return

        smtp_host = email_cfg.get("host") or email_cfg.get("smtp_server", "smtp.gmail.com")
        smtp_port = int(email_cfg.get("port") or email_cfg.get("smtp_port", 587))
        use_tls = email_cfg.get("use_tls", True)
        from_email = email_cfg.get("from_email") or email_cfg.get("username", "")
        to_email = email_cfg.get("reporting_email") or email_cfg.get("to") or from_email

        raw_pwd = email_cfg.get("password_enc") or email_cfg.get("PASSWORD_ENC") or email_cfg.get("password", "")
        try:
            smtp_password = base64.b64decode(raw_pwd).decode("utf-8")
        except Exception:
            smtp_password = raw_pwd

        if not from_email or not to_email:
            log_message("⚠️ Missing sender or recipient email address; skipping license email.", "WARNING")
            return

        if status_type == "GRACE":
            subject = f"⚠️ WARNING: License Grace Period Active [{system_title}]"
            plain_text_body = (
                f"Dear Sir,\n\n"
                f"The Licence to use {system_title} has expired on {strValidUpdt} and remaining grace period is only {grace_remaining} days."
            )
        else:  # EXPIRED / TERMINATED
            subject = f"⛔ CRITICAL: License Expired [{system_title}]"
            plain_text_body = (
                f"Dear Sir,\n\n"
                f"Your Licence to use {system_title} has expired on {strValidUpdt}."
            )

        msg = MIMEText(plain_text_body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        log_message(f"📧 Sending License Alert Email to '{to_email}' via {smtp_host}:{smtp_port}...", "INFO")

        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if email_cfg.get("username"):
                server.login(email_cfg["username"], smtp_password)
            server.sendmail(from_email, [to_email], msg.as_string())

        log_message(f"✅ License Alert Email successfully dispatched to '{to_email}'", "INFO")

    except Exception as email_err:
        log_message(f"⚠️ Failed to send license alert email: {email_err}", "ERROR")

def check_client_license_status():
    """
    Validates client usage limits and license status via TradePlus API endpoint.
    Parses the exact API expiry date directly and applies the 5-day grace period rules.
    """
    cdsl_id, nsdl_id = get_client_dp_ids()

    if not cdsl_id and not nsdl_id:
        log_message("⚠️ [LICENSE CHECK] No CDSLDPID or NSDLDPID found in activity.json. Bypassing check.", "WARNING")
        return True, "No DP ID Defined"

    # --- DYNAMIC SYSTEM NAME DETECTION (CHECKS ROOT & GLOBAL_APP_SETTINGS) ---
    system_name = "AUTOMATION"
    try:
        if os.path.exists(ACTIVITY_PATH):
            with open(ACTIVITY_PATH, 'r', encoding='utf-8') as f:
                act_data = json.load(f)
                global_settings = act_data.get("global_app_settings") or act_data.get("GLOBAL_APP_SETTINGS", {})
                app_path_raw = (
                    act_data.get("app_path") or 
                    act_data.get("APP_PATH") or 
                    global_settings.get("app_path") or 
                    global_settings.get("APP_PATH") or 
                    ""
                )
                if app_path_raw:
                    exe_name = os.path.basename(app_path_raw)
                    system_name = os.path.splitext(exe_name)[0].upper()
    except Exception as err:
        log_message(f"⚠️ Warning resolving application name from activity.json: {err}", "WARNING")

    url = "https://trade-plus.in/TPLUSNARIMAN/api/Main/InitializeLogin"
    headers = {'Content-Type': 'application/xml'}

    xml_payload = f"""<dsXml>
    <J_Ui>"ActionName":"TradeWeb", "Option":"CheckAutomation", "Level":1, "RequestFrom":"w"</J_Ui>
    <Sql></Sql>
    <X_Filter>
        <CDSLDPID>{cdsl_id}</CDSLDPID>
        <NSDLDPID>{nsdl_id}</NSDLDPID>
    </X_Filter>
    <X_Data></X_Data>
    <X_GFilter />
    <J_Api></J_Api>
</dsXml>"""

    log_message("=" * 70, "INFO")
    log_message(f"🔒 [{system_name} LICENSE CHECK INITIATED]", "INFO")
    log_message(f"   🆔 Client IDs: CDSL DP ID = '{cdsl_id}', NSDL DP ID = '{nsdl_id}'", "INFO")
    log_message("=" * 70, "INFO")

    start_time = time.time()

    try:
        response = requests.post(url, data=xml_payload, headers=headers, timeout=15)
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        response_text = response.text.strip()

        log_message(f"📥 [LICENSE RESPONSE RECEIVED | Latency: {elapsed_ms} ms]", "INFO")
        # --- REMOVED RAW RESPONSE LOGGING TO KEEP CONSOLE CLEAN ---

        if response.status_code != 200:
            log_message(f"⚠️ License API Warning: HTTP {response.status_code}. Allowing execution fallback.", "WARNING")
            return True, "API Unreachable (Allowed Fallback)"

        # --- PARSE API EXPIRY DATE DIRECTLY ---
        target_expiry_dt = None

        try:
            json_resp = response.json()
            if json_resp.get("success"):
                rs0 = json_resp.get("data", {}).get("rs0", [])
                if rs0 and "Date" in rs0[0]:
                    raw_api_date = str(rs0[0]["Date"]).strip()
                    target_expiry_dt = datetime.strptime(raw_api_date, "%Y%m%d")
        except Exception:
            pass

        if not target_expiry_dt:
            match = re.search(r'["<](?:Date|ExpiryDate)[">]\s*[:=]?\s*["\']?(\d{8}|\d{4}-\d{2}-\d{2})', response_text, re.IGNORECASE)
            if match:
                raw_date_str = match.group(1).strip()
                fmt = "%Y%m%d" if len(raw_date_str) == 8 else "%Y-%m-%d"
                try:
                    target_expiry_dt = datetime.strptime(raw_date_str, fmt)
                except Exception:
                    pass

        if not target_expiry_dt:
            log_message("⚠️ Could not parse Expiry Date from API response. Allowing execution fallback.", "WARNING")
            return True, "Date Unparseable (Allowed Fallback)"

        now = datetime.now()
        strValidUpdt = target_expiry_dt.strftime("%d/%m/%Y")
        
        datediff = (now - target_expiry_dt).days

        # CONDITION 1: License has expired but inside 5-day Grace Period
        if 0 < datediff <= 5:
            grace_remaining = 5 - datediff
            strFrm = f"The Licence to use {system_name} has expired on {strValidUpdt} and remaining grace period is only {grace_remaining} days"
            log_message(f"⚠️ [GRACE PERIOD WARNING] {strFrm}", "WARNING")
            
            send_license_alert_email(cdsl_id, nsdl_id, status_type="GRACE", strValidUpdt=strValidUpdt, grace_remaining=grace_remaining)
            return True, strFrm

        # CONDITION 2: Past 5-Day Grace Period -> HARD BLOCK AUTOMATION
        elif datediff > 5:
            strFrm = f"Your Licence to use {system_name} has expired on {strValidUpdt}"
            log_message(f"⛔ [LICENSE EXPIRED BLOCKED] {strFrm}", "CRITICAL")
            
            send_license_alert_email(cdsl_id, nsdl_id, status_type="EXPIRED", strValidUpdt=strValidUpdt, grace_remaining=0)
            return False, strFrm

        # CONDITION 3: Active License Window
        else:
            strFrm = f"Your Licence to use {system_name} will expired on {strValidUpdt}"
            log_message(f"✅ [LICENSE VERIFIED] {strFrm}", "INFO")
            return True, strFrm

    except Exception as api_err:
        log_message(f"⚠️ [LICENSE API EXCEPTION] Request failed: {api_err}", "WARNING")
        return True, f"API Exception: {api_err}"

def record_license_audit_log(cdsl_id, nsdl_id, http_status, raw_response, verification_result, days_remaining=None):
    """
    Audit log creation disabled per configuration preference.
    """
    pass

def write_summary_log(process_name, status_result):
    try:
        os.makedirs(SCHEDULER_LOGS_DIR, exist_ok=True)
        summary_file_path = os.path.join(SCHEDULER_LOGS_DIR, "log.json")

        now = datetime.now()
        new_entry = {
            "date": now.strftime("%d-%b-%Y"),
            "task": process_name,
            "Status": "success" if str(status_result).lower() == "success" else "unsuccess",
            "time": now.strftime("%H:%M:%S")
        }

        historical_records = []
        if os.path.exists(summary_file_path):
            try:
                with open(summary_file_path, "r", encoding="utf-8") as rf:
                    historical_records = json.load(rf)
                    if not isinstance(historical_records, list):
                        historical_records = []
            except Exception:
                historical_records = []

        historical_records.append(new_entry)

        with open(summary_file_path, "w", encoding="utf-8") as wf:
            json.dump(historical_records, wf, indent=2)

        log_message(f"✓ Summary log entry recorded safely at {summary_file_path}")
    except Exception as summary_err:
        log_message(f"⚠️ Failed to write summary log entry: {summary_err}", "ERROR")

# Screen Recording Worker Thread
def screen_recorder_worker(video_output_path, stop_recording_flag):
    screen_width, screen_height = pyautogui.size()
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(video_output_path, fourcc, 10.0, (screen_width, screen_height))
    log_message(f"📹 Screen recording pipeline running -> {video_output_path}")
    
    while not stop_recording_flag.is_set():
        start_frame_time = time.time()
        img = pyautogui.screenshot()
        frame = np.array(img)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        video_writer.write(frame)
        
        elapsed = time.time() - start_frame_time
        sleep_delay = max(0.0, 0.1 - elapsed)
        if sleep_delay > 0:
            time.sleep(sleep_delay)
    video_writer.release()
    log_message("✓ Screen recording context released cleanly.")

def check_remote_status(task_config):
    process_name = task_config.get("process_name") or task_config.get("Process_name")

    delay_minutes = task_config.get("delay_times") or task_config.get("Delay_Times") or task_config.get("check_delay_minutes", 0)
    if delay_minutes > 0:
        log_message(f"⏳ Waiting {delay_minutes} minute(s) before dependency checks...", "INFO")
        time.sleep(delay_minutes * 60)

    raw_dependencies = task_config.get("dependency") or task_config.get("DEPENDENCY", [])
    dependencies = [raw_dependencies] if isinstance(raw_dependencies, dict) else (raw_dependencies if isinstance(raw_dependencies, list) else [])

    if not dependencies:
        return True

    for idx, dep in enumerate(dependencies, start=1):
        target_dep_process = dep.get("process_name") or dep.get("Process_name")
        status_path_base = dep.get("status_path") or dep.get("Status_path", "")

        if not status_path_base:
            continue

        summary_file_path = os.path.join(status_path_base, "log.json")
        if not os.path.exists(summary_file_path):
            log_message(f"❌ Aborting: log.json missing at {summary_file_path}", "ERROR")
            return False

        try:
            with open(summary_file_path, 'r', encoding='utf-8') as sf:
                summary_data = json.load(sf)
            matching_entries = [entry for entry in summary_data if str(entry.get("task")).strip().upper() == str(target_dep_process).strip().upper()]

            if not matching_entries:
                log_message(f"❌ Dependency Error: No record found for '{target_dep_process}' in log.json.", "ERROR")
                return False

            target_entry = matching_entries[-1]
            status_val = str(target_entry.get("Status") or target_entry.get("result") or target_entry.get("status")).strip().lower()

            if status_val != "success":
                log_message(f"⛔ Dependency Error [{target_dep_process}]: Result is '{status_val}'. Execution Blocked.", "WARNING")
                return False

        except Exception as e:
            log_message(f"❌ Error decoding log.json for {target_dep_process}: {e}", "ERROR")
            return False

    return True

def send_manager_status_email(process_name, status, attempts_used, max_retries, duration_str=None, video_path=None):
    """
    Dispatches a formatted Log Status Update Report email dynamically.
    Reads global SMTP/sender configuration from activity.json, but overrides 
    the target recipient ('reporting_email') from task settings in scheduler.json.
    """
    try:
        # 1. Load base configuration from activity.json (SMTP / Credentials)
        if not os.path.exists(ACTIVITY_PATH):
            log_message("⚠️ Cannot send manager status email: activity.json missing.", "WARNING")
            return

        with open(ACTIVITY_PATH, 'r', encoding='utf-8') as f:
            act_data = json.load(f)

        email_cfg = act_data.get("email_settings") or act_data.get("EMAIL_SETTINGS", {})
        if not email_cfg:
            log_message("⚠️ No 'email_settings' found in activity.json; skipping manager email report.", "WARNING")
            return

        # 2. Check scheduler.json for task-specific 'reporting_email' override
        to_email = None
        if os.path.exists(SCHEDULER_PATH):
            try:
                with open(SCHEDULER_PATH, 'r', encoding='utf-8') as sf:
                    sched_data = json.load(sf)
                    
                    # Search inside task definitions
                    tasks = sched_data.get("scheduled_tasks") or sched_data.get("SCHEDULED_TASKS", [])
                    for task in tasks:
                        task_p_name = task.get("process_name") or task.get("Process_name")
                        if str(task_p_name).strip().lower() == str(process_name).strip().lower():
                            task_email_cfg = task.get("email_settings") or task.get("EMAIL_SETTINGS", {})
                            to_email = task.get("reporting_email") or task_email_cfg.get("reporting_email") or task.get("to")
                            break
                    
                    # Fallback to top-level scheduler email_settings if not specified inside task
                    if not to_email:
                        sched_email_cfg = sched_data.get("email_settings") or sched_data.get("EMAIL_SETTINGS", {})
                        to_email = sched_email_cfg.get("reporting_email") or sched_email_cfg.get("to")

            except Exception as err:
                log_message(f"⚠️ Error reading reporting_email from scheduler.json: {err}", "WARNING")

        # 3. Fallback to activity.json recipient if scheduler doesn't specify one
        if not to_email:
            to_email = email_cfg.get("reporting_email") or email_cfg.get("to") or email_cfg.get("from_email") or email_cfg.get("username", "")

        from_email = email_cfg.get("from_email") or email_cfg.get("username", "")

        if not from_email or not to_email:
            log_message("⚠️ Missing sender or recipient email address; skipping email report.", "WARNING")
            return

        # 4. Resolve System Title & Credentials from activity.json
        global_settings = act_data.get("global_app_settings") or act_data.get("GLOBAL_APP_SETTINGS", {})
        app_path_raw = (
            act_data.get("app_path") or 
            act_data.get("APP_PATH") or 
            global_settings.get("app_path") or 
            global_settings.get("APP_PATH") or 
            ""
        )
        
        if app_path_raw:
            exe_name = os.path.basename(app_path_raw)
            base_app = os.path.splitext(exe_name)[0].upper()
            system_title = f"{base_app} Master Scheduler"
            engine_name = f"{base_app} Universal Automation Engine"
        else:
            system_title = "Master Scheduler"
            engine_name = "Universal Automation Engine"

        smtp_host = email_cfg.get("host") or email_cfg.get("smtp_server", "smtp.gmail.com")
        smtp_port = int(email_cfg.get("port") or email_cfg.get("smtp_port", 587))
        use_tls = email_cfg.get("use_tls", True)

        raw_pwd = email_cfg.get("password_enc") or email_cfg.get("PASSWORD_ENC") or email_cfg.get("password", "")
        try:
            smtp_password = base64.b64decode(raw_pwd).decode("utf-8")
        except Exception:
            smtp_password = raw_pwd

        is_success = str(status).upper() == "SUCCESS"
        status_color = "#28a745" if is_success else "#dc3545"

        subject = f"{system_title} Report: {process_name} - {status.upper()}"

        html_body = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.5;">
            <div style="max-width: 650px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 6px; padding: 20px;">
              <h2 style="color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 10px;">
                {system_title} Log Status Update Report
              </h2>
              
              <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
                <tr>
                  <td style="padding: 8px 12px; font-weight: bold; background: #f8f9fa; border: 1px solid #dee2e6; width: 40%;">Executed Task Target ID</td>
                  <td style="padding: 8px 12px; border: 1px solid #dee2e6;"><b>{process_name}</b></td>
                </tr>
                <tr>
                  <td style="padding: 8px 12px; font-weight: bold; background: #f8f9fa; border: 1px solid #dee2e6;">Job Automation State</td>
                  <td style="padding: 8px 12px; border: 1px solid #dee2e6; color: {status_color}; font-weight: bold;">{status.upper()}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 12px; font-weight: bold; background: #f8f9fa; border: 1px solid #dee2e6;">Attempts Executed</td>
                  <td style="padding: 8px 12px; border: 1px solid #dee2e6;">{attempts_used} / {max_retries}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 12px; font-weight: bold; background: #f8f9fa; border: 1px solid #dee2e6;">Timestamp</td>
                  <td style="padding: 8px 12px; border: 1px solid #dee2e6;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td>
                </tr>
              </table>

              <p style="margin-top: 20px; font-size: 12px; color: #777;">
                This status update report was automatically generated by {engine_name}.
              </p>
            </div>
          </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        log_message(f"📧 Sending Manager Summary Email to '{to_email}' via {smtp_host}:{smtp_port}...", "INFO")

        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if email_cfg.get("username"):
                server.login(email_cfg["username"], smtp_password)
            server.sendmail(from_email, [to_email], msg.as_string())

        log_message(f"✅ Manager Status Email successfully dispatched to '{to_email}'", "INFO")

    except Exception as email_err:
        log_message(f"⚠️ Failed to send manager status email: {email_err}", "ERROR")

def trigger_existing_script(process_name):
    start_total_time = datetime.now()

    # 1. RUN 7-DAY LICENSE / USAGE CHECK FIRST
    license_ok, license_msg = check_client_license_status()
    if not license_ok:
        log_message(f"🛑 Execution HALTED for {process_name}: {license_msg}", "CRITICAL")
        write_summary_log(process_name, "unsuccess")
        return

    # Locate activity executable or script
    existing_script_exe = os.path.join(ACTIVITY_DIR, "activity.exe")
    if not os.path.exists(existing_script_exe):
        existing_script_exe = os.path.join(BASE_DIR, "activity.exe")
    if not os.path.exists(existing_script_exe):
        existing_script_exe = os.path.join(ACTIVITY_DIR, "activity.py")

    try:
        with open(SCHEDULER_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        manager_cfg = config.get("manager_config", {})
        scheduled_tasks = config.get("scheduled_tasks") or config.get("SCHEDULED_TASKS", [])
        task_config = next(
            (t for t in scheduled_tasks if (t.get("process_name") or t.get("Process_name")) == process_name),
            {"process_name": process_name}
        )
        
        max_retries = int(task_config.get("retry_count") or task_config.get("RETRY_COUNT") or manager_cfg.get("max_retries", 3))
        retry_delay_seconds = float(task_config.get("retry_time") or task_config.get("RETRY_TIME") or manager_cfg.get("retry_delay_minutes", 5)) * 60

    except Exception as err:
        log_message(f"Warning reading scheduler config: {err}", "WARNING")
        max_retries = 3
        retry_delay_seconds = 300
        task_config = {"process_name": process_name}

    if not check_remote_status(task_config):
        log_message(f"🛑 Terminating run execution chain for {process_name} due to invalid dependency state.", "WARNING")
        write_summary_log(process_name, "unsuccess")
        return 

    # --- STRICT DYNAMIC APP DETECTION (EXCLUSIVELY VIA APP_PATH) ---
    is_cross_automation = False
    try:
        if os.path.exists(ACTIVITY_PATH):
            with open(ACTIVITY_PATH, 'r', encoding='utf-8') as act_f:
                act_data_check = json.load(act_f)
                global_settings = act_data_check.get("global_app_settings") or act_data_check.get("GLOBAL_APP_SETTINGS", {})
                app_path_val = str(
                    act_data_check.get("app_path") or 
                    act_data_check.get("APP_PATH") or 
                    global_settings.get("app_path") or 
                    global_settings.get("APP_PATH") or 
                    ""
                ).upper()
                
                # Check strictly if the configured app binary is Cross.exe
                if "CROSS.EXE" in app_path_val or "CROSS" in os.path.basename(app_path_val):
                    is_cross_automation = True
    except Exception as e:
        log_message(f"⚠️ Warning during dynamic app detection: {e}", "WARNING")

    # --- RECORDING DIRECTORY & FILE PATH SETUP ---
    if is_cross_automation:
        log_message("📹 Manager screen recording bypassed for CROSS (handled by activity engine).", "INFO")
        final_video_path = "N/A (Managed by Activity Engine)"
    else:
        # Create recordings folder for CDSLSecureapp / non-CROSS tasks
        runtime_date_stamp = datetime.now().strftime("%d-%b-%Y")
        current_timestamp = datetime.now().strftime("%H-%M-%S")
        dated_recording_folder = os.path.join(RECORDINGS_BASE_DIR, runtime_date_stamp)
        os.makedirs(dated_recording_folder, exist_ok=True) 
        video_filename = f"Execution_{process_name}_{current_timestamp}.mp4"
        final_video_path = os.path.join(dated_recording_folder, video_filename)

    custom_env = os.environ.copy()
    custom_env["PYTHONIOENCODING"] = "utf-8"
    custom_env["PYTHONUTF8"] = "1"

    for attempt in range(1, max_retries + 1):
        log_message(f"🏃 [Attempt {attempt}/{max_retries}] Starting execution for process: {process_name}...")
        
        stop_recording_flag = threading.Event()
        recording_thread = None
        
        # Start background recording thread ONLY if NOT CROSS automation
        if not is_cross_automation:
            recording_thread = threading.Thread(
                target=screen_recorder_worker, 
                args=(final_video_path, stop_recording_flag), 
                daemon=True
            )
            recording_thread.start()

        try:
            # Construct Universal Command
            if existing_script_exe.endswith(".exe"):
                cmd = [existing_script_exe, "--config", ACTIVITY_PATH, "--process", process_name]
            else:
                cmd = [sys.executable, existing_script_exe, "--config", ACTIVITY_PATH, "--process", process_name]

            result = subprocess.run(
                cmd,
                cwd=ACTIVITY_DIR,
                env=custom_env,
                capture_output=True, 
                text=True, 
                encoding="utf-8",
                errors="replace"
            )
            
            if recording_thread:
                stop_recording_flag.set()
                recording_thread.join(timeout=5)

            stdout_txt = result.stdout or ""
            stderr_txt = result.stderr or ""
            combined_output = stdout_txt + "\n" + stderr_txt

            if result.stdout:
                log_message(f"Script stdout:\n{result.stdout.strip()}")

            # CHECK BOTH EXIT CODE AND STDOUT FOR SUCCESS SIGNATURES
            is_success = (
                result.returncode == 0 and 
                "❌ Automation process terminated with errors" not in combined_output and
                "UNSUCCESS" not in combined_output
            )

            if is_success:
                duration_delta = str(datetime.now() - start_total_time)
                log_message(f"✅ Success: {process_name} executed successfully.", "INFO")
                write_summary_log(process_name, "success")

                # DISPATCH SUCCESS REPORT EMAIL
                send_manager_status_email(
                    process_name=process_name,
                    status="SUCCESS",
                    attempts_used=attempt,
                    max_retries=max_retries,
                    duration_str=duration_delta,
                    video_path=final_video_path
                )
                return 
            else:
                raise subprocess.CalledProcessError(
                    returncode=result.returncode if result.returncode != 0 else 1,
                    cmd=cmd,
                    output=stdout_txt,
                    stderr=stderr_txt
                )

        except subprocess.CalledProcessError as e:
            if recording_thread:
                stop_recording_flag.set()
                recording_thread.join(timeout=5)

            error_summary = f"Exit code: {e.returncode}\nSTDOUT:\n{e.output}\nSTDERR:\n{e.stderr}"
            log_message(f"⚠️ Attempt {attempt} failed for {process_name}.\nDetails: {error_summary}", "WARNING")
            
            if attempt < max_retries:
                log_message(f"⏳ Waiting {int(retry_delay_seconds // 60)} minute(s) before launching Retry #{attempt + 1}...", "INFO")
                time.sleep(retry_delay_seconds)
            else:
                duration_delta = str(datetime.now() - start_total_time)
                log_message(f"❌ Critical: {process_name} failed all {max_retries} retries.", "CRITICAL")
                write_summary_log(process_name, "unsuccess")

                # DISPATCH FAILURE REPORT EMAIL
                send_manager_status_email(
                    process_name=process_name,
                    status="FAILED",
                    attempts_used=attempt,
                    max_retries=max_retries,
                    duration_str=duration_delta,
                    video_path=final_video_path
                )

if __name__ == "__main__":
    log_message("🤖 Universal Manager Daemon initializing...", "INFO")
    log_message(f"📄 Active Scheduler Config : {SCHEDULER_PATH}")
    log_message(f"📄 Target Activity Config  : {ACTIVITY_PATH}")

    if not os.path.exists(SCHEDULER_PATH):
        log_message(f"❌ Critical Error: Could not locate scheduler.json at: {SCHEDULER_PATH}", "CRITICAL")
        sys.exit(1)

    try:
        with open(SCHEDULER_PATH, 'r', encoding='utf-8') as f: 
            config = json.load(f)
    except Exception as e:
        log_message(f"❌ Critical Error parsing scheduler.json: {e}", "CRITICAL")
        sys.exit(1)

    scheduled_tasks = config.get("scheduled_tasks") or config.get("SCHEDULED_TASKS", [])
    
    # Filter active enabled tasks that have a non-empty time field
    active_tasks = []
    for task in scheduled_tasks:
        is_enabled = task.get("enabled", True)
        run_time = str(task.get("time") or task.get("TIME") or task.get("execution_time") or task.get("EXECUTION_TIME") or "").strip()
        if is_enabled and run_time != "":
            active_tasks.append((task, run_time))

    enabled_tasks_count = len(active_tasks)
    completed_tasks = set()

    if enabled_tasks_count == 0:
        log_message("ℹ️ No active scheduled tasks with valid times discovered. Exiting.", "INFO")
        sys.exit(0)

    for task, run_time in active_tasks:
        process = task.get("process_name") or task.get("Process_name")
        
        if process:
            def create_task_wrapper(p_name):
                def wrapper():
                    try:
                        trigger_existing_script(p_name)
                    except Exception as err:
                        log_message(f"⚠️ Unhandled error in wrapper for '{p_name}': {err}", "ERROR")
                    finally:
                        completed_tasks.add(p_name)
                        log_message(f"🏁 Task '{p_name}' finished. [{len(completed_tasks)}/{enabled_tasks_count} completed]", "INFO")
                return wrapper

            schedule.every().day.at(run_time).do(create_task_wrapper(process))
            log_message(f"📅 Registered '{process}' to run daily at {run_time}", "INFO")

    log_message(f"⏳ Monitoring active schedule... (Expecting {enabled_tasks_count} task(s) to complete before exit)", "INFO")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
            
            if len(completed_tasks) >= enabled_tasks_count:
                log_message("🎉 All active scheduled tasks completed cleanly. Exiting daemon process.", "INFO")
                time.sleep(2)
                break
    except KeyboardInterrupt:
        log_message("⚠️ Manager daemon interrupted manually via user cancellation.", "WARNING")

    log_message("👋 Manager execution finished. Terminating script.", "INFO")
    sys.exit(0)