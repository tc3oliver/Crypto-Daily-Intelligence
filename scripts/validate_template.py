#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Set

from utils import build_data_path, load_config, read_jsonl, resolve_date_str


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^}]+?)\s*}}")


def collect_placeholders(template_text: str) -> Set[str]:
    return {m.group(1) for m in PLACEHOLDER_PATTERN.finditer(template_text)}


def build_context_for_date(config: Dict[str, Any], date_str: str) -> Dict[str, Any]:
    metrics_path = build_data_path(config, "metrics", f"{date_str}.json")
    research_path = build_data_path(config, "research", f"{date_str}.jsonl")

    metrics: Dict[str, Any] = {}
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    research_rows = read_jsonl(research_path)

    def fmt_b(value: Any) -> Any:
        try:
            return round(float(value) / 1_000_000_000, 2)
        except Exception:
            return None

    def fmt_m(value: Any) -> Any:
        try:
            return round(float(value) / 1_000_000, 2)
        except Exception:
            return None

    btc = metrics.get("btc", {}) if isinstance(metrics, dict) else {}
    eth = metrics.get("eth", {}) if isinstance(metrics, dict) else {}
    market = metrics.get("market", {}) if isinstance(metrics, dict) else {}
    deriv = metrics.get("derivatives", {}) if isinstance(metrics, dict) else {}
    etf = metrics.get("etf", {}) if isinstance(metrics, dict) else {}

    topics_summary = "N/A"
    if research_rows:
        titles = [row.get("topic_title") for row in research_rows if isinstance(row, dict)]
        titles = [t for t in titles if t]
        topics_summary = "、".join(map(str, titles[:5])) if titles else "N/A"

    context: Dict[str, Any] = {
        "report_date": date_str,
        "metrics": metrics,
        "topics_summary": topics_summary,
        "research_sections": "",
        "market_sentiment": "",
        "action_items": "",
        # Template compatibility keys
        "YYYY/MM/DD": date_str.replace("-", "/"),
        "BTC_PRICE": btc.get("price"),
        "BTC_CHANGE": btc.get("change_24h"),
        "ETH_PRICE": eth.get("price"),
        "ETH_CHANGE": eth.get("change_24h"),
        "TOTAL_CAP": fmt_b(market.get("total_cap")),
        "TOTAL_CHANGE": market.get("total_change_24h"),
        "LIQ_TOTAL": fmt_m(deriv.get("liq_total_24h_usd")),
        "LONG_RATIO": deriv.get("long_ratio"),
        "BTC_ETF_FLOW": fmt_m(etf.get("btc_spot_flow_usd")),
        "ETH_ETF_FLOW": fmt_m(etf.get("eth_spot_flow_usd")),
        "主題摘要": topics_summary,
        "主題名稱": (research_rows[0].get("topic_title") if research_rows else None),
    }
    return context


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate that report template placeholders can be resolved")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today)")
    parser.add_argument(
        "--template",
        default="config/report_prompt.md",
        help="Path to the template file",
    )
    args = parser.parse_args()

    config = load_config()
    tz_name = config.get("output", {}).get("timezone", "UTC")
    date_str = args.date or resolve_date_str(tz_name)

    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = Path(__file__).resolve().parents[1] / template_path

    template_text = template_path.read_text(encoding="utf-8")
    placeholders = collect_placeholders(template_text)
    context = build_context_for_date(config, date_str)

    # Resolve: known if direct key or dotted path reachable
    def has_key(key: str) -> bool:
        if key in context:
            return True
        # dotted path check
        value: Any = context
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return False
        return True

    missing = sorted([p for p in placeholders if not has_key(p)])
    if missing:
        print("[FAIL] 未對應的佔位符 (placeholders not mapped):")
        for p in missing:
            print(f" - {p}")
        raise SystemExit(1)
    else:
        print("[OK] 所有佔位符皆可解析")


if __name__ == "__main__":
    main()

