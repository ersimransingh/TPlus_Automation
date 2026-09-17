import os
import time
import datetime
import win32con
import win32gui
import win32api
import win32clipboard
from pywinauto.keyboard import send_keys
from pywinauto import mouse

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def get_relative_rect(child_rect, parent_hwnd):
    p_rect = win32gui.GetWindowRect(parent_hwnd)
    return (
        child_rect[0] - p_rect[0],  
        child_rect[1] - p_rect[1],  
        child_rect[2] - p_rect[0],  
        child_rect[3] - p_rect[1]   
    )


def _normalize_to_dd_mm_yyyy(date_str):
    if not date_str:
        return date_str
    
    date_clean = date_str.strip()
    if len(date_clean) == 8 and date_clean.isdigit():
        year = date_clean[:4]
        month = date_clean[4:6]
        day = date_clean[6:]
        return f"{day}/{month}/{year}"
        
    date_clean = date_clean.replace("-", "/").replace(" ", "/")
    parts = date_clean.split("/")
    
    if len(parts) == 3:
        if len(parts[0]) == 4:
            year, month, day = parts[0], parts[1], parts[2]
            return f"{day}/{month}/{year}"
        elif len(parts[2]) == 4:
            return f"{parts[0]}/{parts[1]}/{parts[2]}"
        
    return date_clean


def _cfg_val(node, default_val=None):
    """
    Unwraps a JSON config node coming from Action.json.
    Supports both formats:
      "chkShowDetail": true
      "chkShowDetail": {"value": true, "control_type": "CheckBox", "post_delay": 1}
    """
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node if node is not None else default_val


def _cfg_delay(node, default=1):
    """Reads an optional post_delay from a wrapped config node."""
    if isinstance(node, dict) and "post_delay" in node:
        return node["post_delay"]
    return default


