"""
Keyboard-based grid row finder + checkbox clicker.

CHANGE LOG (this revision):
Your last run showed:
    Grid headers detected: []
i.e. grid.descendants(control_type="HeaderItem") returned NOTHING, on two
different window handles. That means this grid does not expose its header
row as standard UIA HeaderItem elements (very common with WinForms apps
using a 3rd-party grid control like DevExpress/Infragistics, where the
header row is custom-painted and shows up under a different UIA
control_type, or sometimes doesn't show up as separate elements at all).

Because column-bounds lookup failed, EVERYTHING downstream failed silently:
no alignment, no row scan, straight fallback to the legacy "Download All"
flow -- which is why the real file never got matched/ticked.

This revision:
  1. Adds `_dump_grid_tree()` -- prints the ENTIRE descendant tree of the
     grid (control_type, class_name, auto_id, name/text, rectangle) the
     moment header detection fails, so you can see exactly what pywinauto
     sees and we can target the right control_type/auto_id next time.
  2. Widens `_get_column_bounds()` to try several strategies instead of
     only "HeaderItem":
       a) control_type="HeaderItem" (original)
       b) control_type="Header" -> its own children
       c) control_type in ("Text","Custom","Pane") that sit in the
          topmost row of the grid (smallest 'top' y among all descendants)
          and whose text matches the header fragment
  3. Also calls pywinauto's own `print_control_identifiers()` on the grid
     (best diagnostic tool pywinauto has -- dumps identifiers pywinauto
     would accept for child_window() lookups) wrapped in try/except so it
     never crashes the run.

Nothing about the mouse-click-the-focused-checkbox logic changed; only the
header/column discovery got more robust + more visible when it fails.
"""

import time
import ctypes
import win32gui
import win32process
import win32api
from pywinauto.keyboard import send_keys
from pywinauto.mouse import click as mouse_click
from pywinauto.uia_defines import IUIA
from pywinauto.uia_element_info import UIAElementInfo
from pywinauto.controls.uiawrapper import UIAWrapper


def get_focused_element():
    """Returns a UIAWrapper for whatever UI Automation element currently
    holds keyboard focus, anywhere on the desktop.
    """
    try:
        raw_elem = IUIA().iuia.GetFocusedElement()
        if raw_elem is None:
            return None
        return UIAWrapper(UIAElementInfo(raw_elem))
    except Exception as e:
        print(f"⚠️ Could not read focused UIA element: {e}", flush=True)
        return None


def _force_foreground(hwnd, settle=0.2):
    """Best-effort attempt to bring hwnd to the real OS foreground using the
    AttachThreadInput trick, which works around Windows' anti focus-stealing
    protection.
    """
    try:
        current_fg = win32gui.GetForegroundWindow()
        if current_fg == hwnd:
            return True

        current_thread_id = win32api.GetCurrentThreadId()
        fg_thread_id, _ = win32process.GetWindowThreadProcessId(current_fg)

        ctypes.windll.user32.AttachThreadInput(fg_thread_id, current_thread_id, True)
        try:
            win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            win32gui.SetForegroundWindow(hwnd)
        finally:
            ctypes.windll.user32.AttachThreadInput(fg_thread_id, current_thread_id, False)

        time.sleep(settle)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception as e:
        print(f"⚠️ _force_foreground failed: {e}", flush=True)
        return False


# ------------------------------------------------------------------
# Diagnostics -- these are the important additions
# ------------------------------------------------------------------

