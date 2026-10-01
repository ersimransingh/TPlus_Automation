"""Self-test harness: runs handle_administration's click_import radar against fakes.

Simulates the four client scenarios the radar must distinguish:
  1. frozen app that later unfreezes (silent success, no popup)
  2. result popup appearing (new PID window)
  3. app dying mid-import with more steps configured -> crash report
  4. app exiting after the FINAL import step -> treated as completion
"""
import sys, os, traceback

PAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "activity", "pages")
sys.path.insert(0, PAGES)

import administration_page as ap

# ---------------------------------------------------------------- fakes
STATE = {"tick": 0, "pid_windows": [], "popup_exists": False}
LOGS, MAILS, SHOTS = [], [], []

class FakeTime:
    vclock = None  # optional virtual clock (advanced by sleep) for timed-log scenarios
    @staticmethod
    def sleep(s):
        if FakeTime.vclock is not None:
            FakeTime.vclock += s
    @staticmethod
    def time():
        if FakeTime.vclock is not None:
            return FakeTime.vclock
        import time as _t; return _t.time()

class FakeSpec:
    def __init__(self, name="child"):
        self.name = name
    def child_window(self, **kw): return FakeSpec("child")
    def window(self, **kw): return FakeSpec("popup")
    def exists(self, timeout=None, retry_interval=None):
        STATE["tick"] += 1
        return STATE.get(self.name + "_exists", True)
    def is_enabled(self): return STATE.get(self.name + "_enabled", True)
    def set_focus(self): pass
    def click(self): pass
    def click_input(self, **kw): STATE.setdefault("clicks", []).append(self.name)
    def type_keys(self, *a, **kw): pass
    def wait(self, *a, **kw): pass
    def wrapper_object(self): return self
    def window_text(self):
        if self.name == "popup":
            return STATE.get("popup_title", "Cross")
        return "Cross - DP Back office Software"
    def process_id(self): return 4242
    def menu_select(self, *a, **kw):
        if STATE.get("menu_select_raises"):
            raise RuntimeError("simulated native menu failure")
    def descendants(self, control_type=None, **kw):
        if control_type == "MenuItem":
            return list(STATE.get("menu_items", []))
        if self.name == "popup":
            if control_type == "Text":
                return [FakeWin(t) for t in STATE.get("popup_texts", [])]
            if control_type == "Button":
                return [FakeWin(t) for t in STATE.get("popup_buttons", [])]
        return []

class _FakeElemInfo:
    def __init__(self, aid): self.automation_id = aid

class FakeWin:
    def __init__(self, title, auto_id=""):
        self._t = title
        self.element_info = _FakeElemInfo(auto_id)
    def window_text(self): return self._t
    def click_input(self, **kw): STATE.setdefault("menu_clicks", []).append(self._t)

class FakeDesktop:
    def __init__(self, backend=None): pass
    def windows(self, process=None, **kw):
        # pid_windows entries may be plain titles (wrapped) or pre-built FakeSpec dialogs
        return [item if isinstance(item, FakeSpec) else FakeWin(item)
                for item in STATE["pid_windows"]]
    def window(self, **kw): return FakeSpec("popup")

class LogRec:
    def _l(self, lvl, msg): LOGS.append((lvl, msg))
    def info(self, m): self._l("INFO", m)
    def warning(self, m): self._l("WARN", m)
    def error(self, m, *a, **kw): self._l("ERROR", m)
    def critical(self, m): self._l("CRIT", m)
    def debug(self, m): pass

ap.time = FakeTime
ap.Desktop = FakeDesktop
ap.logger = LogRec()
ap.send_batch_report_email = lambda **kw: MAILS.append(kw)
ap.capture_screenshot = lambda p: (SHOTS.append(p), p)[1]
KEYS = []
ap.send_keys = lambda *a, **kw: KEYS.append(a)

MAIN, CHILD = "Cross - DP Back office Software", "Import File"
BASELINE = [MAIN, CHILD]
IMPORT_STEP = {"action": "click_import", "control_type": "Button", "description": "Click Final Import Button"}
NEXT_STEP = {"action": "wait_for_table", "control_type": "Pane", "description": "Wait for grid"}

