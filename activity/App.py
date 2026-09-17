import json
import os
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
import time
import subprocess
import win32api
import win32con
import win32gui
import win32process
import re
import base64
from datetime import datetime, timedelta
from PIL import Image, ImageEnhance
import pytesseract
from pywinauto import Application
from pywinauto.keyboard import send_keys

from pages.report_download import execute_report_download_form
from pages.report_setup import execute_report_setup_form 

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

class TeeLogger:
    def __init__(self, terminal_stream, file_stream):
        self.terminal = terminal_stream
        self.file = file_stream

    def write(self, message):
        if self.terminal:
            try:
                self.terminal.write(message)
            except UnicodeEncodeError:
                self.terminal.write(message.encode('ascii', 'ignore').decode('ascii'))
            if hasattr(self.terminal, 'flush'):
                try: self.terminal.flush()
                except Exception: pass
                
        if self.file and not self.file.closed:
            try:
                self.file.write(message)
            except Exception:
                pass
            if hasattr(self.file, 'flush'):
                try: self.file.flush()
                except Exception: pass

    def flush(self):
        if self.terminal and hasattr(self.terminal, 'flush'):
            try: self.terminal.flush()
            except Exception: pass
        if self.file and not self.file.closed and hasattr(self.file, 'flush'):
            try: self.file.flush()
            except Exception: pass

def resolve_password_value(val):
    """
    Safely resolves Base64 encoded or plain text passwords.
    Works seamlessly in raw Python environment and PyInstaller compiled EXE files.
    """
    if not val or not isinstance(val, str):
        return str(val) if val is not None else ""

    clean_val = val.strip()

    # Fast-path return if string is empty or clearly not base64
    if not clean_val or len(clean_val) < 2:
        return clean_val

    # Standardize Base64 padding (adds required '=' characters)
    missing_padding = len(clean_val) % 4
    padded_val = clean_val
    if missing_padding:
        padded_val += '=' * (4 - missing_padding)

    try:
        # Attempt standard Base64 decoding
        decoded_bytes = base64.b64decode(padded_val, validate=False)
        decoded_str = decoded_bytes.decode('utf-8')

        # Check if decoded output is printable text
        if decoded_str and decoded_str.isprintable():
            return decoded_str
    except Exception:
        pass

    try:
        # Secondary fallback: URL-safe Base64 decoding
        decoded_bytes = base64.urlsafe_b64decode(padded_val)
        decoded_str = decoded_bytes.decode('utf-8')
        if decoded_str and decoded_str.isprintable():
            return decoded_str
    except Exception:
        pass

    return clean_val

def resolve_all_dynamic_tokens(config_data):
    """
    Recursively scans the entire JSON configuration and replaces 
    CDSLDPID6, CDSLDPID5, and CDSLDPID tokens across strings, lists, 
    and nested dictionaries using the last 5 digits of CDSLDPID.
    """
    if not isinstance(config_data, dict):
        return config_data

    # 1. Extract raw DP ID from CDSLDPID or dp_rta_id inside global_app_settings
    global_settings = config_data.get("global_app_settings") or config_data.get("GLOBAL_APP_SETTINGS", {})
    
    raw_dp_id = str(
        global_settings.get("CDSLDPID") or 
        global_settings.get("dp_rta_id") or ""
    ).strip()

    # 2. If dp_rta_id itself was set to a token like 'CDSLDPID5', resolve it against CDSLDPID
    if raw_dp_id in ("CDSLDPID5", "CDSLDPID6", "CDSLDPID"):
        raw_dp_id = str(global_settings.get("CDSLDPID", "")).strip()

    # 3. If no valid DP ID is defined in JSON, skip replacement and log a warning
    if not raw_dp_id:
        print("⚠️ Warning: Neither 'CDSLDPID' nor 'dp_rta_id' is defined in activity json. Dynamic DP ID tokens will not be replaced.")
        return config_data

    # 4. Extract last 5 digits dynamically (e.g., '12028700' -> '28700')
    base_5_dpid = raw_dp_id[-5:] if len(raw_dp_id) >= 5 else raw_dp_id.zfill(5)
    base_6_dpid = base_5_dpid.zfill(6)  # Zero-padded to 6 digits (e.g., '028700')

    # 5. Recursive replacement helper
    def replace_in_value(val):
        if isinstance(val, str):
            val = val.replace("CDSLDPID6", base_6_dpid)
            val = val.replace("CDSLDPID5", base_5_dpid)
            val = val.replace("CDSLDPID", base_5_dpid)
            return val
        elif isinstance(val, list):
            return [replace_in_value(item) for item in val]
        elif isinstance(val, dict):
            return {k: replace_in_value(v) for k, v in val.items()}
        return val

    return replace_in_value(config_data)

