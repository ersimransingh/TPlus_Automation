import time
from pywinauto.keyboard import send_keys


class MainPage:

    def __init__(self, app):
        self.app = app
        self.window = app.top_window()

    def click_submenu_by_text(self, main_menu_name, submenu_item_name):
        """
        Robustly selects a submenu item by its exact text path.
        Keeps your JSON format intact by cleanly passing target strings directly.
        """
        import re
        from pywinauto.keyboard import send_keys
        print(f" 🖲️ Accessing Application Menu: {main_menu_name} -> {submenu_item_name}")
        
        try:
            # Connect directly to the main running window frame context
            main_window = self.app.window(title="TradePlusX")
            main_window.set_focus()
            time.sleep(0.5)
            
            # --- STRATEGY 1: Native Win32/UIA Menu Selection ---
            try:
                # pywinauto naturally chains paths split by '->'
                menu_path = f"{main_menu_name}->{submenu_item_name}"
                main_window.menu_select(menu_path)
                print(f" ✓ Menu accessed successfully via selection engine path.")
                return
            except Exception as select_err:
                print(f" ℹ️ Native menu path fell through ({select_err}), trying explicit keyboard interaction...")

            # --- STRATEGY 2: Keyboard Sequence Fallback (Extremely Reliable for WinForms) ---
            # 1. Open the top-level menu category via hotkeys (e.g., Alt + first letter of menu name)
            hotkey = f"%{main_menu_name[0].lower()}"  # Generates '%u' for Utilities (Alt+U)
            send_keys(hotkey)
            time.sleep(0.8)  # Let the dropdown populate fully on-screen
            
            # 2. Since dropdown contexts can float outside the window tree, send the name directly via keys 
            # This instantly jumps to and executes the item matching that exact string name
            send_keys(submenu_item_name)
            time.sleep(0.4)
            send_keys("{ENTER}")
            
            print(f" ✓ Successfully triggered menu component target: '{submenu_item_name}'")
            time.sleep(2.0)
            
        except Exception as e:
            print(f" ❌ Failed to select menu item '{submenu_item_name}' via all available methods: {e}")
            raise e