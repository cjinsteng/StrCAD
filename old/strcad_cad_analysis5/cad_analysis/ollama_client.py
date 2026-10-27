"""Minimal Ollama HTTP client (stdlib only)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434", model: str = "", timeout: float = 180.0):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    def _req(self, path, payload=None, timeout=None):
        url = self.host + path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            raise OllamaError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise OllamaError(f"Ollama 연결 실패 ({self.host}): {e}") from e

    def list_models(self) -> list[str]:
        d = self._req("/api/tags", timeout=5)
        return [m.get("name", "") for m in d.get("models", [])]

    def ping(self) -> bool:
        try:
            self.list_models()
            return True
        except OllamaError:
            return False

    # ------------------------------------------------------------------
    def chat_json(self, system: str, user: str, schema: dict | None = None) -> dict:
        """Ask for a JSON object. Tries structured output (schema) first,
        then falls back to plain JSON mode for older Ollama versions."""
        if not self.model:
            raise OllamaError("Ollama 모델이 선택되지 않았습니다.")
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last = None
        for fmt in ([schema, "json"] if schema else ["json"]):
            payload = {"model": self.model, "messages": msgs, "stream": False, "format": fmt,
                       "options": {"temperature": 0, "num_ctx": 8192}}
            try:
                d = self._req("/api/chat", payload)
            except OllamaError as e:
                last = e
                continue
            content = d.get("message", {}).get("content", "")
            try:
                return _parse_json(content)
            except ValueError as e:
                last = OllamaError(f"JSON 파싱 실패: {e}: {content[:200]}")
        raise last or OllamaError("Ollama 응답 없음")


def _parse_json(s: str) -> dict:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            return json.loads(m.group(0))
        raise ValueError("no JSON object")
