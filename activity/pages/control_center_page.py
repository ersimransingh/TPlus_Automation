import time
import win32gui
import win32con
import win32api
import win32clipboard
import re
import ctypes
import ctypes.wintypes
from pywinauto import mouse
from pywinauto.keyboard import send_keys

TRADEPLUS_CLASS = "WindowsForms10.Window.8.app.0.141b42a_r7_ad1"
BUTTON_CLASS    = "WindowsForms10.BUTTON.app.0.141b42a_r7_ad1"
COMBO_CLASS     = "WindowsForms10.COMBOBOX.app.0.141b42a_r7_ad1"
DATETIME_CLASS  = "WindowsForms10.SysDateTimePick32.app.0.141b42a_r7_ad1"


def click_center(rect):
    x = (rect[0] + rect[2]) // 2
    y = (rect[1] + rect[3]) // 2
    mouse.click(button='left', coords=(x, y))
    time.sleep(0.5)


def get_all_children(parent_hwnd):
    children = []
    def cb(hwnd, _):
        try:
            children.append((
                hwnd,
                win32gui.GetClassName(hwnd),
                win32gui.GetWindowText(hwnd),
                win32gui.GetWindowRect(hwnd),
                win32gui.IsWindowVisible(hwnd)
            ))
        except:
            pass
        return True
    win32gui.EnumChildWindows(parent_hwnd, cb, None)
    return children


def is_checked(hwnd):
    result = win32api.SendMessage(hwnd, win32con.BM_GETCHECK, 0, 0)
    return result == win32con.BST_CHECKED


def _strip_date_from_filename(filename):
    return re.sub(r'_\d{8}_', '_', filename)


def _filename_matches(config_fn, grid_fn):
    config_lower = config_fn.lower().strip()
    grid_lower   = grid_fn.lower().strip()

    if config_lower in grid_lower or grid_lower in config_lower:
        return True

    config_stripped = _strip_date_from_filename(config_lower)
    grid_stripped   = _strip_date_from_filename(grid_lower)

    if config_stripped in grid_stripped or grid_stripped in config_stripped:
        return True

    date_re = re.compile(r'^\d{8}$')

    def get_non_date_parts(fn):
        stem = fn.rsplit('.', 1)[0]
        parts = stem.split('_')
        return [p for p in parts if not date_re.match(p)]

    config_parts = get_non_date_parts(config_lower)
    grid_parts   = get_non_date_parts(grid_lower)

    if config_parts and grid_parts:
        return config_parts == grid_parts

    return False

def _cfg_val(node, default_val=None):
    """
    Unwraps a JSON config node coming from Action.json.
    Supports both formats:
      "cmbProduct": "Equity"
      "cmbProduct": {"value": "Equity", "control_type": "ComboBox", "post_delay": 1}
    """
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node if node is not None else default_val


def _cfg_delay(node, default=1):
    """Reads an optional post_delay from a wrapped config node."""
    if isinstance(node, dict) and "post_delay" in node:
        return node["post_delay"]
    return default


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


