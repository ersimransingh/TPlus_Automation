import time
import threading
import ctypes
import ctypes.wintypes
import win32gui
import win32con
import win32api
from pywinauto import mouse
from pywinauto.keyboard import send_keys

TRADEPLUS_CLASS = "WindowsForms10.Window.8.app.0.141b42a_r7_ad1"
BUTTON_CLASS    = "WindowsForms10.BUTTON.app.0.141b42a_r7_ad1"
COMBO_CLASS     = "WindowsForms10.COMBOBOX.app.0.141b42a_r7_ad1"
DATETIME_CLASS  = "WindowsForms10.SysDateTimePick32.app.0.141b42a_r7_ad1"
TAB_CLASS       = "WindowsForms10.SysTabControl32.app.0.141b42a_r7_ad1"


def _get_all_children(parent_hwnd):
    out = []
    def _cb(hwnd, _):
        try:
            out.append((
                hwnd, win32gui.GetClassName(hwnd), win32gui.GetWindowText(hwnd),
                win32gui.GetWindowRect(hwnd), win32gui.IsWindowVisible(hwnd),
            ))
        except: pass
        return True
    win32gui.EnumChildWindows(parent_hwnd, _cb, None)
    return out


def _click_rect_center(rect):
    x = (rect[0] + rect[2]) // 2
    y = (rect[1] + rect[3]) // 2
    mouse.click(button='left', coords=(x, y))
    time.sleep(0.3)


def _bm_click(hwnd):
    win32api.SendMessage(hwnd, win32con.BM_CLICK, 0, 0)
    time.sleep(0.25)


def _normalize_to_dd_mm_yyyy(date_str):
    if not date_str:
        return date_str
    s = str(date_str).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[6:8]}/{s[4:6]}/{s[0:4]}"
    s = s.replace("-", "/").replace(" ", "/")
    p = s.split("/")
    if len(p) == 3:
        if len(p[0]) == 4:
            return f"{p[2]}/{p[1]}/{p[0]}"
        if len(p[2]) == 4:
            return f"{p[0]}/{p[1]}/{p[2]}"
    return s


def _cfg_val(node, default_val=None):
    """
    Unwraps a JSON config node coming from Action.json.
    Supports both flat primitives and dictionary structures.
    """
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node if node is not None else default_val


def _cfg_delay(node, default=1):
    """Reads an optional post_delay from a wrapped config node."""
    if isinstance(node, dict) and "post_delay" in node:
        return node["post_delay"]
    return default


