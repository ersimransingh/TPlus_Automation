# activity/date_engine.py
import os
import re
import json
from datetime import datetime, timedelta

def get_holiday_path():
    """Locates holidays.json across root and activity directory paths."""
    search_files = ["holidays.json", "holiday.json", "Holidays.json"]
    base_dirs = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        os.path.abspath(os.path.join(os.getcwd(), ".."))
    ]
    for b in base_dirs:
        for fname in search_files:
            cand = os.path.join(b, fname)
            if os.path.exists(cand):
                return cand
    return None

def resolve_date_details(date_token):
    """
    Resolves relative tokens ('t', 't-1', 't-4') or absolute strings ('06-Oct-2026')
    to the last valid working date, skipping weekends and holidays.
    Returns: (target_date_object, list_of_skipped_reasons)
    """
    if not date_token:
        date_token = "t"

    normalized = str(date_token).strip().lower()
    base_dt = datetime.now()
    offset_days = 0

    if normalized in ("t", "today"):
        offset_days = 0
    elif normalized == "yesterday":
        offset_days = -1
    elif normalized == "tomorrow":
        offset_days = 1
    # Strict regex: only matches tokens starting with 't', avoiding the 'Oct' bug
    elif re.match(r'^t\s*[-+]\s*\d+$', normalized):
        match = re.search(r'[-+]\s*\d+', normalized)
        offset_days = int(match.group().replace(" ", "")) if match else 0
    else:
        for fmt in ("%d-%b-%Y", "%Y%m%d", "%Y-%m-%d", "%d/%m/%Y", "%d%b%Y"):
            try:
                return datetime.strptime(normalized, fmt).date(), []
            except ValueError:
                continue
        offset_days = 0

    target_dt = base_dt + timedelta(days=offset_days)
    skipped_days = []

    h_path = get_holiday_path()
    if h_path:
        try:
            with open(h_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                holiday_cfg = raw.get("holiday_settings", raw)

            skip_weekends = holiday_cfg.get("skip_weekends", False)
            weekend_days = [d.strip().lower() for d in holiday_cfg.get("weekend_days", [])]

            holiday_dates = set()
            for h in holiday_cfg.get("holidays", []):
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
                    try:
                        holiday_dates.add(datetime.strptime(str(h).strip(), fmt).date())
                        break
                    except ValueError:
                        continue

            while True:
                day_name = target_dt.strftime("%A")
                is_weekend = skip_weekends and (day_name.lower() in weekend_days)
                is_holiday = target_dt.date() in holiday_dates

                if is_weekend:
                    skipped_days.append(f"{target_dt.strftime('%d-%b-%Y')} ({day_name})")
                    target_dt -= timedelta(days=1)
                elif is_holiday:
                    skipped_days.append(f"{target_dt.strftime('%d-%b-%Y')} (Holiday)")
                    target_dt -= timedelta(days=1)
                else:
                    break
        except Exception:
            pass

    return target_dt.date(), skipped_days

def resolve_date(date_token):
    dt, _ = resolve_date_details(date_token)
    return dt

# --- Helpers for CDSL Desktop, Web, and Folder Structures ---

def to_web(token):
    """Returns '06-Oct-2026' for Web fields and Setup forms."""
    return resolve_date(token).strftime("%d-%b-%Y")

def to_date_components(token):
    """Returns ('06', 'Oct', '2026') for CDSL Download panes."""
    d = resolve_date(token)
    return d.strftime("%d"), d.strftime("%b").capitalize(), d.strftime("%Y")

def to_folder(token):
    """Returns '06Oct2026' for target directories."""
    d = resolve_date(token)
    return f"{d.strftime('%d')}{d.strftime('%b').capitalize()}{d.strftime('%Y')}"

def to_yyyymmdd(token):
    """Returns '20261006' for OCR grid searches and filename matching."""
    return resolve_date(token).strftime("%Y%m%d")

def to_picker(token):
    """Returns ('06', '10', '2026') for desktop date pickers."""
    d = resolve_date(token)
    return d.strftime("%d"), d.strftime("%m"), d.strftime("%Y")

def to_custom(token, fmt="%d%m%Y"):
    return resolve_date(token).strftime(fmt)