"""
screenshot_util.py

Captures a single full-screen screenshot, used right after each "click_ok"
import confirmation so a still image of the completed batch can be saved
alongside its recording and attached to the batch report email.

Saved under:

    activity/
      Screenshot/
        <execution_day YYYY-MM-DD>/
          <process_name>/
            screenshot_<HH-MM-SS>.png
"""

import os
import sys
import cv2
import numpy as np
import mss

# Import logger without hardcoded activity package prefixes
try:
    from logger_config import setup_logger
except ImportError:
    from activity.logger_config import setup_logger

logger = setup_logger()


def get_activity_dir():
    """
    Resolves the actual location of the activity folder whether running
    via plain python script or as a compiled PyInstaller executable.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Main "Screenshot" directory anchored dynamically to the real activity directory
BASE_SCREENSHOT_DIR = os.path.join(get_activity_dir(), "Screenshot")


def capture_screenshot(output_path: str) -> str:
    """
    Grabs one frame of the primary monitor and saves it as a PNG at
    `output_path` (parent directories are created if needed).

    Automatically redirects legacy 'Output' folder paths to the 'Screenshot' folder.
    Returns `output_path` for convenience.
    """
    # Redirect legacy 'Output' directory paths to 'Screenshot'
    if "Output" in output_path:
        output_path = output_path.replace("Output", "Screenshot", 1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with mss.mss() as sct:
        monitor = sct.monitors[1]  # primary monitor, full screen
        frame = np.array(sct.grab(monitor))
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        cv2.imwrite(output_path, frame)

    logger.info(f"Screenshot saved: {output_path}")
    return output_path