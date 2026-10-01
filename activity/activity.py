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
    process_name_arg = get_cli_arg("--process") or get_cli_arg("-p")

    target_config_path = resolve_config_path(json_config_arg)

    logger.info("==================================================")
    logger.info("=== UNIVERSAL AUTOMATION ENGINE INITIALIZING ===")
    logger.info(f"📄 Target Configuration File : {target_config_path}")
    logger.info(f"🎯 Target Process Requested   : {process_name_arg or '<none passed — will use first process in JSON>'}")
    logger.info("==================================================")

    if not os.path.exists(target_config_path):
        logger.error(f"❌ Configuration profile not found at: '{target_config_path}'")
        raise FileNotFoundError(f"Configuration profile not found at: '{target_config_path}'")

    with open(target_config_path, "r", encoding="utf-8") as f:
        master_config = json.load(f)

    # When the exe is started with NO process name (double-clicked, or run bare
    # from CMD), default to the FIRST process key defined in this client's JSON
    # instead of a hardcoded name that may not exist on this client.
    if not process_name_arg:
        first_keys = get_process_keys(master_config)
        if first_keys:
            process_name_arg = first_keys[0]
            logger.info(f"ℹ️ No process name passed on the command line — defaulting to the first process in JSON: '{process_name_arg}'")
        else:
            process_name_arg = "process_01"

    # 1. Case and underscore-insensitive key resolution
    matched_key = resolve_process_key(master_config, process_name_arg)
    
    # Fallback to direct arg if resolve_process_key didn't match. The run must fail
    # loudly later if this key has no steps — never launch the app, log in, and close
    # it again with zero work done (that looks like the app closing on its own).
    process_key_unmatched = not matched_key
    if process_key_unmatched:
        available_processes = get_process_keys(master_config)
        logger.critical(
            f"❌ Requested process '{process_name_arg}' was NOT FOUND in the JSON. "
            f"Available keys: {available_processes}. Make the name passed by "
            f"scheduler.json (or the -p argument) match a key in activity.json EXACTLY."
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

        # Guard: an unmatched process key (or a key with no steps) must abort BEFORE
        # the app is launched — otherwise the run does zero steps and auto_close
        # shuts the app again, which looks like the app closing by itself.
        if process_key_unmatched or not process_data.get("steps"):
            raise ValueError(
                f"Process '{process_name_arg}' has no 'steps' in the config (name not "
                f"found or empty definition). Aborting BEFORE launching the app. Fix "
                f"the process name in scheduler.json / activity.json so they match."
            )
        
        from pywinauto import Application, Desktop
        from pywinauto.keyboard import send_keys
        from pages.administration_page import handle_administration
        from pages.administration_page import _is_process_alive, _log_forensic_window_state, _send_keys_traced
        from screenshot_util import capture_screenshot as capture_startup_screenshot
        from screen_recorder import ScreenRecorder

        # Retrieve app path from global or root profile
        app_path = master_config.get('app_path') or (master_config.get('global_app_settings') or {}).get('app_path')
        if not app_path:
            raise ValueError("Missing 'app_path' configuration setting inside activity.json")

        app_exe = os.path.basename(app_path)
        
        logger.info(f"Checking for active instances of '{app_exe}'...")
        os.system(f"taskkill /F /IM {app_exe} /T >nul 2>&1")
        time.sleep(2.0)

        # Launch guard: if the kill failed (instance elevated / in another user session),
        # the next launch will hit the app's 'already running -> do you want to exit?'
        # startup prompt and the automation will stall waiting for a login form.
        try:
            import subprocess
            tasklist_out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {app_exe}"],
                capture_output=True, text=True, timeout=15
            ).stdout or ""
            if app_exe.lower() in tasklist_out.lower():
                logger.warning(
                    f"[LAUNCH GUARD] '{app_exe}' is STILL RUNNING after taskkill (elevated or in "
                    f"another session). Expect an 'already running / do you want to exit' prompt "
                    f"at startup. Close it manually (Task Manager > all users) before scheduling."
                )
        except Exception as tl_err:
            logger.debug(f"Post-taskkill verification skipped: {tl_err}")

        # Initialize screen recorder
        full_execution_recorder = ScreenRecorder()
        exec_time_str = datetime.now().strftime("%H-%M-%S")
        full_execution_folder_name = f"Full Execution_{exec_time_str}"
        full_execution_recorder.start(full_execution_folder_name)

        backend_type = master_config.get('backend', 'uia')

        try:
            logger.info(f"Launching target binary: {app_path}")
            app = Application(backend=backend_type).start(app_path)
            # pywinauto exposes the started PID as an int attribute
            launched_pid = getattr(app, 'process', None)

            main_window = app.window(class_name="ThunderRT6MDIForm")
            login_window = main_window.child_window(class_name="ThunderRT6FormDC", title="Login")

            # Startup monitor: instead of blindly waiting 60s for the login form, watch
            # for the three real startup outcomes so a failure is explicit and evidenced:
            #   (a) login form appears            -> proceed
            #   (b) app EXITS during startup      -> 'do you want to exit?' prompt answered /
            #                                           app server unreachable
            #   (c) app alive, login never shows  -> a blocking startup dialog is on screen
            login_deadline = time.time() + 60
            login_detected = False
            while time.time() < login_deadline:
                try:
                    if login_window.exists(timeout=2, retry_interval=0.5):
                        login_detected = True
                        break
                except Exception:
                    pass

                if launched_pid and not _is_process_alive(launched_pid):
                    _log_forensic_window_state("app_startup", launched_pid)
                    try:
                        shot_dir = os.path.join(SCRIPT_DIR, "Screenshots")
                        os.makedirs(shot_dir, exist_ok=True)
                        capture_startup_screenshot(os.path.join(
                            shot_dir,
                            f"STARTUP_EXIT_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
                        ))
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"'{app_exe}' (PID {launched_pid}) EXITED during startup before the login "
                        f"form appeared. On this app that is the 'Do you want to exit?' startup "
                        f"prompt being answered with Yes, or the app server being unreachable. "
                        f"See the FORENSICS entry and STARTUP_EXIT screenshot."
                    )
                time.sleep(1.0)

            if not login_detected:
                blocker_titles = []
                try:
                    blocker_titles = [str(w.window_text())
                                      for w in Desktop(backend="uia").windows(process=launched_pid)]
                except Exception:
                    pass
                logger.error(
                    f"[STARTUP BLOCKED] Login form never appeared. Current app windows: "
                    f"{blocker_titles}. A startup dialog (server connection / already running) "
                    f"is blocking the login."
                )
                _log_forensic_window_state("app_startup", launched_pid)
                raise RuntimeError(
                    f"Login window never appeared; a blocking startup dialog was detected "
                    f"(app windows: {blocker_titles})."
                )
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
                logger.info("[EXIT-TRACE] auto_close: all processes finished — intentionally closing the app NOW (Alt+F4 + Yes).")
                try:
                    main_window.set_focus()
                    time.sleep(0.3)
                    main_window.type_keys("%{F4}", with_spaces=False)
                    time.sleep(1.5)

                    desktop = Desktop(backend="uia")
                    # The exit-confirmation dialog can carry different titles per client, so
                    # search two groups: exact app-name titles, then ANY window owned by the
                    # app PID. (The old regex '^"(Cross|Estro)$"' contained literal quote
                    # characters and could never match, so the Yes button was never found.)
                    search_groups = []
                    try:
                        search_groups.append(desktop.windows(
                            title_re=r'^(Cross|Estro)$', control_type="Window", top_level_only=False
                        ))
                    except Exception:
                        pass
                    if launched_pid:
                        try:
                            search_groups.append(desktop.windows(process=launched_pid))
                        except Exception:
                            pass

                    yes_btn = None
                    for group in search_groups:
                        for candidate in group:
                            try:
                                # Regex (not exact title) so VB6 accelerator captions
                                # like '&Yes' also match a plain 'Yes' lookup.
                                btn = candidate.child_window(title_re=r"(?i)^\s*&?\s*yes\s*$", control_type="Button")
                                btn.wrapper_object()
                                yes_btn = btn
                                break
                            except Exception:
                                continue
                        if yes_btn:
                            break

                    if yes_btn:
                        logger.info("[EXIT-TRACE] auto_close: clicking 'Yes' on the exit confirmation (intentional end-of-run close).")
                        yes_btn.click_input()
                        logger.info("Application closed cleanly.")
                    else:
                        logger.warning("[EXIT-TRACE] auto_close: no Yes button found; sending LEFT+ENTER fallback.")
                        _send_keys_traced("auto_close fallback", "{LEFT}{ENTER}")

                except Exception as close_err:
                    logger.warning(f"Auto-close fallback: {close_err}")
                    _send_keys_traced("auto_close exception fallback", "{LEFT}{ENTER}")

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
    