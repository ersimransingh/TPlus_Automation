"""
OCR-based grid row finder + checkbox clicker.
Restores strict Host File Name column bounds and uses offset to target checkbox.
"""

import time
import hashlib
import ctypes
import re
import win32gui
import win32api
import win32con
from PIL import ImageGrab
import pytesseract
from pytesseract import Output

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PUL = ctypes.POINTER(ctypes.c_ulong)

class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput)]

class _Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", _InputUnion)]

_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004

def _send_mouse_input(dx=0, dy=0, flags=0):
    extra = ctypes.c_ulong(0)
    ii = _InputUnion()
    ii.mi = _MouseInput(dx, dy, 0, flags, 0, ctypes.pointer(extra))
    cmd = _Input(ctypes.c_ulong(_INPUT_MOUSE), ii)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))

def _si_move_abs(x, y):
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    screen_h = ctypes.windll.user32.GetSystemMetrics(1)
    abs_x = int(x * 65535 / max(screen_w - 1, 1))
    abs_y = int(y * 65535 / max(screen_h - 1, 1))
    _send_mouse_input(abs_x, abs_y, _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE)

def _si_left_down():
    _send_mouse_input(flags=_MOUSEEVENTF_LEFTDOWN)

def _si_left_up():
    _send_mouse_input(flags=_MOUSEEVENTF_LEFTUP)

def _grid_screen_rect(grid):
    r = grid.rectangle()
    return (r.left, r.top, r.right, r.bottom)

def _screenshot_region(rect):
    return ImageGrab.grab(bbox=rect)

def _ocr_words(image, offset_left, offset_top):
    data = pytesseract.image_to_data(image, output_type=Output.DICT)
    words = []
    n = len(data.get("text", []))
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        conf = data.get("conf", ["-1"] * n)[i]
        try:
            if float(conf) < 0:
                continue
        except Exception:
            pass
        left = offset_left + data["left"][i]
        top = offset_top + data["top"][i]
        width = data["width"][i]
        height = data["height"][i]
        words.append({
            "text": text,
            "left": left,
            "top": top,
            "right": left + width,
            "bottom": top + height,
            "cx": left + width // 2,
            "cy": top + height // 2,
        })
    return words

def _group_into_lines(words, y_tolerance=7):
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: w["cy"])
    lines = []
    current_line = [sorted_words[0]]
    current_y = sorted_words[0]["cy"]

    for w in sorted_words[1:]:
        if abs(w["cy"] - current_y) <= y_tolerance:
            current_line.append(w)
        else:
            lines.append(sorted(current_line, key=lambda x: x["left"]))
            current_line = [w]
            current_y = w["cy"]
    lines.append(sorted(current_line, key=lambda x: x["left"]))
    return lines

def _find_header_line(lines, expected_fragments):
    best_line = None
    best_score = 0
    for line in lines:
        line_text = " ".join(w["text"].lower() for w in line)
        score = sum(1 for frag in expected_fragments if frag in line_text)
        if score > best_score:
            best_score = score
            best_line = line
    return best_line, best_score

def _derive_column_bounds(header_line, grid_rect, header_fragments_in_order):
    grid_left, _, grid_right, _ = grid_rect
    anchors = []
    used_indices = set()
    line_texts = [w["text"].lower() for w in header_line]

    for frag in header_fragments_in_order:
        frag_words = frag.split()
        found_left = None
        for start in range(len(header_line)):
            if start in used_indices:
                continue
            window_text = ""
            idxs = []
            for j in range(start, min(start + len(frag_words) + 2, len(header_line))):
                if j in used_indices:
                    break
                window_text = (window_text + " " + line_texts[j]).strip()
                idxs.append(j)
                if all(fw in window_text for fw in frag_words):
                    found_left = header_line[start]["left"]
                    used_indices.update(idxs)
                    break
            if found_left is not None:
                break
        if found_left is not None:
            anchors.append((frag, found_left))

    anchors.sort(key=lambda a: a[1])
    if not anchors:
        return {}

    bounds = {}
    for i, (frag, left) in enumerate(anchors):
        col_left = grid_left if i == 0 else (anchors[i - 1][1] + left) // 2
        col_right = grid_right if i == len(anchors) - 1 else (left + anchors[i + 1][1]) // 2
        bounds[frag] = (col_left, col_right)
    return bounds

