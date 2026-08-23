"""
llm_planner/llm_client.py
--------------------------
Thin adapter over ollama and anthropic backends.
Always returns None on any failure — never raises into the pipeline.

Usage:
    client = LLMClient.from_config("config.yaml")
    response = client.complete(system_prompt="...", user_prompt="...")
    if response is None:
        # LLM unavailable — caller must use fallback
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(
        self,
        provider: str,
        model: str,
        base_url: str,
        api_key: Optional[str],
        timeout_sec: int,
        enabled: bool,
    ):
        self.provider = provider.lower()
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "LLMClient":
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)

        llm_cfg = cfg.get("llm", {})
        api_key_env = llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY")
        api_key = os.environ.get(api_key_env)

        return cls(
            provider=llm_cfg.get("provider", "ollama"),
            model=llm_cfg.get("model", "phi3"),
            base_url=llm_cfg.get("base_url", "http://localhost:11434"),
            api_key=api_key,
            timeout_sec=int(llm_cfg.get("timeout_sec", 30)),
            enabled=bool(llm_cfg.get("enabled", True)),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Send a completion request and return the text response.
        Returns None on any failure (network error, timeout, bad response, disabled).
        """
        if not self.enabled:
            logger.info("LLM disabled in config — returning None")
            return None

        if self.provider == "ollama":
            return self._complete_ollama(system_prompt, user_prompt)
        elif self.provider == "anthropic":
            return self._complete_anthropic(system_prompt, user_prompt)
        else:
            logger.error("Unknown LLM provider: %s", self.provider)
            return None

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _complete_ollama(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        try:
            import httpx  # already in requirements

            url = f"{self.base_url.rstrip('/')}/api/chat"
            payload = {
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                # Ollama chat response shape: {"message": {"content": "..."}}
                content = data["message"]["content"]
                logger.debug("Ollama response length: %d chars", len(content))
                return content

        except Exception as exc:
            logger.warning("Ollama call failed: %s", exc)
            return None

    def _complete_anthropic(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        try:
            import httpx

            if not self.api_key:
                logger.warning("ANTHROPIC_API_KEY not set — cannot call Anthropic API")
                return None

            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": self.model,
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                # Anthropic shape: {"content": [{"type": "text", "text": "..."}]}
                content = data["content"][0]["text"]
                logger.debug("Anthropic response length: %d chars", len(content))
                return content

        except Exception as exc:
            logger.warning("Anthropic call failed: %s", exc)
            return None