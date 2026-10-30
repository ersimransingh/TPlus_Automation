import json

class ConfigReader:
    def __init__(self, file_path="activity.json"):
        with open(file_path, "r") as f:
            self.config = json.load(f)

    def get_settings(self):
        return self.config.get("global_app_settings", {})

    def get_locators(self):
        return self.config.get("locators", {})

    def get_process(self, process_name: str):
        return self.config.get(process_name, {})

    def get_all_processes(self):
        processes = {}
        for key, value in self.config.items():
            if key.startswith("process_") and isinstance(value, dict):
                processes[key] = value
        return processes

    def get_email_settings(self):
        return self.config.get("email_settings", {})