class ControlCenterPage:

    def __init__(self, app):
        self.app = app
        self.main_hwnd = win32gui.FindWindow(TRADEPLUS_CLASS, "TradePlusX")
        if not self.main_hwnd:
            raise Exception("TradePlusX main window not found!")

    def _get_control_center_hwnd(self):
        max_attempts = 600
        print("Waiting for Control Center window to initialize and render (Timeout: 10 min)...")

        for attempt in range(max_attempts):
            result = []
            def cb(hwnd, _):
                try:
                    title = win32gui.GetWindowText(hwnd)
                    if "control" in title.lower() and "center" in title.lower():
                        result.append((hwnd, title))
                except:
                    pass
                return True
            win32gui.EnumChildWindows(self.main_hwnd, cb, None)

            for hwnd, title in result:
                if win32gui.IsWindowVisible(hwnd):
                    print(f"  ✓ Control Center window located on attempt {attempt+1}: handle={hwnd}")
                    return hwnd
            time.sleep(0.2)

        raise Exception("Control Center window failed to load within 10-minute timeout!")

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

    def dismiss_center_msgbox(self, cc_hwnd, date_value):
        if date_value:
            date_value = _normalize_to_dd_mm_yyyy(date_value)
        
        if self.handle_special_settlement_popup(cc_hwnd, date_value):
            return "RESTART"
            
        time.sleep(0.4)  
        popup_hwnd = None

        def find_box(hwnd, _):
            nonlocal popup_hwnd
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).lower()
                    cls   = win32gui.GetClassName(hwnd)
                    if ("are you sure" in title or "information" in title or "#32770" in cls or "windowsforms" in cls.lower()):
                        if hwnd != self.main_hwnd:
                            popup_hwnd = hwnd
            except:
                pass
            return True

        win32gui.EnumWindows(find_box, None)

        if popup_hwnd:
            print("  [ALERT INTERCEPT] Modal target dialog identified. Extracting text strings...")
            try:
                win32gui.SetForegroundWindow(popup_hwnd)
                time.sleep(0.3)
            except:
                pass

            dialog_children = get_all_children(popup_hwnd)
            dialog_text_combined = ""
            
            for hwnd, cls, title, rect, vis in dialog_children:
                if title.strip():
                    dialog_text_combined += " " + title.lower().strip()

            print(f"  [ALERT INTERCEPT] Inspected Text Content: {dialog_text_combined!r}")

            # ── CRITICAL: PRESERVED MISMATCH DETECTION LOGIC ──
            if "mis match found" in dialog_text_combined:
                print("\n[CRITICAL STOP] Mismatch flag triggered inside dialog text panel.")
                raise Exception("Pipeline stopped: 'mis match found' string discovered in popup message box.")
            
            elif "mis match not found" in dialog_text_combined:
                print("  ✓ Verification matched: 'mis match not found' confirmed. Proceeding with clearing the box...")
            
            elif "mis match" in dialog_text_combined:
                print("\n[CRITICAL STOP] Undefined status rule trace context matched.")
                raise Exception("Pipeline stopped: Dialog contains an ambiguous mismatch notification state.")

            # ── DYNAMIC BUTTON READING (NO HARDCODED TERMS) ──
            target_btn_hwnd = None
            target_btn_rect = None

            for hwnd, cls, title, rect, vis in dialog_children:
                # Read the actual controls inside the dialog box pop-up dynamically
                if vis and "button" in cls.lower():
                    # Automatically select the button control found inside the dialog box
                    target_btn_hwnd = hwnd
                    target_btn_rect = rect
                    print(f"    ✓ Dynamically read button control from pop-up: Class='{cls}', Title='{title}'")
                    break

            if target_btn_rect:
                # Click the button control read dynamically from the layout
                click_center(target_btn_rect)
            else:
                print("  WARNING: No button controls found inside the pop-up. Delivering hardware ENTER fallback...")
                send_keys("{ENTER}")
            time.sleep(0.5)
            
        return "SUCCESS"

    def get_clipboard_text(self):
        try:
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return str(data).strip()
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
            return ""

    def _clear_clipboard(self):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.CloseClipboard()
        except:
            pass
        time.sleep(0.1)

    def _close_report_popup(self):
        BM_CLICK = 0x00F5
        REPORT_TITLE_KEYWORDS = [
            "file import report", "obligation", "comparison", "money sheet",
            "reconciliation", "mismatch", "accumulation", "bill reconcil"
        ]

        report_hwnd = None
        def _find_report(hwnd, _):
            nonlocal report_hwnd
            try:
                if hwnd == self.main_hwnd:
                    return True
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).lower()
                    if any(kw in title for kw in REPORT_TITLE_KEYWORDS):
                        report_hwnd = hwnd
            except:
                pass
            return True

        win32gui.EnumWindows(_find_report, None)

        if not report_hwnd:
            return  

        print(f"  [REPORT POPUP] Found: '{win32gui.GetWindowText(report_hwnd)}' handle={report_hwnd}")
        time.sleep(0.5)

        close_btn_hwnd = None
        close_btn_rect = None

        def _find_close_btn(hwnd, _):
            nonlocal close_btn_hwnd, close_btn_rect
            try:
                raw_title = win32gui.GetWindowText(hwnd).strip()
                clean = raw_title.replace("&", "").lower()
                cls   = win32gui.GetClassName(hwnd)
                if clean == "close" and "button" in cls.lower():
                    rect = win32gui.GetWindowRect(hwnd)
                    if close_btn_rect is None or rect[0] > close_btn_rect[0]:
                        close_btn_hwnd = hwnd
                        close_btn_rect = rect
            except:
                pass
            return True

        try:
            win32gui.EnumChildWindows(report_hwnd, _find_close_btn, None)
        except:
            pass

        try:
            win32gui.SetForegroundWindow(report_hwnd)
            time.sleep(0.3)
        except:
            pass

        if close_btn_hwnd:
            try:
                win32api.SendMessage(close_btn_hwnd, BM_CLICK, 0, 0)
                time.sleep(0.5)
            except Exception as e:
                print(f"  [REPORT POPUP] BM_CLICK error: {e}")

            if win32gui.IsWindow(report_hwnd) and win32gui.IsWindowVisible(report_hwnd):
                cx = (close_btn_rect[0] + close_btn_rect[2]) // 2
                cy = (close_btn_rect[1] + close_btn_rect[3]) // 2
                mouse.click(button='left', coords=(cx, cy))
                time.sleep(0.5)
        else:
            try:
                win32api.PostMessage(report_hwnd, win32con.WM_CLOSE, 0, 0)
                time.sleep(0.5)
            except Exception as e:
                print(f"  [REPORT POPUP] WM_CLOSE error: {e}")

        cc_hwnd_refocus = None
        def _find_cc(hwnd, _):
            nonlocal cc_hwnd_refocus
            try:
                if win32gui.IsWindowVisible(hwnd) and "control center" in win32gui.GetWindowText(hwnd).lower():
                    cc_hwnd_refocus = hwnd
            except:
                pass
            return True

        try:
            win32gui.EnumChildWindows(self.main_hwnd, _find_cc, None)
        except:
            pass

        if cc_hwnd_refocus:
            try:
                win32gui.ShowWindow(cc_hwnd_refocus, win32con.SW_SHOW)
                win32gui.SetForegroundWindow(cc_hwnd_refocus)
                time.sleep(0.4)
            except:
                pass

    def scan_and_process_data_grid(self, cc_hwnd, files_workflow_config, date_value, current_segment=None, grid_id="dgvFileImp"):
        if not files_workflow_config:
            return "SUCCESS"

        print("\nStarting File Imports grid scan...")
        time.sleep(1.0)

        cc_win = self.app.window(handle=cc_hwnd)
        grid = cc_win.child_window(auto_id=grid_id, control_type="Pane")
        grid.wait("visible", timeout=10)
        grid.set_focus()
        time.sleep(0.3)

        grid_rect  = win32gui.GetWindowRect(grid.handle)
        HEADER_H   = 25
        ROW_H      = 20
        FILENAME_X = grid_rect[0] + 450

        def click_filename_cell(row_idx):
            y = grid_rect[1] + HEADER_H + (row_idx * ROW_H) + (ROW_H // 2)
            mouse.click(button='left', coords=(FILENAME_X, y))
            time.sleep(0.5)

        MAX_ROWS = 12
        previous_key = None
        consecutive_skipped_duplicates = 0

        for row_idx in range(MAX_ROWS):
            click_filename_cell(row_idx)

            self._clear_clipboard()
            send_keys("^c")
            time.sleep(0.4)

            current_row_filename = self.get_clipboard_text()
            if not current_row_filename:
                break

            send_keys("{LEFT}")
            time.sleep(0.2)
            
            self._clear_clipboard()
            send_keys("^c")
            time.sleep(0.4)
            row_description = self.get_clipboard_text().strip()

            send_keys("{RIGHT}")
            time.sleep(0.2)

            seg_prefix = current_segment if current_segment else "BSE"
            combined_table_key = f"{seg_prefix}_Cash_{row_description}"

            if combined_table_key == previous_key:
                consecutive_skipped_duplicates += 1
                if consecutive_skipped_duplicates >= 2:
                    break
            else:
                consecutive_skipped_duplicates = 0

            previous_key = combined_table_key

            match_found = False
            target_enabled = False
            for config_key, enabled_status in files_workflow_config.items():
                if config_key.strip().lower() == combined_table_key.lower():
                    match_found = True
                    target_enabled = enabled_status
                    break

            if not match_found or not target_enabled:
                time.sleep(0.3)
                continue

            time.sleep(0.3)
            send_keys("{RIGHT}{DOWN}{HOME}")
            time.sleep(0.4)

            is_already_success = False
            all_app_children = get_all_children(self.main_hwnd)
            for hwnd, cls, title, rect, vis in all_app_children:
                if vis and ("success" in title.lower() or "imported successfully" in title.lower()):
                    is_already_success = True
                    break

            if is_already_success:
                send_keys("{ESCAPE}")
                time.sleep(0.3)
                continue

            send_keys("{DOWN}")
            time.sleep(0.3)
            send_keys("{ENTER}")
            time.sleep(7.5)

            msg_status = self.dismiss_center_msgbox(cc_hwnd, date_value)
            if msg_status == "RESTART":
                return "RESTART"

            self._close_report_popup()
            time.sleep(0.8)

            try:
                win32gui.SetForegroundWindow(cc_hwnd)
                time.sleep(0.4)
            except:
                pass

        return "SUCCESS"
    
    def process_processes_grid_selection(self, cc_hwnd, target_settlement, grid_id="dgvBillProcess", proceed_id="btnProcessProceed", status_grid_id="dgvBillStatus"):
        if not target_settlement:
            return

        target_clean = target_settlement.strip()[:2].lower()
        time.sleep(3.5)

        try:
            win32gui.ShowWindow(self.main_hwnd, win32con.SW_SHOWMAXIMIZED)
            win32gui.SetForegroundWindow(self.main_hwnd)
            time.sleep(0.8)
        except: pass

        cc_win = self.app.window(handle=cc_hwnd)
        grid = cc_win.child_window(auto_id=grid_id, control_type="Pane")
        grid.wait("visible", timeout=10)
        time.sleep(0.3)

        grid_rect    = win32gui.GetWindowRect(grid.handle)
        HEADER_H     = 22
        ROW_H        = 28
        SETTLEMENT_X = grid_rect[0] + 100

        def row_centre_y(row_idx):
            return grid_rect[1] + HEADER_H + (row_idx * ROW_H) + (ROW_H // 2)

        anchor_y = row_centre_y(0)
        mouse.click(button='left', coords=(SETTLEMENT_X, anchor_y))
        time.sleep(1.5)

        MAX_ROWS     = 20
        matched_rows = []

        for row_idx in range(MAX_ROWS):
            current_y = row_centre_y(row_idx)
            self._clear_clipboard()
            send_keys("^c")
            time.sleep(0.5)

            cell_text = self.get_clipboard_text().lower().strip()
            if not cell_text:
                break

            if cell_text[:2] == target_clean:
                matched_rows.append((row_idx, current_y))

            send_keys("{DOWN}")
            time.sleep(0.3)

        if not matched_rows:
            return

        for row_idx, scan_y in matched_rows:
            mouse.click(button='left', coords=(SETTLEMENT_X, scan_y))
            time.sleep(0.6)

            self._clear_clipboard()
            send_keys("^c")
            time.sleep(0.4)
            confirmed = self.get_clipboard_text().lower().strip()

            if confirmed[:2] != target_clean:
                continue

            checkbox_toggled = False
            try:
                send_keys("{HOME}{SPACE}")
                time.sleep(0.5)
                checkbox_toggled = True
            except: pass

            if not checkbox_toggled:
                mouse.click(button='left', coords=(SETTLEMENT_X, scan_y))
                time.sleep(0.4)
                for x_offset in [15, 20, 10, 25, 30]:
                    test_checkbox_x = grid_rect[0] + x_offset
                    mouse.click(button='left', coords=(test_checkbox_x, scan_y))
                    time.sleep(0.4)
                    try:
                        mouse.click(button='left', coords=(SETTLEMENT_X, scan_y))
                        time.sleep(0.3)
                        self._clear_clipboard()
                        send_keys("^c")
                        time.sleep(0.3)
                        if self.get_clipboard_text().lower().strip()[:2] == target_clean:
                            break
                    except: pass

        print("Clicking Proceed inside Processes Grid mapping...")
        btn = cc_win.child_window(auto_id=proceed_id, control_type="Button")
        btn.wait("visible enabled", timeout=10)
        btn.click_input()
        time.sleep(2.0)

        self._close_report_popup()
        time.sleep(1.5)

        try:
            cc_win = self.app.window(handle=cc_hwnd)
            cc_win.wait("visible", timeout=10)
            win32gui.SetForegroundWindow(cc_hwnd)
            time.sleep(1.0)
        except: pass

        try:
            status_table = cc_win.child_window(auto_id=status_grid_id, control_type="Table")
            status_table.wait("visible", timeout=20)
        except:
            try:
                status_table = cc_win.child_window(auto_id=status_grid_id, control_type="Pane")
                status_table.wait("visible", timeout=20)
            except:
                self.dismiss_center_msgbox(cc_hwnd, date_value=None)
                self._close_report_popup()
                return

        status_rect = win32gui.GetWindowRect(status_table.handle)
        console_x = (status_rect[0] + status_rect[2]) // 2
        console_y = (status_rect[1] + status_rect[3]) // 2

        completion_keyword = "process completed"
        while True:
            try:
                mouse.click(button='left', coords=(console_x, console_y))
                time.sleep(0.3)
                self._clear_clipboard()
                send_keys("^a^c")
                time.sleep(0.4)

                if completion_keyword in self.get_clipboard_text().lower():
                    break
            except: pass
            time.sleep(5.0)

        self.dismiss_center_msgbox(cc_hwnd, date_value=None)
        self._close_report_popup()

    def set_control_center_date(self, cc_hwnd, date_value, date_id="dtMain"):
        date_value = _normalize_to_dd_mm_yyyy(date_value)
        
        cc_win = self.app.window(handle=cc_hwnd)
        date_ctrl = cc_win.child_window(auto_id=date_id, control_type="Pane")
        date_ctrl.wait("visible", timeout=10)
        date_hwnd = date_ctrl.handle
        date_rect  = win32gui.GetWindowRect(date_hwnd)

        clean_date = date_value.replace(" ", "/")
        parts = clean_date.split("/")
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        
        st_bytes = ctypes.create_string_buffer(16)
        ctypes.memmove(st_bytes,
            ctypes.c_uint16(year).value.to_bytes(2,'little') +
            ctypes.c_uint16(month).value.to_bytes(2,'little') +
            ctypes.c_uint16(0).value.to_bytes(2,'little') +
            ctypes.c_uint16(day).value.to_bytes(2,'little') +
            b'\x00' * 8, 16)
            
        pid = ctypes.wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(date_hwnd, ctypes.byref(pid))
        hProc = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)
        try:
            remote_mem = ctypes.windll.kernel32.VirtualAllocEx(hProc, None, 16, 0x3000, 0x04)
            try:
                ctypes.windll.kernel32.WriteProcessMemory(hProc, remote_mem, st_bytes, 16, None)
                click_center(date_rect)
                time.sleep(0.3)
                ctypes.windll.user32.SendMessageW(date_hwnd, 0x1002, 0, remote_mem)
                time.sleep(0.5)
                send_keys("{RIGHT}{UP}{DOWN}{ENTER}")
                time.sleep(0.5)
            finally:
                ctypes.windll.kernel32.VirtualFreeEx(hProc, remote_mem, 0, 0x8000)
        finally:
            ctypes.windll.kernel32.CloseHandle(hProc)

    def click_proceed_button(self, cc_hwnd, btn_id="btnProceed"):
        cc_win = self.app.window(handle=cc_hwnd)
        btn = cc_win.child_window(auto_id=btn_id, control_type="Button")
        btn.wait("visible enabled", timeout=10)
        btn.click_input()
        time.sleep(1.0)

    def click_processes_button(self, cc_hwnd, btn_id="btnOthers", combo_id="cmbProcProduct"):
        cc_win = self.app.window(handle=cc_hwnd)
        btn = cc_win.child_window(auto_id=btn_id, control_type="Button")
        btn.wait("visible enabled", timeout=10)
        btn.click_input()
        cc_win.child_window(auto_id=combo_id, control_type="ComboBox").wait("visible", timeout=15)
        time.sleep(0.5)

    def set_product_selection(self, cc_hwnd, product_name, combo_id="cmbProcProduct"):
        normalized_name = product_name.strip().capitalize()
        cc_win = self.app.window(handle=cc_hwnd)
        combo = cc_win.child_window(auto_id=combo_id, control_type="ComboBox")
        combo.wait("visible enabled", timeout=10)
        combo.click_input()
        time.sleep(0.4)
        send_keys("{HOME}")
        time.sleep(0.3)
        if normalized_name == "Commodity":
            send_keys("{DOWN}")
            time.sleep(0.2)
        send_keys("{ENTER}")
        time.sleep(0.8)

    def set_process_for_date(self, cc_hwnd, for_date_value, date_id="dtProcess"):
        for_date_value = _normalize_to_dd_mm_yyyy(for_date_value)
        cc_win = self.app.window(handle=cc_hwnd)
        date_ctrl = cc_win.child_window(auto_id=date_id, control_type="Pane")
        date_ctrl.wait("visible", timeout=10)
        date_hwnd = date_ctrl.handle
        date_rect = win32gui.GetWindowRect(date_hwnd)

        parts = for_date_value.replace(" ", "/").split("/")
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        
        st_bytes = ctypes.create_string_buffer(16)
        ctypes.memmove(st_bytes,
            ctypes.c_uint16(year).value.to_bytes(2,'little') +
            ctypes.c_uint16(month).value.to_bytes(2,'little') +
            ctypes.c_uint16(0).value.to_bytes(2,'little') +
            ctypes.c_uint16(day).value.to_bytes(2,'little') +
            b'\x00' * 8, 16)
            
        pid = ctypes.wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(date_hwnd, ctypes.byref(pid))
        hProc = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)
        try:
            remote_mem = ctypes.windll.kernel32.VirtualAllocEx(hProc, None, 16, 0x3000, 0x04)
            try:
                ctypes.windll.kernel32.WriteProcessMemory(hProc, remote_mem, st_bytes, 16, None)
                click_center(date_rect)
                time.sleep(0.3)
                ctypes.windll.user32.SendMessageW(date_hwnd, 0x1002, 0, remote_mem)
                time.sleep(0.5)
                send_keys("{RIGHT}{ENTER}")
            finally:
                ctypes.windll.kernel32.VirtualFreeEx(hProc, remote_mem, 0, 0x8000)
        finally:
            ctypes.windll.kernel32.CloseHandle(hProc)

    def click_process_fetch_button(self, cc_hwnd, fetch_id="btnProcFetch"):
        cc_win = self.app.window(handle=cc_hwnd)
        btn = cc_win.child_window(auto_id=fetch_id, control_type="Button")
        btn.wait("visible enabled", timeout=10)
        btn.click_input()
        time.sleep(1.0)

    def set_processes_checkbox(self, cc_hwnd, auto_id, target_state=True):
        cc_win = self.app.window(handle=cc_hwnd)
        chk = cc_win.child_window(auto_id=auto_id, control_type="CheckBox")
        chk.wait("visible", timeout=10)
        
        current = chk.get_toggle_state()
        desired = 1 if target_state else 0
        if current != desired:
            chk.click_input()
            time.sleep(0.5)

    def click_others_button(self, cc_hwnd, btn_id="btnProcess", combo_id="cmbExch"):
        cc_win = self.app.window(handle=cc_hwnd)
        btn = cc_win.child_window(auto_id=btn_id, control_type="Button")
        btn.wait("visible enabled", timeout=10)
        btn.click_input()
        cc_win.child_window(auto_id=combo_id, control_type="ComboBox").wait("visible", timeout=15)
        time.sleep(0.5)

    def set_others_exchange(self, cc_hwnd, exchange_name, combo_id="cmbExch"):
        target = exchange_name.strip().upper()
        cc_win = self.app.window(handle=cc_hwnd)
        combo = cc_win.child_window(auto_id=combo_id, control_type="ComboBox")
        combo.wait("visible enabled", timeout=10)
        combo.click_input()
        time.sleep(0.4)
        send_keys("{HOME}")
        time.sleep(0.3)
        if target == "NSE":
            send_keys("{DOWN}")
            time.sleep(0.2)
        send_keys("{ENTER}")
        time.sleep(0.8)

    def set_others_segment(self, cc_hwnd, segment_name, combo_id="cmbSeg"):
        target = segment_name.strip().upper()
        cc_win = self.app.window(handle=cc_hwnd)
        combo = cc_win.child_window(auto_id=combo_id, control_type="ComboBox")
        combo.wait("visible enabled", timeout=10)
        combo.click_input()
        time.sleep(0.4)
        send_keys("{HOME}")
        time.sleep(0.3)
        
        if target in ["F&O", "FO", "F AND O"]: send_keys("{DOWN}")
        elif target in ["FX", "CURRENCY"]: send_keys("{DOWN 2}")
        elif target in ["MF", "MUTUAL FUNDS", "MUTUAL FUND"]: send_keys("{DOWN 3}")
            
        time.sleep(0.2)
        send_keys("{ENTER}")
        time.sleep(0.8)

    def set_others_settlement(self, cc_hwnd, settlement_name, combo_id="cmbStlmnt"):
        prefix_target = settlement_name.strip()[:2].upper()
        cc_win = self.app.window(handle=cc_hwnd)
        combo = cc_win.child_window(auto_id=combo_id, control_type="ComboBox")
        combo.wait("visible enabled", timeout=10)
        target_hwnd = combo.handle
        combo.click_input()
        time.sleep(0.5)

        matched_idx = win32api.SendMessage(target_hwnd, 0x014D, -1, prefix_target)
        if matched_idx != -1:
            time.sleep(0.2)
            parent_form_hwnd = win32gui.GetParent(target_hwnd)
            control_id = win32gui.GetDlgCtrlID(target_hwnd)
            notification_message = (1 << 16) | (control_id & 0xFFFF)
            win32api.SendMessage(parent_form_hwnd, 0x0111, notification_message, target_hwnd)
            time.sleep(0.3)
            send_keys("{ESC}")
        else:
            send_keys("^a{BACKSPACE}")
            time.sleep(0.1)
            send_keys(settlement_name)
            time.sleep(0.4)
            send_keys("{ENTER}")
        time.sleep(0.8)

    def select_others_execution_option(self, cc_hwnd, option_key):
        # Accepts either a friendly snake_case key OR the raw JSON auto_id
        # (e.g. "optPrOblComp") directly, since Action.json stores auto_ids.
        mapping = {
            "exchange_obligation_reconciliation": "optPrOblComp",
            "unprocess_bills": "optPrUnProc",
            "display_obligation_money_sheet": "optPrDispObgl",
            "accumulation_difference": "optPrAccuDiff",
            "stt_mismatch": "optPrSTTMismatch",
            "bill_reconciliation": "optPrBillReco"
        }
        key_clean = option_key.strip()
        if key_clean in mapping.values():
            target_auto_id = key_clean
        else:
            target_auto_id = mapping.get(key_clean.lower())
        if not target_auto_id:
            return

        cc_win = self.app.window(handle=cc_hwnd)
        radio = cc_win.child_window(auto_id=target_auto_id, control_type="RadioButton")
        radio.wait("visible enabled", timeout=10)
        radio.click_input()
        time.sleep(0.6)

    def click_others_workspace_proceed(self, cc_hwnd, btn_id="btnProcesses"):
        cc_win = self.app.window(handle=cc_hwnd)
        btn = cc_win.child_window(auto_id=btn_id, control_type="Button")
        btn.wait("visible enabled", timeout=10)
        btn.click_input()
        time.sleep(1.5)

        result = self._dismiss_others_proceed_popup()
        if result == "MISMATCH":
            raise Exception("[OTHERS PROCEED] CRITICAL STOP: 'Mis Match Found' detected. Halting execution pipeline.")
        self._close_report_popup()

    def _dismiss_others_proceed_popup(self):
        DIALOG_TITLE_KEYWORDS = ("information", "are you sure", "mis match", "mismatch", "reconcil")
        popup_hwnd = None
        for _poll in range(20):
            time.sleep(0.5)
            candidate = None

            def _find_dialog(hwnd, _):
                nonlocal candidate
                try:
                    if not win32gui.IsWindowVisible(hwnd) or hwnd == self.main_hwnd:
                        return True
                    cls   = win32gui.GetClassName(hwnd)
                    title = win32gui.GetWindowText(hwnd).lower().strip()

                    if cls == "#32770":
                        candidate = hwnd
                        return True

                    title_hit = any(kw in title for kw in DIALOG_TITLE_KEYWORDS)
                    if "windowsforms" in cls.lower() and title_hit:
                        candidate = hwnd
                        return True
                    if title_hit:
                        candidate = hwnd
                        return True
                except: pass
                return True

            win32gui.EnumWindows(_find_dialog, None)
            if candidate:
                popup_hwnd = candidate
                break

        if not popup_hwnd:
            return None

        dialog_title = win32gui.GetWindowText(popup_hwnd)
        text_parts = [dialog_title.lower()]
        win32gui.EnumChildWindows(popup_hwnd, lambda h, _: [text_parts.append(win32gui.GetWindowText(h).strip().lower()), True][1], None)

        combined = " ".join(text_parts)
        is_mismatch_found     = "mis match found"     in combined or "mismatch found"     in combined
        is_mismatch_not_found = "mis match not found" in combined or "mismatch not found" in combined

        if is_mismatch_found and not is_mismatch_not_found:
            self._click_ok_or_close_on_dialog(popup_hwnd)
            return "MISMATCH"

        self._click_ok_or_close_on_dialog(popup_hwnd)
        return None

    def _click_ok_or_close_on_dialog(self, popup_hwnd):
        try:
            win32gui.SetForegroundWindow(popup_hwnd)
            time.sleep(0.4)
        except: pass

        btn_hwnd = None
        def _find_ok(hwnd, _):
            nonlocal btn_hwnd
            try:
                raw   = win32gui.GetWindowText(hwnd).strip()
                clean = raw.replace("&", "").lower()
                cls   = win32gui.GetClassName(hwnd)
                if clean in ("ok", "yes") and "button" in cls.lower() and win32gui.IsWindowVisible(hwnd):
                    btn_hwnd = hwnd
            except: pass
            return True
        try:
            win32gui.EnumChildWindows(popup_hwnd, _find_ok, None)
        except: pass

        if btn_hwnd:
            try:
                win32api.SendMessage(btn_hwnd, 0x00F5, 0, 0)
                time.sleep(0.5)
                return
            except: pass

        if win32gui.GetForegroundWindow() == popup_hwnd:
            send_keys("{ENTER}")
            time.sleep(0.5)
        else:
            win32api.PostMessage(popup_hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(0.5)

    def click_file_imports_button(self, cc_hwnd, btn_id="btnImports", combo_id="cmbProduct"):
        cc_win = self.app.window(handle=cc_hwnd)
        btn = cc_win.child_window(auto_id=btn_id, control_type="Button")
        btn.wait("visible enabled", timeout=10)
        btn.click_input()
        cc_win.child_window(auto_id=combo_id, control_type="ComboBox").wait("visible", timeout=15)
        time.sleep(0.5)

    def set_imports_product(self, cc_hwnd, product_name, combo_id="cmbProduct"):
        cc_win = self.app.window(handle=cc_hwnd)
        combo = cc_win.child_window(auto_id=combo_id, control_type="ComboBox")
        combo.wait("visible enabled", timeout=10)
        combo.click_input()
        time.sleep(0.4)
        send_keys("{HOME}")
        time.sleep(0.2)
        if product_name.strip().upper() == "COMMODITY":
            send_keys("{DOWN}")
            time.sleep(0.2)
        send_keys("{ENTER}")
        time.sleep(0.5)

    def set_imports_type(self, cc_hwnd, type_name, combo_id="cmbFileType"):
        cc_win = self.app.window(handle=cc_hwnd)
        combo = cc_win.child_window(auto_id=combo_id, control_type="ComboBox")
        combo.wait("visible enabled", timeout=10)
        combo.click_input()
        time.sleep(0.4)
        send_keys("{HOME}")
        time.sleep(0.2)
        if type_name.strip().upper() == "UDIFF":
            send_keys("{DOWN}")
            time.sleep(0.2)
        send_keys("{ENTER}")
        time.sleep(0.5)

    def check_matrix_checkbox(self, cc_hwnd, checkbox_id, state=True):
        cc_win = self.app.window(handle=cc_hwnd)
        chk = cc_win.child_window(auto_id=checkbox_id, control_type="CheckBox")
        chk.wait("visible", timeout=10)

        current = chk.get_toggle_state()
        desired  = 1 if state else 0

        if current != desired:
            chk.click_input()
            time.sleep(0.8)

    def close_window(self):
        try:
            cc_hwnd = self._get_control_center_hwnd()
            win32gui.PostMessage(cc_hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(1.0)
        except: pass

    def process(self, raw_workflow_config):
        """
        Fully JSON-driven entrypoint. Every control id, value, and toggle used
        below is read directly out of the 'control_center' block of Action.json
        (raw_workflow_config) — nothing is passed in as separate kwargs anymore.

        Supports both JSON value formats:
            "cmbProduct": "Equity"
            "cmbProduct": {"value": "Equity", "control_type": "ComboBox", "post_delay": 1}

        All lower-level grid-scan / dialog-dismiss / report-close / window-close
        logic is untouched — this method only decides WHAT to click and WHAT
        values to type, based on the JSON.
        """
        raw_workflow_config = raw_workflow_config or {}

        # ---- top-level: date + proceed ----
        date_value    = _cfg_val(raw_workflow_config.get("dtMain"))
        click_proceed = bool(_cfg_val(raw_workflow_config.get("btnProceed"), False))

        # ---- sub-sections straight from JSON ----
        file_imports_block = raw_workflow_config.get("file_imports", {}) or {}
        others_block        = raw_workflow_config.get("others", {}) or {}
        processes_block      = raw_workflow_config.get("processes", {}) or {}

        # -- file_imports --
        click_file_imports = file_imports_block.get("enabled", True) and \
            bool(_cfg_val(file_imports_block.get("btnImports"), False))
        imports_product    = _cfg_val(file_imports_block.get("cmbProduct"))
        imports_type        = _cfg_val(file_imports_block.get("cmbFileType"))
        matrix_checkboxes    = file_imports_block.get("matrix_checkboxes", {}) or {}
        bse_files_workflow    = file_imports_block.get("bse_files_workflow", {}) or {}
        nse_files_workflow     = file_imports_block.get("nse_files_workflow", {}) or {}

        # -- others --
        click_others = others_block.get("enabled", True) and \
            bool(_cfg_val(others_block.get("btnProcess"), False))
        exchange      = _cfg_val(others_block.get("cmbExch"))
        segment_val    = _cfg_val(others_block.get("cmbSeg"))
        settlement      = _cfg_val(others_block.get("cmbStlmnt"))

        # -- processes --
        click_processes = processes_block.get("enabled", True) and \
            bool(_cfg_val(processes_block.get("btnOthers"), False))
        product          = _cfg_val(processes_block.get("cmbProcProduct"))
        for_date          = _cfg_val(processes_block.get("dtProcess"))
        click_fetch        = bool(_cfg_val(processes_block.get("btnProcFetch"), False))

        while True:
            cc_hwnd = self._get_control_center_hwnd()
            if date_value is not None:
                self.set_control_center_date(cc_hwnd, date_value, date_id="dtMain")
                time.sleep(0.2)
                if click_proceed:
                    self.click_proceed_button(cc_hwnd, btn_id="btnProceed")
                    time.sleep(0.5)
            break

        execution_sequence = ["file_imports", "others", "processes"]

        for step in execution_sequence:
            cc_hwnd = self._get_control_center_hwnd()

            if step == "file_imports" and click_file_imports:
                self.click_file_imports_button(cc_hwnd, btn_id="btnImports", combo_id="cmbProduct")
                time.sleep(0.5)

                if imports_product is not None:
                    self.set_imports_product(cc_hwnd, imports_product, combo_id="cmbProduct")
                    time.sleep(0.2)

                if imports_type is not None:
                    self.set_imports_type(cc_hwnd, imports_type, combo_id="cmbFileType")
                    time.sleep(0.2)

                if matrix_checkboxes and isinstance(matrix_checkboxes, dict):
                    for target_cb_id, cb_enabled in matrix_checkboxes.items():
                        if not _cfg_val(cb_enabled, False):
                            continue

                        self.check_matrix_checkbox(cc_hwnd, checkbox_id=target_cb_id, state=True)
                        time.sleep(0.5)
                        time.sleep(10.0)

                        active_segment = "NSE" if "NSE" in target_cb_id.upper() else "BSE"
                        active_workflow = nse_files_workflow if active_segment == "NSE" else bse_files_workflow

                        status = self.scan_and_process_data_grid(cc_hwnd, active_workflow, date_value=date_value, current_segment=active_segment, grid_id="dgvFileImp")

                        self.check_matrix_checkbox(cc_hwnd, checkbox_id=target_cb_id, state=False)
                        time.sleep(1.5)

                        if status == "RESTART":
                            return "RESTART"

            elif step == "others" and click_others:
                self.click_others_button(cc_hwnd, btn_id="btnProcess", combo_id="cmbExch")
                time.sleep(0.5)

                if exchange is not None:
                    self.set_others_exchange(cc_hwnd, exchange, combo_id="cmbExch")

                if segment_val is not None:
                    self.set_others_segment(cc_hwnd, segment_val, combo_id="cmbSeg")

                if settlement is not None:
                    self.set_others_settlement(cc_hwnd, settlement, combo_id="cmbStlmnt")

                # Read the radio-button auto_ids directly from JSON (matches
                # Action.json keys exactly: optPrOblComp, optPrUnProc, etc.)
                radio_option_ids = [
                    "optPrOblComp", "optPrUnProc", "optPrDispObgl",
                    "optPrAccuDiff", "optPrSTTMismatch", "optPrBillReco"
                ]
                for auto_id in radio_option_ids:
                    if bool(_cfg_val(others_block.get(auto_id), False)):
                        self.select_others_execution_option(cc_hwnd, auto_id)
                        break

                self.click_others_workspace_proceed(cc_hwnd, btn_id="btnProcesses")

            elif step == "processes" and click_processes:
                self.click_processes_button(cc_hwnd, btn_id="btnOthers", combo_id="cmbProcProduct")
                time.sleep(0.5)

                if product is not None:
                    self.set_product_selection(cc_hwnd, product, combo_id="cmbProcProduct")
                    time.sleep(0.2)

                if for_date is not None:
                    self.set_process_for_date(cc_hwnd, for_date, date_id="dtProcess")
                    time.sleep(0.2)

                # Read checkbox auto_ids directly from JSON (chkBillGenerate, etc.)
                checkbox_auto_ids = [
                    "chkBillGenerate", "chkProcAccumulate", "chkAGTS",
                    "chkRemShare", "chkLockBill"
                ]
                for auto_id in checkbox_auto_ids:
                    if auto_id in processes_block:
                        self.set_processes_checkbox(cc_hwnd, auto_id, target_state=bool(_cfg_val(processes_block[auto_id], False)))

                if click_fetch:
                    self.click_process_fetch_button(cc_hwnd, fetch_id="btnProcFetch")
                    time.sleep(0.5)

                    # Read target settlement value from direct element ID key 'dgvBillProcess'
                    target_settlement_name = _cfg_val(processes_block.get("dgvBillProcess"))
                    if target_settlement_name:
                        self.process_processes_grid_selection(cc_hwnd, target_settlement_name, grid_id="dgvBillProcess", proceed_id="btnProcessProceed", status_grid_id="dgvBillStatus")
                        time.sleep(0.8)

        print("ControlCenterPage dynamic sequencing suite processing completed successfully.")
        return "SUCCESS"