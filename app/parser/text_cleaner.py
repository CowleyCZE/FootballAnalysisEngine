import re

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Odstranění zbytečných mezer a prázdných řádků
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = [line for line in lines if line]
    return "\n\n".join(clean_lines)