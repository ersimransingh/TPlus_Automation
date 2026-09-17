import os
import sys
import logging
from datetime import datetime

def get_activity_dir():
    """Returns the actual folder where execution script/exe resides."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def setup_logger():
    logger = logging.getLogger("automation")
    logger.setLevel(logging.INFO)
    
    # Avoid attaching duplicate handlers if setup_logger is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', '%Y-%m-%d %H:%M:%S')

        # 1. Console Stream Handler
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
        
        # 2. File Handler (Internal_logs -> Date Folder -> Log Execution File)
        try:
            base_dir = get_activity_dir()
            current_date = datetime.now().strftime("%Y-%m-%d")
            execution_time = datetime.now().strftime("%H-%M-%S")
            
            # Create folder hierarchy: <base_dir>/Internal_logs/<YYYY-MM-DD>/
            log_dir = os.path.join(base_dir, "Internal_log", current_date)
            os.makedirs(log_dir, exist_ok=True)
            
            # File name format: log_execution_14-30-00.log
            log_file_name = f"log_execution_{execution_time}.log"
            log_file_path = os.path.join(log_dir, log_file_name)
            
            # Attach FileHandler with explicit UTF-8 encoding
            file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
            logger.info(f"📂 Internal Log session initialized at: {log_file_path}")
            
        except Exception as err:
            print(f"⚠️ Failed to initialize FileHandler for logger: {err}")
        
    return logger