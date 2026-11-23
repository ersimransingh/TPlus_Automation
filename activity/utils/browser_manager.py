import ctypes
from ctypes import wintypes
import time


class BrowserManager:
    @staticmethod
    def _get_visible_edge_hwnds():
        """Returns a set of all currently visible Microsoft Edge top-level window handles."""
        hwnds = set()
        try:
            user32 = ctypes.windll.user32
            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            def callback(hwnd, lparam):
                if user32.IsWindowVisible(hwnd):
                    class_buff = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, class_buff, 256)
                    if class_buff.value == "Chrome_WidgetWin_1":
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            title_buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, title_buff, length + 1)
                            if "edge" in title_buff.value.lower():
                                hwnds.add(hwnd)
                return True

            user32.EnumWindows(EnumWindowsProc(callback), 0)
        except Exception:
            pass
        return hwnds

    @staticmethod
    def bring_edge_to_front(target_hwnd=None):
        """Forces the target (or newest) Microsoft Edge window to the foreground and maximizes it."""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            if target_hwnd is None:
                visible = list(BrowserManager._get_visible_edge_hwnds())
                if not visible:
                    return
                target_hwnd = visible[-1]

            fg_hwnd = user32.GetForegroundWindow()
            current_thread = kernel32.GetCurrentThreadId()
            fg_thread = (
                user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            )

            attached = False
            if fg_thread and fg_thread != current_thread:
                attached = bool(
                    user32.AttachThreadInput(current_thread, fg_thread, True)
                )

            try:
                SW_RESTORE = 9
                SW_SHOWMAXIMIZED = 3
                if user32.IsIconic(target_hwnd):
                    user32.ShowWindow(target_hwnd, SW_RESTORE)
                user32.ShowWindow(target_hwnd, SW_SHOWMAXIMIZED)
                user32.BringWindowToTop(target_hwnd)
                user32.SetForegroundWindow(target_hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, fg_thread, False)
        except Exception:
            pass

    @staticmethod
    def _on_new_page(page):
        """Brings newly created tabs/pages and the Edge window to the front."""
        try:
            page.bring_to_front()
            time.sleep(0.2)
            BrowserManager.bring_edge_to_front()
        except Exception:
            pass

    @staticmethod
    def launch_clean_edge(playwright_instance, base_download_path=None):
        print("Clearing cache configurations and launching a fresh Edge browser...")

        existing_hwnds = BrowserManager._get_visible_edge_hwnds()

        browser = playwright_instance.chromium.launch(
            channel="msedge",
            headless=False,
            args=[
                "--new-window",
                "--start-maximized",
                "--window-position=0,0",
                "--disable-blink-features=AutomationControlled",
                "--disable-cache",
                "--disable-application-cache",
                "--disable-offline-load-stale-cache",
                "--disk-cache-size=0",
            ],
        )

        context = browser.new_context(
            no_viewport=True,
            accept_downloads=True,
        )
        context.clear_cookies()
        context.on("page", BrowserManager._on_new_page)

        # Wait briefly for the new Edge window handle and force it to the foreground
        new_hwnd = None
        for _ in range(15):
            current_hwnds = BrowserManager._get_visible_edge_hwnds()
            diff = list(current_hwnds - existing_hwnds)
            if diff:
                new_hwnd = diff[0]
                break
            time.sleep(0.2)

        BrowserManager.bring_edge_to_front(new_hwnd)
        return browser, context