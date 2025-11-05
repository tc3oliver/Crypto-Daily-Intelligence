#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from typing import Dict, List, Any

from dateutil import parser as dtparser

from utils import build_data_path, ensure_dir, load_config, read_jsonl, resolve_date_str, write_jsonl
import argparse

TAG_RE = re.compile(r"<[^>]+>")


def sanitize_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_timestamp(value: Any, tz_name: str) -> str | None:
    """將各式時間字串/數值正規化為指定時區的 ISO8601 字串；失敗回傳 None。"""
    if not value:
        return None
    try:
        dt = dtparser.parse(str(value))
        if not getattr(dt, "tzinfo", None):
            # 無時區資訊則假設為 UTC
            from datetime import timezone as _tz
            dt = dt.replace(tzinfo=_tz.utc)
        # 轉成輸出時區
        from utils import now_in_timezone

        target_tz = now_in_timezone(tz_name).tzinfo
        dt2 = dt.astimezone(target_tz)
        return dt2.isoformat()
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess raw entries into normalized JSONL")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today in timezone)")
    args = parser.parse_args()

    config = load_config()
    tz_name = config.get("output", {}).get("timezone", "UTC")
    today = args.date or resolve_date_str(tz_name)

    raw_path = build_data_path(config, "raw", f"{today}.jsonl")
    normalized_path = build_data_path(config, "normalized", f"{today}.jsonl")

    entries = read_jsonl(raw_path)
    if not entries:
        print(f"[WARN] 找不到原始資料 {raw_path}")
        return

    seen_keys: set[tuple] = set()
    cleaned: List[Dict[str, object]] = []

    for entry in entries:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        url = entry.get("url") or entry.get("link")
        key = (entry.get("id"), title, url)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        content = entry.get("content") or entry.get("summary") or ""
        text = sanitize_html(content)

        published_src = entry.get("published_at") or entry.get("date") or entry.get("created_at")
        published_iso = normalize_timestamp(published_src, tz_name)

        cleaned.append(
            {
                "item_id": entry.get("id"),
                "title": title,
                "text": text,
                "source": entry.get("feed", {}).get("title") if isinstance(entry.get("feed"), dict) else entry.get("feed_title"),
                "published_at": published_iso,
                "url": url,
            }
        )

    if not cleaned:
        print("[INFO] 沒有可用資料可清洗")
        return

    ensure_dir(normalized_path)
    write_jsonl(normalized_path, cleaned)
    print(f"已輸出 {len(cleaned)} 筆清洗後資料至 {normalized_path}")


if __name__ == "__main__":
    main()