def _dump_grid_tree(grid, max_items=250):
    """Prints EVERY descendant of the grid element: control_type,
    class_name, automation_id, visible text, and screen rectangle.

    This is the ground truth of what pywinauto can actually see inside
    the grid. If HeaderItem lookups keep coming back empty, this output
    tells us what control_type the header cells really use (or whether
    they're exposed at all), so _get_column_bounds() can be pointed at
    the right thing.
    """
    print("🧭 [DIAGNOSTIC] Dumping full grid descendant tree "
          f"(max {max_items} items)...", flush=True)
    try:
        elems = grid.descendants()
        print(f"🧭 [DIAGNOSTIC] Total descendants found: {len(elems)}", flush=True)
        for i, el in enumerate(elems[:max_items]):
            try:
                ctrl_type = el.element_info.control_type
            except Exception:
                ctrl_type = "?"
            try:
                class_name = el.element_info.class_name
            except Exception:
                class_name = "?"
            try:
                auto_id = el.element_info.automation_id
            except Exception:
                auto_id = "?"
            try:
                text = el.window_text().strip()
            except Exception:
                text = ""
            try:
                rect = el.rectangle()
                rect_str = f"L{rect.left},T{rect.top},R{rect.right},B{rect.bottom}"
            except Exception:
                rect_str = "?"
            print(f"   [{i:03d}] type={ctrl_type!r} class={class_name!r} "
                  f"auto_id={auto_id!r} text={text!r} rect={rect_str}", flush=True)
    except Exception as e:
        print(f"⚠️ [DIAGNOSTIC] Failed to enumerate descendants: {e}", flush=True)

    # Also try pywinauto's own identifier dump -- shows what strings you
    # could legally pass to child_window(...) for this grid's children.
    try:
        print("🧭 [DIAGNOSTIC] print_control_identifiers() output below:", flush=True)
        grid.print_control_identifiers(depth=4)
    except Exception as e:
        print(f"⚠️ [DIAGNOSTIC] print_control_identifiers() failed: {e}", flush=True)


def _get_column_bounds(grid, header_name_fragment):
    """Finds the (left, right) screen-x bounds of a column by matching its
    header text. Tries multiple strategies since not all grids expose a
    standard UIA HeaderItem row:

      Strategy A: descendants(control_type="HeaderItem")
      Strategy B: descendants(control_type="Header") -> iterate ITS children
      Strategy C: any descendant (Text/Custom/Pane/etc.) whose text matches
                  AND whose vertical position is in the topmost band of the
                  grid (i.e. it's sitting in the header row, not a data row)

    Returns None if nothing matches under any strategy.
    """
    frag = header_name_fragment.strip().lower()

    # --- Strategy A: direct HeaderItem descendants ---
    try:
        headers = grid.descendants(control_type="HeaderItem")
        for h in headers:
            if frag in h.window_text().strip().lower():
                r = h.rectangle()
                return (r.left, r.right)
    except Exception as e:
        print(f"⚠️ Strategy A (HeaderItem) failed for '{header_name_fragment}': {e}", flush=True)

    # --- Strategy B: a "Header" container's children ---
    try:
        header_rows = grid.descendants(control_type="Header")
        for row in header_rows:
            for child in row.children():
                if frag in child.window_text().strip().lower():
                    r = child.rectangle()
                    return (r.left, r.right)
    except Exception as e:
        print(f"⚠️ Strategy B (Header container) failed for '{header_name_fragment}': {e}", flush=True)

    # --- Strategy C: text match in the topmost row band of the grid ---
    try:
        all_elems = grid.descendants()
        candidates = []
        for el in all_elems:
            try:
                text = el.window_text().strip()
                if not text:
                    continue
                rect = el.rectangle()
                if rect.height() <= 0 or rect.width() <= 0:
                    continue
                candidates.append((rect.top, text, rect))
            except Exception:
                continue

        if candidates:
            top_band = min(c[0] for c in candidates)
            # Anything within ~30px of the topmost element is "the header row"
            band_tolerance = 30
            for top, text, rect in candidates:
                if top <= top_band + band_tolerance and frag in text.lower():
                    return (rect.left, rect.right)
    except Exception as e:
        print(f"⚠️ Strategy C (top-band text match) failed for '{header_name_fragment}': {e}", flush=True)

    return None


def _print_all_headers(grid):
    """Debug helper: prints every header the grid actually exposes via the
    standard HeaderItem control_type, so you can see the real header
    names/order if a lookup fails. If this comes back empty, that alone
    is diagnostic -- it means this grid doesn't use HeaderItem, and
    _dump_grid_tree() will be triggered to show the real structure.
    """
    try:
        headers = grid.descendants(control_type="HeaderItem")
        names = [h.window_text().strip() for h in headers]
        print(f"ℹ️ Grid headers detected (HeaderItem): {names}", flush=True)
        return len(names) > 0
    except Exception as e:
        print(f"⚠️ Could not enumerate grid headers: {e}", flush=True)
        return False