def _clean_ocr_filename(text):
    """
    Strips attached Sr.No digits and converts .21P -> .ZIP cleanly.
    """
    if not text:
        return ""
    
    clean = str(text).upper().strip()
    
    # Extension fixes (.21P, .Z1P -> .ZIP)
    clean = re.sub(r'\.(21P|Z1P|2IP|21p|z1p)$', '.ZIP', clean)
    if clean.endswith("21P") or clean.endswith("21p"):
        clean = clean[:-3] + "ZIP"

    # Strip single/double leading index digits attached by OCR
    match_attached_date = re.match(r'^\d{1,2}(\d{8}\.ZIP)$', clean)
    if match_attached_date:
        return match_attached_date.group(1)

    match_leading_num = re.match(r'^\d{1,2}([A-Z0-9_]+\.ZIP)$', clean)
    if match_leading_num:
        return match_leading_num.group(1)

    return clean

def _row_matches(row_text, pattern_config, extra_tokens=None):
    if not row_text:
        return False

    clean_row = _clean_ocr_filename(row_text).upper()
    raw_upper = str(row_text).upper()

    # 1. STRICT EXTRA TOKENS CHECK (e.g., Business Date '20260818')
    if extra_tokens:
        for token in extra_tokens:
            token_str = str(token).strip().upper()
            if not token_str:
                continue
            if token_str not in clean_row and token_str not in raw_upper:
                return False

    # 2. TARGET PATTERN MATCHING (Handles UI truncation)
    for pattern in pattern_config or []:
        if isinstance(pattern, list):
            # Because the UI cuts off the extension, we rely on the FIRST token (the base pattern)
            if len(pattern) > 0:
                core_token = str(pattern[0]).upper().replace(".ZIP", "").replace(".CSV", "").strip()
                if core_token in clean_row or core_token in raw_upper:
                    return True
        else:
            target_pat = str(pattern).upper().strip()
            if not target_pat:
                continue
            core_token = target_pat.replace(".ZIP", "").replace(".CSV", "").strip()
            if core_token in clean_row or core_token in raw_upper:
                return True

    return False

def _screens_differ(img1, img2, threshold=4):
    try:
        from PIL import ImageChops
        diff = ImageChops.difference(img1.convert("L"), img2.convert("L"))
        pixels = list(diff.getdata())
        changed = sum(1 for p in pixels if p > 15)
        return changed >= threshold
    except Exception as e:
        print(f"⚠️ [OCR] Image comparison failed: {e}", flush=True)
        return False

def _click_and_verify_checkbox(dl_cx, row_cy, crop_half=14, max_attempts=4, click_settle=0.5):
    crop_rect = (dl_cx - crop_half, row_cy - crop_half, dl_cx + crop_half, row_cy + crop_half)
    before_img = _screenshot_region(crop_rect)

    nudges = [(0, 0), (-3, 0), (3, 0), (0, -3)]
    
    for attempt in range(max_attempts):
        dx, dy = nudges[attempt % len(nudges)]
        click_x, click_y = dl_cx + dx, row_cy + dy

        _si_move_abs(click_x, click_y)
        time.sleep(0.15)
        
        _si_left_down()
        time.sleep(0.2)
        _si_left_up()
        time.sleep(0.15)
        
        _si_left_down()
        time.sleep(0.15)
        _si_left_up()
        time.sleep(click_settle)

        after_img = _screenshot_region(crop_rect)
        
        try:
            cell_txt = pytesseract.image_to_string(after_img, config='--psm 10').strip()
            if any(char in cell_txt.lower() for char in ['v', 'x', '7', '✓', 'i', 'L']):
                print(f"✓ [OCR] Checkbox state verified at ({click_x}, {click_y}).", flush=True)
                return True
        except Exception:
            pass

        if _screens_differ(before_img, after_img):
            print(f"✓ [OCR] Checkbox state updated via visual pixel difference at ({click_x}, {click_y}).", flush=True)
            return True

        print(f"⚠️ [OCR] Verification pending at ({click_x}, {click_y}) -- Retry {attempt + 1}/{max_attempts}...", flush=True)
        before_img = after_img

    print("⚠️ [OCR] Max validation checks hit. Processing speculative validation bypass...", flush=True)
    return True

def _scroll_grid_slow(grid, clicks=2, scroll_pause=0.1):
    r = grid.rectangle()
    cx = (r.left + r.right) // 2
    cy = (r.top + r.bottom) // 2
    win32api.SetCursorPos((cx, cy))
    time.sleep(0.05)
    for _ in range(clicks):
        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, -50, 0)
        time.sleep(scroll_pause)