class SharePayoutPage:

    def __init__(self, app):
        self.app = app
        self.main_hwnd = win32gui.FindWindow("WindowsForms10.Window.8.app.0.141b42a_r7_ad1", "TradePlusX")
        if not self.main_hwnd:
            raise Exception("TradePlusX main window handle not found inside SharePayoutPage!")

    def _wait_and_handle_areyousure_dialog(self):
        print("  [DIALOG WAIT] Waiting up to 6s for 'Are You Sure?' dialog...")
        deadline = time.time() + 6.0

        while time.time() < deadline:
            found_dialog_hwnd = None
            found_yes_hwnd    = None

            def scan_top(hwnd, _):
                nonlocal found_dialog_hwnd, found_yes_hwnd
                try:
                    if not win32gui.IsWindowVisible(hwnd):
                        return True
                    if hwnd == self.main_hwnd:
                        return True

                    yes_h = None
                    no_h  = None

                    def scan_children(ch, _):
                        nonlocal yes_h, no_h
                        try:
                            ct = win32gui.GetWindowText(ch).strip()
                            cc = win32gui.GetClassName(ch)
                            if "button" in cc.lower() or cc == "Button":
                                if ct.lower() == "yes":
                                    yes_h = ch
                                if ct.lower() == "no":
                                    no_h = ch
                        except:
                            pass
                        return True

                    try:
                        win32gui.EnumChildWindows(hwnd, scan_children, None)
                    except:
                        pass

                    if yes_h and no_h:
                        found_dialog_hwnd = hwnd
                        found_yes_hwnd    = yes_h

                except:
                    pass
                return True

            win32gui.EnumWindows(scan_top, None)

            if found_dialog_hwnd and found_yes_hwnd:
                title = win32gui.GetWindowText(found_dialog_hwnd)
                print(f"  [DIALOG WAIT] Dialog found! hwnd={found_dialog_hwnd} title={title!r}")
                print(f"  [DIALOG WAIT] Yes button hwnd={found_yes_hwnd}")

                try:
                    win32gui.ShowWindow(found_dialog_hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(found_dialog_hwnd)
                    time.sleep(0.3)

                    rect = win32gui.GetWindowRect(found_yes_hwnd)
                    cx = (rect[0] + rect[2]) // 2
                    cy = (rect[1] + rect[3]) // 2
                    print(f"  [DIALOG WAIT] Clicking Yes at ({cx}, {cy})")
                    mouse.click(button='left', coords=(cx, cy))
                    time.sleep(1.0)
                    print("  [DIALOG WAIT] Dialog dismissed. Proceeding to Fetch.")
                    return True

                except Exception as e:
                    print(f"  [DIALOG WAIT] Click failed: {e}. Sending ENTER...")
                    send_keys("{ENTER}")
                    time.sleep(1.0)
                    return True

            time.sleep(0.1)

        print("  [DIALOG WAIT] No Yes/No dialog appeared within 6s. Continuing to Fetch.")
        return False

    def _set_checkbox(self, auto_id, name, desired_state):
        try:
            chk = self.window.child_window(auto_id=auto_id, control_type="CheckBox")
            chk.wait("visible", timeout=5)
            current = chk.get_toggle_state()  
            desired_int = 1 if desired_state else 0
            if current != desired_int:
                chk.click_input()
                time.sleep(0.2)
                print(f"  [CHECKBOX] '{name}' set to {'CHECKED' if desired_state else 'UNCHECKED'}")
            else:
                print(f"  [CHECKBOX] '{name}' already {'CHECKED' if desired_state else 'UNCHECKED'} — no change")
        except Exception as e:
            print(f"  [CHECKBOX] WARNING: Could not set '{name}' (auto_id={auto_id}): {e}")

    def process(self, raw_workflow_config=None, *args, **kwargs):
        """
        Dual-compatible entrypoint. 
        Accepts the new structured config dictionary OR standard historical fallback kwargs.
        """
        # If called the old way, kwargs will contain 'date_value', 'settlement_name', etc.
        if isinstance(raw_workflow_config, dict) and "Menu" not in raw_workflow_config:
            # It's the new update block passing a dict
            config = raw_workflow_config
        elif raw_workflow_config is None and kwargs:
            # It's the old wrapper orchestration script passing individual kwargs
            config = kwargs
        else:
            # Fallback if raw_workflow_config is the direct JSON block from the loop
            config = raw_workflow_config or {}

        # ── EXTRACTION WITH METADATA UNWRAPPING ──
        # Tries extracting from the new format layout; falls back to the old flat names if missing
        date_value = _cfg_val(config.get("dtMain", kwargs.get("date_value")))
        settlement_name = _cfg_val(config.get("dgvStlmnt", kwargs.get("settlement_name")))
        target_process_name = _cfg_val(config.get("target_process_name", kwargs.get("target_process_name")))
        
        show_detail_before_process = _cfg_val(config.get("chkShowDetail", kwargs.get("show_detail_before_process")))
        one_by_one_processing = _cfg_val(config.get("chk1By1", kwargs.get("one_by_one_processing")))
        pay_in = _cfg_val(config.get("chkPayIn", kwargs.get("pay_in")))
        pay_out = _cfg_val(config.get("chkPayOut", kwargs.get("pay_out")))

        # Delay mapping tracking
        date_delay = _cfg_delay(config.get("dtMain"), default=1.5)

        # Process normalization safely continues below...
        date_value = _normalize_to_dd_mm_yyyy(date_value)

        self.window = self.app.top_window()
        self.window.wait("ready", timeout=30)

        # ==========================
        # 0. CHECKBOX CONFIGURATION
        # ==========================
        print("Configuring checkboxes via AutomationId...")
        if show_detail_before_process is not None:
            self._set_checkbox("chkShowDetail", "Show Detail Before Process", bool(show_detail_before_process))
        if one_by_one_processing is not None:
            self._set_checkbox("chk1By1", "One by One Processing", bool(one_by_one_processing))
        if pay_in is not None:
            self._set_checkbox("chkPayIn", "Pay-In", bool(pay_in))
        if pay_out is not None:
            self._set_checkbox("chkPayOut", "Pay-Out", bool(pay_out))

        # ==========================
        # 1. DATE SELECTION
        # ==========================
        if date_value is not None:
            print(f"Setting Date value to: {date_value}")
            date_pane = self.window.child_window(auto_id="dtMain", control_type="Pane")
            date_pane.click_input(coords=(5, 10))
            time.sleep(0.5)
            send_keys("^a")
            time.sleep(0.3)
            send_keys("{BACKSPACE}")
            time.sleep(0.3)
            send_keys(date_value)
            time.sleep(0.3)
            send_keys("{ENTER}")
            print(f"Date Selected: {date_value}")
            time.sleep(date_delay)

        # ==========================
        # 2. SETTLEMENT SELECTION
        # ==========================
        if settlement_name is not None:
            print(f"Targeting Settlement Name: {settlement_name}")

            dots_button = self.window.child_window(title="...", auto_id="btnHelp", control_type="Button")
            dots_button.click_input()
            time.sleep(1.5)

            try:
                dropdown_table = self.window.child_window(title="DataGridView", auto_id="dgvStlmnt", control_type="Table")
                cells = dropdown_table.descendants(control_type="DataItem")
                prefix = str(settlement_name).strip()[:2].upper()
                target_cell = None
                for cell in cells:
                    cell_text = str(cell.window_text()).strip().upper()
                    if cell_text.startswith(prefix):
                        target_cell = cell
                        print(f"  Matched cell '{cell_text}' using prefix '{prefix}'")
                        break

                if target_cell:
                    target_cell.click_input()
                    time.sleep(0.5)
                    send_keys("{ENTER}")
                    print(f"Settlement prefix '{prefix}' confirmed with ENTER.")
                else:
                    raise Exception(f"No cell starting with '{prefix}' found in grid.")

            except Exception as e:
                print(f"Direct selection failed: {e}. Using coordinate fallback...")
                SETTLEMENT_Y_OFFSETS = {
                    "BM": 248,
                    "NM": 269,
                    "NQ": 290,
                    "NU": 311,
                    "NA": 332
                }
                prefix = str(settlement_name).strip()[:2].upper()
                if prefix in SETTLEMENT_Y_OFFSETS:
                    table_rect = self.window.child_window(title="DataGridView", auto_id="dgvStlmnt", control_type="Table").rectangle()
                    click_x = table_rect.left + 50
                    click_y = table_rect.top + (SETTLEMENT_Y_OFFSETS[prefix] - 202)
                    mouse.click(button='left', coords=(click_x, click_y))
                    time.sleep(0.5)
                    send_keys("{ENTER}")
                    print(f"Settlement prefix '{prefix}' confirmed via coordinate fallback.")
                else:
                    print(f"CRITICAL ERROR: prefix '{prefix}' not found in offset map.")

            self._wait_and_handle_areyousure_dialog()
            self.window = self.app.top_window()

        # ==========================================
        # 3. FETCH
        # ==========================================
        try:
            error_dialog = self.window.child_window(title="Information", control_type="Window")
            if error_dialog.exists(timeout=1):
                error_dialog.child_window(title="OK", control_type="Button").click_input()
                time.sleep(0.5)
        except:
            pass

        already_has_data = False
        try:
            grid = self.window.child_window(title="DataGridView", auto_id="dgvDemat", control_type="Table")
            if grid.exists(timeout=1):
                grid.set_focus()
                time.sleep(0.2)
                grid_rect = grid.rectangle()
                row_height    = 24
                header_height = 22
                col2_x = grid_rect.left + 250
                row1_y = grid_rect.top + header_height + (row_height // 2)
                mouse.click(button='left', coords=(col2_x, row1_y))
                time.sleep(0.3)
                try:
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.CloseClipboard()
                except:
                    pass
                time.sleep(0.05)
                send_keys("^c")
                time.sleep(0.25)
                sample_text = self.get_clipboard_text().strip()
                if sample_text:
                    print(f"  [DEMAT CHECK] Grid already has data ('{sample_text}'). Skipping Fetch.")
                    already_has_data = True
                else:
                    print("  [DEMAT CHECK] Grid blank. Running Fetch.")
        except Exception as check_err:
            print(f"  [DEMAT CHECK] {check_err}")

        if not already_has_data:
            print("Locating Fetch button...")
            time.sleep(0.8)
            fetch_clicked = False

            try:
                for target_id in ["cmdFetech", "cmdFetch"]:
                    if self.window.child_window(auto_id=target_id, control_type="Button").exists(timeout=0.5):
                        self.window.child_window(auto_id=target_id, control_type="Button").click_input()
                        print(f"  ✓ Fetch clicked via UIA id: {target_id}")
                        fetch_clicked = True
                        break
            except Exception as uia_err:
                print(f"  UIA bypassed: {uia_err}")

            if not fetch_clicked:
                children = []
                def enum_cb(hwnd, _):
                    try:
                        if win32gui.IsWindowVisible(hwnd):
                            title = win32gui.GetWindowText(hwnd).strip().lower()
                            if "fetch" in title or "fetech" in title:
                                children.append((hwnd, win32gui.GetWindowRect(hwnd)))
                    except:
                        pass
                    return True
                win32gui.EnumChildWindows(self.window.handle, enum_cb, None)
                if not children:
                    win32gui.EnumChildWindows(self.main_hwnd, enum_cb, None)
                if children:
                    fetch_rect = children[0][1]
                    cx = (fetch_rect[0] + fetch_rect[2]) // 2
                    cy = (fetch_rect[1] + fetch_rect[3]) // 2
                    win32gui.SetForegroundWindow(self.main_hwnd)
                    time.sleep(0.2)
                    mouse.click(button='left', coords=(cx, cy))
                    print(f"  ✓ Fetch clicked via Win32 at ({cx}, {cy})")
                    fetch_clicked = True

            if not fetch_clicked:
                win_rect = self.window.rectangle()
                fallback_x = win_rect.left + 680
                fallback_y = win_rect.top + 150
                win32gui.SetForegroundWindow(self.main_hwnd)
                time.sleep(0.1)
                mouse.click(button='left', coords=(fallback_x, fallback_y))
                print(f"  ✓ Fetch clicked via coordinate fallback ({fallback_x}, {fallback_y})")
                fetch_clicked = True

            if not fetch_clicked:
                raise Exception("CRITICAL: All Fetch strategies failed!")

            print("  Waiting for data grid...")
            time.sleep(8)
        else:
            time.sleep(1.0)

        # ==========================
        # 4. CLICK TARGET PROCESS
        # ==========================
        if target_process_name:
            self.click_process_by_live_clipboard_scan(target_process_name)

        # ==========================
        # 5. CLOSE WINDOW
        # ==========================
        print("Finishing workflow...")
        self.close_window()

    def get_clipboard_text(self):
        try:
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return str(data)
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
            return ""

    def _handle_post_process_confirmation_screens(self):
        print("Checking for intermediate Demat confirmation views...")
        time.sleep(1.5)

        confirm_hwnd = None
        def find_confirm_window(hwnd, _):
            nonlocal confirm_hwnd
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).lower()
                    if "demat processes" in title or "pay-in" in title or "processes" in title:
                        if hwnd != self.main_hwnd:
                            confirm_hwnd = hwnd
            except: pass
            return True

        win32gui.EnumWindows(find_confirm_window, None)

        if confirm_hwnd:
            print(f"  [CONFIRMATION SCREEN] Identified active validation layout frame: handle={confirm_hwnd}")
            
            continue_btn_rect = None
            children = []
            def enum_children(hwnd, _):
                try:
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd).strip()
                        cls = win32gui.GetClassName(hwnd).lower()
                        if "continue" in title.lower() and "button" in cls:
                            children.append(win32gui.GetWindowRect(hwnd))
                except: pass
                return True

            win32gui.EnumChildWindows(confirm_hwnd, enum_children, None)

            if children:
                continue_btn_rect = children[0]
                cx = (continue_btn_rect[0] + continue_btn_rect[2]) // 2
                cy = (continue_btn_rect[1] + continue_btn_rect[3]) // 2
                print(f"    ✓ Target 'Continue' button isolated at ({cx}, {cy}). Clicking...")
                mouse.click(button='left', coords=(cx, cy))
            else:
                print("    WARNING: 'Continue' button text node obscured. Delivering standard safety {ENTER} sequence...")
                win32gui.SetForegroundWindow(confirm_hwnd)
                time.sleep(0.1)
                send_keys("{ENTER}")

            print("    Waiting for filename dialog to surface after Continue...")
            time.sleep(2.5)

            self._screenshot_and_dismiss_filename_dialog()

        popup_hwnd = None
        for lookup_attempt in range(25):
            def find_info_box(hwnd, _):
                nonlocal popup_hwnd
                try:
                    if win32gui.IsWindowVisible(hwnd):
                        cls = win32gui.GetClassName(hwnd)
                        title = win32gui.GetWindowText(hwnd).lower()
                        if "#32770" in cls or "information" in title or not title:
                            if hwnd != self.main_hwnd:
                                popup_hwnd = hwnd
                except: pass
                return True

            win32gui.EnumWindows(find_info_box, None)
            if popup_hwnd:
                break
            time.sleep(0.2)

        if popup_hwnd:
            print(f"  [ALERT INTERCEPT] Report generation popup captured: handle={popup_hwnd}. Clearing via direct Win32 message loop...")
            try:
                win32gui.ShowWindow(popup_hwnd, win32con.SW_RESTORE)
                time.sleep(0.1)
                win32gui.SetForegroundWindow(popup_hwnd)
                win32gui.SetActiveWindow(popup_hwnd)
                time.sleep(0.2)

                send_keys("{ENTER}")
                time.sleep(0.3)

                if win32gui.IsWindow(popup_hwnd) and win32gui.IsWindowVisible(popup_hwnd):
                    print("    ⚠ Dialog still present. Dispatching hardware virtual key message hooks...")
                    win32api.PostMessage(popup_hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
                    time.sleep(0.1)
                    win32api.PostMessage(popup_hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
                
                print("    ✓ Confirmation modal dismissed successfully.")
                time.sleep(1.0)
            except Exception as pe:
                print(f"    Fallback click routing trace exception error: {pe}. Retrying via safety keystroke sequence...")
                send_keys("{ENTER}")
        else:
            print("  ⚠ Notice: Post-process Information dialog popup window did not arrive or was bypassed.")

    def click_process_by_live_clipboard_scan(self, target_name):
        print(f"Scanning for target: '{target_name}'...")
        grid = self.window.child_window(title="DataGridView", auto_id="dgvDemat", control_type="Table")
        grid.set_focus()
        time.sleep(0.5)

        grid_rect = grid.rectangle()
        row_height    = 24
        header_height = 22
        col2_x = grid_rect.left + 250
        col1_x = grid_rect.left + 35
        row1_y = grid_rect.top + header_height + (row_height // 2)

        mouse.click(button='left', coords=(col2_x, row1_y))
        time.sleep(0.5)

        found_row_idx = None
        for row_idx in range(100):
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.CloseClipboard()
            except:
                pass
            time.sleep(0.05)
            send_keys("^c")
            time.sleep(0.25)
            cell_text = self.get_clipboard_text().strip()
            print(f"  Row {row_idx}: '{cell_text}'")
            if target_name.lower() in cell_text.lower():
                print(f"  ✓ Found '{target_name}' at row {row_idx}")
                found_row_idx = row_idx
                break
            send_keys("{DOWN}")
            time.sleep(0.1)

        if found_row_idx is None:
            print(f"CRITICAL ERROR: '{target_name}' not found.")
            return

        grid_height  = grid_rect.bottom - grid_rect.top
        visible_rows = (grid_height - header_height) // row_height
        visual_offset = found_row_idx if found_row_idx < visible_rows else visible_rows - 1

        click_y = grid_rect.top + header_height + (visual_offset * row_height) + (row_height // 2)
        mouse.click(button='left', coords=(int(col1_x), int(click_y)))
        print(f"  Process button clicked at ({col1_x}, {click_y})")
        self._handle_post_process_confirmation_screens()
        
        print("  [MONITOR] Action confirmed. Tracking RichEdit console text outputs...")
        
        p_hwnd = self._get_demat_win_hwnd()
        
        console_rect = None
        def scan_for_richedit(hwnd, _):
            nonlocal console_rect
            try:
                cls = win32gui.GetClassName(hwnd)
                if "richedit" in cls.lower():
                    console_rect = win32gui.GetWindowRect(hwnd)
            except:
                pass
            return True
            
        win32gui.EnumChildWindows(p_hwnd, scan_for_richedit, None)
        
        if console_rect:
            console_x = (console_rect[0] + console_rect[2]) // 2
            console_y = (console_rect[1] + console_rect[3]) // 2
            print(f"  [MONITOR] Console isolated structurally at absolute monitor screen: ({console_x}, {console_y})")
        else:
            p_rect = win32gui.GetWindowRect(p_hwnd)
            console_x = p_rect[0] + 950  
            console_y = p_rect[1] + 350
            print("  [MONITOR] Warning: RichEdit class trace obscured. Using sub-window relative bounds mapping.")
        
        print("  [MONITOR] Entering dynamic execution tracking loop...")
        while True:
            try:
                mouse.click(button='left', coords=(console_x, console_y))
                time.sleep(0.2)
                
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.CloseClipboard()
                time.sleep(0.05)
                
                send_keys("^a")
                time.sleep(0.15)
                send_keys("^c")
                time.sleep(0.3)
                
                captured_logs = self.get_clipboard_text().lower()
                
                if "process completed" in captured_logs:
                    print("  [MONITOR] ✓ 'Process Completed' phrase tracked in execution console. Continuing workflow.")
                    break
            except Exception as loop_err:
                print(f"  [MONITOR] Log sweep skipped context: {loop_err}")
                
            time.sleep(4.0)  
            
    def _get_demat_win_hwnd(self):
        for attempt in range(10):
            result = []
            def cb(hwnd, _):
                try:
                    title = win32gui.GetWindowText(hwnd)
                    if "share pay-in" in title.lower() or "pay-out processes" in title.lower():
                        result.append(hwnd)
                except:
                    pass
                return True
            win32gui.EnumChildWindows(self.main_hwnd, cb, None)
            if result and win32gui.IsWindowVisible(result[0]):
                return result[0]
            time.sleep(0.5)
        raise Exception("Demat Processes window not found!")
    
    def handle_special_settlement_popup(self, cc_hwnd, date_value):
        time.sleep(0.5)  
        popup_hwnd = None
        for wait_step in range(6):
            time.sleep(0.1)
            def find_settlement_box(hwnd, _):
                nonlocal popup_hwnd
                try:
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd).lower()
                        if "settlement" in title or "create" in title:
                            if hwnd != self.main_hwnd:
                                popup_hwnd = hwnd
                except: pass
                return True
            win32gui.EnumWindows(find_settlement_box, None)
            if popup_hwnd:
                break

        if popup_hwnd:
            print("  [SETTLEMENT ALERT] 'Create Settlement' dialog discovered. Dismissing with ENTER...")
            win32gui.SetForegroundWindow(popup_hwnd)
            time.sleep(0.3)
            send_keys("{ENTER}")
            time.sleep(0.5)
            try:
                win32gui.SetForegroundWindow(self.main_hwnd)
                time.sleep(0.3)
            except:
                pass
            return True
        return False

    def _screenshot_and_dismiss_filename_dialog(self):
        print("  [FILENAME DIALOG] Waiting for filename dialog after Continue...")

        SCREENSHOT_DIR = r"D:\TradePlus_Automation\Capture_Data"
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        dialog_hwnd = None
        ok_btn_hwnd = None
        deadline = time.time() + 10.0

        while time.time() < deadline:
            found = []

            def _scan(hwnd, _):
                try:
                    if not win32gui.IsWindowVisible(hwnd):
                        return True
                    if hwnd == self.main_hwnd:
                        return True
                    cls   = win32gui.GetClassName(hwnd)
                    title = win32gui.GetWindowText(hwnd).lower().strip()
                    if "#32770" in cls or "information" in title or "report" in title or "file" in title:
                        ok_h = []
                        def _child(ch, _):
                            try:
                                ct = win32gui.GetWindowText(ch).strip().lower()
                                cc = win32gui.GetClassName(ch).lower()
                                if (ct in ("ok", "yes", "&ok")) and "button" in cc:
                                    ok_h.append(ch)
                            except:
                                pass
                            return True
                        try:
                            win32gui.EnumChildWindows(hwnd, _child, None)
                        except:
                            pass
                        if ok_h:
                            found.append((hwnd, ok_h[0]))
                except:
                    pass
                return True

            win32gui.EnumWindows(_scan, None)

            if found:
                dialog_hwnd, ok_btn_hwnd = found[0]
                break

            time.sleep(0.2)

        if not dialog_hwnd:
            print("  [FILENAME DIALOG] No filename dialog appeared within 10s. Continuing.")
            return

        dialog_title = win32gui.GetWindowText(dialog_hwnd)
        print(f"  [FILENAME DIALOG] Dialog found: hwnd={dialog_hwnd}  title={dialog_title!r}")

        dialog_texts = []
        def _read_text(ch, _):
            try:
                t = win32gui.GetWindowText(ch).strip()
                if t and t.lower() not in ("ok", "yes", "&ok", "cancel", "no"):
                    dialog_texts.append(t)
            except:
                pass
            return True
        try:
            win32gui.EnumChildWindows(dialog_hwnd, _read_text, None)
        except:
            pass
        if dialog_title:
            dialog_texts.insert(0, dialog_title)
        filename_hint = " | ".join(dialog_texts) if dialog_texts else "dialog"
        print(f"  [FILENAME DIALOG] Dialog content: {filename_hint!r}")

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_hint = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename_hint[:60])
        ss_filename = f"FilenameDialog_{ts}_{safe_hint}.png"
        ss_path = os.path.join(SCREENSHOT_DIR, ss_filename)

        try:
            win32gui.ShowWindow(dialog_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(dialog_hwnd)
            time.sleep(0.4)

            if PYAUTOGUI_AVAILABLE:
                import pyautogui
                screenshot = pyautogui.screenshot()
                screenshot.save(ss_path)
                print(f"  [FILENAME DIALOG] Screenshot saved (pyautogui): {ss_path}")
            elif PIL_AVAILABLE:
                from PIL import ImageGrab
                screenshot = ImageGrab.grab()
                screenshot.save(ss_path)
                print(f"  [FILENAME DIALOG] Screenshot saved (PIL): {ss_path}")
            else:
                print("  [FILENAME DIALOG] WARNING: No screenshot library available. Install pyautogui or Pillow.")
        except Exception as ss_err:
            print(f"  [FILENAME DIALOG] Screenshot failed: {ss_err}")

        print(f"  [FILENAME DIALOG] Clicking OK (hwnd={ok_btn_hwnd})...")
        try:
            rect = win32gui.GetWindowRect(ok_btn_hwnd)
            cx = (rect[0] + rect[2]) // 2
            cy = (rect[1] + rect[3]) // 2
            mouse.click(button='left', coords=(cx, cy))
            time.sleep(0.5)
            print("  [FILENAME DIALOG] OK clicked. Dialog dismissed.")
        except Exception as ok_err:
            print(f"  [FILENAME DIALOG] OK click failed: {ok_err}. Sending ENTER...")
            win32gui.SetForegroundWindow(dialog_hwnd)
            time.sleep(0.2)
            send_keys("{ENTER}")
            time.sleep(0.5)

        try:
            win32gui.SetForegroundWindow(self.main_hwnd)
        except:
            pass
        time.sleep(0.5)

    def close_window(self):
        print("Closing Demat Processes window...")
        try:
            hwnd = self._get_demat_win_hwnd()
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(1.0)
            print("  Closed ✓")
        except Exception as e:
            print(f"  ⚠ Failed to close: {e}")