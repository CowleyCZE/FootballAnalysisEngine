import hashlib
import json
import uuid
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

from app.ai.client import OllamaClient
from app.ai.context_builder import ContextBuilder
from app.ai.prompts import PromptManager
from app.ai.schemas import AnalysisResult
from app.ai.validator import AIValidator

logger = logging.getLogger(__name__)

class AISynthesizer:
    def __init__(
        self,
        client: OllamaClient,
        db_path: Optional[str] = "database/football.db",
        prompt_version: str = "v1",
    ):
        self.client = client
        self.db_path = db_path
        self.prompt_version = prompt_version
        self.prompt_manager = PromptManager()
        self.context_builder = ContextBuilder()
        self._init_db()

    def _init_db(self):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                match_id INTEGER,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                output_hash TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                raw_response TEXT
            );
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def compute_hash(data: Any) -> str:
        if isinstance(data, (dict, list)):
            serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        else:
            serialized = str(data)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def analyze_match(
        self,
        match_info: Dict[str, Any],
        claims: list,
        statistics: dict,
        conflicts: list = None,
    ) -> Tuple[Optional[AnalysisResult], str]:
        run_id = str(uuid.uuid4())
        match_id = match_info.get("match_id") or match_info.get("id", 0)

        context = self.context_builder.build_context(
            match_info=match_info,
            claims=claims,
            statistics=statistics,
            conflicts=conflicts,
        )

        input_hash = self.compute_hash(context)

        sys_prompt, user_template = self.prompt_manager.load_prompt(
            prompt_type="analyst", version=self.prompt_version
        )
        user_prompt = self.prompt_manager.render_user_prompt(user_template, context)

        raw_output = ""
        validated_result: Optional[AnalysisResult] = None
        status = "FAILED"

        for attempt in range(2):
            try:
                raw_output = self.client.generate(
                    prompt=user_prompt,
                    system_prompt=sys_prompt,
                    require_json=True,
                )
                valid, obj, err, _ = AIValidator.validate(raw_output, AnalysisResult)
                if valid and obj is not None:
                    validated_result = obj
                    status = "SUCCESS"
                    break
                else:
                    logger.warning(f"AI response validation failed (attempt {attempt+1}): {err}")
                    user_prompt = f"{user_prompt}\n\nPREVIOUS OUTPUT WAS INVALID JSON/SCHEMA ({err}). REPAIR AND RETURN ONLY VALID JSON MATCHING SCHEMA."
            except Exception as e:
                logger.error(f"Error calling AI client: {e}")
                raw_output = str(e)

        output_hash = self.compute_hash(raw_output)

        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """
                INSERT INTO ai_runs (run_id, match_id, model, prompt_version, input_hash, output_hash, status, created_at, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    match_id,
                    self.client.model,
                    self.prompt_version,
                    input_hash,
                    output_hash,
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    raw_output,
                ),
            )
            conn.commit()
            conn.close()

        return validated_result, run_id
