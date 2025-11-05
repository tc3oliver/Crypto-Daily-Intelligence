#!/usr/bin/env python3
from __future__ import annotations

"""
高優先實作：使用 LiteLLM chat 產生每個主題的結構化研究 JSON。

輸出欄位：summary、market_impact、sentiment(0-10)、watch_symbols(list[str])、recommendation(optional)、source_count

TODO:
- [Schema] 以 Pydantic/JSON Schema 驗證欄位型別並自動修正異常值。
- [Prompt] 更精細的提示模板與 few-shot，提升穩定性。
"""

import argparse
import json
import re
import time
from typing import Dict, Iterable, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import (
    build_data_path,
    ensure_dir,
    litellm_chat,
    load_config,
    resolve_date_str,
    write_jsonl,
)


def load_topics(topics_path) -> List[Dict[str, object]]:
    with topics_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_json(text: str) -> Dict[str, object]:
    """嘗試從 LLM 回覆中擷取第一個 JSON 物件。"""
    if not text:
        return {}
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _default_row(topic_id: str, title: str, items: Iterable[Dict[str, object]]) -> Dict[str, object]:
    sources = [it.get("url") for it in items if isinstance(it, dict) and it.get("url")]
    return {
        "topic_id": topic_id,
        "topic_title": title,
        "summary": "N/A",
        "market_impact": "N/A",
        "sentiment": 5,
        "watch_symbols": [],
        "recommendation": None,
        "source_count": len(sources),
        "sources": sources[:10],
    }


def _prompt_for_topic(title: str, items: List[Dict[str, object]], *, max_items: int, max_snippet: int) -> List[Dict[str, str]]:
    lines: List[str] = []
    for it in items[:max_items]:
        t = (it.get("title") or "").strip()
        sn = (it.get("snippet") or "").strip()
        if not t and not sn:
            continue
        if sn:
            sn = sn[:max_snippet]
        src = (it.get("source") or "未知來源")
        # 精簡的一行，降低 token：
        # 標題 | 摘要：... | 來源 | URL
        line = f"- {t} | 摘要：{sn} | 來源：{src}"
        url = (it.get("url") or "").strip()
        if url:
            line += f" | {url}"
        lines.append(line)
    bullet = "\n".join(lines)
    system = (
        "你是資深加密市場分析師，請用繁體中文輸出 JSON，不要額外文字。"
        "欄位：summary(2-3 句)、market_impact(高/中/低)、sentiment(0-10 整數)、"
        "watch_symbols(最多 5 個代號)、recommendation(一句話建議)、source_count(整數)。"
    )
    user = f"主題：{title}\n參考資料：\n{bullet}\n請僅輸出 JSON 物件。"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate structured research per topic via LiteLLM chat")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today in timezone)")
    args = parser.parse_args()

    config = load_config()
    tz_name = config.get("output", {}).get("timezone", "UTC")
    today = args.date or resolve_date_str(tz_name)

    # 簡易 logger（同時輸出到 stdout 與 data/logs/YYYY-MM-DD.run.log）
    def _log(msg: str) -> None:
        from utils import iso_now  # 延遲載入避免頂端循環
        ts = iso_now(tz_name)
        log_path = build_data_path(config, "logs", f"{today}.run.log")
        ensure_dir(log_path)
        line = f"{ts} [deepresearch] {msg}\n"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass
        print(msg, flush=True)

    topics_path = build_data_path(config, "topics", f"{today}.json")
    research_path = build_data_path(config, "research", f"{today}.jsonl")

    t0 = time.time()
    _log(f"開始研究摘要：date={today} topics={topics_path} -> research={research_path}")

    if not topics_path.exists():
        _log(f"[ERROR] 找不到主題檔案：{topics_path}")
        raise SystemExit(f"找不到主題檔案：{topics_path}")

    topics = load_topics(topics_path)
    _log(f"載入主題完成：共 {len(topics)} 個主題")

    # 提示控制
    max_items_per_topic = int(config.get("runtime", {}).get("research_items_per_topic", 8))
    max_snippet_chars = int(config.get("runtime", {}).get("research_snippet_chars", 220))

    def _research_one(i: int, topic: Dict[str, object]) -> Dict[str, object]:
        topic_id = topic.get("topic_id", "topic-unknown")
        title = topic.get("title", "未命名主題")
        items: Iterable[Dict[str, object]] = topic.get("items", [])  # type: ignore[arg-type]
        items_list: List[Dict[str, object]] = [it for it in items if isinstance(it, dict)]
        row = _default_row(str(topic_id), str(title), items_list)
        try:
            messages = _prompt_for_topic(str(title), items_list, max_items=max_items_per_topic, max_snippet=max_snippet_chars)
            reply = litellm_chat(messages, config)
            data = _extract_json(reply)
            if data:
                row.update({
                    "summary": data.get("summary", row["summary"]),
                    "market_impact": data.get("market_impact", row["market_impact"]),
                    "sentiment": data.get("sentiment", row["sentiment"]),
                    "watch_symbols": data.get("watch_symbols", row["watch_symbols"]),
                    "recommendation": data.get("recommendation", row.get("recommendation")),
                    "source_count": data.get("source_count", row["source_count"]),
                })
                try:
                    if isinstance(row["sentiment"], (str, float)):
                        row["sentiment"] = int(round(float(row["sentiment"])) )
                except Exception:
                    row["sentiment"] = 5
                if not isinstance(row["watch_symbols"], list):
                    row["watch_symbols"] = []
            _log(f"主題處理完成：{i+1}/{len(topics)} -> {topic_id}：{str(title)[:28]}")
        except Exception as e:
            _log(f"[WARN] 主題處理失敗：{i+1}/{len(topics)} -> {topic_id}：{str(title)[:28]}，錯誤：{type(e).__name__}")
        return row

    max_workers = int(config.get("runtime", {}).get("research_max_workers", 4))
    _log(f"研究並行化：max_workers={max_workers}")

    research_rows_map: Dict[int, Dict[str, object]] = {}
    total = len(topics)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_research_one, i, topic): i for i, topic in enumerate(topics)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                row = fut.result()
            except Exception as e:  # pragma: no cover
                _log(f"[WARN] 研究工作失敗：index={i}，錯誤：{type(e).__name__}")
                # 保底：輸出預設行
                topic = topics[i]
                items: Iterable[Dict[str, object]] = topic.get("items", [])  # type: ignore[arg-type]
                items_list: List[Dict[str, object]] = [it for it in items if isinstance(it, dict)]
                row = _default_row(str(topic.get("topic_id", "topic-unknown")), str(topic.get("title", "未命名主題")), items_list)
            research_rows_map[i] = row
            done += 1
            if (done % 5) == 0 or done == total:
                _log(f"研究進度：{done}/{total}")

    # 依原始順序輸出
    research_rows: List[Dict[str, object]] = [research_rows_map[i] for i in range(total)]

    ensure_dir(research_path)
    write_jsonl(research_path, research_rows)
    _log(f"[OK] 已輸出 {len(research_rows)} 筆研究資料：{research_path}，總耗時={time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