def reset():
    STATE.clear(); STATE.update({"tick": 0, "pid_windows": list(BASELINE), "popup_exists": False})
    LOGS.clear(); MAILS.clear(); SHOTS.clear()
    ap._real_alive = ap._is_process_alive

def has_log(fragment):
    return any(fragment in m for _, m in LOGS)

def run(steps):
    ap.handle_administration(FakeSpec("main"), {"steps": steps}, process_name="SelfTest")

# ---------------------------------------------------------------- scenarios
alive = lambda pid: True

# 1) frozen -> unfreeze via import window
reset(); ap._is_process_alive = alive
ap._orig_exists = FakeSpec.exists
def frozen_then_ok(self, timeout=None, retry_interval=None):
    STATE["tick"] += 1
    if self.name == "popup":
        return False
    return STATE["tick"] > 6            # frozen for first polls, then resolvable
FakeSpec.exists = frozen_then_ok
try:
    run([IMPORT_STEP, NEXT_STEP]); ok1 = has_log("responsive again")
except Exception as e: ok1 = False; traceback.print_exc()
FakeSpec.exists = ap._orig_exists

# 2) popup appears (new PID window)
reset(); ap._is_process_alive = alive
def popup_later(self, timeout=None, retry_interval=None):
    STATE["tick"] += 1
    if self.name == "popup":
        return False
    if STATE["tick"] == 4:
        STATE["pid_windows"].append("File Imported (Success)")
    return False                         # window never 'unfreezes' via this probe
FakeSpec.exists = popup_later
try:
    run([IMPORT_STEP, NEXT_STEP]); ok2 = has_log("completion dialog detected")
except Exception as e: ok2 = False; traceback.print_exc()
FakeSpec.exists = ap._orig_exists

# 3) app dies mid-import, more steps remain -> crash path
reset(); ap._is_process_alive = lambda pid: False
try:
    run([IMPORT_STEP, NEXT_STEP]); ok3 = False; print("FAIL: no RuntimeError raised")
except RuntimeError as e:
    ok3 = ("terminated during import" in str(e)
           and any("CRITICAL ERROR" in m.get("default_subject", "") for m in MAILS)
           and len(SHOTS) == 1)
except Exception as e: ok3 = False; traceback.print_exc()

# 3b) app dies but import window closes + main window responsive would beat death? no - dead is dead; skipped.

# 4) app exits after FINAL import step -> completion, no raise
reset(); ap._is_process_alive = lambda pid: False
try:
    run([IMPORT_STEP]); ok4 = has_log("treating as completed") and not MAILS
except Exception as e: ok4 = False; traceback.print_exc()

# 5) client whose app CLOSES the import dialog after click: unfreeze must be
#    detected via the main window fallback probe (no popup ever appears)
reset(); ap._is_process_alive = alive
STATE["child_exists"] = False            # import dialog gone
STATE["popup_exists"] = False
try:
    run([IMPORT_STEP, NEXT_STEP]); ok5 = has_log("responsive again")
except Exception as e: ok5 = False; traceback.print_exc()

# 6) "Do you want to close?" popup appears during click_ok: the automation must
#    REFUSE to click Yes / send ENTER, log EXIT-TRACE + evidence, not kill the app
reset(); ap._is_process_alive = alive
STATE["pid_windows"] = ["Cross - DP Back office Software", FakeSpec("popup")]
STATE["popup_title"] = "Cross"
STATE["popup_texts"] = ["Do you want to close the application?"]
STATE["popup_buttons"] = ["&Yes", "&No"]
CLICK_OK_STEP = {"action": "click_ok", "control_type": "Button", "description": "Click OK Button to Confirm Import"}
try:
    run([CLICK_OK_STEP])
    ok6 = (has_log("[EXIT-TRACE]") and has_log("REFUSING")
           and not KEYS and not STATE.get("clicks"))
except Exception as e: ok6 = False; traceback.print_exc()

# 6b) SUCCESS dialog titled 'Cross' (same as app) after import: click_ok must
#     find it via window enumeration and click its OK button
reset(); ap._is_process_alive = alive
STATE["pid_windows"] = ["Cross - DP Back office Software", FakeSpec("popup")]
STATE["popup_title"] = "Cross"
STATE["popup_texts"] = ["File Imported Successfully"]
STATE["popup_buttons"] = ["OK"]
class OkBtn(FakeSpec):
    def exists(self, timeout=None, retry_interval=None): return True
    def window_text(self): return "OK"