def setup_execution_logger():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    log_directory = os.path.join(base_dir, "Internal_log")
    if not os.path.exists(log_directory): 
        os.makedirs(log_directory, exist_ok=True)

    current_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f"Log_{current_timestamp}.txt"
    log_filepath = os.path.join(log_directory, log_filename)
    
    file_stream = open(log_filepath, "w", encoding="utf-8")
    sys.stdout = TeeLogger(sys.stdout, file_stream)
    sys.stderr = TeeLogger(sys.stderr, file_stream)
    
    print("=" * 80)
    print(f"🎬 LOGGING PIPELINE ACTIVE | Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 Session Log target generated safely at:\n   -> {log_filepath}")
    print("=" * 80 + "\n")
    return file_stream

def load_activity_master():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            candidate = sys.argv[idx + 1]
            if os.path.isabs(candidate) and os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    return json.load(f)
            cand_local = os.path.join(base_dir, candidate)
            if os.path.exists(cand_local):
                with open(cand_local, "r", encoding="utf-8") as f:
                    return json.load(f)

    for fname in ("activity.json", "Activity.json", "action.json"):
        target_path = os.path.join(base_dir, fname)
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)

    parent_path = os.path.join(os.path.dirname(base_dir), "activity.json")
    if os.path.exists(parent_path):
        with open(target_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        
        # Apply dynamic token replacement across ALL fields (dp_rta_id, main_path, file patterns)
        resolved_data = resolve_all_dynamic_tokens(raw_data)
        return resolved_data

    print("❌ Critical Error: Could not locate 'activity.json' in execution path.")
    sys.exit(1)

def sanitize_send_keys_string(text):
    """
    Escapes special pywinauto key sequence characters like {}, (), %, + so 
    passwords containing special symbols don't crash send_keys().
    """
    if not text:
        return ""
    
    special_chars = ['{', '}', '(', ')', '%', '+', '^', '~']
    clean_text = ""
    for char in text:
        if char in special_chars:
            clean_text += f"{{{char}}}"
        else:
            clean_text += char
    return clean_text

def load_config():
    """Extracts global settings and automatically decodes separate app and web passwords."""
    data = load_activity_master()
    global_settings = data.get("global_app_settings") or data.get("GLOBAL_APP_SETTINGS", {})
    
    # 1. Resolve Desktop App Password (fallback to legacy password_enc if new key is missing)
    raw_app_pwd = (
        global_settings.get("app_password_enc") or 
        global_settings.get("APP_PASSWORD_ENC") or 
        global_settings.get("password_enc") or 
        global_settings.get("PASSWORD_ENC") or 
        global_settings.get("password") or ""
    )
    
    # 2. Resolve Web Portal Password (fallback to app password or legacy key if missing)
    raw_web_pwd = (
        global_settings.get("web_password_enc") or 
        global_settings.get("WEB_PASSWORD_ENC") or 
        raw_app_pwd
    )

    app_pwd_plain = resolve_password_value(raw_app_pwd)
    web_pwd_plain = resolve_password_value(raw_web_pwd)

    global_settings["app_password"] = app_pwd_plain
    global_settings["web_password"] = web_pwd_plain
    
    # Sanitized representations safe for pywinauto send_keys()
    global_settings["app_password_keys"] = sanitize_send_keys_string(app_pwd_plain)
    global_settings["web_password_keys"] = sanitize_send_keys_string(web_pwd_plain)

    return global_settings

def parse_standalone_date(expr_str):
    clean_expr = str(expr_str).strip().lower()
    base_date = datetime.now()
    if clean_expr in ('t', 'today'):
        return base_date.strftime("%d-%b-%Y")
    elif clean_expr == 'yesterday':
        return (base_date - timedelta(days=1)).strftime("%d-%b-%Y")
    match = re.match(r"^t\s*([\+\-])\s*(\d+)$", clean_expr)
    if match:
        op, offset = match.group(1), int(match.group(2))
        target_date = base_date - timedelta(days=offset) if op == '-' else base_date + timedelta(days=offset)
        return target_date.strftime("%d-%b-%Y")
    return expr_str

def load_task_toggles():
    data = load_activity_master()
    email_cfg = data.get("email_settings") or data.get("EMAIL_SETTINGS", {})

    # Resolve email settings password
    raw_email_pwd = (
        email_cfg.get("password_enc") or 
        email_cfg.get("PASSWORD_ENC") or 
        email_cfg.get("sender_password_enc") or 
        email_cfg.get("SENDER_PASSWORD_ENC") or 
        email_cfg.get("password") or 
        email_cfg.get("PASSWORD") or 
        email_cfg.get("sender_password") or 
        email_cfg.get("SENDER_PASSWORD", "")
    )
    email_cfg["smtp_server"] = email_cfg.get("host") or email_cfg.get("smtp_server") or email_cfg.get("HOST", "smtp.gmail.com")
    email_cfg["smtp_port"] = email_cfg.get("port") or email_cfg.get("smtp_port") or email_cfg.get("PORT", 587)
    email_cfg["use_tls"] = email_cfg.get("use_tls", True)
    email_cfg["sender_email"] = email_cfg.get("from_email") or email_cfg.get("username") or email_cfg.get("sender_email", "")
    email_cfg["sender_password"] = resolve_password_value(raw_email_pwd)
    email_cfg["reporting_email"] = email_cfg.get("reporting_email") or email_cfg.get("to") or email_cfg.get("sender_email", "")

    active_profile = {}

    # 1. PRIORITY 1: Read directly from DYNAMIC_RUN_PROFILE passed by activity.py
    if "DYNAMIC_RUN_PROFILE" in os.environ and os.environ["DYNAMIC_RUN_PROFILE"].strip():
        try:
            parsed_profile = json.loads(os.environ["DYNAMIC_RUN_PROFILE"])
            if isinstance(parsed_profile, dict) and parsed_profile:
                active_profile = parsed_profile
                print(f"DEBUG: Successfully loaded profile from DYNAMIC_RUN_PROFILE (Keys: {list(active_profile.keys())})")
        except Exception as err:
            print(f"⚠️ Warning: Could not parse DYNAMIC_RUN_PROFILE: {err}")

    # 2. PRIORITY 2: Fallback lookup in activity.json using ACTIVE_TASK_ID
    if not active_profile:
        raw_task_id = os.environ.get("ACTIVE_TASK_ID", "process_03").strip().lower().replace("_", "").replace(" ", "")
        print(f"DEBUG: Searching activity.json for normalized task ID: '{raw_task_id}'")

        for k, v in data.items():
            clean_k = str(k).strip().lower().replace("_", "").replace(" ", "")
            if clean_k == raw_task_id and isinstance(v, dict):
                active_profile = v
                print(f"DEBUG: Matched profile key '{k}' in activity.json")
                break

    if not active_profile:
        print("⚠️ Warning: Could not resolve target profile. Falling back to default settings.")
        active_profile = data.get("process_03", {})

    import copy
    standalone_profile = copy.deepcopy(active_profile)

    setup_list = standalone_profile.get("setup_tasks") or standalone_profile.get("SETUP_TASKS", [])
    for setup_item in setup_list:
        date_from = setup_item.get("business_date_from") or setup_item.get("BUSINESS_DATE_FROM", "t")
        date_to = setup_item.get("business_date_to") or setup_item.get("BUSINESS_DATE_TO", "t")
        setup_item["business_date_from"] = parse_standalone_date(date_from)
        setup_item["business_date_to"] = parse_standalone_date(date_to)

    download_list = standalone_profile.get("download_task") or standalone_profile.get("TASKS", [])
    for download_item in download_list:
        date_from = download_item.get("business_date_from") or download_item.get("BUSINESS_DATE_FROM", "t")
        date_to = download_item.get("business_date_to") or download_item.get("BUSINESS_DATE_TO", "t")
        download_item["business_date_from"] = parse_standalone_date(date_from)
        download_item["business_date_to"] = parse_standalone_date(date_to)

    run_setup_val = bool(standalone_profile.get("cdsl_setup", standalone_profile.get("run_report_setup", False)))
    run_download_val = bool(standalone_profile.get("cdsl_download", standalone_profile.get("run_report_download", True)))

    return {
        "RUN_REPORT_SETUP": run_setup_val,
        "RUN_REPORT_DOWNLOAD": run_download_val,
        "FILE_EXPLORER_VISIBILITY": standalone_profile.get("file_explorer_visibility", True),
        "MAIN_PATH": standalone_profile.get("main_path", ""),
        "SETUP_TASKS": setup_list,
        "TASKS": download_list,
        "EMAIL_SETTINGS": email_cfg
    }

def clean_and_read_captcha(image_path):
    try:
        img = Image.open(image_path).convert("L")  
        img = img.resize((img.width * 3, img.height * 3), Image.Resampling.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(3.5).point(lambda x: 0 if x < 140 else 255, "1")
        text = pytesseract.image_to_string(img, config=r"--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        return "".join(text.split()).strip()
    except Exception: return ""

def clear_edge_cache():
    print("🧹 Initializing Microsoft Edge cache and cookie cleanup...")
    try: subprocess.run("taskkill /f /im msedge.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass
    edge_profile_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data")
    try:
        preferences_path = os.path.join(edge_profile_dir, "Default", "Preferences")
        if os.path.exists(preferences_path):
            with open(preferences_path, "r", encoding="utf-8") as f: prefs = json.load(f)
            if "profile" not in prefs: prefs["profile"] = {}
            prefs["profile"]["exit_type"] = "Normal"
            prefs["profile"]["exited_cleanly"] = True
            with open(preferences_path, "w", encoding="utf-8") as f: json.dump(prefs, f)
    except Exception: pass
    cache_targets = [
        os.path.join(edge_profile_dir, "Default", "Cache"), os.path.join(edge_profile_dir, "Default", "Code Cache"),
        os.path.join(edge_profile_dir, "Default", "Network", "Cookies"), os.path.join(edge_profile_dir, "Default", "Local Storage"),
    ]
    for target in cache_targets:
        if os.path.exists(target):
            try:
                if os.path.isdir(target): subprocess.run(f'rmdir /s /q "{target}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else: os.remove(target)
            except Exception: pass
    print("✓ Edge cache cleared successfully. Proceeding with a clean slate.")

def kill_all_cdsl_processes():
    """Force terminates all CDSL, Report Download, and associated Java process windows."""
    print("🧹 Force terminating active CDSLSecureapp and Report Download processes...")
    target_processes = [
        "CDSLSecureapp.exe",
        "ReportDownload.exe",
        "reportdownload.exe",
        "javaw.exe",
        "java.exe"
    ]
    for proc_name in target_processes:
        try:
            subprocess.run(
                f"taskkill /f /im {proc_name}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    # Win32 Title Search Fallback for unmanaged Java window handles
    try:
        report_app = Application(backend="uia").connect(title_re=".*Report Download.*", timeout=2)
        for _ in range(5):
            report_win = report_app.window(title_re=".*Report Download.*")
            if report_win.exists():
                hwnd = report_win.handle
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid:
                    subprocess.run(f"taskkill /f /pid {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
            else:
                break
    except Exception:
        pass

def close_stale_edge_tabs():
    print("🧹 Initializing workspace cleanup: Force terminating active Report Download and CDSL processes...")
    
    # Force kill all desktop processes together
    kill_all_cdsl_processes()

    try:
        edge_app = Application(backend="uia").connect(title_re=".*Microsoft\u200b Edge.*|.*Edge.*", timeout=2)
        for _ in range(20):
            target_tab = edge_app.window(title_re=".*cdslweb.*|.*RELIDCDAS.*|.*Home.*|.*REPORTDOWNLOAD.*", visible_only=True)
            if target_tab.exists(timeout=1):
                target_tab.set_focus()
                print("⌨️ [KEYS] Sending Ctrl+W command to discard matching active browser tab frame.")
                send_keys("^w")
                time.sleep(1.0) 
            else: break
    except Exception: pass
    print("✓ Workspace cleanup completed.")

def trigger_system_logout_reset(main_win, app_pid):
    print("Initializing recovery sequence: Forcing session logout to clear background locks...")
    main_win.set_focus()
    logout_btn = main_win.child_window(auto_id="AppWidget.fraHeader.btnLogout", control_type="Button", process=app_pid)
    if logout_btn.exists():
        print("🖱️ [CLICK] Clicking header main Logout button (auto_id: AppWidget.fraHeader.btnLogout).")
        logout_btn.click_input()
        time.sleep(1.0)
        confirm_dialog = Application(backend="uia").connect(title_re=".*CDSLSecureapp.*", found_index=0).window(title_re=".*CDSLSecureapp.*", found_index=0)
        yes_logout_btn = confirm_dialog.child_window(title="Yes", control_type="Button")
        if yes_logout_btn.exists(timeout=2):
            print("🖱️ [CLICK] Clicking Yes button inside the application logout popup modal.")
            yes_logout_btn.click_input()
            print("✓ Logout command executed. State cleared safely.")
            time.sleep(3)
            return True
    return False

def run_automation_flow(is_retry=False):
    config = load_config()
    toggles = load_task_toggles() 
    sys.modules['active_runtime_config'] = toggles
    run_setup = toggles.get("RUN_REPORT_SETUP", False)
    run_download = toggles.get("RUN_REPORT_DOWNLOAD", True)

    print(f"Active Execution Toggles -> Setup Enabled: {run_setup} | Download Enabled: {run_download}")
    
    app_path = config.get("app_path") or config.get("APP_PATH")
    dp_rta_id = config.get("dp_rta_id") or config.get("DP_RTA_ID")
    user_id = config.get("user_id") or config.get("USER_ID")
    app_password_keys = config.get("app_password_keys") or config.get("app_password", "")
    web_password_keys = config.get("web_password_keys") or config.get("web_password", "")

    print("🧹 Purging active or orphaned CDSL desktop app modules...")
    kill_all_cdsl_processes()

    if not is_retry:
        clear_edge_cache()     
        close_stale_edge_tabs() 
        time.sleep(1)
        try: 
            print(f"🚀 Launching main application frame: {app_path}")
            subprocess.Popen(app_path)
            time.sleep(5.0)
        except Exception: return False
    
    app_pid = None
    hwnd = 0
    elapsed_time = 0
    while elapsed_time < 35:
        hwnd = win32gui.FindWindow(None, "CDSLSecureapp")
        if hwnd > 0:
            _, app_pid = win32process.GetWindowThreadProcessId(hwnd)
            break
        time.sleep(3)
        elapsed_time += 3

    if hwnd == 0 or app_pid is None: 
        print("❌ Critical Error: Could not verify application process handle bounds.")
        return False

    try:
        app = Application(backend="uia").connect(process=app_pid, timeout=10)
        main_win = app.window(handle=hwnd)
        print("⏳ Waiting for UI engine structural layouts to fully render...")
        main_win.wait("exists enabled visible", timeout=15)
    except Exception as hook_err:
        print(f"❌ Failed connecting UIA interface block: {hook_err}")
        return False

    try:
        main_win.set_focus()
        time.sleep(2.0) 
        print("🖱️ [CLICK] Clicking central workspace coordinate inside main application screen framework.")
        main_win.click_input()
        time.sleep(1.0)
        
        try:
            logout_btn = main_win.child_window(auto_id="AppWidget.fraHeader.btnLogout", control_type="Button", process=app_pid)
            if logout_btn.exists(timeout=2) and logout_btn.is_visible():
                trigger_system_logout_reset(main_win, app_pid)
                main_win.set_focus(); time.sleep(1.5)
        except Exception: pass

        print("🔍 Evaluating live desktop application display interface layout...")
        state_resolved = False
        
        for attempt_check in range(1, 12):
            main_win.set_focus()
            time.sleep(1.5)
            visible_elements = main_win.descendants()
            auto_ids = [str(el.automation_id()) for el in visible_elements if el.automation_id()]

            if "AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ControlPanelFrame.pgControlPanel.saButtons.qt_scrollarea_viewport.scrollAreaButtonContents.CDAS New" in auto_ids:
                print("🌐 Direct Entry: Dashboard view confirmed active. Initializing inline browser redirection...")
                cdas_new_btn = main_win.child_window(auto_id="AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ControlPanelFrame.pgControlPanel.saButtons.qt_scrollarea_viewport.scrollAreaButtonContents.CDAS New", control_type="Button")
                print("🖱️ [CLICK] Clicking CDAS New dashboard option node button trigger.")
                cdas_new_btn.click_input()
                
                print("⏳ Redirection triggered. Monitoring system processes for Edge browser container mount...", flush=True)
                browser_mounted = False
                for sync_attempt in range(25):
                    try:
                        temp_browser_app = Application(backend="uia").connect(title_re=".*Edge.*|.*Microsoft\u200b Edge.*", timeout=1)
                        temp_win = temp_browser_app.window(title_re=".*RELIDCDAS.*|.*cdslweb.*")
                        if temp_win.exists():
                            doc_element = temp_win.child_window(auto_id="RootWebArea", control_type="Document")
                            if doc_element.exists():
                                print(f"✓ Browser view stabilized and ready after {sync_attempt + 1} second(s)!")
                                browser_mounted = True
                                break
                    except Exception: pass
                    time.sleep(1.0)
                
                if not browser_mounted:
                    print("⚠️ Redirection wait exceeded baseline constraints. Attempting default focus fallback...")
                state_resolved = True
                break 

            elif "AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ChlngHandlerFrame.fraChlng.PasswordFrame.frmContainer.lePassword" in auto_ids:
                print("🔑 Form State: Secondary verification form active. Submitting main application access password...")
                password_field = main_win.child_window(auto_id="AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ChlngHandlerFrame.fraChlng.PasswordFrame.frmContainer.lePassword", control_type="Edit")
                password_field.click_input()
                time.sleep(0.3)
                send_keys("^a{BACKSPACE}")
                # USE DESKTOP APP PASSWORD
                send_keys(app_password_keys, with_spaces=True)
                time.sleep(0.5)
                try:
                    main_win.child_window(title="Submit", auto_id="AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ChlngHandlerFrame.fraChlng.PasswordFrame.fraSubCan.btnSubmit", control_type="Button").click_input()
                except Exception: 
                    send_keys("{ENTER}")
                state_resolved = True
                time.sleep(6.0)
                continue

            elif "AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ChlngHandlerFrame.fraChlng.CheckUserFrame.innerCUF.cmbGroup" in auto_ids:
                print("📝 Form State: Credential form entry view active. Typing user details...")
                dp_dropdown = main_win.child_window(auto_id="AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ChlngHandlerFrame.fraChlng.CheckUserFrame.innerCUF.cmbGroup", control_type="ComboBox")
                print("🖱️ [CLICK] Opening DP RTA identification option combo selection dropdown index grid.")
                dp_dropdown.click_input()
                time.sleep(0.5)
                print("⌨️ [KEYS] Clearing dropdown input buffer via select-all delete sequence.")
                send_keys("^a{BACKSPACE}")
                print(f"⌨️ [KEYS] Direct injection payload value to target object field: '{dp_rta_id}'")
                send_keys(dp_rta_id, with_spaces=True)
                time.sleep(0.5)
                
                username_field = main_win.child_window(auto_id="AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.ChlngHandlerFrame.fraChlng.CheckUserFrame.innerCUF.leUsername", control_type="Edit")
                print("🖱️ [CLICK] Shifting focus parameter boundaries to Username field control structure.")
                username_field.click_input()
                time.sleep(0.3)
                print("⌨️ [KEYS] Clearing username textual tracking layout element structure.")
                send_keys("^a{BACKSPACE}")
                print(f"⌨️ [KEYS] Processing automation string entry payload: '{user_id}'")
                send_keys(user_id, with_spaces=True)
                time.sleep(0.5)
                print("⌨️ [KEYS] Sending operational processing submission trigger key (Enter).")
                send_keys("{ENTER}")
                state_resolved = True
                time.sleep(6.0)
                continue

            elif "AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.LoginFrame.BtnLogin" in auto_ids:
                print("🎯 Landing State: Login Entry view detected. Moving to credential window forms...")
                landing_access_btn = main_win.child_window(auto_id="AppWidget.fraContentHolder.fraMainFrame.fraHolder.fraContent.LoginFrame.BtnLogin", control_type="Button")
                print("🖱️ [CLICK] Pushing central system Entry trigger element action point.")
                landing_access_btn.click_input()
                state_resolved = True
                time.sleep(3.0)
                continue
            
            print("⏳ Refreshing application tree hierarchy checks...")
            
        if not state_resolved:
            print("❌ Error: Application layout structure failed to stabilize into a known state configuration.")
            return False

        # ✅ NEW CODE (Resilient Browser Connection)
        browser_app = Application(backend="uia").connect(title_re=".*Edge.*|.*Microsoft\u200b Edge.*", timeout=15)

        # Try connecting via web portal keywords first
        try:
            browser_win = browser_app.window(title_re="(?i).*(RELIDCDAS|cdslweb|Home|CDSL).*")
            if not browser_win.exists(timeout=3):
                # Fallback to the top-level active Edge window
                browser_win = browser_app.top_window()
        except Exception:
            browser_win = browser_app.top_window()

        try:
            browser_win.maximize()
        except Exception:
            pass

        browser_win.set_focus()
        time.sleep(2.0)
        
        page_text = ""
        try:
            doc_element = browser_win.child_window(auto_id="RootWebArea", control_type="Document")
            if doc_element.exists(timeout=5): 
                page_text = str(doc_element.legacy_properties().get('Value', ''))
        except Exception: pass
            
        if "Already Running" in page_text or "Timed-Out" in page_text or "Timeout" in browser_win.window_text():
            trigger_system_logout_reset(main_win, app_pid); return "RETRY"

        captcha_success = False
        for attempt in range(1, 4):
            print(f"🤖 Captcha Resolution Pipeline: Processing Attempt {attempt}/3...")
            
            web_password_field = browser_win.child_window(auto_id="txt-password", control_type="Edit")
            web_captcha_field = browser_win.child_window(auto_id="txt-captcha", control_type="Edit")
            web_login_btn = browser_win.child_window(auto_id="btn-login", control_type="Button")
            web_captcha_image = browser_win.child_window(auto_id="captcha", control_type="Image", visible_only=True)

            if not web_password_field.exists(timeout=12): 
                print("❌ Web form fields are unavailable or not matching expected tree nodes.")
                break
            
            print("🖱️ [CLICK] Activating portal container webpage password entry text fields.")
            web_password_field.click_input()
            time.sleep(0.5)
            print("⌨️ [KEYS] Flushing standard field content arrays internally.")
            send_keys("^a{BACKSPACE}")
            time.sleep(0.2)
            print("⌨️ [KEYS] Translating credentials target collection array to target field layout.")
            send_keys(web_password_keys, with_spaces=True)
            time.sleep(0.5)

            rect = web_captcha_image.rectangle()
            screenshot = browser_win.capture_as_image()
            win_rect = browser_win.rectangle()
            
            crop_box = (
                rect.left - win_rect.left, 
                rect.top - win_rect.top, 
                rect.right - win_rect.left, 
                rect.bottom - win_rect.top
            )
            
            temp_captcha_path = os.path.join(os.environ.get("TEMP", "."), "temp_captcha.png")
            screenshot.crop(crop_box).save(temp_captcha_path)

            extracted_captcha = clean_and_read_captcha(temp_captcha_path)
            print(f"🤖 OCR Decoded Verification Value: '{extracted_captcha}'")
            try: os.remove(temp_captcha_path)
            except: pass

            print("🖱️ [CLICK] Targeting web browser document model CAPTCHA entry object frame.")
            web_captcha_field.click_input()
            time.sleep(0.5)
            print("⌨️ [KEYS] Discarding residual validation characters text layout elements.")
            send_keys("^a{BACKSPACE}")
            time.sleep(0.2)
            print(f"⌨️ [KEYS] Typing dynamically generated OCR output string tracking payload: '{extracted_captcha}'")
            send_keys(extracted_captcha, with_spaces=True)
            time.sleep(0.5)
            
            print("🖱️ [CLICK] Submitting active browser web authentication entry layout form grid dashboard (auto_id: btn-login).")
            web_login_btn.click_input()
            time.sleep(4.0)

            try:
                invalid_alert = browser_win.child_window(title_re=".*Valid Characters.*|.*Valid.*", control_type="Text")
                if invalid_alert.exists(timeout=2):
                    print("⚠️ Invalid Captcha character block encountered. Requesting new pattern...")
                    ok_btn = browser_win.child_window(title="OK", control_type="Button")
                    if ok_btn.exists(): 
                        print("🖱️ [CLICK] Acknowledging incorrect alphanumeric string input confirmation box.")
                        ok_btn.click_input()
                    else: 
                        print("⌨️ [KEYS] Overriding validation warning box modal loop via Enter key target routing.")
                        send_keys("{ENTER}")
                    time.sleep(1.5)
                    continue  
            except Exception: pass

            try:
                yes_button = browser_win.child_window(title="Yes", control_type="Button")
                if yes_button.exists(timeout=2): 
                    print("🖱️ [CLICK] Clicking Yes on multi-session authentication warning prompt inside browser layout sheet.")
                    yes_button.click_input()
                    time.sleep(2.0)
            except Exception: pass
            
            captcha_success = True
            print("✓ Web login authentication loop verified successfully.")
            break

        if not captcha_success:
            print("❌ All 3 CAPTCHA attempts failed. Initiating full process recycle...")
            trigger_system_logout_reset(main_win, app_pid)
            return "FULL_RESET"

        time.sleep(5) 
        browser_win = browser_app.top_window()
        browser_win.maximize(); browser_win.set_focus(); time.sleep(2)

        if run_setup:
            print("\n⚙️ JSON FLAG ENABLED: Initializing 'Report Setup' routing process...")
            setup_clicked = False
            
            # 1. First check for direct UIA elements
            try:
                report_setup_text = browser_win.child_window(title_re="(?i).*(Reports? Setup).*", control_type="Text")
                if report_setup_text.exists(timeout=4):
                    print("🖱️ [CLICK] Navigating to Reports Setup console navigation sublink text.")
                    report_setup_text.click_input()
                    setup_clicked = True
            except Exception:
                pass

            # 2. Fallback search through all text descendants
            if not setup_clicked:
                try:
                    text_elements = browser_win.descendants(control_type="Text")
                    for el in text_elements:
                        txt_val = el.window_text().strip().lower()
                        if "report setup" in txt_val or "reports setup" in txt_val:
                            if el.is_visible():
                                print(f"🖱️ [CLICK] Navigating to matched setup link: '{el.window_text()}'")
                                el.click_input()
                                setup_clicked = True
                                break
                except Exception as search_err:
                    print(f"⚠️ Fallback menu search error: {search_err}")

            if setup_clicked:
                time.sleep(5.0)
                execute_report_setup_form()
            else:
                print("Error: Could not locate 'Reports Setup' text item on portal layout tree.")

            print("\n🌐 Returning page state context back to the central Home dashboard screen...")
            browser_win = browser_app.top_window()
            browser_win.set_focus()
            print("⌨️ [KEYS] Focusing browser URL navigation box bar using shortcut macro sequence.")
            send_keys("^l")
            time.sleep(0.5)
            print("⌨️ [KEYS] Routing primary window window context directly back to Home portal dashboard URL path.")
            send_keys("http://cdslweb.cdslindia.com/RELIDCDASWEBCORE/Home{ENTER}", with_spaces=True)
            time.sleep(5) 

        if run_download:
            print("\n⚙️ JSON FLAG ENABLED: Initializing 'Report Download' routing process...")
            browser_win = browser_app.top_window()
            browser_win.set_focus()
            time.sleep(1.0)
            
            report_download_text = browser_win.child_window(title="Report Download", control_type="Text")
            if report_download_text.exists(timeout=8):
                print("🖱️ [CLICK] Navigating into Report Download system menu configuration node layer tracking.")
                report_download_text.click_input()
                time.sleep(5) 
                try:
                    open_button = browser_win.child_window(title="Open", control_type="Button")
                    if open_button.exists(timeout=5):
                        print("🎯 Clicked Open. Initiating dynamic synchronization wait for the Report Download environment to load completely...")
                        print("🖱️ [CLICK] Activating system level download file frame handling component Open button.")
                        open_button.click_input()
                        
                        for minutes_left in range(1, 0, -1):
                            print(f"⏳ {minutes_left} minute(s) remaining for report download app preparation...")
                            time.sleep(60)
                            
                        execute_report_download_form()
                        return True
                    else: return False
                except Exception as e: 
                    print(f"❌ Error during download framework generation: {e}")
                    return False
            else: return False

        return True
    except Exception as e:
        print(f"\n[Execution Interrupt]: {e}")
        return False

def main():
    log_file_handle = None
    try:
        log_file_handle = setup_execution_logger()
        attempt_cycle = 1
        print(f"\n🚀 Starting Master Automation Run - Cycle Loop #{attempt_cycle}")
        status = run_automation_flow(is_retry=False)
        
        while status in ("RETRY", "FULL_RESET"):
            attempt_cycle += 1
            time.sleep(3)
            if status == "FULL_RESET":
                print(f"\n🔄 [CAPTCHA RESET TRIGGERED] Entering Cycle Loop #{attempt_cycle} -- Hard resetting environment...")
                clear_edge_cache()
                close_stale_edge_tabs()
                status = run_automation_flow(is_retry=False)
            else:
                print(f"\n🔄 [SESSION TIMEOUT RETRY] Entering Cycle Loop #{attempt_cycle} -- Standard retry...")
                status = run_automation_flow(is_retry=True)
                
        if status is True: 
            print("\n🎉 Run finished successfully!")
        else: 
            print("\n❌ Automation process terminated with errors.")
            sys.exit(1)

    finally:
        print("\n🧹 Final cleanup: Killing all CDSL and Report Download instances...")
        kill_all_cdsl_processes()
        print("\n🏁 Closing log session hook cleanly.")
        if log_file_handle:
            log_file_handle.close()

if __name__ == "__main__":
    main()