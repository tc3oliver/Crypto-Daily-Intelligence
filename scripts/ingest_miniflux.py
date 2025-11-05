#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from dateutil import parser as dtparser

from utils import (
    build_data_path,
    ensure_dir,
    load_config,
    now_in_timezone,
    resolve_date_str,
)
import argparse


def http_get_with_retry(
    url: str,
    *,
    headers: Dict[str, str],
    params: Dict[str, Any],
    timeout: float,
    max_attempts: int = 3,
    backoff_seconds: float = 3.0,
) -> requests.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            # 重試 429/5xx
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"server error {resp.status_code}")
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(backoff_seconds)
            else:
                raise
    assert last_exc is not None
    raise last_exc


def fetch_entries(
    endpoint_url: str,
    token: str,
    params: Dict[str, Any],
    timeout: float,
    max_attempts: int,
    backoff_seconds: float,
) -> List[Dict[str, Any]]:
    headers = {"X-Auth-Token": token, "Accept": "application/json"}
    response = http_get_with_retry(
        endpoint_url,
        headers=headers,
        params=params,
        timeout=timeout,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and "entries" in data:
        return data.get("entries", [])
    if isinstance(data, list):
        return data
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest entries from Miniflux into raw JSONL")
    parser.add_argument("--date", help="Target date YYYY-MM-DD to name output file (defaults to today)")
    args = parser.parse_args()

    config = load_config()
    miniflux_cfg = config.get("miniflux", {})
    tz_name = config.get("output", {}).get("timezone", "UTC")

    base_url = miniflux_cfg.get("base_url")
    token = miniflux_cfg.get("token")
    categories = miniflux_cfg.get("categories", [])
    limit = miniflux_cfg.get("limit", 300)
    window_hours = miniflux_cfg.get("window_hours", 24)

    if not base_url or not token:
        raise SystemExit("Miniflux 設定缺少 base_url 或 token")

    if not categories:
        raise SystemExit("Miniflux 至少需要一個 category")

    now = now_in_timezone(tz_name)
    since = now - timedelta(hours=window_hours)
    # Miniflux 對 RFC3339 時間較嚴格，使用 UTC 並以 Z 結尾
    from datetime import timezone as _tz
    since_utc = since.astimezone(_tz.utc).replace(microsecond=0)
    since_iso = since_utc.isoformat().replace("+00:00", "Z")

    collected: List[Dict[str, Any]] = []
    timeout_seconds = float(miniflux_cfg.get("timeout_seconds", 30))
    r_cfg = miniflux_cfg.get("retries", {}) or {}
    max_attempts = int(r_cfg.get("max_attempts", 3))
    backoff_seconds = float(r_cfg.get("backoff_seconds", 3))
    for category_id in categories:
        endpoint = base_url.rstrip("/") + f"/v1/categories/{category_id}/entries"
        # published_after 依官方文件需為 unix timestamp（秒）
        since_ts = int(since_utc.timestamp())
        params = {
            "limit": limit,
            "published_after": since_ts,
        }
        status_opt = miniflux_cfg.get("status")
        if status_opt:
            params["status"] = status_opt
        order_opt = miniflux_cfg.get("order")
        if order_opt:
            params["order"] = order_opt
        direction_opt = miniflux_cfg.get("direction")
        if direction_opt:
            params["direction"] = direction_opt
        try:
            entries = fetch_entries(
                endpoint,
                token,
                params,
                timeout_seconds,
                max_attempts,
                backoff_seconds,
            )
        except requests.RequestException as exc:
            print(f"[WARN] category {category_id} 取得失敗: {exc}")
            continue
        # 伺服器端參數在某些部署上可能被忽略，保險起見在客戶端再做一次 24 小時過濾（published_at）
        kept: List[Dict[str, Any]] = []
        dropped = 0
        for e in entries:
            ts_str = e.get("published_at") or e.get("created_at")
            if not ts_str:
                dropped += 1
                continue
            try:
                ts = dtparser.isoparse(ts_str)
            except Exception:
                dropped += 1
                continue
            # 與 since 比較（兩者皆為 aware）
            if ts >= since:
                kept.append(e)
            else:
                dropped += 1
        print(
            f"[INFO] category {category_id}: 原始 {len(entries)} 筆，時窗內（>= {since_iso}）保留 {len(kept)} 筆，丟棄 {dropped} 筆"
        )
        collected.extend(kept)

    # 去重（以 id、或 title+url 鍵）
    deduped: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, Any, Any]] = set()
    for entry in collected:
        eid = entry.get("id")
        title = (entry.get("title") or "").strip()
        url = entry.get("url") or entry.get("link")
        key = (eid, title, url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    today = args.date or resolve_date_str(tz_name)
    target = build_data_path(config, "raw", f"{today}.jsonl")
    ensure_dir(target)
    with target.open("w", encoding="utf-8") as handle:
        for entry in deduped:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"共寫入 {len(deduped)} 筆 Miniflux entries 至 {target}")


if __name__ == "__main__":
    main()
