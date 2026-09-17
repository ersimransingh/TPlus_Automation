import os
import json
import time
import re
import ctypes
import smtplib
import glob
import shutil
import subprocess
import datetime
import sys
import zipfile
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import win32api
import win32con
import win32gui
from grid_keyboard_nav import find_and_check_row_via_keyboard
from grid_ocr_nav import find_and_check_row_via_ocr
from pywinauto import Application
from pywinauto.keyboard import send_keys
from pywinauto.mouse import click as mouse_click
from PIL import ImageGrab
import datetime
from datetime import datetime, date, timedelta

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def load_config_profile(filename):
    """Safely handles reading specific JSON profile data maps (PyInstaller compatible)."""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    target_path = os.path.join(base_dir, filename)
    if not os.path.exists(target_path):
        target_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.exists(target_path):
        # Secondary fallback to execution directory
        target_path = os.path.join(os.getcwd(), filename)
        
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Critical configuration initialization map missing: {filename}")
        
    with open(target_path, "r", encoding="utf-8") as f:
        return json.load(f)

def capture_screenshot(tag_name="Dialog_OK"):
    """Captures desktop screenshot safely without datetime import collisions."""
    try:
        from datetime import datetime
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        output_dir = os.path.join(base_dir, "screenshot")
        os.makedirs(output_dir, exist_ok=True)

        current_time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_prefix = f"screenshot_{tag_name}" if tag_name else "screenshot"
        filename = f"{file_prefix}_{current_time_str}.png"
        filepath = os.path.join(output_dir, filename)

        screenshot = ImageGrab.grab()
        screenshot.save(filepath)
        print(f"📸 Dialog OK Screenshot saved successfully at: {filepath}")
        return filepath
    except Exception as e:
        print(f"⚠️ Failed to capture screenshot: {e}")
        return None

import re
from datetime import datetime, date, timedelta

