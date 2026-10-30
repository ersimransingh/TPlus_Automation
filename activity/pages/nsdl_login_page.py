import time

class LoginPage:
    def __init__(self, page, locators):
        self.page = page
        self.locators = locators
        self.page.on("dialog", lambda dialog: self._handle_dialog(dialog))

    def _handle_dialog(self, dialog):
        print(f"⚠️ Popup Alert detected: '{dialog.message}' - Clicking OK automatically.")
        dialog.accept()

    def navigate(self, url):
        print(f"Navigating to {url}...")
        self.page.goto(url)
        self.page.wait_for_load_state("load")

    def login(self, username, password):
        print("Waiting for login frame to fully load...")
        self.page.wait_for_timeout(3000)

        target_frame = None
        for frame in self.page.frames:
            if frame.locator(self.locators["user_id_xpath"]).count() > 0:
                print(f"✅ Found input fields inside a frame: {frame.name or 'Unnamed Frame'}")
                target_frame = frame
                break

        if target_frame is None:
            print("⚠️ Elements not found in frames. Defaulting to main page.")
            target_frame = self.page

        try:
            if target_frame != self.page:
                target_frame.wait_for_load_state("load")

            print(f"Logging in as {username}...")

            # 1. User ID Field
            user_field = target_frame.locator(self.locators["user_id_xpath"]).first
            user_field.wait_for(state="visible", timeout=15000)
            user_field.click(force=True)
            user_field.fill("")
            user_field.press_sequentially(username, delay=200)
            self.page.wait_for_timeout(300)

            # 2. Password Field
            pass_field = target_frame.locator(self.locators["password_xpath"]).first
            pass_field.click(force=True)
            pass_field.fill("")
            pass_field.press_sequentially(password, delay=200)
            self.page.wait_for_timeout(300)

            # 3. Trigger validation
            print("Tabbing out of password field to trigger validation...")
            pass_field.press("Tab")
            self.page.wait_for_timeout(1000)

            # 4. Login Submission
            print("Submitting login form...")
            login_btn = target_frame.locator(self.locators["login_btn_xpath"]).first
            
            # Submit via Enter key
            pass_field.press("Enter")
            self.page.wait_for_timeout(1500)

            # Fallback click only if still on the login frame
            if target_frame.locator(self.locators["login_btn_xpath"]).count() > 0:
                try:
                    login_btn.click(force=True, timeout=2000)
                except Exception:
                    pass

            print("✅ Login steps completed! Waiting for dashboard to appear...")
            self.page.wait_for_timeout(5000)

        except Exception as e:
            print(f"❌ ERROR during login interaction: {e}")