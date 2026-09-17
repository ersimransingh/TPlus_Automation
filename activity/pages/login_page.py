import time


class LoginPage:

    def __init__(self, app):
        self.window = app.top_window()

    def login(self, username, password):
        # 1. Ensure the window is popped up and active
        self.window.wait("ready", timeout=30)
        self.window.set_focus()
        time.sleep(1)

        print(
            f"DEBUG: Attempting login with Username: '{username}' (Length: {len(str(username))})"
        )

        # Isolate edit controls safely
        username_field = self.window.child_window(
            control_type="Edit", found_index=0
        )
        password_field = self.window.child_window(
            control_type="Edit", found_index=1
        )

        # --- USERNAME FIELD PROCESS ---
        print("Clicking and focusing Username field...")
        # Cleanly double click to highlight existing text natively
        username_field.double_click_input()
        username_field.set_focus()
        time.sleep(0.5)

        # Corrected: Removed 'protect_first' keyword argument
        username_field.type_keys("^a{BACKSPACE}")
        time.sleep(0.5)

        # Type the username string character-by-character
        print("Typing username...")
        username_field.type_keys(username, with_spaces=True, pause=0.08)
        time.sleep(1)

        # --- PASSWORD FIELD PROCESS ---
        print("Clicking and focusing Password field...")
        password_field.double_click_input()
        password_field.set_focus()
        time.sleep(0.5)

        # Corrected: Removed 'protect_first' keyword argument
        password_field.type_keys("^a{BACKSPACE}")
        time.sleep(0.5)

        print("Typing password...")
        password_field.type_keys(password, with_spaces=True, pause=0.08)
        time.sleep(1)

        # --- SUBMIT ---
        print("Clicking Login Button...")
        self.window.child_window(
            title="Login", control_type="Button"
        ).click_input()
        time.sleep(3)