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

def _log_forensic_window_state(context):
    """Logs all top-level window titles so client-side failures are diagnosable from the log alone."""
    try:
        titles = [w.window_text() for w in Desktop(backend="uia").windows()]
        logger.error(f"[FORENSICS:{context}] Top-level windows on screen: {titles}")
    except Exception as forensics_err:
        logger.debug(f"Forensic window enumeration failed: {forensics_err}")

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

def parse_relative_date(date_token, date_format="%d%m%Y"):
    """
    Parses dynamic date tokens such as 't', 't-1', 't+2' into specific string formats.
    e.g. 't' -> Today
         't-1' -> Yesterday
    """
    date_token = str(date_token).strip().lower()
    
    # Baseline is today
    target_date = datetime.now()
    
    if date_token.startswith("t"):
        modifier = date_token[1:]  # Extracts '-1', '+2', etc.
        if modifier:
            try:
                # Calculate delta offset based on operator sign
                days_offset = int(modifier)
                target_date += timedelta(days=days_offset)
            except ValueError:
                pass  # Fallback to today if string structure is corrupted
        
        return target_date.strftime(date_format)
    
    # Return raw text fallback if token syntax is not recognized
    return date_token


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
    failure_reason = ""

    # Helper to resolve SMTP settings cleanly across configurations
    smtp_config = (global_config or {}).get("email_settings") or (global_config or {}).get("smtp_config") or {}

    # Resolve the app PID once while the window is responsive. Re-resolving the main
    # window spec fails on VB6 apps whenever the UI thread is blocked (import running)
    # because the window stops answering UIA property requests.
    try:
        cached_app_pid = main_window.process_id()
    except Exception:
        cached_app_pid = None

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
                    
                    if auto_id:
                        menu_item = parent_win.child_window(auto_id=str(auto_id), control_type="MenuItem")
                        menu_item.click_input()
                    else:
                        # Resolve ALL matching items and pick the JSON occurrence index so
                        # duplicate menu entries (e.g. two 'Utilities' items on UAT builds)
                        # no longer abort the whole traversal.
                        matches = parent_win.descendants(title_re=f"(?i)^{re.escape(item_title)}$", control_type="MenuItem")
                        if not matches:
                            raise ElementNotFoundError(f"No menu item matching '{item_title}' was found")
                        try:
                            occ_idx = int(step.get('class_occurrence_index', 0) or 0)
                        except (TypeError, ValueError):
                            occ_idx = 0
                        if occ_idx < 0 or occ_idx >= len(matches):
                            occ_idx = 0
                        if len(matches) > 1:
                            logger.info(f"Menu item '{item_title}' matched {len(matches)} elements; using occurrence index {occ_idx}.")
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
                send_keys("^i")
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
                if action in ["select_dropdown", "switch_tab", "click_close"]:
                    logger.info(f"Resetting error bypass flag. Found next setup action configuration entry: {action}")
                    skip_until_next_batch = False
                else:
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
                    _log_forensic_window_state("switch_tab")
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
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        screenshot_path = os.path.join(screenshot_folder, f"FOLDER_NOT_FOUND_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(screenshot_path) or screenshot_path
                        
                        table_rows = [
                            ("Process Status", "FAILED"),
                            ("Process Name", process_name),
                            ("Error Captured", f"Folder Not Found: {target_subfolder}"),
                            ("Client Context", current_client_value),
                            ("System Execution Time", current_exec_time),
                        ]
                        try:
                            send_batch_report_email(smtp_config, mail_config, table_rows, actual_saved_path, f"CRITICAL ERROR: Folder Not Found - {process_name}")
                        except Exception as email_err:
                            pass
                        # ---------------------------------------------
                        
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
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        screenshot_path = os.path.join(screenshot_folder, f"FILE_NOT_FOUND_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(screenshot_path) or screenshot_path
                        
                        table_rows = [
                            ("Process Status", "FAILED"),
                            ("Process Name", process_name),
                            ("Error Captured", f"File Not Found: {target_pattern}"),
                            ("Client Context", current_client_value),
                            ("System Execution Time", current_exec_time),
                        ]
                        try:
                            send_batch_report_email(smtp_config, mail_config, table_rows, actual_saved_path, f"CRITICAL ERROR: File Not Found - {process_name}")
                        except Exception as email_err:
                            pass
                        # ---------------------------------------------
                        
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

                        import_action_btn.click()
                        logger.info("Successfully requested document structural engine processing via final file Import control.")
                        
                        # ========================================================
                        # 🚀 NEW: THE LOOKAHEAD RADAR (Cross vs Estro Router)
                        # ========================================================
                        next_action = ""
                        # Peek at the very next step in the JSON array
                        if index + 1 < len(other_steps):
                            next_action = other_steps[index + 1].get('action')

                        if next_action == "wait_for_table":
                            logger.info("Engine Auto-Detect: Grid-based UI (Cross). Applying 3-second static buffer...")
                            time.sleep(3.0)
                        else:
                            logger.info("Engine Auto-Detect: Locked-thread UI (Estro / Compliance Sutra). Initiating dynamic OS polling...")
                            max_wait_seconds = 10800 # 3-hour safety net
                            start_time = time.time()
                            time.sleep(3.0) # Buffer to allow application to freeze
                            
                            desktop_spy = Desktop(backend="uia")

                            while (time.time() - start_time) < max_wait_seconds:
                                try:
                                    # Break if ANY popup appears (Success OR Error)
                                    active_windows = desktop_spy.windows(process=target_pid)
                                    popup_detected = False
                                    for win in active_windows:
                                        win_text = str(win.window_text()).strip()
                                        # (Kept your custom "Sucess" spelling catch here!)
                                        if any(keyword in win_text for keyword in ["Information", "Message", "Success","Sucess","Estro", "Error", "Fatal"]):
                                            popup_detected = True
                                            break
                                    if popup_detected:
                                        break

                                    # Break if main window naturally unfreezes (silent success)
                                    if import_window.is_enabled():
                                        break
                                except Exception:
                                    pass # Swallow Pywinauto COM errors while frozen
                                
                                time.sleep(0.5) 
                        # ========================================================
                        
                        desktop = Desktop(backend="uia")
                        
                        try:
                            fatal_dialog = desktop.window(title_re="(?i).*(fatal|error).*", control_type="Window", top_level_only=True)
                            if fatal_dialog.exists(timeout=1.5):
                                failure_reason = fatal_dialog.window_text()
                                logger.warning(f"Detected Application Error Layer Context: '{failure_reason}'")
                                
                                fatal_dialog.set_focus()
                                time.sleep(0.2)
                                send_keys("{ENTER}")
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
                            screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name)
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
                    import_window = _get_target_window(step)
                    
                    if auto_id:
                        table_grid = import_window.child_window(auto_id=str(auto_id), control_type=ctrl_type)
                    else:
                        grid_cls = step.get('class_name', 'MSHFlexGridWndClass')
                        table_grid = import_window.child_window(class_name=grid_cls, control_type=ctrl_type, found_index=0)

                    grid_timeout = step.get('timeout', 60)
                    logger.info("Waiting for data grid table initialization...")
                    table_grid.wait('exists', timeout=grid_timeout)
                    table_grid.wait('ready', timeout=grid_timeout)
                    time.sleep(1.5)
                    logger.info("Data table successfully loaded and populated with imported values.")
                except Exception as e:
                    logger.error(f"Failed while waiting for processing table to display records: {e}", exc_info=True)
                    _log_forensic_window_state("wait_for_table")
                    # A result dialog can legitimately sit in front of the grid (e.g. 'File
                    # Imported (Success)'); defer to the configured click_ok step instead
                    # of aborting the whole run.
                    blocker_active = False
                    try:
                        local_desktop = Desktop(backend="uia")
                        blocker = local_desktop.window(
                            title_re=r"(?i).*(information|imported|confirmation|notice|message|error|warning|fatal).*",
                            control_type="Window",
                            top_level_only=True,
                            process=cached_app_pid
                        )
                        if blocker.exists(timeout=1):
                            logger.warning(f"Active result dialog '{blocker.window_text()}' detected; skipping grid verification.")
                            blocker_active = True
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
                target_pid = cached_app_pid
                
                # Check up to 5 consecutive dialog popups (handles consecutive error/info popups)
                max_dialog_checks = step.get('max_popup_count', 5)
                dialogs_cleared = 0

                for check_idx in range(1, max_dialog_checks + 1):
                    logger.info(f"Polling for active pop-up dialog window (Attempt {check_idx}/{max_dialog_checks})...")
                    btn_clicked = False

                    # Strategy 1: Search top-level modal popups strictly within target application PID
                    try:
                        dialog_title_cfg = step.get('dialog_title') or step.get('window_title')
                        if dialog_title_cfg:
                            active_dialog = desktop.window(
                                title_re=f"(?i).*{re.escape(dialog_title_cfg)}.*", 
                                top_level_only=True, 
                                process=target_pid
                            )
                        else:
                            active_dialog = desktop.window(
                                title_re=r"(?i).*(Cross|Information|Message|Confirmation|Notice|Alert|Error|Warning|Fatal).*", 
                                top_level_only=True, 
                                process=target_pid
                            )

                        if active_dialog.exists(timeout=2):
                            active_dialog.set_focus()
                            time.sleep(0.3)

                            # Find target button inside modal
                            if auto_id:
                                target_btn = active_dialog.child_window(auto_id=str(auto_id), control_type=ctrl_type)
                            else:
                                btn_title = step.get('title') or step.get('text', 'OK')
                                target_btn = active_dialog.child_window(title_re=f"(?i).*{re.escape(btn_title)}.*", control_type=ctrl_type)

                            if not target_btn.exists():
                                target_btn = active_dialog.child_window(title_re=r"(?i).*(OK|Yes|Close|Dismiss).*", control_type="Button")

                            if target_btn.exists(timeout=1):
                                logger.info(f"🖱️ Clicking button '{target_btn.window_text()}' inside popup dialog #{check_idx}...")
                                target_btn.click_input()
                                dialogs_cleared += 1
                                btn_clicked = True
                                time.sleep(1.2)
                    except Exception as modal_err:
                        logger.debug(f"Modal popup search iteration {check_idx}: {modal_err}")

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

                    # Strategy 3: Single modal dismissal via ENTER keypress
                    if not btn_clicked:
                        if check_idx == 1:
                            logger.info("No explicit button caught via UIA. Sending Enter keypress to clear active modal...")
                            send_keys("{ENTER}")
                            dialogs_cleared += 1
                            time.sleep(1.0)
                        else:
                            break

                logger.info(f"✓ Cleared total of {dialogs_cleared} pop-up dialog window(s).")

                if recorder.is_active():
                    recorder.stop()

                if current_batch_name and not import_failed:
                    try:
                        day_folder = datetime.now().strftime("%Y-%m-%d")
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        
                        target_path = os.path.join(screenshot_folder, f"screenshot_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(target_path) or target_path

                        table_rows = [
                            ("Process Status", "SUCCESSFUL"),
                            ("Process", process_name),
                            ("Date", current_json_date),
                            ("Client Value", current_client_value),
                            ("Execution Time", current_exec_time),
                        ]
                        
                        send_batch_report_email(
                            smtp_config=smtp_config,
                            mail_config=mail_config,
                            table_rows=table_rows,
                            screenshot_path=actual_saved_path,
                            default_subject=f"Import Batch Report - {process_name}",
                        )
                    except Exception as e:
                        logger.error(f"Failed to capture screenshot / send batch report email: {e}", exc_info=True)


            # ============================================================
            # 8B. DYNAMIC EXPLICIT REPORT / EMAIL DISPATCH HANDLER
            # ============================================================
            elif action == "send_report":
                logger.info(f"Executing Batch Report Notification Dispatch Step: {desc}")
                
                if recorder.is_active():
                    recorder.stop()

                if current_batch_name and not import_failed:
                    try:
                        day_folder = datetime.now().strftime("%Y-%m-%d")
                        screenshot_folder = os.path.join(BASE_OUTPUT_DIR, day_folder, current_batch_name)
                        os.makedirs(screenshot_folder, exist_ok=True)
                        
                        target_path = os.path.join(screenshot_folder, f"screenshot_{datetime.now().strftime('%H-%M-%S')}.png")
                        actual_saved_path = capture_screenshot(target_path) or target_path

                        table_rows = [
                            ("Process Status", "SUCCESSFUL"),
                            ("Process", process_name),
                            ("Date", current_json_date),
                            ("Client Value", current_client_value),
                            ("Execution Time", current_exec_time),
                        ]
                        
                        send_batch_report_email(
                            smtp_config=smtp_config,
                            mail_config=mail_config,
                            table_rows=table_rows,
                            screenshot_path=actual_saved_path,
                            default_subject=f"Import Batch Report - {process_name}",
                        )
                        logger.info(f"Successfully transmitted report email for: {current_batch_name}")
                        current_batch_name = None
                    except Exception as e:
                        logger.error(f"Failed to capture screenshot / send batch report email: {e}", exc_info=True)            

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
                        send_keys(close_shortcut)
                        logger.info(f"Successfully requested closure of Import frame.")
                        time.sleep(2.0)
                except Exception as e:
                    logger.warning(f"Close step encountered an issue: {e}. Executing emergency shortcut fallback...")
                    try:
                        send_keys("^{F4}")
                        time.sleep(1.5)
                    except Exception as fallback_err:
                        logger.error(f"Fallback close shortcut failed: {fallback_err}", exc_info=True)

    finally:
        if recorder.is_active():
            recorder.stop()