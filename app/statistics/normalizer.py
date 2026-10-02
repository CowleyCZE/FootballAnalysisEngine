import re
from typing import Optional, Tuple

class SourceNormalizer:
    @staticmethod
    def parse_int(value: any) -> Optional[int]:
        if value is None or value == "" or value == "-":
            return None
        try:
            # Odstranění mezer a převod
            cleaned = str(value).strip().replace(",", ".")
            val = float(cleaned)
            return int(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def parse_float(value: any) -> Optional[float]:
        if value is None or value == "" or value == "-":
            return None
        try:
            cleaned = str(value).strip().replace("%", "").replace(",", ".")
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def parse_score(score_str: str) -> Tuple[Optional[int], Optional[int]]:
        if not score_str or not isinstance(score_str, str):
            return None, None
        
        # Hledá vzor "2-1" nebo "2:1"
        match = re.search(r'(\d+)\s*[:\-]\s*(\d+)', score_str.strip())
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None