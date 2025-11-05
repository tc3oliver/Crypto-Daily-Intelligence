import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import requests
import yaml

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config" / "app.yaml"

def load_config() -> Dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)

def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def iso_now(tz_name: str) -> str:
    return now_in_timezone(tz_name).isoformat()


def resolve_date_str(tz_name: str) -> str:
    return now_in_timezone(tz_name).strftime("%Y-%m-%d")

def read_jsonl(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]

def write_jsonl(path: Path, rows: list[Dict[str, Any]]) -> None:
    ensure_dir(path)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_data_path(config: Dict[str, Any], *parts: str) -> Path:
    base_dir = Path(config.get("output", {}).get("base_dir", "data"))
    return (BASE_DIR / base_dir).joinpath(*parts)


def now_in_timezone(tz_name: str) -> datetime:
    if tz_name == "local" or ZoneInfo is None:
        return datetime.now().astimezone()
    return datetime.now(ZoneInfo(tz_name))


# === LiteLLM/OpenAI-compatible helpers ===

def _build_litellm_headers(config: Dict[str, Any]) -> Dict[str, str]:
    api_key = config.get("litellm", {}).get("api_key") or ""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _join_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    path = path.lstrip("/")
    return f"{base}/{path}"


def request_with_retry(method: str, url: str, *, json_body: Any | None, headers: Dict[str, str], timeout: float, max_attempts: int, backoff_seconds: float) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(method, url, json=json_body, headers=headers, timeout=timeout)
            # retry on 429/5xx
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"server error {resp.status_code}")
            return resp
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(backoff_seconds)
            else:
                raise
    # should not reach here
    assert last_exc is not None
    raise last_exc


def litellm_embed(texts: list[str], config: Dict[str, Any]) -> list[list[float]]:
    """呼叫 LiteLLM proxy 的 embeddings 端點（OpenAI 兼容）。
    可能的路徑：/v1/embeddings 或 /embeddings。"""
    base = config.get("litellm", {}).get("base_url", "http://localhost:9400")
    model = config.get("litellm", {}).get("model_embed", "text-embedding-3-small")
    timeout = float(config.get("litellm", {}).get("timeouts", {}).get("embed", 30))
    rt = config.get("litellm", {}).get("retries", {}).get("embed", {})
    max_attempts = int(rt.get("max_attempts", 2))
    backoff = float(rt.get("backoff_seconds", 4))

    url = _join_url(base, "v1/embeddings")
    headers = _build_litellm_headers(config)
    body = {"model": model, "input": texts}
    try:
        resp = request_with_retry("POST", url, json_body=body, headers=headers, timeout=timeout, max_attempts=max_attempts, backoff_seconds=backoff)
        resp.raise_for_status()
        data = resp.json() or {}
        vectors: list[list[float]] = []
        for item in data.get("data", []) or []:
            emb = item.get("embedding")
            if isinstance(emb, list):
                vectors.append([float(x) for x in emb])
        return vectors
    except Exception:
        return []


def litellm_chat(messages: list[Dict[str, Any]], config: Dict[str, Any]) -> str:
    """呼叫 LiteLLM proxy 的 chat/completions；回傳第一段文字。"""
    base = config.get("litellm", {}).get("base_url", "http://localhost:9400")
    model = config.get("litellm", {}).get("model_chat", "gpt-3.5-turbo")
    timeout = float(config.get("litellm", {}).get("timeouts", {}).get("chat", 60))
    max_tokens = config.get("litellm", {}).get("max_tokens")
    rt = config.get("litellm", {}).get("retries", {}).get("chat", {})
    max_attempts = int(rt.get("max_attempts", 3))
    backoff = float(rt.get("backoff_seconds", 4))

    url = _join_url(base, "v1/chat/completions")
    headers = _build_litellm_headers(config)
    body = {"model": model, "messages": messages, "temperature": 0.2, "stream": False}
    if isinstance(max_tokens, int) and max_tokens > 0:
        body["max_tokens"] = max_tokens
    try:
        resp = request_with_retry("POST", url, json_body=body, headers=headers, timeout=timeout, max_attempts=max_attempts, backoff_seconds=backoff)
        resp.raise_for_status()
        data = resp.json() or {}
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                return content.strip()
        return ""
    except Exception:
        return ""
