from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import litellm
from litellm import completion
from aisbot.providers.base import BaseProvider
import os


class LitellmProvider(BaseProvider):
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        super().__init__(api_key, api_base)
        self.api_key = api_key
        self.api_base = api_base

    def initialize(self):
        if self.api_base:
            litellm.api_base = self.api_base

        if self.api_key:
            litellm.api_key = self.api_key
        
        litellm.suppress_debug_info = True
        os.environ['NVIDIA_NIM_API_KEY'] = self.api_key


    @classmethod
    def match_model(cls, model: str) -> bool:
        return model.startswith("nvidia/") or model.startswith("z-ai/")

    def get_default_model(self) -> str:
        return "nvidia/llama-3.1-nemotron-70b-instruct"

    async def completions(self, **kwargs):
        import sys
        
        messages = kwargs.get("messages", [{}])
        try:
            response = completion(
                    **kwargs
                )
            return response
        except Exception as e:
            print(f"DEBUG API call error: {type(e).__name__}: {e}", file=sys.stderr)
            raise

       
