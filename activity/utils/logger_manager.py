import os
import sys
import logging
from datetime import datetime

class StreamToLogger:
    """Helper stream to capture print statements and forward them to the logger."""
    def __init__(self, original_stream, logger, level):
        self.original_stream = original_stream
        self.logger = logger
        self.level = level

    def write(self, message):
        self.original_stream.write(message)
        self.original_stream.flush()
        cleaned_msg = message.strip()
        if cleaned_msg:
            self.logger.log(self.level, cleaned_msg)

    def flush(self):
        self.original_stream.flush()

class LoggerManager:
    _initialized = False

    @classmethod
    def get_logger(cls, name="AutomationLogger"):
        logger = logging.getLogger(name)
        if cls._initialized:
            return logger

        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        # Create logs directory
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)

        # Date-wise log file name (e.g., logs/2026-09-23.log)
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file_path = os.path.join(logs_dir, f"{date_str}.log")

        formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

        # File Handler
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console Handler (using original stdout to prevent recursion loops)
        console_handler = logging.StreamHandler(sys.__stdout__)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Intercept ALL print statements and errors globally
        sys.stdout = StreamToLogger(sys.__stdout__, logger, logging.INFO)
        sys.stderr = StreamToLogger(sys.__stderr__, logger, logging.ERROR)

        cls._initialized = True
        return logger