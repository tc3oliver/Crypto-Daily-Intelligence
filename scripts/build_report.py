#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# 讓此檔案可直接以 `python scripts/build_report.py` 執行並找到 scripts/utils.py
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from utils import (  # noqa: E402
    build_data_path,
    ensure_dir,
    iso_now,
    litellm_chat,
    load_config,
    read_jsonl,
    resolve_date_str,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the daily markdown report via LLM (using prompt)")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today in timezone)")
    args = parser.parse_args()

    config = load_config()
    tz_name = config.get("output", {}).get("timezone", "UTC")
    today = args.date or resolve_date_str(tz_name)

    # logger
    def _log(msg: str) -> None:
        ts = iso_now(tz_name)
        log_path = build_data_path(config, "logs", f"{today}.run.log")
        ensure_dir(log_path)
        line = f"{ts} [build_report] {msg}\n"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass
        print(msg, flush=True)

    metrics_path = build_data_path(config, "metrics", f"{today}.json")
    research_path = build_data_path(config, "research", f"{today}.jsonl")
    report_path = build_data_path(config, "reports", f"{today}.md")

    _log(f"開始生成報告（LLM 模式）：date={today}")

    # 讀取 prompt 模板（作為 system 指令）
    template_config = (
        config.get("output", {}).get("report_template")
        or config.get("report_template")
        or config.get("template_path")
        or "config/report_prompt.md"
    )
    prompt_path = Path(template_config)
    if not prompt_path.is_absolute():
        prompt_path = Path(__file__).resolve().parents[1] / prompt_path
    system_prompt = prompt_path.read_text(encoding="utf-8")

    # 讀取研究資料
    if not research_path.exists():
        _log(f"[ERROR] 找不到研究資料：{research_path}")
        raise SystemExit(f"找不到研究資料：{research_path}")
    research_rows: List[Dict[str, Any]] = read_jsonl(research_path)
    _log(f"研究資料載入完成：{len(research_rows)} 筆")

    # 讀取可用 metrics（可選，無則忽略）
    metrics: Dict[str, Any] = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            _log("已載入 metrics")
        except Exception:
            _log("[WARN] 讀取 metrics 失敗，將忽略")

    # 控制輸入大小：只保留研究所需欄位
    max_topics = int(config.get("runtime", {}).get("report_max_topics_in_prompt", 35))
    max_src = int(config.get("runtime", {}).get("report_sources_per_topic", 5))
    max_watch = int(config.get("runtime", {}).get("report_watch_per_topic", 5))

    def _compact_row(r: Dict[str, Any]) -> Dict[str, Any]:
        srcs = r.get("sources") or []
        if isinstance(srcs, list):
            srcs = srcs[:max_src]
        watch = r.get("watch_symbols") or []
        if isinstance(watch, list):
            watch = watch[:max_watch]
        return {
            "topic_id": r.get("topic_id"),
            "topic_title": r.get("topic_title"),
            "summary": r.get("summary"),
            "market_impact": r.get("market_impact"),
            "sentiment": r.get("sentiment"),
            "watch_symbols": watch,
            "source_count": r.get("source_count"),
            "sources": srcs,
        }

    compact_research = [_compact_row(r) for r in research_rows[:max_topics]]

    # 構建對話：system=報告提示、user=資料+指令
    ymd_slash = today.replace("-", "/")
    user_note = (
        f"請根據以上『研究資料』與『可用指標』，直接輸出完整的 Markdown 報告，日期標題為 {ymd_slash}。\n"
        "務必遵守輸出格式模板（章節與段落標題保持一致），若數值缺失以 N/A 填寫，不要保留 {{...}} 佔位符。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "研究資料（JSON 列表）：\n" + json.dumps(compact_research, ensure_ascii=False) +
                "\n\n可用指標（如有）：\n" + json.dumps(metrics or {}, ensure_ascii=False) +
                "\n\n" + user_note
            ),
        },
    ]

    t0 = time.time()
    _log("呼叫 LLM 生成報告…")
    md = litellm_chat(messages, config)
    cost = time.time() - t0
    if not md:
        # Fallback：進一步縮小輸入，僅保留 title/summary/sentiment
        _log("[WARN] LLM 無回應，將以精簡資料重試一次…")
        small_n = min(20, max_topics)
        tiny_research = [
            {
                "topic_title": r.get("topic_title"),
                "summary": r.get("summary"),
                "sentiment": r.get("sentiment"),
            }
            for r in research_rows[:small_n]
        ]
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "研究資料（精簡版）：\n" + json.dumps(tiny_research, ensure_ascii=False) +
                    "\n\n可用指標（如有）：\n" + json.dumps(metrics or {}, ensure_ascii=False) +
                    "\n\n" + user_note
                ),
            },
        ]
        t1 = time.time()
        md = litellm_chat(messages, config)
        cost = time.time() - t1
        if not md:
            _log("[WARN] LLM 仍無回應，輸出失敗。")
            raise SystemExit("LLM 生成失敗，未得到內容（含精簡重試）")

    ensure_dir(report_path)
    report_path.write_text(md, encoding="utf-8")
    _log(f"[OK] 報告已生成：{report_path}，耗時={cost:.2f}s")


if __name__ == "__main__":
    main()