def _current_cell_center_x():
    focused = get_focused_element()
    if focused is None:
        return None, None
    try:
        rect = focused.rectangle()
        return (rect.left + rect.right) // 2, focused
    except Exception:
        return None, focused


def _align_to_column(target_bounds, max_moves=15, settle=0.2):
    """Presses LEFT/RIGHT one step at a time, checking the ACTUAL pixel
    position of whatever is now focused after each press, until it falls
    inside target_bounds (left, right). This replaces guessing a fixed
    number of key presses.

    Returns True once aligned, False if it couldn't align within max_moves.
    """
    target_left, target_right = target_bounds
    for attempt in range(max_moves):
        cx, _ = _current_cell_center_x()
        if cx is None:
            send_keys("{RIGHT}")
            time.sleep(settle)
            continue
        if target_left <= cx <= target_right:
            return True
        if cx < target_left:
            send_keys("{RIGHT}")
        else:
            send_keys("{LEFT}")
        time.sleep(settle)

    cx, _ = _current_cell_center_x()
    return cx is not None and target_left <= cx <= target_right


def _row_matches(cell_text, pattern_config, extra_tokens=None):
    """True if cell_text satisfies any single pattern group (AND within the
    group), plus ALL extra_tokens (AND, applied on top of every group).
    """
    extra_tokens = [str(t).strip() for t in (extra_tokens or []) if t and str(t).strip()]

    for pattern in pattern_config or []:
        if isinstance(pattern, list):
            sub_tokens = [str(s).strip() for s in pattern if s and str(s).strip()]
        else:
            if not pattern or not str(pattern).strip():
                continue
            sub_tokens = [str(pattern).strip()]

        if not sub_tokens:
            continue

        group_ok = all(tok in cell_text for tok in sub_tokens)
        extras_ok = all(tok in cell_text for tok in extra_tokens)

        if group_ok and extras_ok:
            return True

    return False


