import os
import time
import zipfile
from datetime import datetime, timedelta
from utils.logger_manager import LoggerManager

logger = LoggerManager.get_logger()

class DashboardPage:
    def __init__(self, page, locators):
        self.page = page
        self.locators = locators

    def _check_session_expired(self):
        """Immediately aborts if redirected to SignOut.aspx or login screen."""
        if self.page.is_closed():
            raise ConnectionError("Browser window closed unexpectedly.")

        # 1. Check main page URL
        if "signout.aspx" in self.page.url.lower():
            logger.error("🚨 Session Expired detected (Redirected to SignOut.aspx). Closing browser...")
            raise ConnectionError("Session expired: Redirected to SignOut.aspx")

        # 2. Check all frame URLs and login inputs
        for frame in self.page.frames:
            try:
                if "signout.aspx" in frame.url.lower():
                    logger.error("🚨 Session Expired detected in frame (SignOut.aspx). Closing browser...")
                    raise ConnectionError("Session expired: Redirected to SignOut.aspx")
                if frame.locator(self.locators["user_id_xpath"]).count() > 0:
                    logger.error("🚨 Session Expired detected (Login screen visible). Closing browser...")
                    raise ConnectionError("Session expired: Redirected to login page.")
            except ConnectionError:
                raise
            except Exception:
                pass

    def _find_element_anywhere(self, xpath, timeout=10000):
        end_time = time.time() + (timeout / 1000.0)
        while time.time() < end_time:
            # Check for SignOut.aspx on every lookup cycle
            self._check_session_expired()
            try:
                if self.page.locator(xpath).count() > 0:
                    return self.page.locator(xpath)
                for frame in self.page.frames:
                    if frame.locator(xpath).count() > 0:
                        return frame.locator(xpath)
            except Exception:
                pass
            self.page.wait_for_timeout(300)
        raise Exception(f"Element {xpath} never appeared in any frame.")

    def _get_target_frame(self, xpath, timeout_seconds=15):
        end_time = time.time() + timeout_seconds
        while time.time() < end_time:
            for frame in self.page.frames:
                try:
                    if frame.locator(xpath).count() > 0:
                        return frame
                except Exception:
                    continue
            self.page.wait_for_timeout(500)
        return None

    def _find_element_anywhere(self, xpath, timeout=10000):
        end_time = time.time() + (timeout / 1000.0)
        while time.time() < end_time:
            try:
                if self.page.locator(xpath).count() > 0:
                    return self.page.locator(xpath)
                for frame in self.page.frames:
                    if frame.locator(xpath).count() > 0:
                        return frame.locator(xpath)
            except Exception:
                pass
            self.page.wait_for_timeout(300)
        raise Exception(f"Element {xpath} never appeared in any frame.")

    def _resolve_date(self, date_str: str) -> str:
        if not date_str:
            return ""
        
        date_str = str(date_str).strip().lower()
        today = datetime.now()

        if date_str == "t":
            return today.strftime("%d/%m/%Y")
        elif date_str.startswith("t-"):
            try:
                days_to_subtract = int(date_str.split("-")[1])
                target_date = today - timedelta(days=days_to_subtract)
                return target_date.strftime("%d/%m/%Y")
            except Exception:
                return today.strftime("%d/%m/%Y")
        elif date_str.startswith("t+"):
            try:
                days_to_add = int(date_str.split("+")[1])
                target_date = today + timedelta(days=days_to_add)
                return target_date.strftime("%d/%m/%Y")
            except Exception:
                return today.strftime("%d/%m/%Y")
        
        return date_str

    def navigate_to_master_module(self, module_name="Client Master"):
        logger.info(f"Waiting for dashboard to navigate to '{module_name}'...")
        self.page.wait_for_load_state("load")

        initial_xpath = self.locators["uploads_menu_xpath"]
        target_frame = self._get_target_frame(initial_xpath, timeout_seconds=15)
        if target_frame:
            logger.info(f"✅ Found initial menu frame: {target_frame.name or 'Unnamed Frame'}")

        # Step 1: Hover 'Uploads/Downloads'
        logger.info("Triggering 'Uploads/Downloads' menu...")
        menu_1 = self._find_element_anywhere(self.locators["uploads_menu_xpath"], timeout=10000)
        menu_1.evaluate_all("elements => elements.forEach(el => el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})))")
        self.page.wait_for_timeout(1500)

        # Step 2: Hover 'Downloads'
        logger.info("Triggering 'Downloads' menu...")
        menu_2 = self._find_element_anywhere(self.locators["downloads_menu_xpath"], timeout=5000)
        menu_2.evaluate_all("elements => elements.forEach(el => el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})))")
        self.page.wait_for_timeout(1500)

        clean_name = str(module_name).strip().lower()

        # Branch 1: Statement of Transactions
        if "sot" in clean_name or "transaction" in clean_name:
            logger.info("Triggering 'Statement of Transactions'...")
            sot_xpath = self.locators.get("sot_xpath", "(//b[text()='ransaction'])[2]")
            sot_menu = self._find_element_anywhere(sot_xpath, timeout=5000)
            sot_menu.evaluate_all("elements => elements.forEach(el => (el.parentElement || el).click())")
            logger.info(f"✅ Successfully clicked '{module_name}'!")
            self.page.wait_for_timeout(4000)
            return

        # Branch 2: Statement of Holding
        if "soh" in clean_name or "holding" in clean_name:
            logger.info("Triggering 'Statement of Holding'...")
            soh_xpath = self.locators.get("soh_xpath", "//b[text()='olding']")
            soh_menu = self._find_element_anywhere(soh_xpath, timeout=5000)
            soh_menu.evaluate_all("elements => elements.forEach(el => (el.parentElement || el).click())")
            logger.info(f"✅ Successfully clicked '{module_name}'!")
            self.page.wait_for_timeout(4000)
            return

        # Branch 3: Master Submenus (Client Master & ISIN Master)
        logger.info("Triggering 'Master' menu...")
        menu_3 = self._find_element_anywhere(self.locators["master_menu_xpath"], timeout=5000)
        menu_3.evaluate_all("elements => elements.forEach(el => el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})))")
        self.page.wait_for_timeout(1500)

        if "isin" in clean_name or "security" in clean_name:
            target_xpath = self.locators["security_master_xpath"]
        else:
            target_xpath = self.locators["client_master_xpath"]

        final_menu = self._find_element_anywhere(target_xpath, timeout=5000)
        final_menu.evaluate_all("elements => elements.forEach(el => (el.parentElement || el).click())")
        logger.info(f"✅ Successfully clicked '{module_name}'!")
        self.page.wait_for_timeout(4000)

    def process_export_form(self, module_name="", report_type="Incremental", date_from=None, date_to=None) -> str:
        logger.info("=" * 60)
        logger.info(f"⏳ Processing Form for: '{module_name}' | Mode: '{report_type}'")
        logger.info(f"🔍 [PARAM CHECK] date_from: '{date_from}' | date_to: '{date_to}'")
        logger.info("=" * 60)
        self.page.wait_for_timeout(3000)

        clean_name = str(module_name).strip().lower()
        formatted_from = self._resolve_date(date_from)
        formatted_to = self._resolve_date(date_to)

        # =========================================================================
        # STEP 1: SELECT REPORT OPTION (Incremental / Full) FIRST
        # =========================================================================
        is_full = str(report_type).strip().lower() == "full"
        target_label_xpath = self.locators["full_label_xpath"] if is_full else self.locators["incremental_label_xpath"]
        label_name = "Full" if is_full else "Incremental"

        try:
            logger.info(f"👉 Selecting report option: '{label_name}'...")
            target_label = self._find_element_anywhere(target_label_xpath, timeout=4000)
            target_label.evaluate_all("elements => elements.forEach(el => el.click())")
            
            logger.info("⏳ Waiting for ASP.NET PostBack / page reload to complete...")
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            self.page.wait_for_timeout(3000)
            logger.info("✅ Page reloaded and stable.")
        except Exception as e:
            logger.info(f"ℹ️ Form does not require '{label_name}' selection or already set: {e}")

        # =========================================================================
        # STEP 2: SAFELY INJECT VALUE INTO ASP.NET / MASKED-EDIT CONTROLS
        # =========================================================================
        def set_asp_masked_value(xpath, target_val, label):
            logger.info(f"👉 Setting {label} using: {xpath}")
            try:
                field = self._find_element_anywhere(xpath, timeout=6000)
                el = field.first

                # 1. Strip readonly & set value into DOM + AjaxControlToolkit MaskedEdit Behavior
                el.evaluate(f"""e => {{
                    e.removeAttribute('readonly');
                    e.removeAttribute('disabled');
                    e.readOnly = false;

                    // Sync with AjaxControlToolkit MaskedEdit Extender if active
                    if (window.$find) {{
                        try {{
                            var behavior = window.$find(e.id);
                            if (behavior && behavior.set_Value) {{
                                behavior.set_Value('{target_val}');
                            }}
                        }} catch(err) {{}}
                    }}

                    // Set standard DOM properties
                    e.value = '{target_val}';
                    e.setAttribute('value', '{target_val}');

                    // Dispatch standard change events
                    e.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    e.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    e.dispatchEvent(new Event('blur', {{ bubbles: true }}));

                    // Re-run ASP.NET validation so 'The date is invalid' clears
                    if (window.Page_ClientValidate) {{
                        try {{ window.Page_ClientValidate(); }} catch(err) {{}}
                    }}
                }}""")

                self.page.wait_for_timeout(500)
                final_val = el.input_value()
                logger.info(f"✅ [{label}] Successfully updated! Value on screen: '{final_val}'")
            except Exception as e:
                logger.error(f"❌ Failed to set {label}: {e}")

        # --- A. ISIN Master (Requires Date + Time: DD/MM/YYYY HH:MM:SS) ---
        if "isin" in clean_name or "security" in clean_name:
            base_date = formatted_from or datetime.now().strftime("%d/%m/%Y")
            # If time is not provided, append midnight 00:00:00 to satisfy the 19-character mask
            target_timestamp = f"{base_date} 00:00:00" if len(base_date) == 10 else base_date
            isin_xpath = "//input[contains(@id, 'txtLastDownLoadDate')] | //input[@type='text']"
            set_asp_masked_value(isin_xpath, target_timestamp, "ISIN Master Timestamp")

        # --- B. Statement of Holding (Requires Date Only: DD/MM/YYYY) ---
        elif "soh" in clean_name or "holding" in clean_name:
            target_date = formatted_from or datetime.now().strftime("%d/%m/%Y")
            soh_xpath = self.locators.get("soh_date_xpath", "(//input[@type='text'])[1]")
            set_asp_masked_value(soh_xpath, target_date, "Statement of Holding Date")

        # --- C. Client Master Incremental & SOT (Dual Date Fields) ---
        else:
            if formatted_from:
                date_from_xpath = self.locators.get("date_from_xpath", "//input[@id='ctl00_RightContentPlaceHolder_txtStmtDateFrm']")
                set_asp_masked_value(date_from_xpath, formatted_from, "Date From")

            if formatted_to:
                date_to_xpath = self.locators.get("date_to_xpath", "//input[@id='ctl00_RightContentPlaceHolder_txtStmtDateTo']")
                set_asp_masked_value(date_to_xpath, formatted_to, "Date To")

        # =========================================================================
        # STEP 3: SUBMIT FORM
        # =========================================================================
        logger.info("Clicking 'Submit'...")
        submit_btn = self._find_element_anywhere(self.locators["submit_btn_xpath"], timeout=5000)
        submit_btn.evaluate_all("elements => elements.forEach(el => el.click())")
        logger.info("✅ Submitted export request successfully!")
        self.page.wait_for_timeout(4000)

        # =========================================================================
        # STEP 4: EXTRACT REQUEST ID
        # =========================================================================
        request_id = None
        req_id_xpath = self.locators.get("request_id_xpath", '(//input[@type="text"])[1]')
        try:
            req_id_el = self._find_element_anywhere(req_id_xpath, timeout=5000)
            val = req_id_el.first.input_value().strip()
            # If the box still contains a date timestamp, submission did not navigate away
            if val and not (":" in val and "/" in val):
                request_id = val
            elif not request_id:
                attr_val = (req_id_el.first.get_attribute("value") or "").strip()
                if attr_val and not (":" in attr_val and "/" in attr_val):
                    request_id = attr_val
            logger.info(f"🆔 Extracted Request ID for '{module_name}': {request_id}")
        except Exception as e:
            logger.warning(f"⚠️ Could not extract Request ID for '{module_name}': {e}")

        return request_id
           
    def _select_or_click(self, locator_key: str):
        """Helper to handle either dropdown selects or clickable navigation links."""
        xpath = self.locators.get(locator_key)
        if not xpath:
            raise KeyError(f"Locator key '{locator_key}' not found in locators configuration.")
        
        element = self._find_element_anywhere(xpath, timeout=10000)
        tag = element.first.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            element.first.select_option(index=1)
        else:
            element.first.click(force=True)
        self.page.wait_for_timeout(1000)

    def download_by_request_id_search(self, primary_id: str, download_dir: str, poll_interval: int = 15, max_attempts: int = 3, secondary_id: str = None) -> str:
        """
        Navigates to Download & Status -> Download inquiry screen, enters the
        Request ID, and triggers the download.
        """
        logger.info("=" * 60)
        logger.info(f"🔍 [SEARCH RECOVERY] Navigating to inquiry menu (Target ID: '{primary_id}')")
        logger.info("=" * 60)

        self.page.wait_for_load_state("load")
        os.makedirs(download_dir, exist_ok=True)

        # Wait for the menu frame to load after login
        initial_xpath = self.locators["uploads_menu_xpath"]
        target_frame = self._get_target_frame(initial_xpath, timeout_seconds=15)
        if target_frame:
            logger.info(f"✅ Found menu frame: {target_frame.name or 'Unnamed Frame'}")

        # Step 1: Hover 'Uploads/Downloads'
        logger.info("👉 Triggering 'Uploads/Downloads' menu...")
        menu_1 = self._find_element_anywhere(self.locators["uploads_menu_xpath"], timeout=10000)
        menu_1.evaluate_all("elements => elements.forEach(el => el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})))")
        self.page.wait_for_timeout(1500)

        # Step 2: Hover/Click 'Download and Status' -> (//b[text()="tatus"])[4]
        status_xpath = self.locators.get("download_status_xpath", '(//b[text()="tatus"])[4]')
        logger.info(f"👉 Triggering 'Download and Status' menu ({status_xpath})...")
        menu_2 = self._find_element_anywhere(status_xpath, timeout=5000)
        menu_2.evaluate_all("""elements => elements.forEach(el => {
            var target = el.parentElement || el;
            target.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
            target.click();
        })""")
        self.page.wait_for_timeout(1500)

        # Step 3: Click 'Download' -> //b[text()="Do"]
        download_sub_xpath = self.locators.get("download_sub_xpath", '//b[text()="Do"]')
        logger.info(f"👉 Clicking 'Download' option ({download_sub_xpath})...")
        menu_3 = self._find_element_anywhere(download_sub_xpath, timeout=5000)
        menu_3.evaluate_all("elements => elements.forEach(el => (el.parentElement || el).click())")
        logger.info("✅ Successfully navigated to Download & Status inquiry page!")
        self.page.wait_for_timeout(4000)

        ids_to_try = [primary_id]
        if secondary_id and secondary_id != primary_id:
            ids_to_try.append(secondary_id)

        for current_id in ids_to_try:
            is_old = (current_id == primary_id and len(ids_to_try) > 1)
            id_type = "OLD" if is_old else "PENDING/FRESH"
            logger.info(f"📝 Pasting {id_type} Request ID '{current_id}' into search field...")

            req_input = self._find_element_anywhere(self.locators["request_id_xpath"], timeout=10000)
            req_input.first.fill("")
            req_input.first.fill(str(current_id).strip())

            for attempt in range(1, max_attempts + 1):
                logger.info(f"🔎 Clicking Search for [{id_type}: {current_id}] (Attempt {attempt}/{max_attempts})...")
                search_btn = self._find_element_anywhere(self.locators["search_btn_xpath"], timeout=10000)
                search_btn.first.click(force=True)
                self.page.wait_for_timeout(4000)

                try:
                    download_element = self._find_element_anywhere(self.locators["download_link_xpath"], timeout=5000)
                    if download_element.count() > 0 and download_element.first.is_visible():
                        logger.info(f"✅ File ready for {id_type} Request ID '{current_id}'! Triggering download...")
                        with self.page.expect_download(timeout=90000) as download_info:
                            download_element.first.evaluate("node => node.click()")
                        
                        download = download_info.value
                        saved_zip_path = os.path.join(download_dir, download.suggested_filename)
                        download.save_as(saved_zip_path)

                        if zipfile.is_zipfile(saved_zip_path):
                            with zipfile.ZipFile(saved_zip_path, "r") as zip_ref:
                                zip_ref.extractall(download_dir)
                                extracted_files = zip_ref.namelist()
                            os.remove(saved_zip_path)
                            return os.path.join(download_dir, extracted_files[0]) if extracted_files else download_dir
                        return saved_zip_path
                except Exception:
                    pass

                if attempt < max_attempts:
                    logger.info(f"⏳ File not ready yet. Waiting {poll_interval}s before next attempt...")
                    for _ in range(poll_interval):
                        self._check_session_expired()
                        self.page.wait_for_timeout(1000)

        raise TimeoutError(f"Download link did not appear for Request IDs: {ids_to_try}")

    def wait_and_download_file(self, download_dir: str, poll_interval=60, refresh_limit=5, target_request_id: str = None, fallback_request_id: str = None) -> str:
        try:
            os.makedirs(download_dir, exist_ok=True)
        except Exception as e:
            fallback_dir = os.path.join(os.getcwd(), "downloads")
            logger.warning(f"⚠️ Cannot create '{download_dir}' ({e}). Falling back to: {fallback_dir}")
            os.makedirs(fallback_dir, exist_ok=True)
            download_dir = fallback_dir

        logger.info(f"Starting status polling (Poll Interval: {poll_interval}s | Refresh Limit: {refresh_limit})...")

        for refresh_count in range(refresh_limit + 1):
            if self.page.is_closed():
                raise ConnectionError("Browser window closed unexpectedly.")

            for frame in self.page.frames:
                try:
                    if frame.locator(self.locators["user_id_xpath"]).count() > 0:
                        raise ConnectionError("Session expired, redirected to login page.")
                except Exception:
                    pass

            for refresh_count in range(refresh_limit + 1):
                self._check_session_expired()

                # Check if download link appears directly on current page
                try:
                    download_element = self._find_element_anywhere(self.locators["download_link_xpath"], timeout=3000)
                    if download_element.count() > 0 and download_element.first.is_visible():
                        logger.info("✅ File generated! 'Click here to download' is active.")
                        
                        with self.page.expect_download(timeout=90000) as download_info:
                            download_element.first.evaluate("node => node.click()")
                        
                        download = download_info.value
                        saved_zip_path = os.path.join(download_dir, download.suggested_filename)
                        download.save_as(saved_zip_path)

                        extracted_files = []
                        if zipfile.is_zipfile(saved_zip_path):
                            with zipfile.ZipFile(saved_zip_path, "r") as zip_ref:
                                zip_ref.extractall(download_dir)
                                extracted_files = zip_ref.namelist()
                            
                            os.remove(saved_zip_path)
                            return os.path.join(download_dir, extracted_files[0]) if extracted_files else download_dir
                        else:
                            return saved_zip_path
                except ConnectionError:
                    raise
                except Exception:
                    pass

                if refresh_count >= refresh_limit:
                    break

                logger.info(
                    f"[Refresh {refresh_count + 1}/{refresh_limit}] Status is still 'Requested'. "
                    f"Waiting {poll_interval}s before refresh..."
                )
                
                for _ in range(poll_interval):
                    self._check_session_expired()
                    self.page.wait_for_timeout(1000)

            logger.info(f"Refreshing export status table ({refresh_count + 1}/{refresh_limit})...")
            try:
                search_btn = self._find_element_anywhere(self.locators["search_btn_xpath"], timeout=10000)
                search_btn.first.click(force=True)
                self.page.wait_for_timeout(4000)
            except Exception as e:
                logger.warning(f"⚠️ Search button interaction deferred ({e}).")

        # Refreshes finished without link: Switch to inquiry search using the OLD request ID
        if target_request_id:
            logger.warning(
                f"⚠️ Link did not appear on page after {refresh_limit} refreshes. "
                f"Switching to search using Target Request ID '{target_request_id}' without logging out..."
            )
            return self.download_by_request_id_search(
                primary_id=target_request_id,
                download_dir=download_dir,
                poll_interval=poll_interval,
                max_attempts=3,
                secondary_id=fallback_request_id
            )

        raise TimeoutError(f"File did not generate after {refresh_limit} refreshes and no Request ID was provided.")

    
    def logout(self):
        """Cleanly logs out of NSDL DPM to terminate server session and release maker user ID."""
        logger.info("🔒 Attempting clean Logout to release user session...")
        logout_xpath = self.locators["logout_btn_xpath"]

        try:
            logout_btn = self._find_element_anywhere(logout_xpath, timeout=5000)
            logout_btn.first.click(force=True)
            self.page.wait_for_timeout(2000)
            logger.info("✅ Successfully logged out. User ID released on server.")

        except Exception as e:
            logger.warning(f"⚠️ Logout interaction skipped or session already terminated: {e}")
