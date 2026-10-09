import re
import time
import os
import sys
import base64
from datetime import datetime, timedelta
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from pywinauto.findwindows import ElementNotFoundError
from PIL import ImageGrab
# Direct module import first (PyInstaller-friendly); fall back to package import
# when loaded from the repo root (selftest / manager contexts).
try:
    from date_engine import to_custom
except ImportError:
    from activity.date_engine import to_custom

def capture_screenshot(filepath):
    """
    Captures desktop screen and saves directly to a dynamic, client-independent path.
    Returns the absolute path of the saved image on success.
    """
    try:
        # Create directory recursively on the client system if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        screenshot = ImageGrab.grab()
        screenshot.save(filepath)
        print(f"📸 Screenshot saved successfully at: {filepath}")
        return os.path.abspath(filepath)
    except Exception as e:
        print(f"⚠️ Failed to capture screenshot: {e}")
        return None

# Resolves directory pointers cleanly within PyInstaller or standard Python execution
def get_activity_dir():
    """
    Resolves the actual location of the activity directory whether running
    via plain python script or as a compiled PyInstaller executable.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ACTIVITY_DIR = get_activity_dir()
PAGES_DIR = os.path.join(ACTIVITY_DIR, "pages")

def _is_process_alive(pid):
    if not pid: return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle: return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False

def _get_foreground_window_info():
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd: return "<none>"
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return f"'{buf.value}' (pid={pid.value})"
    except Exception:
        return "<unknown>"

def _send_keys_traced(location, keys):
    logger.info(f"[KEY-TRACE] {location}: sending {keys!r} | foreground: {_get_foreground_window_info()}")
    send_keys(keys)

_EXIT_DIALOG_HINTS = ("exit", "close", "quit", "terminate")

def _inspect_dialog(dialog):
    title = ""
    texts, buttons = [], []
    try: title = str(dialog.window_text())
    except Exception: pass
    try: texts = [str(t.window_text()) for t in dialog.descendants(control_type="Text")][:5]
    except Exception: pass
    try: buttons = [str(b.window_text()) for b in dialog.descendants(control_type="Button")][:8]
    except Exception: pass
    return title, texts, buttons

def _looks_like_exit_dialog(title, texts):
    joined = " ".join([str(title)] + [str(t) for t in (texts or [])]).lower()
    return any(h in joined for h in _EXIT_DIALOG_HINTS)

def _get_child_processes(parent_pid):
    if not parent_pid: return {}
    try:
        import ctypes
        from ctypes import wintypes
        TH32CS_SNAPPROCESS = 0x00000002
        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        class PE32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
            ]

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == ctypes.c_void_p(-1).value: return {}
        children = {}
        try:
            entry = PE32W()
            entry.dwSize = ctypes.sizeof(PE32W)
            have = k32.Process32FirstW(snap, ctypes.byref(entry))
            while have:
                if entry.th32ParentProcessID == int(parent_pid) and entry.th32ProcessID != int(parent_pid):
                    children[entry.th32ProcessID] = entry.szExeFile
                have = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(ctypes.c_void_p(snap))
        return children
    except Exception:
        return {}

def _get_foreground_pid():
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd: return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value or None
    except Exception:
        return None

def _log_forensic_window_state(context, target_pid=None):
    try:
        desktop = Desktop(backend="uia")
        titles = [w.window_text() for w in desktop.windows()]
        pid_detail = ""
        if target_pid:
            pid_titles = [w.window_text() for w in desktop.windows(process=target_pid)]
            pid_detail = f" | process {target_pid} alive={_is_process_alive(target_pid)}, windows={pid_titles}"
        logger.error(f"[FORENSICS:{context}] Top-level windows on screen: {titles}{pid_detail}")
    except Exception as forensics_err:
        logger.debug(f"Forensic window enumeration failed: {forensics_err}")

# Add paths to sys.path dynamically
for p in (PAGES_DIR, ACTIVITY_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# Direct module imports (No 'activity.' prefix to prevent PyInstaller import crashes)
from logger_config import setup_logger
from screen_recorder import ScreenRecorder, build_batch_folder_name
from screenshot_util import capture_screenshot
from mail_sender import send_batch_report_email

logger = setup_logger()

# Main output directory anchored dynamically to the real activity directory
BASE_OUTPUT_DIR = os.path.join(ACTIVITY_DIR, "Screenshots")

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

def get_scheduler_json_path():
    """
    Bulletproof locator for scheduler.json. Scans the parent directory, 
    the active directory, and the execution root.
    """
    candidates = [
        # 1. Standard Client Setup: One level up from the activity folder
        os.path.abspath(os.path.join(ACTIVITY_DIR, "..", "scheduler.json")),
        # 2. Fallback: Inside the activity folder itself
        os.path.join(ACTIVITY_DIR, "scheduler.json"),
        # 3. Fallback: The current terminal/CMD working directory root
        os.path.abspath(os.path.join(os.getcwd(), "scheduler.json")),
        # 4. Fallback: One level up from the current terminal working directory
        os.path.abspath(os.path.join(os.getcwd(), "..", "scheduler.json"))
    ]
    
    for path in candidates:
        if os.path.exists(path):
            return path
            
    return None    

def parse_relative_date(date_token, date_format="%d%m%Y"):
    return to_custom(date_token, fmt=date_format)

def _derive_menu_name(step):
    if 'name' in step and step['name']:
        return step['name']
    desc = step.get('description', '')
    cleaned = re.sub(r'^Click\s+', '', desc, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+Menu Item$', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def handle_administration(main_window, process_config, global_config=None, process_name="Process"):
    if isinstance(process_config, dict):
        steps = process_config.get("steps", [])
        mail_config = process_config.get("mail")
    else:
        steps = process_config
        mail_config = None

    last_client_value = None
    current_batch_name = None
    current_json_date = None
    current_client_value = None
    current_exec_time = None

    skip_until_next_batch = False
    import_failed = False
    overall_process_failed = False
    failure_reason = ""
    skipped_step_count = 0

# Helper to resolve SMTP settings cleanly across configurations
    smtp_config = (global_config or {}).get("email_settings") or (global_config or {}).get("smtp_config") or {}

    try:
        cached_app_pid = main_window.process_id()
    except Exception:
        cached_app_pid = None
    
    try:
        main_frame_title = str(main_window.window_text()).strip()
    except Exception:
        main_frame_title = ""

    # Main frame title, captured while the app is responsive. Used to distinguish
    # the main window from result dialogs that carry the SAME app-name title
    # (e.g. a popup titled 'Cross' in front of a window titled 'Cross - DP ...').
    try:
        main_frame_title = str(main_window.window_text()).strip()
    except Exception:
        main_frame_title = ""

    menu_steps = [s for s in steps if s.get('control_type') == "MenuItem" and s.get('action') == "click"]
    other_steps = [s for s in steps if s.get('control_type') != "MenuItem" or s.get('action') != "click"]

    menu_steps = [s for s in steps if s.get('control_type') == "MenuItem" and s.get('action') == "click"]
    other_steps = [s for s in steps if s.get('control_type') != "MenuItem" or s.get('action') != "click"]    
    # ============================================================
    # 1. FULLY DYNAMIC MENU NAVIGATION
    # ============================================================
    if menu_steps:
        logger.info("Processing top-level application menu navigation...")
        menu_names = [_derive_menu_name(s) for s in menu_steps if _derive_menu_name(s)]
        menu_path = " -> ".join(menu_names)
        logger.info(f"Resolved JSON action sequence into menu path: {menu_path}")

        try:
            main_window.set_focus()
            time.sleep(0.5)
            # Strategy 1: Native Window Menu Path
            main_window.menu_select(menu_path)
            logger.info(f"Successfully navigated workflow path: '{menu_path}'")
            time.sleep(2.0)
        except Exception as e:
            logger.warning(f"Native menu selection failed ({e}). Executing dynamic UIA step traversal...")
            
            desktop = Desktop(backend="uia")
            parent_win = main_window

            # Strategy 2: Dynamically click each menu item from JSON steps
            try:
                for step in menu_steps:
                    item_title = step.get('title') or step.get('text') or _derive_menu_name(step)
                    auto_id = step.get('automation_id')
                    
                    logger.info(f"Dynamically targeting menu item: '{item_title}' (AutoID: {auto_id})")
                    
                    # Some builds expose DUPLICATE menu entries (two 'Utilities' items, two
                    # items sharing AutoID 226), so both paths enumerate the MenuItems and
                    # pick by JSON occurrence index — a direct child_window() click raises
                    # an ambiguous-match error when 2+ elements share the criteria.
                    all_menu_items = parent_win.descendants(control_type="MenuItem")

                    if auto_id:
                        matches = []
                        for el in all_menu_items:
                            try:
                                if str(getattr(el.element_info, 'automation_id', '') or '') == str(auto_id):
                                    matches.append(el)
                            except Exception:
                                continue
                        if not matches:
                            raise ElementNotFoundError(f"No menu item with AutoID '{auto_id}' was found")
                    else:
                        # title_re is not supported by every bundled pywinauto version
                        # (IUIA.build_condition() raises 'unexpected keyword argument'),
                        # so match titles in Python instead.
                        item_pattern = re.compile(rf"(?i)^{re.escape(str(item_title).strip())}$")
                        matches = [el for el in all_menu_items
                                   if item_pattern.match(str(el.window_text() or '').strip())]
                        if not matches:
                            raise ElementNotFoundError(f"No menu item matching '{item_title}' was found")

                    try:
                        occ_idx = int(step.get('class_occurrence_index', 0) or 0)
                    except (TypeError, ValueError):
                        occ_idx = 0
                    if occ_idx < 0 or occ_idx >= len(matches):
                        occ_idx = 0
                    if len(matches) > 1:
                        logger.info(f"Menu item '{item_title}' (AutoID: {auto_id}) matched {len(matches)} elements; using occurrence index {occ_idx}.")
                    matches[occ_idx].click_input()
                    time.sleep(0.5)
                    # Next sub-menu context attaches to the desktop popup layer if available
                    parent_win = desktop.window(title=item_title) if desktop.window(title=item_title).exists() else parent_win

                logger.info("Successfully completed dynamic menu sequence.")
                time.sleep(2.5)
            except Exception as uia_err:
                logger.warning(f"Dynamic UIA menu selection failed: {uia_err}. Transmitting fallback shortcut key sequence...")
                # Re-focus the app first so the accelerator keystroke is not lost to
                # whatever window currently holds foreground focus.
                try:
                    main_window.set_focus()
                    time.sleep(0.3)
                except Exception:
                    pass
                _send_keys_traced("menu selection fallback accelerator", "^i")
                time.sleep(2.5)

    recorder = ScreenRecorder()

    # Helper to resolve window handle dynamically per step
    def _get_target_window(step_cfg):
        target_title = (
            step_cfg.get('window_title') or 
            step_cfg.get('window') or 
            step_cfg.get('parent_window') or 
            step_cfg.get('title')
        )
        if target_title:
            return main_window.child_window(
                title_re=f"(?i).*{re.escape(target_title)}.*", 
                control_type="Window", 
                top_level_only=False
            )
        # Universal fallback regex: Catches 'Import File', 'Import Files', 'File Import', etc.
        return main_window.child_window(
            title_re="(?i).*(Import|File).*", 
            control_type="Window", 
            top_level_only=False
        )

    try:
        for index, step in enumerate(other_steps):
            action = step.get('action')
            desc = step.get('description', '')
            auto_id = step.get('automation_id')
            ctrl_type = step.get('control_type', 'Button')

            if skip_until_next_batch:
                # 1. Added 'type_date' so the engine resets properly for the ISIN file
                if action in ["type_date", "select_dropdown", "switch_tab", "click_close"]:
                    logger.info(f"Resetting error bypass flag. Found next setup action configuration entry: {action}")
                    skip_until_next_batch = False

                    # 2. Latch the overall failure for the Manager Summary, but reset local flags
                    if import_failed:
                        overall_process_failed = True
                    import_failed = False
                    failure_reason = ""
                    
                    # ====================================================
                    # PRE-FLIGHT SWEEP: DESTROY GHOST WINDOWS BEFORE STARTING
                    # ====================================================
                    try:
                        target_pid = main_window.process_id()
                        desktop_win32 = Desktop(backend="win32")
                        for leftover_win in desktop_win32.windows(visible_only=True):
                            if leftover_win.process_id() == target_pid:
                                w_title = leftover_win.window_text()
                                if "report" in w_title.lower() and "estro" not in w_title.lower().strip()[:5]:
                                    logger.info(f"Pre-flight sweep caught hidden ghost window: {w_title}. Destroying...")
                                    try:
                                        leftover_win.close()
                                        time.sleep(0.4)
                                    except Exception:
                                        pass
                    except Exception as sweep_err:
                        logger.debug(f"Pre-flight sweep bypassed: {sweep_err}")
                    # ====================================================
                else:
                    skipped_step_count += 1
                    logger.info(f"Skipping dependency step due to previous File-Not-Found state: {desc}")
                    continue

            # ============================================================
            # 2. DYNAMIC TAB SWITCHING
            # ============================================================
            if action == "switch_tab":
                logger.info(f"Executing Tab Switch Step: {desc}")
                try:
                    import_window = None
                    target_title = step.get('window_title') or step.get('title')
                    
                    # Poll up to 10 seconds for target/fallback window
                    for _ in range(10):
                        try:
                            win = _get_target_window(step)
                            if win.exists():
                                import_window = win
                                break
                        except Exception:
                            pass
                        time.sleep(1.0)

                    if import_window is None:
                        raise ElementNotFoundError(f"Could not locate active Import window frame on screen.")

                    import_window.set_focus()
                    time.sleep(0.4)

                    tab_cls = step.get('class_name', 'SSTabCtlWndClass')
                    if auto_id:
                        tab_control = import_window.child_window(auto_id=str(auto_id), control_type="Pane")
                    else:
                        tab_control = import_window.child_window(class_name=tab_cls, control_type="Pane")

                    tab_control.set_focus()
                    time.sleep(0.4)

                    tab_key = step.get('key_sequence', '{RIGHT}')
                    tab_control.type_keys(tab_key)
                    logger.info(f"Successfully switched tab view using key sequence: {tab_key}")
                    time.sleep(1.0)
                except Exception as e:
                    logger.error(f"Failed to dynamically process tab change: {e}", exc_info=True)
                    raise RuntimeError(f"Failed to dynamically process tab change: {e}")

            # ============================================================
            # 3. DYNAMIC DROPDOWN SELECTION
            # ============================================================
            elif action == "select_dropdown":
                logger.info(f"Executing Dropdown Selection Step: {desc}")
                import_window = _get_target_window(step)

                if auto_id:
                    active_combo = import_window.child_window(auto_id=str(auto_id), control_type="ComboBox").wrapper_object()
                else:
                    active_combo = import_window.child_window(class_name=step.get('class_name', 'ComboBox'), control_type="ComboBox").wrapper_object()

                try:
                    active_combo.set_focus()
                    time.sleep(0.3)
                    active_combo.select(step['value'])
                    logger.info(f"Successfully selected dropdown item: '{step['value']}'")
                    last_client_value = step['value']
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Direct selection bypassed: {e}. Executing drop-down list traversal...")
                    try:
                        active_combo.set_focus()
                        time.sleep(0.2)
                        active_combo.click_input()
                        time.sleep(0.5)

                        target_value = step['value']
                        active_combo.type_keys("{HOME}")
                        time.sleep(0.3)

                        matched = False
                        for _ in range(30):
                            current_text = active_combo.window_text()
                            if target_value.lower() in current_text.lower() or current_text == "":
                                matched = True
                                logger.info(f"Positioned successfully on target value option: '{current_text}'")
                                break

                            active_combo.type_keys("{DOWN}")
                            time.sleep(0.15)

                        if not matched:
                            active_combo.type_keys("^a{BACKSPACE}" + target_value, with_spaces=True)
                            logger.info("Re-routed selection to direct entry string fallback.")

                        last_client_value = target_value
                        time.sleep(0.8)
                    except Exception as critical_err:
                        logger.error(f"Could not interact with ComboBox target {auto_id}: {critical_err}", exc_info=True)
                        raise RuntimeError(f"Could not interact with ComboBox target {auto_id}: {critical_err}")

            # ============================================================
            # 4. DYNAMIC DATE INPUT MASK
            # ============================================================
            elif action == "type_date":
                logger.info(f"Executing Date Mask Text Selection Step: {desc}")
                try:
                    import_window = _get_target_window(step)

                    if auto_id:
                        date_field = import_window.child_window(auto_id=str(auto_id), control_type=ctrl_type)
                    else:
                        date_field = import_window.child_window(
                            class_name=step.get('class_name', 'Edit'),
                            control_type=ctrl_type,
                            found_index=step.get('class_occurrence_index', 0)
                        )
                        
                    date_field.set_focus()
                    time.sleep(0.2)
                    date_field.click_input(coords=(5, 10))
                    time.sleep(0.2)

                    date_field.type_keys("{DELETE}" * 8, with_spaces=False)
                    time.sleep(0.2)

                    date_format = step.get('date_format', '%d%m%Y')
                    date_str = parse_relative_date(step['value'], date_format)
                    date_field.type_keys(date_str, with_spaces=False)
                    logger.info(f"Successfully structured transaction date field to: {date_str}")
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Failed writing target automation date format string value: {e}", exc_info=True)
                    raise RuntimeError(f"Failed writing target automation date format string value: {e}")

            # ============================================================
            # 5. DYNAMIC BROWSE & CASE-INSENSITIVE FILE DIALOG NAVIGATOR
            # ============================================================
            elif action == "click_browse":
                logger.info(f"Executing File Browse and File Dialog Target Step: {desc}")

                raw_folder_token = step.get("target_folder", "unspecified_date")
                date_format = step.get("folder_date_format", "%d%b%Y")
                json_date = parse_relative_date(raw_folder_token, date_format)
                
                exec_time_str = datetime.now().strftime("%H-%M-%S")
                batch_name = build_batch_folder_name(
                    process_name=process_name,
                    json_date=json_date,
                    client_value=last_client_value or "unspecified_client",
                    exec_time=exec_time_str,
                )
                recorder.start(batch_name)

                current_batch_name = batch_name
                current_json_date = json_date
                current_client_value = last_client_value or "unspecified_client"
                current_exec_time = exec_time_str

                try:
                    # 1. Resolve base directory and locate file on disk first
                    base_directory = step.get("base_directory") or global_config.get("main_file_path", "C:\\Users\\Admin\\Desktop\\Reports")
                    target_subfolder = json_date
                    target_pattern = step.get("target_file_pattern", "")
                    target_ends_with = step.get("target_file_ends_with", "")

                    if not target_subfolder or not target_pattern:
                        raise ValueError("Missing 'target_folder' or 'target_file_pattern' in step configuration.")

                    final_target_directory = os.path.join(base_directory, target_subfolder)
                    logger.info(f"Scanning disk target directory: {final_target_directory}")

                    # Verify physical folder presence on hard drive
                    if not os.path.exists(final_target_directory):
                        logger.error(f"CRITICAL ERROR: Folder not found on disk: {final_target_directory}")
                        if recorder.is_active():
                            recorder.stop()
                            
                        # --- ADDED: EMAIL LOGIC FOR MISSING FOLDER ---
                        day_folder = datetime.now().strftime("%Y-%m-%d")
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name or process_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        screenshot_path = os.path.join(screenshot_folder, f"FOLDER_NOT_FOUND_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(screenshot_path) or screenshot_path
                        
                        table_rows = [
                            ("Process Status", "SKIPPED - FOLDER NOT FOUND"),
                            ("Process Name", process_name),
                            ("Error Captured", f"Folder Not Found: {target_subfolder}"),
                            ("Client Context", current_client_value),
                            ("System Execution Time", current_exec_time),
                        ]
                        try:
                            send_batch_report_email(smtp_config, mail_config, table_rows, actual_saved_path, f"CRITICAL ERROR: Folder Not Found - {process_name}")
                            logger.info(f"📧 Folder skip notification email dispatched for '{target_subfolder}'")
                        except Exception as email_err:
                            logger.error(f"⚠️ Failed to transmit folder error email: {email_err}")
                        # ---------------------------------------------
                        
                        import_failed = True
                        overall_process_failed = True
                        skipped_step_count += 1
                        failure_reason = f"Folder Not Found: {target_subfolder}"

                        skip_until_next_batch = True
                        continue
                    # Search disk for file matching prefix and optional suffix
                    target_file_name = ""
                    for file_name in os.listdir(final_target_directory):
                        lower_name = file_name.lower()
                        starts_match = lower_name.startswith(target_pattern.lower())
                        if target_ends_with:
                            ends_match = lower_name.endswith(target_ends_with.lower())
                        else:
                            ends_match = lower_name.endswith(".csv") or lower_name.endswith(".txt")
                        
                        if starts_match and ends_match:
                            target_file_name = file_name
                            break
                    
                    if not target_file_name:
                        logger.error(f"CRITICAL ERROR: No file matching '{target_pattern}' in '{final_target_directory}'")
                        if recorder.is_active():
                            recorder.stop()
                            
                        # --- ADDED: EMAIL LOGIC FOR MISSING FILE ---
                        day_folder = datetime.now().strftime("%Y-%m-%d")
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name or process_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        screenshot_path = os.path.join(screenshot_folder, f"FILE_NOT_FOUND_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(screenshot_path) or screenshot_path
                        
                        table_rows = [
                            ("Process Status", "SKIPPED - FILE NOT FOUND"),
                            ("Process Name", process_name),
                            ("Error Captured", f"File Not Found: {target_pattern}"),
                            ("Client Context", current_client_value),
                            ("System Execution Time", current_exec_time),
                        ]
                        try:
                            send_batch_report_email(smtp_config, mail_config, table_rows, actual_saved_path, f"CRITICAL ERROR: File Not Found - {process_name}")
                            logger.info(f"📧 File skip notification email dispatched for '{target_pattern}'")
                        except Exception as email_err:
                            logger.error(f"⚠️ Failed to transmit file error email: {email_err}")
                        # ---------------------------------------------
                        
                        import_failed = True
                        overall_process_failed = True
                        skipped_step_count += 1
                        failure_reason = f"File Not Found: {target_pattern}"

                        skip_until_next_batch = True
                        continue

                    absolute_target_path = os.path.join(final_target_directory, target_file_name)
                    logger.info(f"Target file found: {absolute_target_path}")

                    # 2. Trigger browse button
                    import_window = _get_target_window(step)
                    if auto_id:
                        browse_btn = import_window.child_window(auto_id=str(auto_id), control_type="Button")
                    else:
                        browse_btn = import_window.child_window(title_re="(?i).*Browse.*", control_type="Button")

                    browse_btn.set_focus()
                    time.sleep(0.5)
                    browse_btn.click_input()
                    
                    logger.info("Browse clicked. Waiting for system file picker dialog...")
                    time.sleep(1.5)

                    desktop = Desktop(backend="uia")
                    dialog_title = step.get("dialog_title", "Select a file to be imported")
                    dialog = desktop.window(title_re=f"(?i).*{re.escape(dialog_title)}.*", control_type="Window")
                    
                    dialog.wait('exists ready', timeout=10)
                    dialog.set_focus()
                    time.sleep(0.5)

                    # 3. Detect dialog architecture: Modern (Items View) vs Legacy (Folders/Drives list)
                    list_view = dialog.child_window(control_type="List", title="Items View")
                    is_modern_dialog = list_view.exists(timeout=1.5)

                    if is_modern_dialog:
                        logger.info("Detected Modern Explorer Dialog. Running folder navigation...")
                        dialog.type_keys("%d", with_spaces=True)
                        time.sleep(0.4)
                        dialog.type_keys(base_directory + "{ENTER}", with_spaces=False)
                        time.sleep(1.2)

                        # Match and open subfolder
                        folder_opened = False
                        try:
                            target_regex = f"(?i)^{re.escape(target_subfolder)}$"
                            folder_item = list_view.child_window(title_re=target_regex, control_type="ListItem")
                            if folder_item.exists(timeout=2):
                                folder_item.double_click_input()
                                time.sleep(1.2)
                                folder_opened = True
                        except Exception:
                            pass

                        if not folder_opened:
                            try:
                                for item in list_view.children(control_type="ListItem"):
                                    if item.window_text().strip().lower() == target_subfolder.lower():
                                        item.double_click_input()
                                        time.sleep(1.2)
                                        folder_opened = True
                                        break
                            except Exception:
                                pass

                    # 4. Input file name into dialog
                    # Uses full path for legacy dialogs (to bypass navigation), or simple filename for modern ones
                    path_to_populate = target_file_name if is_modern_dialog else absolute_target_path
                    logger.info(f"Injecting target string into file dialog: {path_to_populate}")

                    file_selected = False
                    try:
                        file_name_edit = dialog.child_window(auto_id="1148", control_type="Edit")
                        if not file_name_edit.exists(timeout=1):
                            file_name_edit = dialog.child_window(title_re="(?i).*(File name|File name:).*", control_type="Edit")
                            
                        if file_name_edit.exists(timeout=1):
                            file_name_edit.set_focus()
                            time.sleep(0.2)
                            file_name_edit.type_keys("^a{BACKSPACE}", with_spaces=False)
                            time.sleep(0.2)
                            file_name_edit.type_keys(path_to_populate, with_spaces=True)
                            time.sleep(0.3)
                            file_selected = True
                    except Exception as err:
                        logger.debug(f"Direct Edit box targeting passed to fallback: {err}")

                    if not file_selected:
                        try:
                            dialog.set_focus()
                            time.sleep(0.2)
                            dialog.type_keys("%n", with_spaces=False)
                            time.sleep(0.3)
                            dialog.type_keys("^a{BACKSPACE}", with_spaces=False)
                            dialog.type_keys(path_to_populate, with_spaces=True)
                            time.sleep(0.3)
                            file_selected = True
                        except Exception as alt_err:
                            logger.debug(f"Alt+N selection fallback failed: {alt_err}")

                    # 5. Commit File Selection
                    committed = False
                    try:
                        dialog.type_keys("{ENTER}")
                        time.sleep(1.0)
                        if not dialog.exists():
                            committed = True
                    except Exception:
                        pass

                    if not committed and dialog.exists():
                        try:
                            open_btn = dialog.child_window(title_re="(?i).*(Open|Select|&Open|OK).*", control_type="Button")
                            if open_btn.exists(timeout=1):
                                open_btn.click_input()
                                time.sleep(1.0)
                        except Exception:
                            try:
                                dialog.type_keys("%o", with_spaces=False)
                            except Exception:
                                pass

                    logger.info("File targeting complete. Dialog dismissed.")
                    time.sleep(1.0)

                except SystemExit:
                    raise
                except Exception as e:
                    logger.error(f"Failed coordinating file browse dialog: {e}", exc_info=True)
                    try:
                        dialog.close()
                    except Exception:
                        pass
                    skip_until_next_batch = True
                    continue
            # ============================================================
            # 6. DYNAMIC ACTION BUTTON CLICK (IMPORT / PROCESS)
            # ============================================================
            elif action == "click_import":
                    logger.info(f"Executing Process Confirmation Target Step: {desc}")
                    try:
                        # Each import cycle starts from a clean failure state
                        import_failed = False
                        failure_reason = ""
                        import_window = _get_target_window(step)
                        
                        if auto_id:
                            import_action_btn = import_window.child_window(auto_id=str(auto_id), control_type=ctrl_type)
                        else:
                            btn_title = step.get('title') or step.get('text', 'Import')
                            import_action_btn = import_window.child_window(title_re=f"(?i).*{re.escape(btn_title)}.*", control_type=ctrl_type)

                        import_action_btn.set_focus()
                        time.sleep(0.2)

                        # 1. Grab PID before clicking so the engine remembers it before the freeze
                        target_pid = cached_app_pid

                        # Snapshot the app's top-level windows while it is still responsive so
                        # completion popups are detected as NEW arrivals instead of title guessing.
                        baseline_titles = set()
                        baseline_window_count = None
                        if target_pid:
                            try:
                                baseline_wins = Desktop(backend="uia").windows(process=target_pid)
                                baseline_titles = {str(w.window_text()).strip() for w in baseline_wins}
                                baseline_window_count = len(baseline_wins)
                            except Exception:
                                pass

                        # Snapshot already-running helper processes too, so only helpers
                        # spawned BY THIS IMPORT (e.g. CSVTransformer.exe) gate the wait.
                        baseline_child_pids = set(_get_child_processes(target_pid).keys()) if target_pid else set()

                        import_action_btn.click()
                        logger.info("Successfully requested document structural engine processing via final file Import control.")

                        # ========================================================
                        # 🚀 POST-IMPORT COMPLETION RADAR (freeze-tolerant)
                        # ========================================================
                        # VB6 apps (Cross / Estro / Compliance Sutra) block their UI thread
                        # while an import runs. While frozen, re-resolving the main window
                        # spec raises ElementNotFoundError (the classic 'ThunderRT6MDIForm'
                        # abort), so every probe below is guarded and can never crash the
                        # run by itself. The loop exits on: result popup (new PID window or
                        # keyword title), silent-success unfreeze, or process death.
                        popup_keywords = ("Information", "Message", "Success", "Sucess", "Imported",
                                          "Confirmation", "Notice", "Warning", "Error", "Fatal")

                        max_wait_seconds = 10800  # 3-hour safety net
                        death_confirmations = 0
                        start_time = time.time()
                        next_heartbeat = time.time() + 30
                        next_helper_log = time.time() + 10
                        time.sleep(3.0)  # Buffer to allow the application to settle into processing
                        desktop_spy = Desktop(backend="uia")

                        while (time.time() - start_time) < max_wait_seconds:
                            # 1) Detect application death (crash / session drop), debounced
                            #    so a transient window recreation is never misread as a crash.
                            if target_pid and not _is_process_alive(target_pid):
                                death_confirmations += 1
                                if death_confirmations >= 3:
                                    # Config-agnostic guard: when click_import is the FINAL step of
                                    # the client's JSON, an app that exits on success must not be
                                    # reported as a crash. Anything after this step needs the app.
                                    if index + 1 >= len(other_steps):
                                        logger.warning(
                                            f"Target application (PID {target_pid}) exited after the final "
                                            f"import step; treating as completed."
                                        )
                                        break
                                    logger.critical(
                                        f"Target application process (PID {target_pid}) terminated while "
                                        f"processing the import. Capturing evidence before aborting..."
                                    )
                                    _log_forensic_window_state("click_import", target_pid)

                                    crash_screenshot_path = None
                                    try:
                                        day_folder = datetime.now().strftime("%Y-%m-%d")
                                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name or process_name)
                                        os.makedirs(screenshot_folder, exist_ok=True)
                                        crash_screenshot_path = os.path.join(
                                            screenshot_folder,
                                            f"APP_CRASH_CAPTURE_{datetime.now().strftime('%H-%M-%S')}.png"
                                        )
                                        capture_screenshot(crash_screenshot_path)
                                    except Exception as shot_err:
                                        logger.error(f"Crash screenshot capture failed: {shot_err}")

                                    try:
                                        send_batch_report_email(
                                            smtp_config=smtp_config,
                                            mail_config=mail_config,
                                            table_rows=[
                                                ("Process Status", "FAILED - APPLICATION TERMINATED"),
                                                ("Process Name", process_name),
                                                ("Error Captured", f"Application process (PID {target_pid}) exited during import processing"),
                                                ("Client Context", current_client_value),
                                                ("System Execution Time", current_exec_time),
                                            ],
                                            screenshot_path=crash_screenshot_path,
                                            default_subject=f"CRITICAL ERROR: Application Closed During Import - {process_name}",
                                        )
                                    except Exception as email_err:
                                        logger.error(f"Failed to transmit crash alert email: {email_err}")

                                    raise RuntimeError(
                                        f"Target application process (PID {target_pid}) terminated during import "
                                        f"processing (application crash or session drop). See the FORENSICS log "
                                        f"entry and crash screenshot for details."
                                    )
                                time.sleep(0.5)
                                continue
                            death_confirmations = 0

                            # 2) HELPER-PROCESS WAIT. The app can delegate the real import work
                            #    to a spawned helper exe (Cross launches CSVTransformer.exe
                            #    with a visible console for big ISIN master files). The main
                            #    window stays ENABLED while the helper runs, so nothing else
                            #    may break the radar until every helper of THIS import exits.
                            if target_pid:
                                try:
                                    active_helpers = {cp: name for cp, name in _get_child_processes(target_pid).items()
                                                      if cp not in baseline_child_pids}
                                except Exception:
                                    active_helpers = {}
                                if active_helpers:
                                    if time.time() >= next_helper_log:
                                        next_helper_log = time.time() + 15
                                        logger.info(
                                            f"[RADAR] Import helper process still running: "
                                            f"{sorted(active_helpers.values())} — waiting for it to finish."
                                        )
                                    time.sleep(1.0)
                                    continue

                            try:
                                # 2) Break as soon as a result popup appears: either a NEW titled
                                #    window under the app PID, a NEW window COUNT (untitled
                                #    dialogs), or a known keyword title.
                                if target_pid:
                                    pid_titles = [str(w.window_text()).strip()
                                                  for w in desktop_spy.windows(process=target_pid)]
                                    popups = []
                                    if baseline_titles:
                                        popups = [t for t in pid_titles if t and t not in baseline_titles]
                                    if not popups and baseline_window_count is not None and len(pid_titles) > baseline_window_count:
                                        popups = ["<new app window appeared>"]
                                    if not popups:
                                        popups = [t for t in pid_titles
                                                  if any(keyword in t for keyword in popup_keywords)]
                                    if popups:
                                        logger.info(f"Import completion dialog detected: {popups[0]}")
                                        break

                                # 3) Break as soon as the app window RESOLVES again after the
                                #    freeze. Enabled = silent success (grid UI). Disabled = a
                                #    modal result dialog (e.g. 'File Imported') owns the window —
                                #    the import is finished either way, and the following steps
                                #    (grid verification / click_ok) handle the dialog.
                                probe_state = None  # None=still unresolvable(frozen), True/False=resolved
                                for probe_window in (import_window, main_window):
                                    if probe_window.exists(timeout=1, retry_interval=0.2):
                                        try:
                                            probe_state = probe_window.is_enabled()
                                        except Exception:
                                            probe_state = None
                                        if probe_state is not None:
                                            break
                                if probe_state is True:
                                    logger.info("Main application window is responsive again (silent success path).")
                                    break
                                if probe_state is False:
                                    logger.info("App window resolves but is disabled — a modal result dialog is up; proceeding to dialog handling.")
                                    break
                            except Exception:
                                pass  # Swallow pywinauto COM/element errors while frozen

                            if time.time() >= next_heartbeat:
                                next_heartbeat = time.time() + 30
                                try:
                                    hb_titles = [str(w.window_text()) for w in desktop_spy.windows(process=target_pid)] if target_pid else []
                                except Exception:
                                    hb_titles = []
                                logger.info(
                                    f"[RADAR] Still waiting after {int(time.time() - start_time)}s | "
                                    f"app windows: {hb_titles}"
                                )

                            time.sleep(0.5)
                        else:
                            logger.warning("Post-import completion radar reached its safety timeout; proceeding to next step.")
                        
                        desktop = Desktop(backend="uia")
                        
                        try:
                            # Scoped to the app PID so unrelated desktop windows titled
                            # 'error' (browsers, chat tools) can't fake an import failure.
                            fatal_dialog = desktop.window(title_re="(?i).*(fatal|error).*", control_type="Window", top_level_only=True, process=cached_app_pid)
                            if fatal_dialog.exists(timeout=1.5):
                                failure_reason = fatal_dialog.window_text()
                                logger.warning(f"Detected Application Error Layer Context: '{failure_reason}'")
                                fatal_dialog.set_focus()
                                time.sleep(0.2)
                                f_title, f_texts, f_buttons = _inspect_dialog(fatal_dialog)
                                logger.warning(f"[DIALOG-TRACE] Fatal/error dialog being dismissed: '{f_title}' | text: {f_texts} | buttons: {f_buttons}")
                                _send_keys_traced(f"click_import error-dialog dismissal ('{f_title}')", "{ENTER}")
                                import_failed = True
                                time.sleep(2.0)
                        except Exception as dialog_check_err:
                            logger.debug(f"No explicit error frame intercepted: {dialog_check_err}")

                        if import_failed:
                            logger.info("Fatal Error intercepted. Closing error notification window...")
                            try:
                                close_id = step.get('error_close_autoid')
                                close_cls = step.get('error_class_name')
                                
                                if close_cls:
                                    error_tab = main_window.window(class_name=close_cls, top_level_only=False, found_index=0)
                                    error_tab.set_focus()
                                    time.sleep(0.2)
                                    if close_id:
                                        error_tab.child_window(auto_id=str(close_id), control_type="Button").click_input()
                                    else:
                                        send_keys("%{c}")
                                else:
                                    send_keys("%{c}")
                            except Exception:
                                send_keys("%{c}")
                                
                            if recorder.is_active():
                                recorder.stop()

                            day_folder = datetime.now().strftime("%Y-%m-%d")
                            screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name or process_name)
                            os.makedirs(screenshot_folder, exist_ok=True)
                            screenshot_path = os.path.join(screenshot_folder, f"IMPORT_FAILURE_CAPTURE_{datetime.now().strftime('%H-%M-%S')}.png")
                            capture_screenshot(screenshot_path)

                            table_rows = [
                                ("Process Status", "FAILED - TRANSACTION ERROR"),
                                ("Process Name", process_name),
                                ("Error Captured", failure_reason if failure_reason else "No transaction is active"),
                                ("Client Context", current_client_value),
                                ("System Execution Time", current_exec_time),
                            ]
                            
                            try:
                                send_batch_report_email(
                                    smtp_config=smtp_config,
                                    mail_config=mail_config,
                                    table_rows=table_rows,
                                    screenshot_path=screenshot_path,
                                    default_subject=f"CRITICAL ERROR: Import Failed - {process_name}",
                                )
                            except Exception as email_err:
                                logger.error(f"Failed to transmit error alert email: {email_err}")

                            skip_until_next_batch = True
                            continue
                        else:
                            time.sleep(1.0) 
                        
                    except Exception as e:
                        logger.error(f"Failed handling post-browse main automation execution button trigger sequence: {e}", exc_info=True)
                        raise RuntimeError(f"Failed handling post-browse main automation execution button trigger sequence: {e}") 
            # ============================================================
            # 7. DYNAMIC TABLE GRID LOAD VERIFIER
            # ============================================================
            elif action == "wait_for_table":
                logger.info(f"Executing Table Loading Verification Step: {desc}")
                try:
                    logger.info("Waiting dynamically for data grid to populate (bypassing 'Not Responding' UI freezes)...")
                    
                    max_timeout = step.get('timeout', 300) 
                    start_time = time.time()
                    table_ready = False
                    
                    while (time.time() - start_time) < max_timeout:
                        try:
                            import_window = _get_target_window(step)
                            
                            if auto_id:
                                table_grid = import_window.child_window(auto_id=str(auto_id), control_type=ctrl_type)
                            else:
                                grid_cls = step.get('class_name', 'MSHFlexGridWndClass')
                                table_grid = import_window.child_window(class_name=grid_cls, control_type=ctrl_type, found_index=0)

                            # RESTORED: Native strict check. 
                            # If app is frozen/processing, this will purposefully fail and trigger the 'except' block
                            table_grid.wait('exists', timeout=2)
                            table_grid.wait('ready', timeout=2)
                            
                            # If it gets here without throwing an error, the thread is genuinely unlocked
                            table_ready = True
                            break
                        except Exception:
                            # Safely swallow TimeoutError and ElementNotFoundError while app processes
                            pass
                            
                        time.sleep(2.0)
                        
                    if not table_ready:
                        raise TimeoutError(f"Table did not load after {max_timeout} seconds.")

                    grid_timeout = step.get('timeout', 300)

                    # A result dialog (e.g. 'File Imported') can sit in front of the grid with
                    # the app-name itself as its title. Detect it up front by enumerating the
                    # app's windows (skipping the main frame) and defer straight to the
                    # configured click_ok step instead of burning the full grid timeout.
                    blocker_pre = None
                    try:
                        for w in Desktop(backend="uia").windows(process=cached_app_pid, top_level_only=True) if cached_app_pid else []:
                            t = str(w.window_text()).strip()
                            if (t and t != main_frame_title
                                    and re.search(r"(?i).*(cross|information|imported|confirmation|notice|message|error|warning|fatal).*", t)):
                                blocker_pre = t
                                break
                    except Exception:
                        pass

                    if blocker_pre:
                        logger.warning(f"Active result dialog '{blocker_pre}' detected before grid wait; skipping grid verification and deferring to the dialog step.")
                    else:
                        logger.info(f"Waiting for data grid table initialization (timeout: {grid_timeout}s)...")
                        table_grid.wait('exists', timeout=grid_timeout)
                        table_grid.wait('ready', timeout=grid_timeout)
                        time.sleep(1.5)
                        logger.info("Data table successfully loaded and populated with imported values.")
                except Exception as e:
                    logger.error(f"Failed while waiting for processing table to display records: {e}", exc_info=True)
                    if not _is_process_alive(cached_app_pid):
                        logger.critical(
                            f"Target application process (PID {cached_app_pid}) is no longer running; "
                            f"it terminated before or during the grid verification wait."
                        )
                    _log_forensic_window_state("wait_for_table", cached_app_pid)
                    # A result dialog can legitimately sit in front of the grid (e.g. 'File
                    # Imported (Success)'); defer to the configured click_ok step instead
                    # of aborting the whole run.
                    blocker_active = False
                    try:
                        for w in Desktop(backend="uia").windows(process=cached_app_pid, top_level_only=True) if cached_app_pid else []:
                            t = str(w.window_text()).strip()
                            if (t and t != main_frame_title
                                    and re.search(r"(?i).*(cross|information|imported|confirmation|notice|message|error|warning|fatal).*", t)):
                                logger.warning(f"Active result dialog '{t}' detected; skipping grid verification.")
                                blocker_active = True
                                break
                    except Exception:
                        pass
                    if not blocker_active:
                        raise RuntimeError(f"Failed while waiting for processing table to display records: {e}")

            # ============================================================
            # 8. DYNAMIC CONFIRMATION / MULTI-DIALOG OK CLICK HANDLER
            # ============================================================
            elif action == "click_ok":
                logger.info(f"Executing Process Confirmation Target Step: {desc}")
                desktop = Desktop(backend="uia")
                desktop_win32 = Desktop(backend="win32")
                target_pid = cached_app_pid
                max_dialog_checks = step.get('max_popup_count', 5)
                dialogs_cleared = 0
                exit_dialog_seen = False

                for check_idx in range(1, max_dialog_checks + 1):
                    logger.info(f"Polling for active pop-up dialog window (Attempt {check_idx}/{max_dialog_checks})...")
                    btn_clicked = False
                    active_dialog = None

                    # Strategy 1: Search top-level modal popups strictly within target application PID.
                    # Result dialogs often carry the app name itself as their title (e.g. a popup
                    # titled 'Cross'), so we ENUMERATE the app's top-level windows and skip the
                    # main frame — a single window() lookup would match the main window first.
                    try:
                        dialog_title_cfg = step.get('dialog_title') or step.get('window_title')
                        dialog_candidates = []

                        if dialog_title_cfg and target_pid:
                            spec = desktop.window(
                                title_re=f"(?i).*{re.escape(dialog_title_cfg)}.*",
                                top_level_only=True,
                                process=target_pid
                            )
                            if spec.exists(timeout=2):
                                dialog_candidates.append(spec)
                        elif target_pid:
                            for w in desktop.windows(process=target_pid, top_level_only=True):
                                w_title = str(w.window_text()).strip()
                                if w_title and w_title != main_frame_title:
                                    dialog_candidates.append(w)
                        else:
                            spec = desktop.window(
                                title_re=r"(?i).*(Cross|Information|Message|Confirmation|Notice|Alert|Error|Warning|Fatal).*",
                                top_level_only=True
                            )
                            if spec.exists(timeout=2):
                                dialog_candidates.append(spec)

                        for active_dialog in dialog_candidates:
                            try:
                                active_dialog.set_focus()
                            except Exception:
                                pass
                            time.sleep(0.3)

                            # Trace EVERY popup we act on: title, message text, buttons.
                            dlg_title, dlg_texts, dlg_buttons = _inspect_dialog(active_dialog)
                            logger.info(
                                f"[DIALOG-TRACE] Popup candidate (attempt {check_idx}): '{dlg_title}' | "
                                f"text: {dlg_texts} | buttons: {dlg_buttons}"
                            )

                            if _looks_like_exit_dialog(dlg_title, dlg_texts):
                                # SAFETY GUARD: click_ok is meant for result dialogs (OK /
                                # confirmation), NEVER for closing the app. If an exit/close
                                # prompt shows up here we do not answer it — we log it loudly,
                                # screenshot it, and stop dismissing popups so the real error
                                # surfaces instead of the app silently dying.
                                logger.critical(
                                    f"[EXIT-TRACE] Exit/close dialog appeared unexpectedly at step "
                                    f"'{desc}': '{dlg_title}' text={dlg_texts} buttons={dlg_buttons}. "
                                    f"REFUSING to click any button on it — the app will NOT be "
                                    f"closed by this step."
                                )
                                try:
                                    day_folder = datetime.now().strftime("%Y-%m-%d")
                                    shot_dir = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name or process_name)
                                    os.makedirs(shot_dir, exist_ok=True)
                                    capture_screenshot(os.path.join(
                                        shot_dir, f"EXIT_DIALOG_{datetime.now().strftime('%H-%M-%S')}.png"))
                                except Exception:
                                    pass
                                exit_dialog_seen = True
                                break

                            # DATA EXTRACTION: Read specific internal label texts (e.g. RichText fields)
                            body_texts = [active_dialog.window_text()]
                            clean_report_text = ""
                            for ctrl in active_dialog.descendants():
                                try:
                                    t = ctrl.window_text().strip()
                                    if t: body_texts.append(t)
                                    if ctrl.class_name() == "RichTextWndClass":
                                        clean_report_text = t
                                except Exception:
                                    pass

                            # FAILURE EVALUATION: flag the run when the dialog text carries
                            # known error keywords (RichText fields carry the real report).
                            full_popup_text = " ".join(body_texts).lower()
                            if any(word in full_popup_text for word in ["error", "fatal", "warning", "fail", "invalid", "not found", "unsuccess", "mismatch"]):
                                logger.warning("Tampered file error caught in modal.")
                                import_failed = True
                                overall_process_failed = True
                                failure_reason = clean_report_text.replace('\n', ' ').strip() if clean_report_text else dlg_title

                            # Find target button inside modal
                            if auto_id:
                                target_btn = active_dialog.child_window(auto_id=str(auto_id), control_type=ctrl_type)
                            else:
                                btn_title = step.get('title') or step.get('text', 'OK')
                                target_btn = active_dialog.child_window(title_re=f"(?i).*{re.escape(btn_title)}.*", control_type=ctrl_type)

                            # Click OK / Yes / Close
                            btn_title = step.get('title') or step.get('text', 'OK')
                            target_btn = active_dialog.child_window(title_re=f"(?i).*{re.escape(btn_title)}.*", class_name="Button")
                            if not target_btn.exists():
                                target_btn = active_dialog.child_window(title_re=r"(?i).*(OK|Yes|Close|Dismiss).*", class_name="Button")

                            if target_btn.exists():
                                target_btn.click_input()
                                dialogs_cleared += 1
                                btn_clicked = True
                                time.sleep(1.2)
                                break
                    except Exception as modal_err:
                        logger.debug(f"Modal popup search iteration {check_idx}: {modal_err}")

                    # An exit/close dialog must never fall through to the generic strategies.
                    if exit_dialog_seen:
                        break

                    # Strategy 2: Search inside main_window children
                    if not btn_clicked:
                        try:
                            if auto_id:
                                target_btn = main_window.child_window(auto_id=str(auto_id), control_type=ctrl_type)
                            else:
                                btn_title = step.get('title') or step.get('text', 'OK')
                                target_btn = main_window.child_window(title_re=f"(?i).*{re.escape(btn_title)}.*", control_type=ctrl_type)

                            if target_btn.exists(timeout=1):
                                logger.info(f"🖱️ Clicking button inside main window context (Popup #{check_idx})...")
                                target_btn.click_input()
                                dialogs_cleared += 1
                                btn_clicked = True
                                time.sleep(1.2)
                        except Exception:
                            pass

                    # Fallback keypress dismissal
                    if not btn_clicked:
                        if check_idx == 1:
                            # ENTER presses the DEFAULT button, which is 'Yes' on close/exit
                            # prompts — never send it blindly into an exit-looking window.
                            fg_info = _get_foreground_window_info()
                            if any(h in fg_info.lower() for h in _EXIT_DIALOG_HINTS):
                                logger.critical(
                                    f"[EXIT-TRACE] Blind ENTER SUPPRESSED: the foreground window "
                                    f"looks like an exit/close dialog: {fg_info}. "
                                    f"Not sending keys; leaving dialog untouched."
                                )
                                exit_dialog_seen = True
                                break
                            fg_pid = _get_foreground_pid()
                            if target_pid and fg_pid is not None and fg_pid != target_pid:
                                logger.warning(
                                    f"[KEY-TRACE] Blind ENTER suppressed: the foreground window "
                                    f"belongs to process {fg_pid} (not the target app {target_pid}). "
                                    f"Not sending keys outside the target application."
                                )
                            else:
                                logger.info("No explicit button caught via UIA. Sending Enter keypress to clear active modal...")
                                _send_keys_traced(f"click_ok '{desc}' (blind ENTER fallback)", "{ENTER}")
                                dialogs_cleared += 1
                                time.sleep(1.0)
                        else:
                            break

                logger.info(f"✓ Cleared total of {dialogs_cleared} pop-up dialog window(s).")

                # WIN32 AGGRESSIVE SWEEP AND DESTROY POST-OK
                logger.info("Sweeping strictly for secondary white report windows post-OK...")
                time.sleep(1.5)
                try:
                    desktop_win32 = Desktop(backend="win32") 
                    
                    for leftover_win in desktop_win32.windows(visible_only=True):
                        if leftover_win.process_id() == cached_app_pid:
                            w_title = leftover_win.window_text()
                            
                            # STRICT FILTER: Only destroy windows that contain "Report" in the title
                            if "report" in w_title.lower() and "estro" not in w_title.lower().strip()[:5]:
                                logger.info(f"Target locked. Destroying specific report window: {w_title}")
                                
                                try:
                                    leftover_win.set_focus()
                                    time.sleep(0.2)
                                    leftover_win.close() 
                                    time.sleep(0.5)
                                except Exception:
                                    pass
                                
                                if leftover_win.exists():
                                    try:
                                        send_keys("%{F4}")
                                        time.sleep(0.3)
                                        send_keys("%{c}")
                                        time.sleep(0.3)
                                        send_keys("{ESC}")
                                        time.sleep(0.5)
                                    except Exception:
                                        pass
                except Exception as cleanup_err:
                    logger.debug(f"Failed to clear leftover report windows: {cleanup_err}")

                if recorder.is_active():
                    recorder.stop()

                # Dispatch Per-Batch Email
                if current_batch_name:
                    try:
                        day_folder = datetime.now().strftime("%Y-%m-%d")
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name or process_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        target_path = os.path.join(screenshot_folder, f"screenshot_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(target_path) or target_path

                        table_rows = [
                            ("Process Status", "FAILED - DATA ERROR" if import_failed else "SUCCESSFUL"),
                            ("Process", process_name),
                            ("Date", current_json_date),
                            ("Client Value", current_client_value),
                            ("Execution Time", current_exec_time),
                        ]
                        if import_failed:
                            table_rows.append(("Error Details", failure_reason or "Tampered file rejected"))

                        send_batch_report_email(
                            smtp_config=smtp_config,
                            mail_config=mail_config,
                            table_rows=table_rows,
                            screenshot_path=actual_saved_path,
                            default_subject=f"Import Batch Report - {process_name} {'[FAILED]' if import_failed else ''}".strip(),
                        )
                    except Exception as e:
                        logger.error(f"Failed to send batch report email: {e}", exc_info=True)

                    import_failed = False
                    current_batch_name = None            
            # ============================================================
            # 8B. DYNAMIC EXPLICIT REPORT / EMAIL DISPATCH HANDLER
            # ============================================================
            elif action == "send_report":
                logger.info(f"Executing Batch Report Notification Dispatch Step: {desc}")
                
                if recorder.is_active():
                    recorder.stop()

                # MUST BE WIN32 TO READ VB6 DIALOG TEXT
                desktop = Desktop(backend="win32")

                # Scan for lingering error dialogs using Win32
                for win in desktop.windows():
                    try:
                        w_title = win.window_text()
                        w_cls = win.class_name()
                        if re.search(r"(?i).*(Cross|Information|Message|Confirmation|Notice|Alert|Error|Warning|Fatal|#32770).*", w_title) or w_cls in ["#32770", "ThunderRT6FormDC"]:
                            if win.is_visible() and win.handle != main_window.handle:
                                body_texts = [w_title]
                                clean_report_text = ""

                                for ctrl in win.descendants():
                                    try:
                                        t = ctrl.window_text().strip()
                                        if t:
                                            body_texts.append(t)
                                        # Target the dedicated report viewer control directly
                                        if ctrl.class_name() == "RichTextWndClass":
                                            clean_report_text = t
                                    except Exception:
                                        pass
                                full_popup_text = " ".join(body_texts).lower()

                                if any(word in full_popup_text for word in ["error", "fatal", "warning", "fail", "invalid", "not found", "unsuccess", "mismatch"]):
                                    logger.warning(f"Tampered file error caught during send_report: '{full_popup_text}'")
                                    import_failed = True
                                    overall_process_failed = True
                                    
                                    # Use clean RichTextWndClass text if available without the prefix
                                    if clean_report_text:
                                        failure_reason = clean_report_text.replace('\n', ' ').replace('\r', '').strip()
                                    else:
                                        failure_reason = win.window_text().strip()                                    
                                   # WIN32 TARGETED CLOSE LINGERING WINDOW
                                    logger.info("Attempting to forcefully close lingering white report window in send_report...")
                                    w_title = win.window_text()
                                    
                                    # Strictly only kill it if it is a report window
                                    if "report" in w_title.lower() and "estro" not in w_title.lower().strip()[:5]:
                                        try:
                                            win.set_focus()
                                            time.sleep(0.2)
                                            win.close() 
                                            time.sleep(0.5)
                                        except Exception:
                                            pass

                                        if win.exists():
                                            try:
                                                send_keys("%{F4}")
                                                time.sleep(0.3)
                                                send_keys("%{c}")
                                                time.sleep(0.3)
                                                send_keys("{ESC}")
                                                time.sleep(0.5)
                                            except Exception:
                                                pass
                                        
                                    time.sleep(1.0)
                                    break
                    except Exception:
                        continue

                # Dispatch email with accurate failure/success table rows
                if current_batch_name:
                    try:
                        day_folder = datetime.now().strftime("%Y-%m-%d")
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name or process_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        
                        target_path = os.path.join(screenshot_folder, f"screenshot_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(target_path) or target_path

                        # FIX: Removed overall_process_failed so per-file reporting is accurate
                        table_rows = [
                            ("Process Status", "FAILED - DATA ERROR" if import_failed else "SUCCESSFUL"),
                            ("Process", process_name),
                            ("Date", current_json_date),
                            ("Client Value", current_client_value),
                            ("Execution Time", current_exec_time),
                        ]
                        if import_failed:
                            table_rows.append(("Error Details", failure_reason or "Tampered file rejected"))
                        
                        send_batch_report_email(
                            smtp_config=smtp_config,
                            mail_config=mail_config,
                            table_rows=table_rows,
                            screenshot_path=actual_saved_path,
                            default_subject=f"Import Batch Report - {process_name} {'[FAILED]' if import_failed else ''}".strip(),
                        )
                        logger.info(f"Successfully transmitted report email for: {current_batch_name}")
                    except Exception as e:
                        logger.error(f"Failed to capture screenshot / send batch report email: {e}", exc_info=True)

                    current_batch_name = None
                    import_failed = False     
            # ============================================================
            # 9. DYNAMIC CONTAINER CLOSE ACTION
            # ============================================================
            elif action == "click_close":
                logger.info(f"Executing Inner Tab Close Step: {desc}")
                try:
                    # Dynamically resolves window title via JSON parameters (e.g. 'File Import' or 'Import File')
                    import_window = _get_target_window(step)
                   
                    if auto_id:
                        logger.info(f"Automation ID '{auto_id}' detected. Attempting direct button click...")
                        close_btn = import_window.child_window(auto_id=str(auto_id), control_type=ctrl_type)

                        if close_btn.exists(timeout=2):
                            close_btn.set_focus()
                            time.sleep(0.3)
                            try:
                                close_btn.click_input()
                            except Exception:
                                close_btn.type_keys("{SPACE}")
                            time.sleep(1.5)
                        else:
                            raise ValueError(f"Control with auto_id '{auto_id}' not found")
                    else:
                        try:
                            import_window.set_focus()
                            time.sleep(0.4)
                        except Exception:
                            pass

                        close_shortcut = step.get('shortcut', '^{F4}')
                        logger.info(f"Sending internal container close shortcut ({close_shortcut})...")
                        _send_keys_traced(f"click_close '{desc}' (import window close)", close_shortcut)
                        logger.info(f"Successfully requested closure of Import frame.")
                        time.sleep(2.0)
                except Exception as e:
                    logger.warning(f"Close step encountered an issue: {e}. Executing emergency shortcut fallback...")
                    try:
                        # Refocus our app first; never send the window-close shortcut while
                        # ANOTHER application (browser, console, ...) holds the foreground.
                        try:
                            main_window.set_focus()
                            time.sleep(0.3)
                        except Exception:
                            pass
                        fg_pid = _get_foreground_pid()
                        if cached_app_pid and fg_pid is not None and fg_pid != cached_app_pid:
                            logger.warning(
                                f"[KEY-TRACE] Close shortcut suppressed: the foreground window "
                                f"belongs to process {fg_pid}, not the target app ({cached_app_pid})."
                            )
                        else:
                            _send_keys_traced(f"click_close '{desc}' (emergency fallback)", "^{F4}")
                            time.sleep(1.5)
                    except Exception as fallback_err:
                        logger.error(f"Fallback close shortcut failed: {fallback_err}", exc_info=True)

        # End-of-run summary: makes a run where every import was silently skipped
        # (file/folder missing) unmistakable in the log before auto_close fires.
        if skipped_step_count:
            logger.critical(
                f"[SUMMARY] {skipped_step_count} of {len(other_steps)} step(s) were SKIPPED "
                f"because of a File/Folder-Not-Found state — those import batches did NOT run. "
                f"Check D:\\CDSLFILES date folders and files before the next schedule."
            )
        else:
            logger.info(f"[SUMMARY] All {len(other_steps)} non-menu step(s) processed; no steps were skipped.")

    finally:
        if recorder.is_active():
            recorder.stop()

    # Latch: True if ANY file failed during the run
    # Latch: True if ANY file failed OR if folders were skipped
    final_verdict = bool(overall_process_failed or import_failed or skipped_step_count > 0)
    if skipped_step_count > 0 and not failure_reason:
       failure_reason = f"{skipped_step_count} step(s) were skipped due to missing folders"

    if final_verdict:
       logger.error(f"🛑 Run completed with errors (final_verdict=FAILED). Reason: {failure_reason or 'Tampered data detected'}")
    else:
       logger.info("✅ Run completed without any recorded failures.")

    return (final_verdict, failure_reason or "Application Data Error")        