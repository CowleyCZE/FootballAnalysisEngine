import os
from typing import Dict, Any, Tuple

class PromptManager:
    def __init__(self, base_dir: str = "prompts"):
        self.base_dir = base_dir

    def load_prompt(
        self, prompt_type: str = "analyst", version: str = "v1"
    ) -> Tuple[str, str]:
        dir_path = os.path.join(self.base_dir, prompt_type, version)
        sys_file = os.path.join(dir_path, "system.txt")
        user_file = os.path.join(dir_path, "user.txt")

        if not os.path.exists(sys_file) or not os.path.exists(user_file):
            raise FileNotFoundError(f"Prompt templates not found in {dir_path}")

        with open(sys_file, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        with open(user_file, "r", encoding="utf-8") as f:
            user_prompt = f.read()

        return system_prompt, user_prompt

    def render_user_prompt(
        self, template: str, context: Dict[str, Any]
    ) -> str:
        import json
        context_str = json.dumps(context, indent=2, ensure_ascii=False)
        return template.replace("{{CONTEXT}}", context_str)
