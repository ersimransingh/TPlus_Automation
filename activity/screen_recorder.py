"""
screen_recorder.py

Background screen recorder used to capture a video of each individual
file-import batch that the automation performs.

On disk this produces inside the activity directory:

    Records/
      2026-07-23/
        Process_01/
          recording_14-32-05.mp4
        Process_02/
          recording_14-41-10.mp4
"""

import os
import sys
import threading
import time
from datetime import datetime

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


# Main "Records" folder, anchored dynamically to the real activity directory
BASE_RECORDS_DIR = os.path.join(get_activity_dir(), "Records")

# Characters that Windows does not allow in a folder/file name.
_INVALID_WIN_CHARS = '<>:"/\\|?*'


def _sanitize_folder_name(name: str) -> str:
    """
    Strips characters that are illegal in Windows folder names and trims stray whitespace/dots.
    """
    cleaned = "".join(ch for ch in name if ch not in _INVALID_WIN_CHARS)
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "unnamed"


def build_batch_folder_name(process_name: str, json_date: str = None, client_value: str = None, exec_time: str = None) -> str:
    """
    Builds the folder name using ONLY the process name (e.g., 'Process_01', 'Process_02').
    """
    raw_name = process_name or "Process"
    return _sanitize_folder_name(raw_name)


class ScreenRecorder:
    """
    Thread-safe lightweight background screen recorder instance wrapper.
    """

    def __init__(self, fps: int = 8):
        self.fps = fps
        self._thread = None
        self._stop_event = threading.Event()
        self._active_batch = None
        self.output_path = None

    def is_active(self) -> bool:
        return self._thread is not None

    def start(self, batch_folder_name: str):
        batch_folder_name = _sanitize_folder_name(batch_folder_name)

        if self.is_active():
            logger.info(f"A recording for batch '{self._active_batch}' is active; resetting instance thread...")
            self.stop()

        now = datetime.now()
        day_folder = now.strftime("%Y-%m-%d")
        folder = os.path.join(BASE_RECORDS_DIR, day_folder, batch_folder_name)
        os.makedirs(folder, exist_ok=True)

        timestamp = now.strftime("%H-%M-%S")
        self.output_path = os.path.join(folder, f"recording_{timestamp}.mp4")
        self._active_batch = batch_folder_name

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._record_loop, args=(self.output_path, self._stop_event), daemon=True)
        self._thread.start()
        logger.info(f"Screen recording started for tracking block '{batch_folder_name}': {self.output_path}")

    def _record_loop(self, target_output_path, stop_signal):
        writer = None
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  
                width, height = monitor["width"], monitor["height"]

                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(target_output_path, fourcc, self.fps, (width, height))

                frame_interval = 1.0 / self.fps
                while not stop_signal.is_set():
                    loop_start = time.time()

                    frame = np.array(sct.grab(monitor))
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    writer.write(frame)

                    elapsed = time.time() - loop_start
                    remaining = frame_interval - elapsed
                    if remaining > 0:
                        time.sleep(remaining)
        except Exception as e:
            logger.error(f"Screen recording loop critical fault: {e}", exc_info=True)
        finally:
            if writer is not None:
                writer.release()

    def stop(self):
        if not self.is_active():
            return

        self._stop_event.set()
        self._thread.join(timeout=15)
        self._thread = None

        logger.info(f"Screen recording stopped and finalized successfully: {self.output_path}")
        self._active_batch = None