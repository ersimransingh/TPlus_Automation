import os
import json
import time
from pywinauto import Application
from pywinauto.keyboard import send_keys

def load_config_profile(filename):
    """Safely handles reading specific JSON profile data maps from the root workspace."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_path = os.path.join(base_dir, filename)
    
    if not os.path.exists(target_path):
        target_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Critical configuration initialization map missing: {filename}")
        
    with open(target_path, "r", encoding="utf-8") as f:
        return json.load(f)

def execute_report_setup_form():
    print("\n--- Initializing Report Setup Form Automation Pipeline ---")
    try:
        import sys
        if 'active_runtime_config' in sys.modules:
            config_data = sys.modules['active_runtime_config']
        else:
            from activity.App import load_task_toggles
            config_data = load_task_toggles()
            
        # Change line 34 in pages/report_setup.py to:
        active_process_name = os.environ.get("ACTIVE_TASK_ID", "process_01").strip().lower()
        
        # Case-insensitive key lookup for active_process_name
        task_profile = {}
        for k, v in config_data.items():
            if str(k).strip().lower() == active_process_name:
                task_profile = v
                break

        setup_tasks = (
            task_profile.get("setup_tasks") or 
            task_profile.get("SETUP_TASKS") or 
            config_data.get("setup_tasks") or 
            config_data.get("SETUP_TASKS", [])
        )
        
        if not setup_tasks:
            print("Warning: No active tasks defined inside the 'setup_tasks' configuration array.")
            return False
            
        total_tasks = len(setup_tasks)
        print(f"Discovered total setup task entries: {total_tasks}")

        browser_app = Application(backend="uia").connect(title_re=".*Microsoft​ Edge.*|.*Edge.*", timeout=5)
        browser_win = browser_app.top_window()
        browser_win.set_focus()
        time.sleep(1.0)

        web_document = browser_win.child_window(title="Reports", auto_id="RootWebArea", control_type="Document")
        if not web_document.exists(timeout=5):
            print("Error: Could not locate the 'Reports' document area inside the browser window.")
            return False

        print("Synchronizing tab input focus metrics...")
        web_document.click_input()
        time.sleep(0.5)

        for index, task in enumerate(setup_tasks, start=1):
            module_id = str(task.get("module_id") or task.get("MODULE_ID", "")).strip()
            report_id = str(task.get("report_id") or task.get("REPORT_ID", "")).strip()
            date_from = str(task.get("business_date_from") or task.get("BUSINESS_DATE_FROM", "")).strip()
            date_to = str(task.get("business_date_to") or task.get("BUSINESS_DATE_TO", "")).strip()
            report_type_target = str(task.get("report_type") or task.get("REPORT_TYPE", "Incremental")).strip()
            
            print(f"\n--- [Setup Task {index}/{total_tasks}] Processing Module: {module_id} | Report: {report_id} ---")

            # Ensure document area is focused for each task iteration
            web_document.click_input()
            time.sleep(0.3)

            # --- Fill Module ID ---
            module_field = web_document.child_window(auto_id="txtSelectModule", control_type="Edit")
            module_field.click_input()
            time.sleep(0.2)
            send_keys("^a{BACKSPACE}")
            time.sleep(0.1)
            if module_id:
                send_keys(module_id, with_spaces=True)
            time.sleep(0.2)

            # --- Fill Report ID ---
            report_field = web_document.child_window(auto_id="txtSelectReport", control_type="Edit")
            report_field.click_input()
            time.sleep(0.2)
            send_keys("^a{BACKSPACE}")
            time.sleep(0.1)
            if report_id:
                send_keys(report_id, with_spaces=True)
            time.sleep(0.2)

            # --- Fill Business Date From ---
            date_from_field = web_document.child_window(auto_id="dtBusinessFromDate", control_type="Edit")
            date_from_field.click_input()
            time.sleep(0.2)
            send_keys("^a{BACKSPACE}")
            time.sleep(0.1)
            if date_from:
                send_keys(date_from, with_spaces=True)
            time.sleep(0.2)

            # --- Fill Business Date To ---
            date_to_field = web_document.child_window(auto_id="dtBusinessToDate", control_type="Edit")
            date_to_field.click_input()
            time.sleep(0.2)
            send_keys("^a{BACKSPACE}")
            time.sleep(0.1)
            if date_to:
                send_keys(date_to, with_spaces=True)
            time.sleep(0.4)

            # --- Trigger Setup Button ---
            setup_btn = web_document.child_window(title="Setup", auto_id="btnReportSetup", control_type="Button")
            if not setup_btn.exists(timeout=3):
                print(f"❌ Error: 'Setup' button not found for Task {index}.")
                continue

            print("-> Dispatching Setup selection commands...")
            report_criteria_label = web_document.child_window(title="Report Criteria", control_type="Text")
            
            panel_loaded = False
            for attempt in range(1, 4):  # Try clicking up to 4 times
                try:
                    # Optional: .invoke() is often more reliable than .click_input() for UIA browser buttons
                    setup_btn.invoke() 
                except Exception:
                    # Fallback to physical click if invoke isn't supported by the element
                    setup_btn.click_input()
                
                print(f"   [Attempt {attempt}] Waiting for Report Criteria panel...")
                
                # Wait up to 4 seconds for the panel to appear after the click
                if report_criteria_label.exists(timeout=4):
                    panel_loaded = True
                    break
                    
                # Brief pause before the next click attempt
                time.sleep(1.0) 

            if not panel_loaded:
                print(f"❌ Error: 'Report Criteria' panel failed to render for Task {index}.")
                continue
                
            print("-> Verification sequence active: Report Criteria panel detected!")

            # --- Handle Report Type Selection ---
            report_dropdown = web_document.child_window(auto_id="statusselect", control_type="ComboBox")
            rdb_incremental = web_document.child_window(auto_id="rdbReportFileUploadIncremental", control_type="RadioButton")
            rdb_full = web_document.child_window(auto_id="rdbReportFileUploadFull", control_type="RadioButton")

            if report_dropdown.exists(timeout=1):
                report_dropdown.click_input()
                time.sleep(0.5)
                if report_type_target.lower() == "full":
                    send_keys("Incremental{ENTER}", with_spaces=True)
                    time.sleep(0.8)
                    report_dropdown.click_input()
                    time.sleep(0.5)
                    send_keys("Full{ENTER}", with_spaces=True)
                else:
                    send_keys("Incremental{ENTER}", with_spaces=True)
                time.sleep(1.0)

            elif rdb_incremental.exists(timeout=1) or rdb_full.exists(timeout=1):
                if report_type_target.lower() == "full":
                    rdb_full.click_input()
                else:
                    rdb_incremental.click_input()
                time.sleep(1.0)

            # --- Commit Transaction ---
            commit_btn = web_document.child_window(title="Commit", auto_id="btnCD97ReportCommit", control_type="Button")
            if not commit_btn.exists():
                commit_btn = web_document.child_window(title="Commit", auto_id="btnSB01ReportCommit", control_type="Button")

            if commit_btn.exists():
                commit_btn.click_input()
                time.sleep(2.0)

                # Pop-up 1: Confirmation
                try:
                    confirm_popup = browser_app.top_window()
                    yes_button = confirm_popup.child_window(title="Yes", control_type="Button")
                    if yes_button.exists(timeout=3):
                        yes_button.click_input()
                        time.sleep(2.0)
                except Exception:
                    send_keys("{ENTER}")
                    time.sleep(2.0)

                # Pop-up 2: Success Message
                try:
                    success_popup = browser_app.top_window()
                    ok_button = success_popup.child_window(title="OK", control_type="Button")
                    if ok_button.exists(timeout=3):
                        ok_button.click_input()
                        time.sleep(2.0)
                except Exception:
                    send_keys("{ENTER}")
                    time.sleep(2.0)

                print(f"✓ Setup Task {index}/{total_tasks} finalized successfully.")
            else:
                print(f"❌ Error: Unable to locate 'Commit' button for Task {index}.")

            time.sleep(1.5)

        print("\n✓ All configuration setup workflow tasks processed successfully!")
        return True

    except Exception as err:
        print(f"\n[Setup Process Interrupt Failure]: {err}")
        return False

if __name__ == "__main__":
    execute_report_setup_form()
    