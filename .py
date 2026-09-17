import sys
import os

# --- CRITICAL FIX: Force UTF-8 stdout/stderr streams on Windows ---
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
# -------------------------------------------------------------------

os.environ["PYWINAUTO_LOG_LEVEL"] = "OFF"
import logging

if getattr(sys, 'frozen', False):
    import logging.config
    def dummy_file_config(*args, **kwargs):
        pass
    logging.config.fileConfig = dummy_file_config
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

def resolve_password_value(val):
    """Decodes Base64 password if applicable; otherwise returns plain text."""
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
    """Case-insensitively resolves requested process key inside JSON."""
    if not requested_name:
        return None
    for key in config.keys():
        if key.lower() == requested_name.lower():
            return key
    return None


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

    # 2. Case-insensitive lookup of target process block
    matched_key = resolve_process_key(master_config, process_name_arg)
    process_data = master_config.get(matched_key, {}) if matched_key else {}

    if not matched_key:
        available_processes = get_process_keys(master_config)
        logger.warning(
            f"⚠️ Requested process '{process_name_arg}' not explicitly matched. "
            f"Available keys in JSON: {available_processes}"
        )
        # Check if process_name_arg exists directly or use fallback
        process_data = master_config.get(process_name_arg, {})
        matched_key = process_name_arg

    # Set active runtime environment parameters (for CDAS legacy sub-modules)
    os.environ["ACTIVE_TASK_ID"] = matched_key
    os.environ["DYNAMIC_RUN_PROFILE"] = json.dumps(process_data)

    # 3. ROUTING ENGINE: Route based on JSON signature
    
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

            login_window.wait('visible', timeout=12)
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
            handle_administration(main_window, process_data, global_config=master_config, process_name=matched_key)
            logger.info(f"=== Process execution completed: '{matched_key}' ===")

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
                    candidates = desktop.windows(title="Cross", control_type="Window", top_level_only=False)

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

        finally:
            if full_execution_recorder.is_active():
                logger.info("Finalizing background video recorder tracking...")
                full_execution_recorder.stop()

    else:
        logger.error(f"❌ Unknown workflow JSON structure for process '{process_name_arg}' in {target_config_path}")
        raise ValueError(f"Unknown workflow JSON structure for process '{process_name_arg}' in {target_config_path}")


if __name__ == "__main__":
    run_universal_automation()