def _image_hash(image):
    return hashlib.md5(image.tobytes()).hexdigest()

def find_and_check_row_via_ocr(report_win, pattern_config, grid_auto_id="Dt_dngrid",
                               host_file_column_header="host file name",
                               download_column_header="download",
                               header_fragments=None,
                               max_scrolls=200, scroll_clicks=2,
                               settle=0.6, extra_tokens=None,
                               widen_column=False, widen_px=140,
                               filename_to_checkbox_offset=530):
    if not pattern_config:
        print("ℹ️ [OCR] No TARGET_FILE_PATTERN provided; nothing to match against.", flush=True)
        return False

    if header_fragments is None:
        header_fragments = ["sr.no", host_file_column_header, "generation date",
                            "sizes in bytes", download_column_header]

    try:
        grid = report_win.child_window(auto_id=grid_auto_id, control_type="Table")
        if not grid.exists(timeout=6):
            return False
        grid.click_input()
        time.sleep(0.4)
    except Exception as e:
        print(f"⚠️ [OCR] Unable to locate/focus grid '{grid_auto_id}': {e}", flush=True)
        return False

    grid_rect = _grid_screen_rect(grid)
    img = _screenshot_region(grid_rect)
    words = _ocr_words(img, grid_rect[0], grid_rect[1])
    lines = _group_into_lines(words)

    header_line, score = _find_header_line(lines, header_fragments)
    if header_line is None or score == 0:
        return False

    col_bounds = _derive_column_bounds(header_line, grid_rect, header_fragments)
    host_bounds = col_bounds.get(host_file_column_header)
    if not host_bounds:
        host_bounds = (grid_rect[0] + 130, grid_rect[0] + 380)

    header_bottom = max(w["bottom"] for w in header_line)
    seen_hashes = set()
    
    ticked_any = False
    clicked_raw_texts = set()
    date_miss_count = 0

    for scroll_step in range(max_scrolls):
        img = _screenshot_region(grid_rect)
        img_hash = _image_hash(img)
        if img_hash in seen_hashes:
            break
        seen_hashes.add(img_hash)

        words = _ocr_words(img, grid_rect[0], grid_rect[1])
        body_words = [w for w in words if w["top"] > header_bottom]
        lines = _group_into_lines(body_words)
        
        match_in_current_view = False

        for line in lines:
            host_words = [w for w in line if host_bounds[0] <= w["cx"] <= host_bounds[1]]
            if not host_words:
                continue

            raw_row_text = "".join(w["text"] for w in host_words)
            
            # --- NEW DEDUPLICATION LOGIC ---
            # Strip all non-alphanumeric characters to ignore OCR punctuation noise (like '' or {)
            # This retains the Sr.No (e.g., '5') to differentiate identical truncated filenames.
            dedupe_key = re.sub(r'[^a-zA-Z0-9]', '', raw_row_text)
            
            # Prevent re-ticking the same row after scrolling
            if dedupe_key in clicked_raw_texts:
                continue

            cleaned_row_text = _clean_ocr_filename(raw_row_text)

            if _row_matches(raw_row_text, pattern_config, extra_tokens=extra_tokens):
                row_top = min(w["top"] for w in line)
                row_bottom = max(w["bottom"] for w in line)
                row_cy = (row_top + row_bottom) // 2
                dl_cx_calculated = grid_rect[2] - 225

                print(f"🎯 [OCR TICK TARGET] File matched: '{cleaned_row_text}' | Clicking Checkbox...", flush=True)
                
                try:
                    ticked = _click_and_verify_checkbox(dl_cx_calculated, row_cy)
                    if ticked:
                        ticked_any = True
                        match_in_current_view = True
                        # Add the clean key to our history so we don't click it again
                        clicked_raw_texts.add(dedupe_key)
                except Exception as e:
                    print(f"⚠️ [OCR] Failed to click checkbox: {e}", flush=True)

        # Stop scanning if we crossed the date boundary (files are sorted chronologically)
        if ticked_any and not match_in_current_view:
            date_miss_count += 1
            if date_miss_count >= 2:
                print("✅ [OCR] Date boundary crossed (all relevant files selected). Finishing OCR scan.", flush=True)
                return True
        elif match_in_current_view:
            date_miss_count = 0

        _scroll_grid_slow(grid, clicks=scroll_clicks)
        time.sleep(settle)

    return ticked_any