import base64

class SecurityManager:
    @staticmethod
    def decode_base64(encoded_str: str) -> str:
        if not encoded_str:
            return ""
        try:
            # Attempt to decode as base64
            decoded_bytes = base64.b64decode(encoded_str.strip(), validate=True)
            return decoded_bytes.decode("utf-8").strip()
        except Exception:
            # Fallback: if it's already plain text, return as-is
            return encoded_str.strip()