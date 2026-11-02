import os
import sys
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

from date_engine import resolve_date
from utils.security_manager import SecurityManager
from utils.browser_manager import BrowserManager
from pages.nsdl_login_page import LoginPage
from pages.nsdl_dashboard_page import DashboardPage
from logger_config import setup_logger

logger = setup_logger()

REQ_TRACKER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule_log", "nsdl_request_history.json")

def get_previous_request_id(proc_key: str) -> str:
    """Retrieves the request ID generated earlier today, if any exists."""
    if not os.path.exists(REQ_TRACKER_FILE):
        return None
    try:
        with open(REQ_TRACKER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data.get(proc_key, {})
        if entry.get("date") == datetime.now().strftime("%Y-%m-%d"):
            return entry.get("current_request_id")
    except Exception:
        pass
    return None

def record_request_ids(proc_key: str, req_id: str):
    """Saves the pending Request ID for today in nsdl_request_history.json."""
    if not req_id:
        return
    try:
        os.makedirs(os.path.dirname(REQ_TRACKER_FILE), exist_ok=True)
        data = {}
        if os.path.exists(REQ_TRACKER_FILE):
            with open(REQ_TRACKER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

        data[proc_key] = {
            "current_request_id": str(req_id).strip(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }

        with open(REQ_TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"💾 Recorded Pending Request ID -> '{req_id}'")
    except Exception as e:
        logger.warning(f"⚠️ Failed to record request ID: {e}")

def clear_request_history(proc_key: str):
    """Clears tracked IDs on successful download."""
    try:
        if os.path.exists(REQ_TRACKER_FILE):
            with open(REQ_TRACKER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if proc_key in data:
                del data[proc_key]
                with open(REQ_TRACKER_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
    except Exception:
        pass

def execute_nsdl_process(proc_key: str, proc_config: dict, master_config: dict) -> tuple[bool, str]:
    global_settings = master_config.get("global_app_settings", {})
    locators = master_config.get("locators", {})
    
    module_name = proc_config.get("module_name", proc_key)
    report_type = proc_config.get("report_type", "Full")
    
    # 1. Date resolution via date_engine
    date_from_token = proc_config.get("business_date") or proc_config.get("business_date_from")
    date_to_token = proc_config.get("business_date") or proc_config.get("business_date_to")
    
    date_from = resolve_date(date_from_token).strftime("%d/%m/%Y") if date_from_token else None
    date_to = resolve_date(date_to_token).strftime("%d/%m/%Y") if date_to_token else None
    
    # 2. Download directory setup
    base_path = proc_config.get("main_path", global_settings.get("main_download_path", "C:\\NSDLFILES"))
    folder_date = resolve_date(date_from_token or "t").strftime("%Y-%m-%d")
    save_dir = os.path.join(base_path, folder_date)
    os.makedirs(save_dir, exist_ok=True)

    poll_sec = proc_config.get("poll_interval_seconds", global_settings.get("poll_interval_seconds", 60))
    refresh_limit = proc_config.get("refresh_limit", global_settings.get("refresh_limit", 3))

    raw_pwd = global_settings.get("app_password_enc", "")
    decoded_password = SecurityManager.decode_base64(raw_pwd)

    # Check if a pending Request ID already exists from an earlier failed attempt today
    pending_request_id = get_previous_request_id(proc_key)

    logger.info("=" * 60)
    logger.info(f"▶️ Starting NSDL Task: {proc_key} ({module_name})")
    if pending_request_id:
        logger.info(f"📌 Pending Request ID found: '{pending_request_id}'. Will skip form submission and go directly to Status/Search.")
    logger.info(f"   Date Range: {date_from} to {date_to} | Poll: {poll_sec}s | Limit: {refresh_limit}")
    logger.info(f"   Download Directory: {save_dir}")
    logger.info("=" * 60)

    with sync_playwright() as p:
        browser, context = BrowserManager.launch_clean_edge(p, base_download_path=base_path)
        page = context.new_page()
        dashboard_page = None

        try:
            # Step A: Formal Login
            login_page = LoginPage(page, locators)
            login_page.navigate(global_settings["url"])
            login_page.login(global_settings["user_id"], decoded_password)

            dashboard_page = DashboardPage(page, locators)

            # =================================================================
            # BRANCH 1: Pending Request ID exists -> Skip New Request & Search
            # =================================================================
            if pending_request_id:
                logger.info(f"🔄 Resuming download for existing Request ID: '{pending_request_id}'...")
                downloaded_file = dashboard_page.download_by_request_id_search(
                    primary_id=pending_request_id,
                    download_dir=save_dir,
                    poll_interval=poll_sec,
                    max_attempts=refresh_limit
                )

            # =================================================================
            # BRANCH 2: No Pending ID -> Submit Fresh Export Request
            # =================================================================
            else:
                # Step B: Formal Navigation
                dashboard_page.navigate_to_master_module(module_name=module_name)

                # Step C: Formal Form Submission & Capture Fresh ID
                fresh_request_id = dashboard_page.process_export_form(
                    module_name=module_name,
                    report_type=report_type,
                    date_from=date_from,
                    date_to=date_to
                )

                # Step D: Record fresh ID to disk immediately in case download times out
                record_request_ids(proc_key, req_id=fresh_request_id)

                # Step E: Wait & Download (falls back to inquiry search with fresh_request_id if needed)
                downloaded_file = dashboard_page.wait_and_download_file(
                    download_dir=save_dir,
                    poll_interval=poll_sec,
                    refresh_limit=refresh_limit,
                    target_request_id=fresh_request_id
                )

            # Clean up history file ONLY when download succeeds
            clear_request_history(proc_key)
            logger.info(f"✅ Success: {module_name} -> {downloaded_file}")
            return True, ""

        except Exception as err:
            logger.error(f"❌ Failed: {module_name} error: {err}")
            return False, str(err)

        finally:
            try:
                if dashboard_page and not page.is_closed():
                    dashboard_page.logout()
            except Exception:
                pass

            try:
                if not page.is_closed():
                    page.close()
                context.close()
                browser.close()
            except Exception:
                pass