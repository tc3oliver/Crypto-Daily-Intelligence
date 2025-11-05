#!/usr/bin/env python3
from __future__ import annotations

"""
高優先實作：取得每日市場指標（擴充硬指標）

來源與注意事項：
- 價格/總市值：CoinGecko 公開 API（無需金鑰，偶有速率限制）
- 清算/多空比：Coinglass API（需 API Key；若無則回退為 None）
- 硬指標（新增）：
    1) Fear & Greed Index（Alternative.me）
    2) Funding Rate（Binance Futures）
    3) Long/Short Ratio（Binance Futures）
    4) 24h Liquidations（Gate.io BigData；嘗試 requests，若失敗再用 Playwright）
    5) BTC/ETH 現貨 ETF 淨流入（SoSoValue，HTML 解析）

輸出欄位：
- btc.price/usd、btc.change_24h、eth.price/usd、eth.change_24h
- market.total_cap（USD）與 market.total_change_24h（%）
- derivatives.liq_total_24h_usd（USD）、derivatives.long_ratio（0-1）
- etf.btc_spot_flow_usd、etf.eth_spot_flow_usd（USD，可能為正負值）
- hard（新增）：fear_greed_index、funding_rate、long_short_ratio、liquidations_24h、btc_etf_netflow、eth_etf_netflow（多為字串 display）

TODO:
- [ETF] 改由穩定 provider（商業 API 或快取策略）
- [Caching] 視需要加入磁碟/記憶體快取，避免同日重複打 API。
- [Backfill] 支援指定日期歷史資料回填（目前抓即時）。
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from bs4 import BeautifulSoup  # type: ignore

from utils import build_data_path, ensure_dir, iso_now, load_config, resolve_date_str


COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGLASS_BASE = "https://open-api.coinglass.com/api/pro/v1"
GATE_BIGDATA_API = "https://www.gate.com/api/bigdata/zone/v1/liquidation/overview"

# SoSoValue ETF pages
SOSO_BTC = "https://sosovalue.com/tc/assets/etf/us-btc-spot"
SOSO_ETH = "https://sosovalue.com/tc/assets/etf/us-eth-spot"


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def fetch_prices_from_coingecko(timeout: float = 10.0) -> Dict[str, Any]:
    """抓取 BTC/ETH 的 USD 價格與 24h 變化。"""
    url = f"{COINGECKO_BASE}/simple/price"
    params = {
        "ids": "bitcoin,ethereum",
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json() or {}
        btc = data.get("bitcoin", {})
        eth = data.get("ethereum", {})
        return {
            "btc": {
                "price": _safe_float(btc.get("usd")),
                "change_24h": _safe_float(btc.get("usd_24h_change")),
            },
            "eth": {
                "price": _safe_float(eth.get("usd")),
                "change_24h": _safe_float(eth.get("usd_24h_change")),
            },
        }
    except requests.RequestException:
        return {"btc": {"price": None, "change_24h": None}, "eth": {"price": None, "change_24h": None}}


def fetch_global_from_coingecko(timeout: float = 10.0) -> Dict[str, Any]:
    """抓取總市值與 24h 變化百分比。"""
    url = f"{COINGECKO_BASE}/global"
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json() or {}
        d = data.get("data", {}) if isinstance(data, dict) else {}
        total_cap = None
        total_change = None
        mcap = d.get("total_market_cap", {})
        if isinstance(mcap, dict):
            total_cap = _safe_float(mcap.get("usd"))
        total_change = _safe_float(d.get("market_cap_change_percentage_24h_usd"))
        return {"market": {"total_cap": total_cap, "total_change_24h": total_change}}
    except requests.RequestException:
        return {"market": {"total_cap": None, "total_change_24h": None}}


def fetch_derivatives_from_coinglass(api_key: Optional[str], timeout: float = 10.0) -> Dict[str, Any]:
    """抓取 24h 清算總額與多空比。
    需要 COINGLASS_API_KEY，若無則回傳 None 欄位。
    注意：實際端點與參數可能會調整，這裡採通用寫法並加上 TODO。"""
    if not api_key:
        return {"derivatives": {"liq_total_24h_usd": None, "long_ratio": None}}

    headers = {"coinglassSecret": api_key}
    liq_total = None
    long_ratio = None

    # TODO: 確認正式端點與參數（此為參考樣式）
    try:
        # 24H liquidation (all symbols aggregated)
        url_liq = f"{COINGLASS_BASE}/futures/liquidation_history"
        params_liq = {"symbol": "all", "interval": "24H"}
        r1 = requests.get(url_liq, headers=headers, params=params_liq, timeout=timeout)
        if r1.status_code == 200:
            j = r1.json() or {}
            # 依照實際 API 結構彙總 USD 清算額
            data = j.get("data")
            if isinstance(data, list) and data:
                # 簡化：取最後一筆的 totalUSD 或自行 sum
                last = data[-1]
                liq_total = _safe_float(last.get("totalUSD")) or _safe_float(last.get("total_usd"))
    except requests.RequestException:
        pass

    try:
        # Long/Short ratio（示意）
        url_longshort = f"{COINGLASS_BASE}/futures/long_short_account_ratio"
        params_ls = {"symbol": "BTC", "interval": "24H"}
        r2 = requests.get(url_longshort, headers=headers, params=params_ls, timeout=timeout)
        if r2.status_code == 200:
            j = r2.json() or {}
            data = j.get("data")
            # 依實際 API 結構計算 long_ratio（0-1）。這裡示意取 long/(long+short)
            if isinstance(data, list) and data:
                last = data[-1]
                long_val = _safe_float(last.get("longAccount"))
                short_val = _safe_float(last.get("shortAccount"))
                if long_val is not None and short_val is not None and (long_val + short_val) > 0:
                    long_ratio = round(long_val / (long_val + short_val), 4)
    except requests.RequestException:
        pass

    return {"derivatives": {"liq_total_24h_usd": liq_total, "long_ratio": long_ratio}}


def fetch_etf_flows_placeholder() -> Dict[str, Any]:
    """ETF 淨流入暫置：保留欄位以利模板解析。"""
    # TODO: 實作實際 ETF 流量來源（例如：商業 API 或抓取 Farside/SoSoValue）
    return {"etf": {"btc_spot_flow_usd": None, "eth_spot_flow_usd": None}}


# === 硬指標擴充 ===

def fetch_fear_greed(timeout: float = 10.0) -> Any:
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json().get("data", [])
        if data:
            return int(data[0].get("value"))
    except Exception:
        pass
    return "N/A"


def fetch_funding_rate_binance(timeout: float = 10.0) -> Any:
    try:
        url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json() or {}
        rate = float(data.get("lastFundingRate")) * 100.0
        return f"{rate:.4f}%"
    except Exception:
        return "N/A"


def fetch_long_short_ratio_binance(timeout: float = 10.0) -> Dict[str, Any]:
    try:
        url = (
            "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
            "?symbol=BTCUSDT&period=1d&limit=1"
        )
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        arr = r.json() or []
        if arr:
            last = arr[0]
            long_acc = float(last.get("longAccount"))
            short_acc = float(last.get("shortAccount"))
            display = long_acc / max(short_acc, 1e-9)
            denom = long_acc + short_acc
            ratio_0_1 = (long_acc / denom) if denom > 0 else None
            return {"display": f"{display:.2f}", "ratio_0_1": ratio_0_1}
    except Exception:
        return {"display": "N/A", "ratio_0_1": None}


def _gate_liq_via_requests(timeout: float = 12.0) -> Optional[Dict[str, Any]]:
    try:
        params = {"coin_type": "ALL", "ex": "ALL", "time_type": "24H"}
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(GATE_BIGDATA_API, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()  # type: ignore[return-value]
    except Exception:
        return None


def _gate_liq_via_playwright(timeout_ms: int = 60000) -> Optional[Dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://www.gate.com/zh-tw/crypto-market-data/funds/liquidation", timeout=timeout_ms)
            resp = page.request.get(
                f"{GATE_BIGDATA_API}?coin_type=ALL&ex=ALL&time_type=24H"
            )
            data = resp.json()
            browser.close()
            return data
    except Exception:
        return None


def fetch_liquidations_24h_gate() -> Dict[str, Any]:
    # 先嘗試 requests，若不通再走 Playwright
    data = _gate_liq_via_requests()
    if data is None:
        data = _gate_liq_via_playwright()
    try:
        if not data:
            raise ValueError("empty")
        if not data.get("success") or "data" not in data:
            raise ValueError("unexpected response")
        d = data["data"]
        liquid_24h = d.get("24H", {})
        summary = d.get("summary", {})
        total_amt = liquid_24h.get("total_burst_amt") or summary.get("total_burst_amt_24h") or 0
        total = float(total_amt)
        return {"display": f"${total:,.0f}", "usd": total}
    except Exception:
        return {"display": "N/A", "usd": None}


def _parse_money_cell(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = raw.replace("$", "").replace(",", "").strip()
    multiplier = 1.0
    for suffix, mul in ("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000):
        if s.endswith(suffix):
            s = s[:-1]
            multiplier = mul
            break
    try:
        return float(s) * multiplier
    except Exception:
        return None


def parse_sosovalue_etf_netflow(url: str, timeout: float = 15.0) -> Dict[str, Any]:
    """解析 SoSoValue ETF 表格，回傳 display 與 numeric。"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if not table:
            raise ValueError("No table found")
        rows = table.find_all("tr")
        if len(rows) < 2:
            raise ValueError("No data rows")
        header_tds = rows[0].find_all(["th", "td"])
        col_map = {td.get_text(strip=True): idx for idx, td in enumerate(header_tds)}
        target_col = None
        for key, idx in col_map.items():
            if "單日淨流入" in key or "單日净流入" in key:
                target_col = idx
                break
        if target_col is None:
            raise ValueError("Cannot locate '單日淨流入' column")
        total = 0.0
        for tr in rows[1:]:
            tds = tr.find_all("td")
            if len(tds) <= target_col:
                continue
            raw = tds[target_col].get_text(strip=True)
            if not raw or raw == "-" or ("未更新" in raw):
                continue
            v = _parse_money_cell(raw)
            if v is not None:
                total += v
        return {"display": f"${total:,.0f}", "usd": total}
    except Exception:
        return {"display": "N/A", "usd": None}


