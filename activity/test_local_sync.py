import os
import json
import shutil
import zipfile
import datetime
import re

# ==========================================
# 1. CORE FUNCTIONS FROM LIVE SCRIPT
# ==========================================

def resolve_date_string(date_str):
    if not date_str:
        return "Downloaded_Reports"

    normalized = str(date_str).strip().lower()
    today = datetime.date.today()

    if normalized in ("t", "today"):
        target_date = today
    elif normalized == "yesterday":
        target_date = today - datetime.timedelta(days=1)
    elif normalized == "tomorrow":
        target_date = today + datetime.timedelta(days=1)
    elif normalized.startswith("t") and ("-" in normalized or "+" in normalized):
        try:
            offset_match = re.search(r'[-+]\s*\d+', normalized)
            if offset_match:
                offset = int(offset_match.group().replace(" ", ""))
                target_date = today + datetime.timedelta(days=offset)
            else:
                target_date = today
        except Exception:
            target_date = today
    else:
        return normalized.replace("-", "")

    day = target_date.strftime("%d")
    month = target_date.strftime("%b").capitalize()  # Formats as "06Aug2026"
    year = target_date.strftime("%Y")
    return f"{day}{month}{year}"

def matches_pattern_strict(filename, pattern_config):
    if not pattern_config:
        return True

    file_upper = filename.upper()

    for pattern in pattern_config:
        if isinstance(pattern, list):
            if all(str(sub_segment).strip().upper() in file_upper for sub_segment in pattern if sub_segment):
                return True
        else:
            if str(pattern).strip().upper() in file_upper:
                return True

    return False

def extract_and_copy_zip_files(source_directory, destination_directory, pattern_config=None):
    if not os.path.exists(source_directory):
        print(f"⚠️ [FILE SYNC] Source directory does not exist: '{source_directory}'")
        return False

    os.makedirs(destination_directory, exist_ok=True)
    is_isin_path = "ISIN" in source_directory.upper()

    print(f"\n🔍 [FILE SYNC ENGINE]")
    print(f"   ↳ Source Directory      : '{source_directory}'")
    print(f"   ↳ Destination Directory : '{destination_directory}'")
    print(f"   ↳ ISIN Unzip Mode Active : {is_isin_path}")

    files_found = os.listdir(source_directory)
    transferred_count = 0

    for item in files_found:
        item_path = os.path.join(source_directory, item)

        if not os.path.isfile(item_path):
            continue

        if not matches_pattern_strict(item, pattern_config):
            continue

        item_upper = item.upper()

        # BRANCH A: ISIN PATH -> UNZIP ARCHIVE TO DESTINATION
        if is_isin_path and item_upper.endswith(".ZIP"):
            try:
                print(f"📦 [ZIP ENGINE] Extracting ISIN archive: '{item}' -> '{destination_directory}'")
                with zipfile.ZipFile(item_path, 'r') as zip_ref:
                    zip_ref.extractall(destination_directory)
                print(f"   ✓ [ZIP ENGINE] Successfully unzipped '{item}'.")
                transferred_count += 1
            except Exception as zip_err:
                print(f"   ⚠️ [ZIP ENGINE ERROR] Could not extract '{item}': {zip_err}")

        # BRANCH B: STANDARD PATH -> DIRECT COPY WITHOUT UNZIPPING
        elif not is_isin_path:
            dst_file_path = os.path.join(destination_directory, item)
            try:
                shutil.copy2(item_path, dst_file_path)
                print(f"🚚 [DIRECT COPY] Transferring raw file: '{item}' -> '{destination_directory}'")
                transferred_count += 1
            except Exception as copy_err:
                print(f"   ⚠️ [FILE COPY ERROR] Could not copy '{item}': {copy_err}")

    print(f"✓ Total items processed and synced: {transferred_count}")
    return transferred_count > 0

def clear_files_in_dir(directory):
    if os.path.exists(directory):
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isfile(item_path):
                try:
                    os.remove(item_path)
                except Exception:
                    pass

# ==========================================
# 2. TEST SUITE RUNNER
# ==========================================

def run_live_simulation():
    # Load JSON file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "activity_2.json")

    with open(json_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    master_destination_root = config["global_app_settings"]["main_path"]

    print("\n=================== SIMULATION 1: PROCESS_01 (STANDARD DIRECT COPY) ===================")
    proc_1 = config["process_01"]
    proc_1_source = proc_1["main_path"]
    task_1 = proc_1["download_task"][0]
    pats_1 = task_1["target_file_pattern"]
    date_subfolder_1 = resolve_date_string(task_1["business_date_from"])
    dest_path_1 = os.path.join(master_destination_root, date_subfolder_1)

    # Create dummy mock CSV in process_01 main_path
    os.makedirs(proc_1_source, exist_ok=True)
    clear_files_in_dir(proc_1_source)
    mock_csv = os.path.join(proc_1_source, "CLN_MSTR_028700_INCREMENTAL_I_20260806_0000_999_P0.csv")
    with open(mock_csv, "w") as f:
        f.write("Col1,Col2\nVal1,Val2")

    # Run sync
    extract_and_copy_zip_files(proc_1_source, dest_path_1, pattern_config=pats_1)

    print("\n=================== SIMULATION 2: PROCESS_03 (ISIN UNZIP MODE) ===================")
    proc_3 = config["process_03"]
    proc_3_source = proc_3["main_path"]
    task_3 = proc_3["download_task"][0]
    pats_3 = task_3["target_file_pattern"]
    date_subfolder_3 = resolve_date_string(task_3["business_date_from"])
    dest_path_3 = os.path.join(master_destination_root, date_subfolder_3)

    # Create dummy mock ZIP in process_03 main_path
    os.makedirs(proc_3_source, exist_ok=True)
    clear_files_in_dir(proc_3_source)
    mock_zip = os.path.join(proc_3_source, "ISIN_RATE_000001_6721_F_20260806_01.csv.ZIP")
    with zipfile.ZipFile(mock_zip, 'w') as zf:
        zf.writestr("ISIN_RATE_000001_6721_F_20260806_01.csv", "Col1,Col2\nVal1,Val2")

    # Run sync
    extract_and_copy_zip_files(proc_3_source, dest_path_3, pattern_config=pats_3)

if __name__ == "__main__":
    run_live_simulation()