_orig_child = FakeSpec.child_window
def child_with_ok(self, **kw):
    c = FakeSpec("btn")
    c.exists = lambda timeout=None, retry_interval=None: True
    c.window_text = lambda: "OK"
    c.click_input = lambda **kw: STATE.setdefault("clicks", []).append("OK")
    return c
FakeSpec.child_window = child_with_ok
try:
    run([CLICK_OK_STEP])
    ok6b = ("OK" in STATE.get("clicks", []) and not KEYS)
except Exception as e: ok6b = False; traceback.print_exc()
FakeSpec.child_window = _orig_child

# 7) menu navigation: native menu_select fails -> dynamic UIA clicking of each
#    menu item must work WITHOUT title_re (unsupported by bundled pywinauto),
#    including DUPLICATE titles AND duplicate AutoIDs (occurrence index 0)
reset(); ap._is_process_alive = alive
STATE["menu_select_raises"] = True
STATE["menu_items"] = [FakeWin("Administration"), FakeWin("Reports"),
                       FakeWin("Utilities"), FakeWin("Utilities"),
                       FakeWin("Import", auto_id="226"), FakeWin("Import", auto_id="226")]
MENU_STEPS = [
    {"action": "click", "control_type": "MenuItem", "description": "Click Administration Menu Item", "name": "Administration"},
    {"action": "click", "control_type": "MenuItem", "description": "Click Utilities Menu Item", "name": "Utilities", "class_occurrence_index": 0},
    {"action": "click", "control_type": "MenuItem", "description": "Click Import Menu Item", "automation_id": "226"},
]
try:
    ap.handle_administration(FakeSpec("main"), {"steps": MENU_STEPS}, process_name="SelfTest")
    clicks = STATE.get("menu_clicks", [])
    ok7 = (has_log("Successfully completed dynamic menu sequence.")
           and "Administration" in clicks and "Utilities" in clicks and "Import" in clicks
           and has_log("matched 2 elements")
           and not has_log("Dynamic UIA menu selection failed"))
except Exception as e: ok7 = False; traceback.print_exc()

# 8) ISIN-style import delegated to a helper exe (CSVTransformer console): the
#    radar must WAIT for the helper process to exit before proceeding, even
#    though the main window stays 'enabled' the whole time
reset(); ap._is_process_alive = alive
import time as _real_time
FakeTime.vclock = _real_time.time()
_helper_calls = {"n": 0}
def fake_children(pid):
    _helper_calls["n"] += 1
    if 2 <= _helper_calls["n"] <= 14:   # baseline call first, helper then for ~13s
        return {3392: "CSVTransformer.exe"}
    return {}
ap._get_child_processes = fake_children
try:
    run([IMPORT_STEP, NEXT_STEP])
    ok8 = (has_log("helper process still running") and has_log("responsive again"))
except Exception as e: ok8 = False; traceback.print_exc()
FakeTime.vclock = None

print()
print(f"scenario 1 (unfreeze silent success):  {'PASS' if ok1 else 'FAIL'}")
print(f"scenario 2 (popup detected):           {'PASS' if ok2 else 'FAIL'}")
print(f"scenario 3 (crash reported cleanly):   {'PASS' if ok3 else 'FAIL'}")
print(f"scenario 4 (final-step exit = done):   {'PASS' if ok4 else 'FAIL'}")
print(f"scenario 5 (dialog closed, main win):  {'PASS' if ok5 else 'FAIL'}")
print(f"scenario 6 (exit-dialog refusal):      {'PASS' if ok6 else 'FAIL'}")
print(f"scenario 6b (Cross-titled OK dialog):  {'PASS' if ok6b else 'FAIL'}")
print(f"scenario 7 (dynamic menu traversal):   {'PASS' if ok7 else 'FAIL'}")
print(f"scenario 8 (helper-process wait):      {'PASS' if ok8 else 'FAIL'}")
sys.exit(0 if (ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok6b and ok7 and ok8) else 1)
