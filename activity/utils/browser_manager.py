import os
from datetime import datetime

class BrowserManager:
    @staticmethod
    def launch_clean_edge(playwright_instance, base_download_path="C:\\NSDLFILES"):
        print("Clearing cache configurations and launching a fresh Edge browser...")
        
        # Create date-based folder for screen recordings
        date_str = datetime.now().strftime("%Y-%m-%d")
        recordings_dir = os.path.join(base_download_path, date_str, "recordings")
        os.makedirs(recordings_dir, exist_ok=True)

        browser = playwright_instance.chromium.launch(
            channel="msedge",
            headless=False,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--disable-cache",
                "--disable-application-cache",
                "--disable-offline-load-stale-cache",
                "--disk-cache-size=0"
            ]
        )
        
        # Enable video recording and explicit file downloads in context
        context = browser.new_context(
            no_viewport=True,
            accept_downloads=True,
            record_video_dir=recordings_dir
        )
        context.clear_cookies()
        return browser, context