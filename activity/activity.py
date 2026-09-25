import sys
import types
import re
import logging

# =========================================================================
# 1. MUST BE FIRST: Mock 'logger' module to stop PyWinAuto logging.conf crash
# =========================================================================
if 'logger' not in sys.modules:
    mock_logger = types.ModuleType('logger')
    mock_logger.Logger = logging.getLogger
    sys.modules['logger'] = mock_logger

# Disable pywinauto internal logging
os_env = getattr(sys, 'frozen', False)
import os
os.environ["PYWINAUTO_LOG_LEVEL"] = "OFF"

if getattr(sys, 'frozen', False):
    import logging.config
    def dummy_file_config(*args, **kwargs):
        pass
    logging.config.fileConfig = dummy_file_config

# =========================================================================
# 2. NOW standard imports can execute safely
# =========================================================================
import pytesseract  # Forces PyInstaller to detect pytesseract automatically
import App          # App.py imports pywinauto, which now uses our mock 'logger'

# UTF-8 Stream fix
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import json
import time
import re
import base64
from datetime import datetime

# Resolves base execution directory whether running raw .py or PyInstaller EXE
def get_base_dir():
    """Returns the base directory where activity.exe or activity.py resides."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

SCRIPT_DIR = get_base_dir()
PAGES_DIR = os.path.join(SCRIPT_DIR, "pages")

# Dynamically bind local module lookup paths
for p in (SCRIPT_DIR, PAGES_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from logger_config import setup_logger

logger = setup_logger()

RESERVED_KEYS = {
    "app_path", "backend", "main_file_path", "auto_close", 
    "common_steps", "smtp_config", "email_settings", "global_app_settings"
}


# --- Shared task-result ledger (log.json) -----------------------------------
def default_log_json_path():
    return os.path.join(SCRIPT_DIR, "schedule_log", "log.json")

def resolve_log_json_path():
    target_path = get_cli_arg("--config") or get_cli_arg("-c")
    try:
        if target_path and os.path.exists(target_path):
            with open(target_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            override = cfg.get("log_json")
            if override:
                if os.path.isabs(override):
                    return override
                return os.path.join(SCRIPT_DIR, override)
    except Exception:
        pass
    return default_log_json_path()

def get_log_json_path():
    if not hasattr(get_log_json_path, "_cached"):
        get_log_json_path._cached = resolve_log_json_path()
    return get_log_json_path._cached

def load_log_ledger():
    ledger_path = get_log_json_path()
    if not os.path.exists(ledger_path):
        return []
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def append_log_entry(entry):
    ledger_path = get_log_json_path()
    try:
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        entries = load_log_ledger()
        entries.append(entry)
        tmp_path = ledger_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp_path, ledger_path)
    except Exception as err:
        logger.warning(f"Failed to append activity ledger entry: {err}")

def write_activity_result(process_name, ok, reason=""):
    """Record the real business outcome for a process in the shared ledger."""
    now = datetime.now()
    entry = {
        "date": now.strftime("%d-%b-%Y"),
        "task": process_name,
        "Status": "success" if ok else "unsuccess",
        "time": now.strftime("%H:%M:%S"),
    }
    append_log_entry(entry)
    logger.info(f"Ledger result recorded for '{process_name}': {'success' if ok else 'failure'}")



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

def get_cli_arg(param_name, default_val=None):
    """Safely extracts command line argument values by key (e.g. --config path)."""
    if param_name in sys.argv:
        idx = sys.argv.index(param_name)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return default_val


def resolve_config_path(config_arg):
    """Resolves local or absolute path to the target activity JSON file."""
    if config_arg and os.path.isabs(config_arg) and os.path.exists(config_arg):
        return config_arg
    
    if config_arg:
        cand = os.path.join(SCRIPT_DIR, config_arg)
        if os.path.exists(cand):
            return cand

    # Fallback to standard local activity filenames
    for default_fname in ("activity.json", "Activity.json", "action.json", "Action.json"):
        def_cand = os.path.join(SCRIPT_DIR, default_fname)
        if os.path.exists(def_cand):
            return def_cand
            
    return config_arg or os.path.join(SCRIPT_DIR, "activity.json")


def get_process_keys(config):
    """Retrieves process block keys excluding reserved global configurations."""
    return [key for key in config.keys() if key not in RESERVED_KEYS]


def resolve_process_key(config, requested_name):
    """Case-insensitive and symbol-agnostic lookup for JSON process keys."""
    if not requested_name or not isinstance(config, dict):
        return None
        
    clean_requested = str(requested_name).lower().replace("_", "").replace(" ", "").strip()
    
    for key in config.keys():
        clean_key = str(key).lower().replace("_", "").replace(" ", "").strip()
        if clean_key == clean_requested:
            return key
            
    return None


def run_tradeplus_pipeline(master_config):
    """
    TradePlus automation branch. Reuses the existing, already-working page
    objects (LoginPage, MainPage, ControlCenterPage, SharePayoutPage,
    PledgePage) - these must live in the same 'pages' folder as
    administration_page.py. This function mirrors app.py's orchestration
    loop, adapted to run as part of the universal engine instead of a
    standalone script.
    """
    from pywinauto import Application
    from pywinauto.keyboard import send_keys
    from screen_recorder import ScreenRecorder
    from pages.login_page import LoginPage
    from pages.main_page import MainPage
    from pages.control_center_page import ControlCenterPage
    from pages.share_payout_page import SharePayoutPage
    from pages.pledge_page import PledgePage

    app_config = master_config.get("app_config", {})
    application_path = app_config.get("application_path") or app_config.get("APPLICATION_PATH")
    username = app_config.get("username") or app_config.get("USERNAME")
    password = app_config.get("password") or app_config.get("PASSWORD")

    if not application_path:
        raise ValueError("Missing 'app_config.application_path' inside JSON for TradePlus pipeline")

    app_exe = os.path.basename(application_path)
    logger.info(f"Checking for active instances of '{app_exe}'...")
    os.system(f"taskkill /F /IM {app_exe} /T >nul 2>&1")
    time.sleep(2.0)

    recorder = ScreenRecorder()
    exec_time_str = datetime.now().strftime("%H-%M-%S")
    recorder.start(f"TradePlus Execution_{exec_time_str}")

    try:
        logger.info(f"Launching target binary: {application_path}")
        app = Application(backend="uia").start(application_path)
        time.sleep(6.0)

        logger.info(f"Performing login for username: '{username}'")
        login_page = LoginPage(app)
        login_page.login(username, password)
        time.sleep(4.0)

        main_page = MainPage(app)
        pipeline = master_config.get("execution_pipeline", [])
        total_steps = sum(len(p.get("sub_pipeline", [])) for p in pipeline)
        logger.info(f"Discovered {total_steps} sub-pipeline step(s) across {len(pipeline)} parent menu block(s).")

        for parent_cfg in pipeline:
            if not parent_cfg.get("enabled", False):
                continue
            parent_menu_name = parent_cfg.get("Parent_Menu", "Utilities")

            for step_cfg in parent_cfg.get("sub_pipeline", []):
                if not step_cfg.get("enabled", False):
                    continue
                menu_type = step_cfg.get("Menu", "").strip().lower()
                logger.info(f"--- Processing step: {menu_type} ---")

                if menu_type == "control_center":
                    main_page.click_submenu_by_text(parent_menu_name, "Control Center")
                    time.sleep(3.0)
                    page = ControlCenterPage(app)
                    while True:
                        status = page.process(raw_workflow_config=step_cfg)
                        if status == "RESTART":
                            logger.warning("Control Center requested restart (settlement dialog). Retrying step...")
                            time.sleep(3.0)
                            continue
                        break
                    page.close_window()

                elif menu_type == "demat_processes":
                    main_page.click_submenu_by_text(parent_menu_name, "Demat Processes")
                    time.sleep(2.5)
                    page = SharePayoutPage(app)
                    page.process(raw_workflow_config=step_cfg)

                elif menu_type == "pledge_management":
                    main_page.click_submenu_by_text(parent_menu_name, "Pledge Management")
                    time.sleep(2.5)
                    page = PledgePage(app)
                    page.process(raw_workflow_config=step_cfg)

                else:
                    logger.warning(f"Unrecognized Menu type '{menu_type}' inside sub_pipeline - skipping.")

        logger.info("TradePlus pipeline completed successfully.")

        auto_close_flag = master_config.get("auto_close", False)
        if auto_close_flag:
            logger.info("'auto_close' is enabled. Attempting to close TradePlusX...")
            try:
                send_keys("%{F4}")
                time.sleep(1.5)
                send_keys("{LEFT}{ENTER}")
            except Exception as close_err:
                logger.warning(f"Auto-close fallback failed: {close_err}")

    finally:
        if recorder.is_active():
            logger.info("Finalizing TradePlus execution recorder...")
            recorder.stop()


def run_universal_automation():
    # 1. Parse CLI inputs or fallbacks
    json_config_arg = get_cli_arg("--config") or get_cli_arg("-c", "activity.json")
    process_name_arg = get_cli_arg("--process") or get_cli_arg("-p", "process_01")

    target_config_path = resolve_config_path(json_config_arg)

    logger.info("==================================================")
    logger.info("=== UNIVERSAL AUTOMATION ENGINE INITIALIZING ===")
    logger.info(f"📄 Target Configuration File : {target_config_path}")
    logger.info(f"🎯 Target Process Requested   : {process_name_arg}")
    logger.info("==================================================")

    if not os.path.exists(target_config_path):
        logger.error(f"❌ Configuration profile not found at: '{target_config_path}'")
        raise FileNotFoundError(f"Configuration profile not found at: '{target_config_path}'")

    with open(target_config_path, "r", encoding="utf-8") as f:
        master_config = json.load(f)

    # 1. Case and underscore-insensitive key resolution
    matched_key = resolve_process_key(master_config, process_name_arg)
    
    # Fallback to direct arg if resolve_process_key didn't match
    if not matched_key:
        available_processes = get_process_keys(master_config)
        logger.warning(
            f"⚠️ Requested process '{process_name_arg}' not explicitly matched. "
            f"Available keys in JSON: {available_processes}"
        )
        matched_key = process_name_arg

    # Retrieve process dictionary safely
    process_data = master_config.get(matched_key, {})

    # 2. FORCE update environment variables BEFORE calling App.py / CDAS Pipeline
    os.environ["ACTIVE_TASK_ID"] = str(matched_key).lower().strip()
    os.environ["DYNAMIC_RUN_PROFILE"] = json.dumps(process_data)

    logger.info(f"🔑 Environment ACTIVE_TASK_ID set to: '{os.environ['ACTIVE_TASK_ID']}'")
    logger.info(f"📦 Environment DYNAMIC_RUN_PROFILE keys: {list(process_data.keys())}")

    # --- BRANCH 1: CDAS AUTOMATION PIPELINE ---
    if any(k in process_data for k in ("download_task", "setup_tasks", "cdsl_download", "cdsl_setup")):
        logger.info("🌐 [ROUTER] Signature Matched: CDAS AUTOMATION PIPELINE")
        try:
            from App import main as run_cdas_app
            run_cdas_app()
        except ImportError:
            import App
            App.main()

    # --- BRANCH 2: CROSS STEP-BASED AUTOMATION PIPELINE ---
    elif "steps" in process_data or "common_steps" in master_config:
        logger.info("🖥️ [ROUTER] Signature Matched: CROSS APPLICATION STEP PIPELINE")
        
        from pywinauto import Application, Desktop
        from pywinauto.keyboard import send_keys
        from pages.administration_page import handle_administration
        from screen_recorder import ScreenRecorder

        # Retrieve app path from global or root profile
        app_path = master_config.get('app_path') or (master_config.get('global_app_settings') or {}).get('app_path')
        if not app_path:
            raise ValueError("Missing 'app_path' configuration setting inside activity.json")

        app_exe = os.path.basename(app_path)
        
        logger.info(f"Checking for active instances of '{app_exe}'...")
        os.system(f"taskkill /F /IM {app_exe} /T >nul 2>&1")
        time.sleep(2.0)

        # Initialize screen recorder
        full_execution_recorder = ScreenRecorder()
        exec_time_str = datetime.now().strftime("%H-%M-%S")
        full_execution_folder_name = f"Full Execution_{exec_time_str}"
        full_execution_recorder.start(full_execution_folder_name)

        backend_type = master_config.get('backend', 'uia')

        try:
            logger.info(f"Launching target binary: {app_path}")
            app = Application(backend=backend_type).start(app_path)
            time.sleep(3.0)

            main_window = app.window(class_name="ThunderRT6MDIForm")
            login_window = main_window.child_window(class_name="ThunderRT6FormDC", title="Login")

            login_window.wait('visible', timeout=60)
            logger.info("Login modal container detected.")

            # --- Inside run_universal_automation() where common_steps are processed ---
            common_steps = master_config.get('common_steps', [])
            for index, step in enumerate(common_steps, start=1):
                logger.info(f"Executing Login Step {index}: {step.get('description', '')}")
                element = login_window.child_window(
                    auto_id=step['automation_id'],
                    control_type=step['control_type']
                )

                if step['action'] == "type_keys":
                    element.set_focus()
                    time.sleep(0.1)
                    try:
                        element.set_text("")
                    except Exception:
                        pass
                    element.click_input()
                    element.type_keys("^a{BACKSPACE}", with_spaces=True)
                    time.sleep(0.2)

                    # --- RESOLVE BASE64 OR PLAIN TEXT VALUE FOR BOTH 'value_enc' AND 'value' ---
                    raw_val = (
                        step.get('value_enc') or 
                        step.get('VALUE_ENC') or 
                        step.get('value') or 
                        step.get('VALUE', '')
                    )
                    resolved_val = resolve_password_value(raw_val)

                    element.type_keys(resolved_val, with_spaces=True, pause=0.05)

                elif step['action'] == "click":
                    element.click()

                time.sleep(0.5)

            logger.info("Login sequence finalized. Waiting for desktop workspace interface...")
            time.sleep(4.0)

            
           # Run process sequence
            logger.info(f"=== Starting process execution: '{matched_key}' ===")
            import_failed = False
            failure_reason = ""
            try:
                # Capture the verdict returned from administration_page
                result = handle_administration(main_window, process_data, global_config=master_config, process_name=matched_key)
                if result and isinstance(result, tuple):
                    import_failed, failure_reason = bool(result[0]), str(result[1] or "")
            except Exception as proc_err:
                import_failed = True
                failure_reason = f"Process execution raised: {proc_err}"
                logger.error(f"Process execution failed: {proc_err}")
            logger.info(f"=== Process execution completed: '{matched_key}' ===")

            # Write the result to schedule_log/log.json
            write_activity_result(matched_key, ok=not import_failed, reason=failure_reason)
            
            # Check auto_close setting
            auto_close_flag = master_config.get("auto_close", False)
            if auto_close_flag:
                logger.info("'auto_close' is enabled. Initiating main application termination sequence...")
                try:
                    main_window.set_focus()
                    time.sleep(0.3)
                    main_window.type_keys("%{F4}", with_spaces=False)
                    time.sleep(1.5)

                    desktop = Desktop(backend="uia")
                    candidates = desktop.windows(title_re=r'^"(Cross|Estro)$"', control_type="Window", top_level_only=False)

                    yes_btn = None
                    for candidate in candidates:
                        try:
                            btn = candidate.child_window(title="Yes", control_type="Button")
                            btn.wrapper_object()
                            yes_btn = btn
                            break
                        except Exception:
                            continue

                    if yes_btn:
                        yes_btn.click_input()
                        logger.info("Application closed cleanly.")
                    else:
                        send_keys("{LEFT}{ENTER}")

                except Exception as close_err:
                    logger.warning(f"Auto-close fallback: {close_err}")
                    send_keys("{LEFT}{ENTER}")

        # Hard exit if failure occurred so manager registers the failure
            if import_failed:
                logger.error("Automation process terminated with errors (import_failed).")
                sys.exit(1)

        finally:
            if full_execution_recorder.is_active():
                logger.info("Finalizing background video recorder tracking...")
                full_execution_recorder.stop()

    # --- BRANCH 3: TRADEPLUS AUTOMATION PIPELINE ---
    elif "execution_pipeline" in master_config or "app_config" in master_config:
        logger.info("📈 [ROUTER] Signature Matched: TRADEPLUS AUTOMATION PIPELINE")
        run_tradeplus_pipeline(master_config)

    else:
        logger.error(f"❌ Unknown workflow JSON structure for process '{process_name_arg}' in {target_config_path}")
        raise ValueError(f"Unknown workflow JSON structure for process '{process_name_arg}' in {target_config_path}")


if __name__ == "__main__":
    run_universal_automation()
    