def find_and_check_row_via_keyboard(report_win, pattern_config, grid_auto_id="Dt_dngrid",
                                     host_file_column_header="Host File Name",
                                     download_column_header="Download",
                                     max_rows=800, row_settle=0.45, initial_settle=0.3,
                                     extra_tokens=None):
    """Walks the grid row by row, verifying real column position via header
    bounds (not assumed key-press counts), until a Host File Name match is
    found. Then aligns to the Download column and mouse-clicks the checkbox
    there.

    Returns True if a matching row's checkbox was located and clicked.
    """
    if not pattern_config:
        print("ℹ️ No TARGET_FILE_PATTERN provided; nothing to match against.", flush=True)
        return False

    try:
        grid = report_win.child_window(auto_id=grid_auto_id, control_type="Table")
        if not grid.exists(timeout=6):
            print(f"⚠️ Grid with AutomationId '{grid_auto_id}' not found.", flush=True)
            return False
    except Exception as e:
        print(f"⚠️ Unable to locate grid '{grid_auto_id}': {e}", flush=True)
        return False

    # --- Force real OS foreground focus onto the app BEFORE sending any keys ---
    try:
        target_hwnd = report_win.handle
    except Exception:
        target_hwnd = None

    if target_hwnd:
        got_fg = _force_foreground(target_hwnd)
        print(f"ℹ️ Foreground window forced to app: {got_fg}", flush=True)

    try:
        grid.click_input()
    except Exception as e:
        print(f"⚠️ Could not click grid to force OS focus: {e}", flush=True)

    time.sleep(initial_settle)

    if target_hwnd:
        actual_fg = win32gui.GetForegroundWindow()
        if actual_fg != target_hwnd:
            print(f"⚠️ WARNING: foreground window (hwnd={actual_fg}) still does not "
                  f"match target app (hwnd={target_hwnd}). Avoid touching your "
                  f"keyboard/mouse while this runs.", flush=True)

    # --- Resolve real column boundaries from the header row ---
    had_header_items = _print_all_headers(grid)

    host_bounds = _get_column_bounds(grid, host_file_column_header)
    download_bounds = _get_column_bounds(grid, download_column_header)

    if host_bounds is None or download_bounds is None:
        if not had_header_items:
            print("⚠️ HeaderItem lookup returned nothing AND fallback strategies "
                  "could not resolve column bounds either. Dumping full grid tree "
                  "so we can see the real structure:", flush=True)
        _dump_grid_tree(grid)

    if host_bounds is None:
        print(f"⚠️ Could not resolve '{host_file_column_header}' column header bounds. "
              f"Check the diagnostic dump above and adjust host_file_column_header "
              f"if the real name differs, or hardcode bounds based on the printed "
              f"rectangles.", flush=True)
        return False

    if download_bounds is None:
        print(f"⚠️ Could not resolve '{download_column_header}' column header bounds. "
              f"Check the diagnostic dump above and adjust download_column_header "
              f"if the real name differs, or hardcode bounds based on the printed "
              f"rectangles.", flush=True)
        return False

    print(f"ℹ️ '{host_file_column_header}' column x-bounds: {host_bounds}", flush=True)
    print(f"ℹ️ '{download_column_header}' column x-bounds: {download_bounds}", flush=True)

    # Return to row 1: HOME (leftmost cell in current row), then UP repeatedly
    # to guarantee we reach the very first row regardless of where the
    # initial click landed.
    send_keys("{HOME}")
    time.sleep(row_settle)
    send_keys("{UP}" * 60)
    time.sleep(row_settle)

    print(f"🔎 Aligning to '{host_file_column_header}' column...", flush=True)
    if not _align_to_column(host_bounds, settle=row_settle):
        print(f"⚠️ Could not align to '{host_file_column_header}' column after multiple attempts.", flush=True)
        return False

    print(f"🔎 Scanning '{host_file_column_header}' column (row_settle={row_settle}s)...", flush=True)
    if extra_tokens:
        print(f"   (additionally requiring: {extra_tokens})", flush=True)

    matched = False
    for row_num in range(1, max_rows + 1):
        focused = get_focused_element()
        cell_text = ""
        if focused is not None:
            try:
                cell_text = focused.window_text().strip()
            except Exception:
                cell_text = ""

        if cell_text:
            print(f"   row {row_num}: '{cell_text}'", flush=True)
        else:
            print(f"   row {row_num}: <empty/unreadable>", flush=True)

        if cell_text and _row_matches(cell_text, pattern_config, extra_tokens):
            print(f"🎯 Match found at row {row_num}: '{cell_text}'", flush=True)
            matched = True
            break

        send_keys("{DOWN}")
        time.sleep(row_settle)

        # Safety: re-verify we're still in the Host File Name column, in case
        # DOWN ever drifts the focused column (defensive, cheap check).
        cx, _ = _current_cell_center_x()
        if cx is not None and not (host_bounds[0] <= cx <= host_bounds[1]):
            print(f"   ↺ Drifted out of '{host_file_column_header}' column, re-aligning...", flush=True)
            _align_to_column(host_bounds, settle=row_settle)
    else:
        print(f"⚠️ Reached max_rows ({max_rows}) without finding a matching row.", flush=True)
        return False

    if not matched:
        return False

    print(f"🔎 Aligning to '{download_column_header}' column to click checkbox...", flush=True)
    if not _align_to_column(download_bounds, settle=row_settle):
        print(f"⚠️ Could not align to '{download_column_header}' column after multiple attempts.", flush=True)
        return False

    checkbox_elem = get_focused_element()
    if checkbox_elem is None:
        print("⚠️ Could not resolve focused checkbox element after aligning.", flush=True)
        return False

    try:
        rect = checkbox_elem.rectangle()
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        mouse_click(button='left', coords=(cx, cy))
        time.sleep(0.3)
        print(f"✓ Checkbox clicked via mouse at focused element coords ({cx}, {cy}).", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ Failed to mouse-click checkbox at focused coords: {e}", flush=True)
        return False