def async_popup_killer(main_hwnd):
    for _ in range(35):
        time.sleep(0.2)
        result = []
        def cb(hwnd, _):
            try:
                title = win32gui.GetWindowText(hwnd)
                cls   = win32gui.GetClassName(hwnd)
                if win32gui.IsWindowVisible(hwnd):
                    if ("information" in title.lower() or "confirm" in title.lower() or not title):
                        if "#32770" in cls or "WindowsForms10.Window" in cls:
                            r = win32gui.GetWindowRect(hwnd)
                            if r[2]-r[0] < 600 and r[3]-r[1] < 400:
                                result.append(hwnd)
            except: pass
            return True
        win32gui.EnumChildWindows(main_hwnd, cb, None)
        if result:
            phwnd = result[0]
            try:
                win32gui.ShowWindow(phwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(phwnd)
                time.sleep(0.15)
                send_keys("{ENTER}")
                return True
            except:
                win32gui.PostMessage(phwnd, win32con.WM_CLOSE, 0, 0)
                return True
    return False


class PledgePage:

    def __init__(self, app):
        self.app = app
        self.main_hwnd = win32gui.FindWindow(TRADEPLUS_CLASS, "TradePlusX")
        if not self.main_hwnd:
            raise Exception("TradePlusX main window not found!")

    def _get_pledge_win_hwnd(self):
        for attempt in range(12):
            found = []
            def cb(hwnd, _):
                try:
                    t = win32gui.GetWindowText(hwnd).lower()
                    if ("pledge" in t or "unpledge" in t) and win32gui.IsWindowVisible(hwnd):
                        found.append(hwnd)
                except: pass
                return True
            win32gui.EnumChildWindows(self.main_hwnd, cb, None)
            if found:
                return found[0]
            time.sleep(0.5)
        raise Exception("Pledge Management window not found after 12 attempts!")

    def click_manage_tab(self, tab_idx=1):
        pledge_hwnd = self._get_pledge_win_hwnd()
        
        win32gui.ShowWindow(pledge_hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(pledge_hwnd)
        time.sleep(0.3)

        from pywinauto import Application
        uia_app = Application(backend="uia").connect(handle=pledge_hwnd)
        pledge_win = uia_app.window(handle=pledge_hwnd)

        print("   [PLEDGE] Locating Tab Control via AutomationId='tabMain'...")
        tab_control = pledge_win.child_window(auto_id="tabMain", control_type="Tab")

        try:
            print("   [PLEDGE] Natively selecting 'Manage' tab...")
            tab_control.select("Manage")
        except Exception as e:
            print(f"   ⚠ Selection by name failed ({e}), trying index fallback via UIA...")
            tab_control.select(tab_idx)

        time.sleep(1.5)

    def set_manage_action(self, action_value, combo_keyword="securities"):
        normalized = action_value.strip().lower()
        pledge_hwnd = self._get_pledge_win_hwnd()
        
        win32gui.ShowWindow(pledge_hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(pledge_hwnd)
        time.sleep(0.5)

        from pywinauto import Application
        uia_app = Application(backend="uia").connect(handle=pledge_hwnd)
        pledge_win = uia_app.window(handle=pledge_hwnd)

        print("   [PLEDGE] Locating target drop-down control via AutomationId='cmbManage'...")
        dropdown = pledge_win.child_window(auto_id="cmbManage", control_type="ComboBox")

        if normalized in ("un-pledge", "un pledge", "unpledge"):
            target_item = "Un Pledge"
        elif normalized in ("un re-pledge", "un re pledge", "un repledge"):
            target_item = "Un Re-Pledge"
        else:
            target_item = "Pledge"

        print(f"   [PLEDGE] Natively selecting item: '{target_item}'")
        dropdown.select(target_item)
        time.sleep(0.5)

    def set_manage_date(self, date_value):
        date_value = _normalize_to_dd_mm_yyyy(date_value)
        pledge_hwnd = self._get_pledge_win_hwnd()
        children    = _get_all_children(pledge_hwnd)

        date_controls = [(hwnd, rect) for hwnd, cls, title, rect, vis in children if cls == DATETIME_CLASS and vis]
        if not date_controls:
            raise Exception("No DateTimePicker found in Pledge window!")

        date_controls.sort(key=lambda x: x[1][1])
        date_hwnd, date_rect = date_controls[0]

        parts = date_value.split("/")
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])

        st = (ctypes.c_uint16(year).value.to_bytes(2, 'little') +
              ctypes.c_uint16(month).value.to_bytes(2, 'little') +
              ctypes.c_uint16(0).value.to_bytes(2, 'little') +
              ctypes.c_uint16(day).value.to_bytes(2, 'little') +
              b'\x00' * 8)
        buf = ctypes.create_string_buffer(16)
        ctypes.memmove(buf, st, 16)

        pid = ctypes.wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(date_hwnd, ctypes.byref(pid))
        hProc = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)
        try:
            remote = ctypes.windll.kernel32.VirtualAllocEx(hProc, None, 16, 0x3000, 0x04)
            try:
                ctypes.windll.kernel32.WriteProcessMemory(hProc, remote, buf, 16, None)
                _click_rect_center(date_rect)
                time.sleep(0.1)
                ctypes.windll.user32.SendMessageW(date_hwnd, 0x1002, 0, remote)
                time.sleep(0.2)
                send_keys("{RIGHT}{UP}{DOWN}{ENTER}")
                time.sleep(0.3)
            finally:
                ctypes.windll.kernel32.VirtualFreeEx(hProc, remote, 0, 0x8000)
        finally:
            ctypes.windll.kernel32.CloseHandle(hProc)

    def set_checkbox_state(self, checkbox_label, target_state, title_mappings=None):
        win32_title = None
        if title_mappings:
            win32_title = title_mappings.get(checkbox_label.strip().lower())
        if not win32_title:
            win32_title = checkbox_label.strip().title()

        pledge_hwnd = self._get_pledge_win_hwnd()
        children    = _get_all_children(pledge_hwnd)

        chk_hwnd = None
        for hwnd, cls, title, rect, vis in children:
            if cls == BUTTON_CLASS and vis and title.strip().lower() == win32_title.strip().lower():
                chk_hwnd = hwnd
                break

        if not chk_hwnd:
            raise Exception(f"Checkbox element target structural identity '{win32_title}' not found!")

        current = win32api.SendMessage(chk_hwnd, win32con.BM_GETCHECK, 0, 0) == win32con.BST_CHECKED
        if current != target_state:
            _bm_click(chk_hwnd)

    def click_pledge_button_by_title(self, button_title="Fetch", apply_layout_filter=False):
        pledge_hwnd = self._get_pledge_win_hwnd()
        children    = _get_all_children(pledge_hwnd)
        pledge_rect = win32gui.GetWindowRect(pledge_hwnd)
        right_half  = pledge_rect[0] + (pledge_rect[2] - pledge_rect[0]) * 0.6

        btn_hwnd = None
        for hwnd, cls, title, rect, vis in children:
            if cls == BUTTON_CLASS and vis and title.strip().lower() == button_title.lower():
                if apply_layout_filter and rect[0] < right_half:
                    continue
                btn_hwnd = hwnd
                break

        if not btn_hwnd:
            raise Exception(f"Target button '{button_title}' control could not be parsed.")

        _bm_click(btn_hwnd)

    def close_slip_printing_tab(self):
        time.sleep(1.0)
        found = []
        win32gui.EnumWindows(lambda h, _: [found.append(h) if win32gui.IsWindowVisible(h) and any(k in win32gui.GetWindowText(h).lower() for k in ["slip", "printing"]) else None, True][1], None)
        if found:
            win32gui.PostMessage(found[0], win32con.WM_CLOSE, 0, 0)
            time.sleep(1.0)

    def close_window(self):
        try:
            hwnd = self._get_pledge_win_hwnd()
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(1.0)
        except: pass

    def process(self, raw_workflow_config=None, *args, **kwargs):
        """
        Hybrid compatible entrypoint tailored to parse JSON configuration blocks.
        Gracefully unwraps nested metadata values and handles manual keywords.
        """
        # Determine data configuration source structure
        if isinstance(raw_workflow_config, dict) and "Menu" not in raw_workflow_config:
            config = raw_workflow_config
        elif raw_workflow_config is None and kwargs:
            config = kwargs
        else:
            config = raw_workflow_config or {}

        # ── EXTRACT CONFIG VALUES VIA UNWRAPPING LOGIC ──
        tab_name = _cfg_val(config.get("tabMain", kwargs.get("tab_name")), "Manage")
        manage_action = _cfg_val(config.get("cmbManage", kwargs.get("manage_action")))
        manage_date = _cfg_val(config.get("dtManageDate", kwargs.get("manage_date")))
        
        items_sold_by_client = _cfg_val(config.get("chkItemsSold", kwargs.get("items_sold_by_client")))
        with_epn_blk = _cfg_val(config.get("chkWithEPN", kwargs.get("with_epn_blk")))
        
        click_fetch = bool(_cfg_val(config.get("btnFetchSecurities", kwargs.get("click_fetch", False))))
        click_save = bool(_cfg_val(config.get("btnSavePledgeData", True)))

        # Operational logic loop execution
        if str(tab_name).strip().lower() == "manage":
            self.click_manage_tab(tab_idx=1)

            if manage_action is not None:
                self.set_manage_action(str(manage_action), combo_keyword="securities")

            if manage_date is not None:
                self.set_manage_date(manage_date)

            if with_epn_blk is not None:
                # Value structural target matches configuration title label fallback mappings
                self.set_checkbox_state("with epn-blk", bool(with_epn_blk))

            if items_sold_by_client is not None:
                self.set_checkbox_state("items sold by client", bool(items_sold_by_client))

            if click_fetch:
                killer = threading.Thread(target=async_popup_killer, args=(self.main_hwnd,), daemon=True)
                killer.start()
                
                self.click_pledge_button_by_title(button_title="Fetch", apply_layout_filter=True)
                time.sleep(10.0)
                time.sleep(3.0)

                if click_save:
                    save_killer = threading.Thread(target=async_popup_killer, args=(self.main_hwnd,), daemon=True)
                    save_killer.start()
                    
                    self.click_pledge_button_by_title(button_title="Save", apply_layout_filter=False)
                    time.sleep(3.5)

                    self.close_slip_printing_tab()
                    time.sleep(1.0)

        self.close_window()