def fetch_btc_etf_flow_soso() -> Dict[str, Any]:
    return parse_sosovalue_etf_netflow(SOSO_BTC)


def fetch_eth_etf_flow_soso() -> Dict[str, Any]:
    return parse_sosovalue_etf_netflow(SOSO_ETH)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch market metrics and write daily JSON")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today in timezone)")
    args = parser.parse_args()

    config = load_config()
    tz_name = config.get("output", {}).get("timezone", "UTC")
    today = args.date or resolve_date_str(tz_name)

    # 1) 現貨價格與總市值（CoinGecko）
    prices = fetch_prices_from_coingecko()
    global_mkt = fetch_global_from_coingecko()

    # 2) 衍生品（Coinglass，可選）
    api_key = os.getenv("COINGLASS_API_KEY")
    derivatives = fetch_derivatives_from_coinglass(api_key)

    # 3) ETF（暫置 + SoSoValue 覆蓋 display/數值）
    etf = fetch_etf_flows_placeholder()
    btc_etf = fetch_btc_etf_flow_soso()
    eth_etf = fetch_eth_etf_flow_soso()
    if btc_etf.get("usd") is not None:
        etf["etf"]["btc_spot_flow_usd"] = btc_etf["usd"]
    if eth_etf.get("usd") is not None:
        etf["etf"]["eth_spot_flow_usd"] = eth_etf["usd"]

    # 4) 硬指標（Fear&Greed、Funding、Long/Short、Gate 清算、SoSoValue 顯示值）
    fg = fetch_fear_greed()
    fr = fetch_funding_rate_binance()
    ls = fetch_long_short_ratio_binance()
    liq = fetch_liquidations_24h_gate()
    hard: Dict[str, Any] = {
        "fear_greed_index": fg,
        "funding_rate": fr,
        "long_short_ratio": ls.get("display"),
        "liquidations_24h": liq.get("display"),
        "btc_etf_netflow": btc_etf.get("display"),
        "eth_etf_netflow": eth_etf.get("display"),
    }

    # 若 Coinglass 缺失，嘗試用 fallback 補上 derivatives 數值
    if derivatives.get("derivatives", {}).get("liq_total_24h_usd") in (None,):
        if liq.get("usd") is not None:
            derivatives["derivatives"]["liq_total_24h_usd"] = liq.get("usd")
    if derivatives.get("derivatives", {}).get("long_ratio") in (None,):
        if ls.get("ratio_0_1") is not None:
            derivatives["derivatives"]["long_ratio"] = ls.get("ratio_0_1")

    payload: Dict[str, Any] = {
        "as_of": iso_now(tz_name),
        **prices,
        **global_mkt,
        **derivatives,
        **etf,
        "hard": hard,
    }

    target: Path = build_data_path(config, "metrics", f"{today}.json")
    ensure_dir(target)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 指標寫入：{target}")


if __name__ == "__main__":
    main()
