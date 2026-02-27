"""Ollama HTTP provider wrapper."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Dict, Any


class OllamaError(RuntimeError):
    """Raised for Ollama API or connectivity problems."""


class OllamaProvider:
    """Thin wrapper around Ollama's /api/chat endpoint."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, messages: List[Dict[str, str]], timeout: int = 120) -> str:
        """Send a chat request and return the assistant message content."""
        payload = json.dumps(
            {"model": self.model, "messages": messages, "stream": False}
        ).encode()

        url = f"{self.base_url}/api/chat"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode()
        except urllib.error.URLError as exc:
            reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            raise OllamaError(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Is it running? (hint: `ollama serve`)\nDetail: {reason}"
            ) from exc
        except TimeoutError as exc:
            raise OllamaError(
                f"Ollama request timed out after {timeout}s. "
                "Try increasing --timeout or check model load time."
            ) from exc

        try:
            data: Dict[str, Any] = json.loads(body)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Unexpected response from Ollama: {body[:200]}") from exc

        if "error" in data:
            raise OllamaError(
                f"Ollama error: {data['error']}\n"
                "Hint: make sure the model is pulled, e.g. `ollama pull llama3.1`"
            )

        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaError(f"Unexpected response structure: {data}") from exc
