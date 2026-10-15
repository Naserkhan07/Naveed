"""A tiny, dependency-free client for any OpenAI-compatible chat endpoint.

Deliberately built on ``urllib`` from the standard library instead of
``requests``/``httpx``: the one thing Naveed must never do is fail to start
because an HTTP library is missing, and the request it makes is a single POST.

It supports exactly what a screen-operating agent needs:

* **vision** — images are sent as base64 ``image_url`` content parts, JPEG-encoded
  and resized first (see :func:`encode_image`) because a raw 4K PNG is ~8 MB and
  would blow both the request limit and the latency budget;
* **JSON mode** — ``response_format`` is requested when the server advertises it,
  and the reply is still parsed defensively (:func:`extract_json`) because small
  models wrap JSON in prose or code fences;
* **retries** — transient network and 429/5xx failures are retried with backoff,
  while a 401 tells the user their key is wrong instead of silently looping;
* **cancellation** — every call takes a ``should_stop`` callable so pressing Stop
  in the panel aborts a request in flight.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import lazy
from ..config import LLMSettings

__all__ = [
    "LLMError",
    "LLMReply",
    "LLMClient",
    "encode_image",
    "extract_json",
    "image_part",
    "text_part",
]

logger = logging.getLogger("naveed.llm")

#: Longest side of an image handed to a model.  1280 keeps UI text legible while
#: staying inside the token budget of a small model.
DEFAULT_MAX_SIDE = 1280
DEFAULT_JPEG_QUALITY = 72


class LLMError(RuntimeError):
    """The model could not be reached or answered unusably."""

    def __init__(self, message: str, *, status: int = 0, retryable: bool = False) -> None:
        self.status = status
        self.retryable = retryable
        super().__init__(message)


@dataclass
class LLMReply:
    """One assistant turn."""

    text: str = ""
    json: Optional[Any] = None
    model: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    latency: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)
    finish_reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text) or self.json is not None


# --- content helpers --------------------------------------------------------

def text_part(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def image_part(data_url: str, *, detail: str = "auto") -> Dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": data_url, "detail": detail}}


def encode_image(
    image: Any,
    *,
    max_side: int = DEFAULT_MAX_SIDE,
    quality: int = DEFAULT_JPEG_QUALITY,
    fmt: str = "JPEG",
) -> str:
    """Encode a PIL image (or raw PNG bytes) as a base64 data URL.

    Images are downscaled to *max_side* and JPEG-compressed, which typically cuts
    a screenshot by 90 % with no loss of readable UI text at the sizes a vision
    model actually consumes.
    """
    PILImage = lazy.load("PIL.Image", extra="capture")

    if isinstance(image, (bytes, bytearray)):
        image = PILImage.open(io.BytesIO(bytes(image)))
    if not hasattr(image, "save"):
        raise LLMError("encode_image expects a PIL image or PNG bytes")

    working = image.convert("RGB")
    width, height = working.size
    longest = max(width, height)
    if longest > max_side:
        ratio = max_side / float(longest)
        working = working.resize((max(1, int(width * ratio)), max(1, int(height * ratio))))

    buffer = io.BytesIO()
    working.save(buffer, format=fmt, quality=quality, optimize=True)
    mime = "image/jpeg" if fmt.upper() in ("JPEG", "JPG") else f"image/{fmt.lower()}"
    return f"data:{mime};base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> Optional[Any]:
    """Pull JSON out of a model reply.

    Handles the three shapes small models produce: pure JSON, JSON inside a
    fenced block, and JSON embedded in a sentence.  Also repairs the most common
    malformations (trailing commas, smart quotes, single quotes) before retrying.
    """
    if not text:
        return None
    candidates: List[str] = []

    stripped = text.strip()
    candidates.append(stripped)
    for match in _JSON_BLOCK.finditer(text):
        candidates.append(match.group(1).strip())

    # First balanced object/array anywhere in the text.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:index + 1])
                    break

    for candidate in candidates:
        if not candidate:
            continue
        for attempt in (candidate, _repair_json(candidate)):
            if not attempt:
                continue
            try:
                return json.loads(attempt)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def _repair_json(text: str) -> str:
    """Best-effort fixes for the JSON a small model is likely to emit."""
    repaired = text.strip()
    repaired = repaired.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)          # trailing commas
    repaired = re.sub(r"(?<![\w\"])'([^'\n]*)'(\s*:)", r'"\1"\2', repaired)  # 'key':
    if repaired and repaired[0] not in "[{":
        start = min([index for index in (repaired.find("{"), repaired.find("[")) if index >= 0] or [-1])
        if start >= 0:
            repaired = repaired[start:]
    return repaired


# --- client -----------------------------------------------------------------

class LLMClient:
    """Minimal OpenAI-compatible chat client."""

    def __init__(self, settings: LLMSettings, *, should_stop: Optional[Callable[[], bool]] = None) -> None:
        self.settings = settings
        self.should_stop = should_stop
        self._json_mode_unsupported = False
        self.last_error = ""

    # --- public API -----------------------------------------------------
    @property
    def configured(self) -> bool:
        return self.settings.configured

    def chat(
        self,
        messages: Sequence[Dict[str, Any]],
        *,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> LLMReply:
        """Send one completion request and return the parsed reply."""
        if not self.settings.configured:
            raise LLMError(
                "No model is configured. Put an API key (or point Naveed at a local "
                "server) in ~/.naveed/config.env, for example:\n"
                "  LLM_BASE_URL=http://127.0.0.1:11434/v1\n  LLM_MODEL=qwen2.5vl:7b"
            )

        payload: Dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": [dict(message) for message in messages],
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "stream": False,
        }
        if json_mode and not self._json_mode_unsupported:
            payload["response_format"] = {"type": "json_object"}
        if self.settings.reasoning_effort:
            payload["reasoning_effort"] = self.settings.reasoning_effort

        started = time.time()
        data = self._post(payload, timeout=timeout or self.settings.timeout, json_mode=json_mode)
        latency = time.time() - started
        return self._parse_reply(data, latency)

    def probe(self, timeout: float = 1.5) -> Tuple[bool, str]:
        """Is something *actually* answering at the configured endpoint?

        ``configured`` only means a base URL and a model name are set, and that
        difference has bitten this project twice: the report said "✓ configured"
        for an Ollama address where nothing was listening, and the user only found
        out when a task died. This asks the server (``GET /models``, the standard
        OpenAI-compatible route) and, when the server lists its models, says
        whether the configured one is among them.

        Returns ``(ok, sentence)`` and never raises.
        """
        if not self.settings.configured:
            return False, "no model configured"
        base = str(self.settings.base_url or "").rstrip("/")
        if not base:
            return False, "no base URL configured"
        request = urllib.request.Request(f"{base}/models", method="GET")
        if self.settings.api_key:
            request.add_header("Authorization", f"Bearer {self.settings.api_key}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                return False, f"{base} answered but rejected the key (HTTP {error.code})"
            if error.code in (404, 405):
                return True, f"{base} is answering (it has no model list to check)"
            return False, f"{base} answered with HTTP {error.code}"
        except urllib.error.URLError as error:
            return False, f"nothing is answering at {base} ({error.reason})"
        except (TimeoutError, OSError) as error:
            return False, f"{base} did not answer in {timeout}s ({type(error).__name__})"

        names: List[str] = []
        try:
            payload = json.loads(body or "{}")
            entries = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(entries, list):
                names = [str(item.get("id") or item.get("name") or "") for item in entries if isinstance(item, dict)]
        except ValueError:
            names = []
        wanted = str(self.settings.model or "")
        if names and wanted and wanted not in names:
            short = ", ".join(name for name in names[:6] if name)
            return True, (
                f"{base} is answering, but {wanted!r} is not in its model list "
                f"(it has: {short}). Pull it, or change LLM_MODEL."
            )
        return True, f"{base} is answering" + (f" and has {wanted}" if names else "")

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        image: Any = None,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
    ) -> LLMReply:
        """Convenience wrapper for one system+user turn with an optional image."""
        content: List[Dict[str, Any]] = []
        if image is not None:
            content.append(image_part(encode_image(image)))
        content.append(text_part(prompt))
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        return self.chat(messages, json_mode=json_mode, max_tokens=max_tokens)

    # --- transport ------------------------------------------------------
    def _post(self, payload: Dict[str, Any], *, timeout: float, json_mode: bool) -> Dict[str, Any]:
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        headers.update(self.settings.extra_headers or {})

        attempts = max(1, self.settings.max_retries + 1)
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            if self.should_stop is not None and self.should_stop():
                raise LLMError("cancelled")
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw)
            except urllib.error.HTTPError as error:
                detail = ""
                try:
                    detail = error.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                if error.code == 401:
                    raise LLMError(
                        f"The model server rejected the API key (401). Check LLM_API_KEY in {self.settings.base_url}.",
                        status=401,
                    ) from error
                if error.code == 400 and json_mode and "response_format" in detail:
                    # Endpoint does not support JSON mode: drop it and retry once.
                    self._json_mode_unsupported = True
                    payload.pop("response_format", None)
                    body = json.dumps(payload).encode("utf-8")
                    last_error = error
                    continue
                last_error = LLMError(f"HTTP {error.code} from {url}: {detail}", status=error.code, retryable=error.code >= 500)
                if error.code < 500 and error.code != 429:
                    raise last_error from error
            except urllib.error.URLError as error:
                last_error = LLMError(f"Could not reach {url}: {error.reason}", retryable=True)
            except (TimeoutError, json.JSONDecodeError) as error:
                last_error = LLMError(f"Bad response from {url}: {type(error).__name__}: {error}", retryable=True)

            if attempt < attempts - 1:
                time.sleep(min(4.0, 0.6 * (2 ** attempt)) + random.uniform(0, 0.3))

        self.last_error = str(last_error)
        raise LLMError(str(last_error) if last_error else "the model request failed")

    @staticmethod
    def _parse_reply(data: Dict[str, Any], latency: float) -> LLMReply:
        if not isinstance(data, dict):
            raise LLMError(f"Unexpected response: {data!r}")
        if data.get("error"):
            raise LLMError(f"Model error: {data['error']}")
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"No choices in response: {str(data)[:300]}")
        first = choices[0] or {}
        message = first.get("message") or {}
        # Newer reasoning models put the answer in `content` but the plan may
        # arrive as a JSON string there; some send `parsed`.
        text = message.get("content") or ""
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        parsed = message.get("parsed")
        return LLMReply(
            text=text.strip(),
            json=parsed if parsed is not None else extract_json(text),
            model=str(data.get("model") or ""),
            usage=data.get("usage") or {},
            latency=latency,
            raw=data,
            finish_reason=str(first.get("finish_reason") or ""),
        )
