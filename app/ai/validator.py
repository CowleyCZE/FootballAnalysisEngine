import json
import re
import logging
from typing import Tuple, Type, Optional, TypeVar, Any, Dict
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)

class AIValidator:
    @staticmethod
    def extract_json_string(text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    @classmethod
    def validate(
        cls,
        raw_text: str,
        schema_cls: Type[T],
    ) -> Tuple[bool, Optional[T], str, Optional[Dict[str, Any]]]:
        clean_str = cls.extract_json_string(raw_text)
        try:
            data_dict = json.loads(clean_str)
        except json.JSONDecodeError as e:
            msg = f"JSON Decode Error: {e}"
            logger.error(msg)
            return False, None, msg, None

        try:
            validated_obj = schema_cls.model_validate(data_dict)
            return True, validated_obj, "VALID", data_dict
        except ValidationError as ve:
            msg = f"Pydantic Validation Error: {ve}"
            logger.error(msg)
            return False, None, msg, data_dict