def get_date_components(date_str):
    """
    Parses date_str into (day, month, year) tuples safely.
    Handles relative dates (t-1, t-4) and absolute formatted dates.
    """
    if not date_str:
        today = date.today()  # <--- FIX: Use 'date.today()' directly instead of 'datetime.date.today()'
        return today.strftime("%d"), today.strftime("%b").capitalize(), today.strftime("%Y")

    normalized = str(date_str).strip().lower()

    if "t" in normalized and ("-" in normalized or "+" in normalized):
        try:
            match = re.search(r'[-+]\s*\d+', normalized)
            if match:
                offset = int(match.group().replace(" ", ""))
                target_dt = date.today() + timedelta(days=offset)
                return target_dt.strftime("%d"), target_dt.strftime("%b").capitalize(), target_dt.strftime("%Y")
        except Exception as err:
            print(f"⚠️ [DATE ERROR] Could not parse relative offset '{date_str}': {err}")

    # Fallback parsing for YYYYMMDD or dd-Mon-YYYY strings
    for fmt in ("%Y%m%d", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed_dt = datetime.strptime(normalized, fmt)
            return parsed_dt.strftime("%d"), parsed_dt.strftime("%b").capitalize(), parsed_dt.strftime("%Y")
        except ValueError:
            continue

    # Default fallback
    today = date.today()
    return today.strftime("%d"), today.strftime("%b").capitalize(), today.strftime("%Y")

def resolve_date_string(date_str):
    """
    Formats dates into standardized folder string format (e.g., '03Aug2026').
    """
    if not date_str:
        return "Downloaded_Reports"

    normalized = str(date_str).strip().lower()
    today_dt = date.today()  # FIXED: Use 'date.today()' directly

    if normalized in ("t", "today"):
        target_date = today_dt
    elif normalized == "yesterday":
        target_date = today_dt - timedelta(days=1)  # FIXED
    elif normalized == "tomorrow":
        target_date = today_dt + timedelta(days=1)   # FIXED
    elif normalized.startswith("t") and ("-" in normalized or "+" in normalized):
        try:
            offset_match = re.search(r'[-+]\s*\d+', normalized)
            if offset_match:
                offset = int(offset_match.group().replace(" ", ""))
                target_date = today_dt + timedelta(days=offset)  # FIXED
            else:
                target_date = today_dt
        except Exception:
            target_date = today_dt
    else:
        try:
            target_date = datetime.strptime(normalized.replace("-", ""), "%Y%m%d").date()
        except Exception:
            return normalized.replace("-", "")

    day = target_date.strftime("%d")
    month = target_date.strftime("%b").capitalize()  # Outputs '03Aug2026'
    year = target_date.strftime("%Y")
    return f"{day}{month}{year}"


def resolve_date_yyyymmdd(date_str):
    """
    Strictly resolves date expressions (e.g., 't-1', '06-Aug-2026', '20260806') 
    to exact 'YYYYMMDD' (e.g., '20260806').
    """
    if not date_str:
        return date.today().strftime("%Y%m%d")  # FIXED: date.today() instead of datetime.date.today()

    normalized = str(date_str).strip().lower()
    today_dt = date.today()  # FIXED

    if normalized in ("t", "today"):
        target_date = today_dt
    elif normalized == "yesterday":
        target_date = today_dt - timedelta(days=1)
    elif normalized == "tomorrow":
        target_date = today_dt + timedelta(days=1)
    elif "t" in normalized and ("-" in normalized or "+" in normalized):
        try:
            match = re.search(r'[-+]\s*\d+', normalized)
            if match:
                offset = int(match.group().replace(" ", ""))
                target_date = today_dt + timedelta(days=offset)
            else:
                target_date = today_dt
        except Exception as err:
            print(f"⚠️ [DATE ENGINE WARNING] Could not parse relative offset '{date_str}': {err}")
            target_date = today_dt
    else:
        # Check if already a pure YYYYMMDD string
        clean_digits = re.sub(r'\D', '', normalized)
        if len(clean_digits) == 8:
            return clean_digits
        
        # Try explicit string parsing
        for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                target_date = datetime.strptime(normalized, fmt).date()
                return target_date.strftime("%Y%m%d")
            except ValueError:
                continue
        target_date = today_dt

    resolved_str = target_date.strftime("%Y%m%d")
    print(f"📅 [DATE ENGINE] Resolved input '{date_str}' -> YYYYMMDD: '{resolved_str}'")
    return resolved_str

def send_notification_email(email_settings, subject, body, attachments=None):
    if not email_settings:
        print("⚠️ Email notification skipped: No email_settings found in config.")
        return
    try:
        sender_email = (
            email_settings.get("from_email") or 
            email_settings.get("username") or 
            email_settings.get("sender_email") or 
            email_settings.get("SENDER_EMAIL")
        )
        reporting_email = (
            email_settings.get("reporting_email") or 
            email_settings.get("to") or 
            email_settings.get("REPORTING_EMAIL") or 
            sender_email
        )
        smtp_server = (
            email_settings.get("host") or 
            email_settings.get("smtp_server") or 
            email_settings.get("SMTP_SERVER", "smtp.gmail.com")
        )
        smtp_port = int(
            email_settings.get("port") or 
            email_settings.get("smtp_port") or 
            email_settings.get("SMTP_PORT", 587)
        )
        use_tls = email_settings.get("use_tls", True)
        
        raw_password = (
            email_settings.get("password_enc") or 
            email_settings.get("sender_password_enc") or 
            email_settings.get("sender_password") or 
            email_settings.get("password", "")
        )
        
        # Import Base64 resolver helper
        try:
            from App import resolve_password_value
            sender_password = resolve_password_value(raw_password)
        except ImportError:
            sender_password = raw_password

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = reporting_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Attach captured Dialog_OK screenshot
        if attachments:
            for filepath in attachments:
                if filepath and os.path.exists(filepath):
                    try:
                        with open(filepath, 'rb') as f:
                            img_data = f.read()
                            img_name = os.path.basename(filepath)
                            image_part = MIMEImage(img_data, name=img_name)
                            msg.attach(image_part)
                            print(f"📎 Attached dialog screenshot to email: {img_name}")
                    except Exception as att_err:
                        print(f"⚠️ Could not attach file {filepath}: {att_err}")

        server = smtplib.SMTP(smtp_server, smtp_port)
        if use_tls:
            server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(f"📧 Notification email dispatched successfully to '{reporting_email}': '{subject}'")
    except Exception as e:
        print(f"⚠️ Failed to send notification email: {e}")

def verify_files_silently(directory_path, patterns):
    print(f"🔍 [Background Audit] Checking items in directory: {directory_path}")
    if not os.path.exists(directory_path):
        print(f"⚠️ Target directory missing: {directory_path}")
        return False, patterns

    try:
        downloaded_files = os.listdir(directory_path)
    except Exception as e:
        print(f"⚠️ Error reading directory files: {e}")
        return False, patterns

    missing_patterns = []
    for pattern in patterns:
        if isinstance(pattern, list):
            match_found = False
            for filename in downloaded_files:
                if all(str(sub_segment).strip() in filename for sub_segment in pattern if sub_segment):
                    print(f"   ✓ Multi-part Match Detected: '{filename}' covers patterns {pattern}")
                    match_found = True
                    break
            if not match_found:
                print(f"   ❌ Missing multi-part pattern target match: {pattern}")
                missing_patterns.append(pattern)
        else:
            if not pattern or str(pattern).strip() == "":
                continue
            match_found = any(str(pattern).strip() in filename for filename in downloaded_files)
            if match_found:
                print(f"   ✓ Substring Match Detected for pattern: '*{pattern}*'")
            else:
                print(f"   ❌ Missing pattern target match: '*{pattern}*'")
                missing_patterns.append(pattern)

    success = len(missing_patterns) == 0
    return success, missing_patterns

def verify_files_via_explorer(base_path, date_folder_name, patterns):
    print(f"📂 [UI Explorer Mode] Opening File Explorer target frame for path: {base_path}")
    if not os.path.exists(base_path):
        os.makedirs(base_path, exist_ok=True)

    subprocess.Popen(f'explorer.exe "{base_path}"')
    time.sleep(2.5)

    try:
        explorer_app = Application(backend="uia").connect(path="explorer.exe", title_re=".*", timeout=5)
        explorer_win = explorer_app.top_window()
        explorer_win.set_focus()
        time.sleep(0.5)

        target_folder_path = os.path.join(base_path, date_folder_name) if date_folder_name else base_path
        print(f"🗂️ Navigating Explorer layout view into target folder context -> {target_folder_path}")

        send_keys("%d")
        time.sleep(0.3)
        send_keys(target_folder_path + "{ENTER}", with_spaces=True)
        time.sleep(2.0)

        success, missing = verify_files_silently(target_folder_path, patterns)
        explorer_win.close()
        return success, missing
    except Exception as explorer_err:
        print(f"⚠️ Explorer UI automation error encountered: {explorer_err}. Falling back to background verification logic.")
        full_target_path = os.path.join(base_path, date_folder_name) if date_folder_name else base_path
        return verify_files_silently(full_target_path, patterns)

def _flatten_pattern_tokens(pattern_config):
    tokens = []
    for pattern in pattern_config or []:
        if isinstance(pattern, list):
            if pattern and str(pattern[0]).strip():
                tokens.append(str(pattern[0]).strip())
        else:
            if pattern and str(pattern).strip():
                tokens.append(str(pattern).strip())
    return tokens

def _get_column_bounds(grid, header_name_fragment):
    try:
        headers = grid.descendants(control_type="HeaderItem")
        for h in headers:
            if header_name_fragment.strip().lower() in h.window_text().strip().lower():
                r = h.rectangle()
                return (r.left, r.right)
    except Exception as e:
        print(f"⚠️ Could not read grid headers while locating '{header_name_fragment}': {e}")
    return None

def _get_download_column_x(grid):
    bounds = _get_column_bounds(grid, "download")
    if bounds:
        left, right = bounds
        return (left + right) // 2
    grid_rect = grid.rectangle()
    return grid_rect.right - 45

def scroll_and_click_checkbox(report_win, pattern_config, grid_auto_id="Dt_dngrid",
                               host_file_column_header="Host File Name",
                               max_scrolls=400, scroll_lines=3, settle_pause=0.15):
    tokens = _flatten_pattern_tokens(pattern_config)
    if not tokens:
        print("ℹ️ No file-name pattern tokens available to match against grid rows.")
        return False

    try:
        grid = report_win.child_window(auto_id=grid_auto_id, control_type="Table")
        if not grid.exists(timeout=6):
            print(f"⚠️ Grid with AutomationId '{grid_auto_id}' not found.")
            return False
        grid.set_focus()
    except Exception as e:
        print(f"⚠️ Unable to locate grid '{grid_auto_id}': {e}")
        return False

    try:
        grid.scroll("up", "page", 50)
    except Exception:
        try:
            send_keys("{HOME}")
        except Exception:
            pass
    time.sleep(0.4)

    checkbox_x = _get_download_column_x(grid)
    host_file_bounds = _get_column_bounds(grid, host_file_column_header)
    if host_file_bounds:
        hf_left, hf_right = host_file_bounds
        print(f"ℹ️ '{host_file_column_header}' column bounds resolved: x=[{hf_left}, {hf_right}]")
    else:
        hf_left, hf_right = None, None

    for attempt in range(max_scrolls):
        try:
            cell_elements = grid.descendants(control_type="Text")
        except Exception as e:
            print(f"⚠️ Error enumerating grid cells: {e}")
            cell_elements = []

        matched_cell = None
        matched_text = None
        for cell in cell_elements:
            try:
                if not cell.is_visible():
                    continue
                rect = cell.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    continue

                if hf_left is not None:
                    cell_center_x = (rect.left + rect.right) // 2
                    if not (hf_left <= cell_center_x <= hf_right):
                        continue

                text = cell.window_text().strip()
            except Exception:
                continue
            if text and any(tok in text for tok in tokens):
                matched_cell = cell
                matched_text = text
                break

        if matched_cell is not None:
            row_rect = matched_cell.rectangle()
            row_y_center = (row_rect.top + row_rect.bottom) // 2
            print(f"🎯 Match found after {attempt} scroll step(s) in '{host_file_column_header}' column: '{matched_text}'")
            try:
                mouse_click(button='left', coords=(checkbox_x, row_y_center))
                time.sleep(0.3)
                print("✓ Checkbox clicked via coordinate click.")
                return True
            except Exception as e:
                print(f"⚠️ Failed to click checkbox at computed coords: {e}")
                return False

        try:
            grid.scroll("down", "line", scroll_lines)
        except Exception:
            try:
                send_keys("{DOWN}" * scroll_lines)
            except Exception:
                pass
        time.sleep(settle_pause)

    print(f"⚠️ Reached max_scrolls ({max_scrolls}) without finding a matching row for tokens: {tokens}")
    return False

def click_grid_download_button(*containers, auto_id="cmdDownload", timeout=5):
    for container in containers:
        if container is None:
            continue
        try:
            dl_btn = container.child_window(auto_id=auto_id, control_type="Button")
            if dl_btn.exists(timeout=timeout):
                dl_btn.click_input()
                print("✓ Clicked Download button (cmdDownload).")
                return True
        except Exception:
            continue
    print("⚠️ Could not locate the 'cmdDownload' button in any candidate window.")
    return False

def handle_post_download_dialogs(app, overwrite_wait=4, complete_wait=8):
    dialog_screenshots = []
    try:
        popup = app.top_window()
        title = popup.window_text()
        yes_btn = popup.child_window(title="Yes", control_type="Button")
        if yes_btn.exists(timeout=overwrite_wait):
            print(f"⚠️ Overwrite/confirmation dialog detected ('{title}'). Clicking Yes...")
            yes_btn.click_input()
            time.sleep(1.0)
    except Exception as e:
        print(f"ℹ️ No overwrite confirmation dialog detected: {e}")

    try:
        popup2 = app.top_window()
        title2 = popup2.window_text()
        ok_btn = popup2.child_window(title="OK", control_type="Button")
        if ok_btn.exists(timeout=complete_wait):
            print(f"✓ Download completion dialog detected ('{title2}'). Capturing screenshot before clicking OK...")
            # Capture the exact Report Download OK dialog screen
            ss_path = capture_screenshot("Dialog_OK")
            if ss_path:
                dialog_screenshots.append(ss_path)
            ok_btn.click_input()
            time.sleep(1.0)
    except Exception as e:
        print(f"ℹ️ No download-completion dialog detected: {e}")

    return dialog_screenshots

def matches_pattern_strict(filename, pattern_config, date_token=""):
    """
    Strict matching that strips extension noise (.ZIP / .CSV) 
    so files match whether they are zipped or direct .csv downloads.
    """
    if not pattern_config:
        return True

    file_upper = filename.upper()

    # Enforce Business Date Token (e.g., '20260806') presence in filename
    if date_token and str(date_token).strip() not in file_upper:
        return False

    for pattern in pattern_config:
        if isinstance(pattern, list):
            # Clean .ZIP and .CSV extensions from sub-tokens for flexible matching
            cleaned_tokens = [
                str(sub).strip().upper().replace(".ZIP", "").replace(".CSV", "") 
                for sub in pattern if sub
            ]
            if all(token in file_upper for token in cleaned_tokens):
                return True
        else:
            cleaned_token = str(pattern).strip().upper().replace(".ZIP", "").replace(".CSV", "")
            if cleaned_token in file_upper:
                return True

    return False

def format_date_folder_name(date_token):
    """
    Converts ANY date input into 'ddMonYYYY' format with capitalized months 
    (e.g., '06Aug2026', '01Jun2026', '03Jul2026', '05Mar2026', '01Dec2026').
    """
    if not date_token:
        return ""

    raw = str(date_token).strip()
    target_dt = None

    # 1. Handle pure digits YYYYMMDD (e.g., '20260806')
    if raw.isdigit() and len(raw) == 8:
        try:
            target_dt = datetime.strptime(raw, "%Y%m%d")
        except ValueError:
            pass

    # 2. Handle Relative Date Expressions (e.g., 't-1', 't-4')
    elif "t" in raw.lower() and ("-" in raw or "+" in raw):
        try:
            match = re.search(r'[-+]\s*\d+', raw.lower())
            if match:
                offset = int(match.group().replace(" ", ""))
                target_dt = datetime.now() + timedelta(days=offset)
        except Exception:
            pass

    # 3. Handle Formatted Date Strings (e.g., '06-Aug-2026', '2026-08-06', '06/08/2026')
    if not target_dt:
        for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d%b%Y"):
            try:
                target_dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    # Format output specifically with mixed-case Month (dd + Mon + YYYY)
    if target_dt:
        day_str = target_dt.strftime("%d")          # e.g., '06'
        month_str = target_dt.strftime("%b").capitalize()  # e.g., 'Aug', 'Jun', 'Jul', 'Mar', 'Dec'
        year_str = target_dt.strftime("%Y")         # e.g., '2026'
        
        folder_name = f"{day_str}{month_str}{year_str}"
        print(f"📅 [FOLDER RESOLUTION] Converted date token '{date_token}' -> Folder: '{folder_name}'")
        return folder_name

    return ""

def extract_and_copy_zip_files(source_directory, destination_directory, pattern_config=None, date_token=""):
    """
    Sync Engine that dynamically navigates to mixed-case date subfolders (e.g., '\06Aug2026').
    """
    is_isin_path = "ISIN" in source_directory.upper()
    actual_source_dir = source_directory

    # Standard Reports Resolution: Append dynamic date subfolder
    if not is_isin_path and date_token:
        target_folder_name = format_date_folder_name(date_token)  # Outputs '06Aug2026'
        
        if target_folder_name:
            candidate_dir = os.path.join(source_directory, target_folder_name)
            
            # Direct match check (e.g., \28700\06Aug2026)
            if os.path.exists(candidate_dir):
                actual_source_dir = candidate_dir
            else:
                # Case-insensitive fallback check for subfolders on network drive
                try:
                    for entry in os.listdir(source_directory):
                        if entry.lower() == target_folder_name.lower():
                            actual_source_dir = os.path.join(source_directory, entry)
                            break
                except Exception as list_err:
                    print(f"⚠️ [FILE SYNC] Cannot list network path '{source_directory}': {list_err}")

    if not os.path.exists(actual_source_dir):
        print(f"⚠️ [FILE SYNC] Source path does not exist: '{actual_source_dir}'")
        return 0

    os.makedirs(destination_directory, exist_ok=True)

    print(f"\n🚚 [FILE SYNC ENGINE]")
    print(f"   ↳ Base Source Directory : '{source_directory}'")
    print(f"   ↳ Active Target Path    : '{actual_source_dir}'")
    print(f"   ↳ Destination Directory : '{destination_directory}'")
    print(f"   ↳ Business Date Token   : '{date_token}'")
    print(f"   ↳ Unzip Mode Active     : {is_isin_path}")

    try:
        files_found = os.listdir(actual_source_dir)
    except Exception as list_err:
        print(f"⚠️ [FILE SYNC] Failed to read directory '{actual_source_dir}': {list_err}")
        return 0

    transferred_count = 0

    for item in files_found:
        item_path = os.path.join(actual_source_dir, item)

        if not os.path.isfile(item_path):
            continue

        if not matches_pattern_strict(item, pattern_config, date_token=date_token):
            continue

        item_upper = item.upper()

        # ISIN Path: Unzip
        if is_isin_path and item_upper.endswith(".ZIP"):
            try:
                print(f"📦 [ZIP ENGINE] Extracting: '{item}' -> '{destination_directory}'")
                with zipfile.ZipFile(item_path, 'r') as zip_ref:
                    zip_ref.extractall(destination_directory)
                print(f"   ✓ [ZIP ENGINE] Unzipped successfully.")
                transferred_count += 1
            except Exception as zip_err:
                print(f"   ⚠️ [ZIP ENGINE ERROR] Could not extract '{item}': {zip_err}")

        # Standard CSV Paths: Direct Copy
        elif not is_isin_path:
            dst_file_path = os.path.join(destination_directory, item)
            try:
                print(f"🚚 [DIRECT CSV COPY] Copying file: '{item}' -> '{destination_directory}'")
                shutil.copy2(item_path, dst_file_path)
                print(f"   ✓ [DIRECT COPY] Copied successfully.")
                transferred_count += 1
            except Exception as copy_err:
                print(f"   ⚠️ [FILE COPY ERROR] Could not copy '{item}': {copy_err}")

    print(f"✓ Total target items processed for date ({date_token}): {transferred_count}")
    return transferred_count

def resolve_dynamic_pattern(pattern_config, global_config=None):
    """
    Reads CDSLDPID / dp_rta_id from global_app_settings, extracts the last 5 digits,
    and replaces CDSLDPID5 (5-digit e.g. '28700') and CDSLDPID6 (6-digit zero-padded e.g. '028700').
    Retains legacy static file patterns.
    """
    if not pattern_config:
        return pattern_config

    raw_dp_id = ""
    try:
        master_config = load_config_profile("activity.json")
        global_settings = master_config.get("global_app_settings") or master_config.get("GLOBAL_APP_SETTINGS", {})
        raw_dp_id = str(
            global_settings.get("CDSLDPID") or 
            global_settings.get("dp_rta_id") or 
            (global_config or {}).get("dp_rta_id") or ""
        ).strip()
    except Exception:
        pass

    if not raw_dp_id:
        raw_dp_id = "28700"

    # EXTRACT LAST 5 DIGITS (e.g. '12328700' -> '28700')
    base_5_dpid = raw_dp_id[-5:] if len(raw_dp_id) >= 5 else raw_dp_id.zfill(5)
    base_6_dpid = base_5_dpid.zfill(6)  # '028700'

    def replace_tokens(text):
        if not isinstance(text, str):
            return text
        text = text.replace("CDSLDPID6", base_6_dpid)
        text = text.replace("CDSLDPID5", base_5_dpid)
        text = text.replace("CDSLDPID", base_5_dpid)
        return text

    resolved_patterns = []
    for item in pattern_config:
        if isinstance(item, list):
            resolved_patterns.append([replace_tokens(sub) for sub in item])
        else:
            resolved_patterns.append(replace_tokens(item))

    return resolved_patterns

def process_single_report_task(app, report_win, task, task_index, total_tasks, email_settings, global_config):
    module_id = str(task.get("module_id") or task.get("MODULE_ID", "")).strip()
    report_id = str(task.get("report_id") or task.get("REPORT_ID", "")).strip()
    date_from_raw = str(task.get("business_date_from") or task.get("BUSINESS_DATE_FROM", "")).strip()
    date_to_raw = str(task.get("business_date_to") or task.get("BUSINESS_DATE_TO", "")).strip()
    
    # READ RAW PATTERN FROM TASK
    raw_pattern = task.get("target_file_pattern") or task.get("TARGET_FILE_PATTERN", [])

    # 💥 CALL RESOLVE DYNAMIC PATTERN HERE 💥
    pattern_config = resolve_dynamic_pattern(raw_pattern, global_config=global_config)

    print(f" Active File Pattern Config Resolved: {pattern_config}")

    day_from, month_from, year_from = get_date_components(date_from_raw)
    day_to, month_to, year_to = get_date_components(date_to_raw)

    captured_screenshots = []

    print(f"\n--- [Task {task_index}/{total_tasks}] Processing Module: '{module_id}' | Report: '{report_id}' ---")

    # 1. Fill Module ID
    if module_id:
        module_field = report_win.child_window(auto_id="_txt_ModuleID", control_type="Edit")
        module_field.click_input()
        time.sleep(0.1)
        send_keys("{END}" + "{BACKSPACE}" * 8)
        time.sleep(0.1)
        send_keys(module_id, with_spaces=True)

    # 2. Fill Report ID
    if report_id:
        report_field = report_win.child_window(auto_id="_txt_ReportID", control_type="Edit")
        report_field.click_input()
        time.sleep(0.1)
        send_keys("{END}" + "{BACKSPACE}" * 8)
        time.sleep(0.1)
        send_keys(report_id, with_spaces=True)

    # 3. Fill From Date
    if day_from and month_from and year_from:
        date_from_pane = report_win.child_window(auto_id="_Date_from", control_type="Pane")
        date_from_pane.click_input()
        time.sleep(0.1)
        send_keys("{HOME}{LEFT}{LEFT}")
        send_keys(day_from + "{RIGHT}" + month_from + "{RIGHT}" + year_from)

    # 4. Fill To Date
    if day_to and month_to and year_to:
        date_to_pane = report_win.child_window(auto_id="_Date_To", control_type="Pane")
        date_to_pane.click_input()
        time.sleep(0.1)
        send_keys("{HOME}{LEFT}{LEFT}")
        send_keys(day_to + "{RIGHT}" + month_to + "{RIGHT}" + year_to)
        time.sleep(0.3)

    print("Locating download transaction trigger switch...")
    download_btn = report_win.child_window(title="Download", auto_id="_cmd_Download", control_type="Button")
    download_btn.click_input()

    print("✓ Criteria submitted. Waiting for window compilation responses...")
    time.sleep(6)

    # Handle Popup Detours
    active_popup_win = app.top_window()
    window_title = active_popup_win.window_text()

    if "Miscellaneous Report" in window_title or "Report" in window_title:
        popup_ok_btn = active_popup_win.child_window(title="OK", auto_id="cmd_ok", control_type="Button")
        if popup_ok_btn.exists():
            print("⚠️ DETOUR DETECTED: Acknowledging 'Miscellaneous Report' popup...")
            popup_ok_btn.click_input()
            time.sleep(5)

    time.sleep(2)

    # Resolve Exact Business Date Token (e.g. '20260803' for t-4)
    date_yyyymmdd = resolve_date_yyyymmdd(date_from_raw)

    # ✅ NEW CODE (Dynamic pattern & report check - No hardcoded module IDs)
    requires_ocr = False

    report_id_str = str(task.get("report_id") or task.get("REPORT_ID", "")).strip().upper()

    # 1. Check if the Report ID explicitly indicates ISIN Rate
    if "ISIN" in report_id_str and "MSTR" not in report_id_str and "MASTER" not in report_id_str:
        requires_ocr = True
    else:
        # 2. Inspect pattern config dynamically, strictly excluding master files
        for pat in pattern_config:
            pat_str = str(pat).upper()
            
            # Exclude ISIN Master variations
            if "ISIN_MSTR" in pat_str or "ISIN_MASTER" in pat_str:
                continue
                
            # Target ISIN Rate or compressed ZIP report patterns
            if "ISIN_RATE" in pat_str or "ISINRATE" in pat_str or ".ZIP" in pat_str:
                requires_ocr = True
                break

    # ------------------------------------------------------------
    # OCR GRID SEARCH WITH DATE FILTERING (MULTI-SELECT UPDATE)
    # ------------------------------------------------------------
    if requires_ocr:
        print(f"🔍 [WORKFLOW] ISIN/ZIP file pattern detected. Initializing Multi-Select OCR Grid Search for Date: '{date_yyyymmdd}'...")
        
        active_grid_win = app.top_window()
        extra_tokens = [date_yyyymmdd] if date_yyyymmdd else None

        # Call OCR engine ONCE with the entire pattern list to tick ALL matching rows simultaneously
        checkbox_selected = find_and_check_row_via_ocr(
            active_grid_win, pattern_config, grid_auto_id="Dt_dngrid",
            extra_tokens=extra_tokens
        )
        if not checkbox_selected:
            checkbox_selected = find_and_check_row_via_ocr(
                report_win, pattern_config, grid_auto_id="Dt_dngrid",
                extra_tokens=extra_tokens
            )

        if not checkbox_selected:
            print(f"ℹ️ OCR found nothing. Trying Keyboard fallback...")
            checkbox_selected = find_and_check_row_via_keyboard(
                active_grid_win, pattern_config, grid_auto_id="Dt_dngrid",
                row_settle=0.45, max_rows=50, extra_tokens=extra_tokens
            )

        if checkbox_selected:
            print(f"🎯 [OCR TICK TARGET] Checkboxes ticked successfully. Clicking Download button...")
            clicked = click_grid_download_button(active_grid_win, report_win, auto_id="cmdDownload")
            if clicked:
                time.sleep(2.0)
                dialog_ss = handle_post_download_dialogs(app)
                captured_screenshots.extend(dialog_ss)
        else:
            print(f"⚠️ No match found for patterns.")
            time.sleep(2.0)

    else:
        
        print("⚡ [WORKFLOW] Standard report task detected. Executing direct 'Download All'...")
        active_grid_win = app.top_window()
        clicked = False

        for candidate_win in (active_grid_win, report_win):
            if candidate_win is None:
                continue
            for target_id in ("_CmdDownloadAll", "cmdDownloadAll", "_cmdDownloadAll"):
                try:
                    dl_all_btn = candidate_win.child_window(auto_id=target_id, control_type="Button")
                    if dl_all_btn.exists(timeout=2):
                        dl_all_btn.click_input()
                        clicked = True
                        print(f"✓ Clicked 'Download All' button via auto_id: '{target_id}'")
                        break
                except Exception:
                    continue
            if clicked:
                break

        if clicked:
            time.sleep(2.0)
            dialog_ss = handle_post_download_dialogs(app)
            captured_screenshots.extend(dialog_ss)

    # ------------------------------------------------------------
    # RESOLVE PATHS & SYNC FILES
    # ------------------------------------------------------------
    # 1. Source Path: Take process-specific network directory from task config
    process_source_path = task.get("main_path") or global_config.get("main_path") or global_config.get("MAIN_PATH", "")

    # 2. Target Path: Take master output directory from activity.json global settings
    try:
        master_config = load_config_profile("activity.json")
        global_settings = master_config.get("global_app_settings") or master_config.get("GLOBAL_APP_SETTINGS", {})
    except Exception:
        global_settings = {}

    archive_master_root = global_settings.get("main_path") or "D:\\EXE\\activity\\Folder"
    
    # 3. Form Subfolder Path: e.g. D:\EXE\activity\Folder\03Aug2026
    clean_folder_date = resolve_date_string(date_from_raw if date_from_raw else "t")
    master_destination_path = os.path.join(archive_master_root, clean_folder_date)
    os.makedirs(master_destination_path, exist_ok=True)

    print(f"\n🚚 [FILE SYNC] Transferring files for Date Token '{date_yyyymmdd}' from '{process_source_path}' -> '{master_destination_path}'")
    
    # Run sync engine passing the strict Date Token ('20260803')
    extract_and_copy_zip_files(
        process_source_path, 
        master_destination_path, 
        pattern_config=pattern_config, 
        date_token=date_yyyymmdd
    )
    time.sleep(2.0)

    # ------------------------------------------------------------
    # AUDIT AND VERIFICATION
    # ------------------------------------------------------------
    show_explorer = global_settings.get("file_explorer_visibility", False)
    if show_explorer:
        verify_files_via_explorer(archive_master_root, clean_folder_date, pattern_config)

    # Verify inside local destination folder (D:\EXE\activity\Folder\03Aug2026)
    dest_files = os.listdir(master_destination_path) if os.path.exists(master_destination_path) else []
    missing = []

    print(f"🔍 [Background Audit] Checking items in directory: {master_destination_path}")
    for pattern in pattern_config:
        pat_list = [pattern] if not isinstance(pattern, list) else pattern
        matched_this_pat = False
        for file_name in dest_files:
            if matches_pattern_strict(file_name, [pat_list], date_token=date_yyyymmdd):
                matched_this_pat = True
                break
        if not matched_this_pat:
            missing.append(pattern)

    success = (len(missing) == 0) and (len(dest_files) > 0)

    # Email Reporting
    subject_module_info = f"Module: {module_id or 'Default'}, Report: {report_id or 'Default'} [{date_from_raw}]"
    attachments_to_send = list(dict.fromkeys(captured_screenshots))

    if success:
        log_msg = f"✅ SUCCESS: Business Date ({date_yyyymmdd}) target files verified in: {master_destination_path}"
        print(log_msg)
        email_body = f"Report Download Automation Update\n\nStatus: SUCCESS\nDetails: {log_msg}\nJob Parameters: {subject_module_info}\nDestination Folder: {master_destination_path}"
        send_notification_email(email_settings, f"File Download Successful - {subject_module_info}", email_body, attachments=attachments_to_send)
    else:
        log_msg = f"❌ FAILURE: Missing required Business Date ({date_yyyymmdd}) file patterns {missing} inside: {master_destination_path}"
        print(log_msg)
        email_body = f"Report Download Automation Update\n\nStatus: FAILED\nDetails: {log_msg}\nJob Parameters: {subject_module_info}"
        send_notification_email(email_settings, f"File Download Unsuccessful - {subject_module_info}", email_body, attachments=attachments_to_send)

    print(f"🧹 [Task {task_index} Cleanup] Resetting window states...")
    try:
        active_grid_win = app.top_window()
        close_btn = active_grid_win.child_window(title="Close", control_type="Button")
        if close_btn.exists(timeout=2):
            close_btn.click_input()
            time.sleep(1.0)
    except Exception:
        pass

    return True

def execute_report_download_form():
    print("\n--- Initializing Multi-Task Report Generation Pipeline ---")
    try:
        import sys
        if 'active_runtime_config' in sys.modules:
            config_data = sys.modules['active_runtime_config']
        else:
            from App import load_task_toggles
            config_data = load_task_toggles()

        email_settings = config_data.get("email_settings") or config_data.get("EMAIL_SETTINGS", None)
        active_process_name = os.environ.get("ACTIVE_TASK_ID", "process_01").strip().lower()
        
        task_profile = {}
        for k, v in config_data.items():
            if str(k).strip().lower() == active_process_name:
                task_profile = v
                break
        if not task_profile:
            task_profile = config_data

        if not task_profile:
            print("Warning: Specific task configurations missing from active runtime matrix.")
            return False

        global_config = task_profile
        run_download_flag = task_profile.get("run_report_download", task_profile.get("RUN_REPORT_DOWNLOAD", True))
        
        combined_tasks = []
        if run_download_flag:
            print("⚙️ run_report_download is True: Enqueueing download_task structure exclusively.")
            download_list = task_profile.get("download_task") or task_profile.get("TASKS", [])
            combined_tasks.extend(download_list)

        total_tasks = len(combined_tasks)
        print(f"Discovered total filtered task count profile logs: {total_tasks}")

        if total_tasks == 0:
            print("Warning: No active operational tasks enabled inside config matching current toggles.")
            return True

        app = Application(backend="uia").connect(title_re=".*Report Download.*", timeout=5)
        report_win = app.window(title_re=".*Report Download.*")
        report_win.set_focus()
        time.sleep(0.5)

        for index, single_task in enumerate(combined_tasks, start=1):
            process_single_report_task(app, report_win, single_task, index, total_tasks, email_settings, global_config)
            time.sleep(2.0)

        try:
            print("\n🌐 All tasks processed. Redirecting active tab to Home...")
            browser_app = Application(backend="uia").connect(title_re=".*Edge.*|.*Microsoft\u200b Edge.*", timeout=5)
            browser_win = browser_app.top_window()
            browser_win.set_focus()
            time.sleep(0.5)
            send_keys("^l")
            time.sleep(0.5)
            send_keys("http://cdslweb.cdslindia.com/RELIDCDASWEBCORE/Home{ENTER}", with_spaces=True)
            print("✓ Redirection completed successfully!")
            return True
        except Exception as browser_err:
            print(f"  Could not redirect browser session: {browser_err}")
            return False

    except FileNotFoundError as fnf:
        print(f"Setup Conflict Error: {fnf}")
    except Exception as err:
        import traceback
        print(f"\n[Master Processing Interrupt Failure]: {err}")
        traceback.print_exc()
        return False
    