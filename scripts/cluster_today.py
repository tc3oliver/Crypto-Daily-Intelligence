#!/usr/bin/env python3
from __future__ import annotations

"""
高優先實作：以 LiteLLM embeddings 進行 cosine 分群，並以 chat 生成主題名稱。

TODO:
- [Batching] 將 embedding 請求分批（目前一次全部，若文本很多可能超參數上限）。
- [RepText] 代表文本可改為 TF-IDF 關鍵句或中心句；目前採用首兩則標題拼接。
- [RateLimit] 如遇 429 需更精細的節流策略；現依 utils 重試處理。
"""

import argparse
import json
import time
import re
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

import numpy as np

from utils import (
    build_data_path,
    ensure_dir,
    iso_now,
    litellm_chat,
    litellm_embed,
    load_config,
    read_jsonl,
    resolve_date_str,
)


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n == 0:
        return v
    return v / n


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def _prepare_text(item: Dict[str, object]) -> str:
    title = str(item.get("title") or "").strip()
    text = str(item.get("text") or "").strip()
    if text:
        text = text[:500]
    return (title + "\n" + text).strip()


def _title_with_chat(headlines: List[str], config: Dict[str, object]) -> str:
    sample = "\n".join(f"- {h}" for h in headlines[:6])
    messages = [
        {"role": "system", "content": "你是一位加密市場分析師，請用繁體中文生成精煉、可讀性高的主題標題（10-30 字），不要加標點。"},
        {"role": "user", "content": f"根據以下文章標題，產出一個主題名稱：\n{sample}"},
    ]
    title = litellm_chat(messages, config) or ""
    title = title.strip().splitlines()[0] if title else ""
    if not title:
        title = headlines[0] if headlines else "未命名主題"
    return title


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster today's normalized items into topics")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today in timezone)")
    args = parser.parse_args()

    config = load_config()
    tz_name = config.get("output", {}).get("timezone", "UTC")
    today = args.date or resolve_date_str(tz_name)

    normalized_path = build_data_path(config, "normalized", f"{today}.jsonl")
    topics_path = build_data_path(config, "topics", f"{today}.json")

    # 簡易 logger（同時輸出到 stdout 與 data/logs/YYYY-MM-DD.run.log）
    def _log(msg: str) -> None:
        tz_name_local = config.get("output", {}).get("timezone", "UTC")
        ts = iso_now(tz_name_local)
        log_path = build_data_path(config, "logs", f"{today}.run.log")
        ensure_dir(log_path)
        line = f"{ts} [cluster_today] {msg}\n"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            # 忽略檔案寫入失敗，保留 stdout
            pass
        print(msg, flush=True)

    t0 = time.time()
    _log(f"開始分群：date={today} normalized={normalized_path}")

    items = read_jsonl(normalized_path)
    if not items:
        _log(f"[WARN] 無清洗資料可供分群：{normalized_path}")
        return

    # 取文本，產生 embeddings
    texts = [_prepare_text(it) for it in items]
    _log(f"Embeddings 開始：items={len(texts)} 模型={config.get('litellm', {}).get('model_embed')}")
    e0 = time.time()
    vectors = litellm_embed(texts, config)
    _log(f"Embeddings 完成：耗時={time.time()-e0:.2f}s 取得={len(vectors) if vectors else 0}")
    if not vectors or len(vectors) != len(items):
        # Fallback：全部放在單一主題
        primary_topic: Dict[str, object] = {
            "topic_id": "topic-001",
            "title": "今日焦點匯總",
            "count": len(items),
            "representative_text": (items[0].get("title") if items else ""),
            "items": items,
        }
        ensure_dir(topics_path)
        topics_path.write_text(json.dumps([primary_topic], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _log(f"[WARN] 無法取得 embeddings，已回退為單一主題：{topics_path}")
        return

    vecs = np.array([_norm(np.array(v, dtype=float)) for v in vectors])

    # 將分群邏輯封裝以便做自適應閾值調整
    def _cluster_with_threshold(th: float) -> List[Dict[str, object]]:
        _log(f"分群開始：threshold={th:.4f} items={len(vecs)}")
        cl: List[Dict[str, object]] = []
        for idx, v in enumerate(vecs):
            best_ci = -1
            best_sim = -1.0
            for ci, c in enumerate(cl):
                cvec = c["centroid"]  # type: ignore[index]
                sim = _cosine(v, cvec)
                if sim > best_sim:
                    best_sim = sim
                    best_ci = ci
            if best_ci >= 0 and best_sim >= th:
                c = cl[best_ci]
                indices: List[int] = c["indices"]  # type: ignore[index]
                n = len(indices)
                cvec = c["centroid"]  # type: ignore[index]
                new_centroid = _norm((cvec * n + v) / (n + 1))
                c["centroid"] = new_centroid  # type: ignore[index]
                indices.append(idx)
            else:
                cl.append({"centroid": v, "indices": [idx]})
            if (idx + 1) % 200 == 0:
                _log(f"分群進度：{idx+1}/{len(vecs)}，目前群數={len(cl)}")
        return cl

    # 閾值自適應：嘗試在 [min,max] 範圍調整，使得群數不大於 1.2 * max_topics
    max_topics = int(config.get("runtime", {}).get("max_topics_per_day", 40))
    desired_max = int(max_topics * 1.2)
    threshold = float(config.get("runtime", {}).get("similarity_threshold", 0.82))
    th_min = float(config.get("runtime", {}).get("similarity_threshold_min", 0.60))
    th_max = float(config.get("runtime", {}).get("similarity_threshold_max", 0.90))
    threshold = max(min(threshold, th_max), th_min)

    clusters: List[Dict[str, object]] = _cluster_with_threshold(threshold)
    tries = 0
    while len(clusters) > desired_max and threshold > th_min and tries < 6:
        old_th = threshold
        threshold = max(th_min, threshold - 0.02)
        _log(f"群數過多（{len(clusters)}），下調 threshold：{old_th:.4f} -> {threshold:.4f}")
        clusters = _cluster_with_threshold(threshold)
        tries += 1

    # 二次合併：嘗試將 singleton 以較低門檻併入最近的群
    merge_th = max(th_min, threshold - 0.05)
    singletons = [c for c in clusters if len(c["indices"]) == 1]  # type: ignore[index]
    non_single = [c for c in clusters if len(c["indices"]) > 1]   # type: ignore[index]
    if singletons and non_single:
        moved = 0
        for c in list(singletons):
            idx = c["indices"][0]  # type: ignore[index]
            v = vecs[idx]
            best_ci = -1
            best_sim = -1.0
            for ci, d in enumerate(non_single):
                sim = _cosine(v, d["centroid"])  # type: ignore[index]
                if sim > best_sim:
                    best_sim = sim
                    best_ci = ci
            if best_ci >= 0 and best_sim >= merge_th:
                # 併入目標群
                tgt = non_single[best_ci]
                indices: List[int] = tgt["indices"]  # type: ignore[index]
                n = len(indices)
                cvec = tgt["centroid"]  # type: ignore[index]
                new_centroid = _norm((cvec * n + v) / (n + 1))
                tgt["centroid"] = new_centroid  # type: ignore[index]
                indices.append(idx)
                moved += 1
            else:
                # 仍保留為單一群
                non_single.append(c)
        clusters = non_single
        if moved:
            _log(f"二次合併完成：併入 {moved} 個單一項群，合併門檻={merge_th:.4f}")

    # 以群大小排序，取前 N 群
    max_items_per_topic = int(config.get("runtime", {}).get("max_items_per_topic", 15))
    _log(f"分群完成：總群數={len(clusters)}，排序裁切至前 {max_topics} 群（門檻={threshold:.4f}）")
    clusters.sort(key=lambda c: len(c["indices"]) if isinstance(c.get("indices"), list) else 0, reverse=True)
    clusters = clusters[:max_topics]

    topic_dicts: List[Dict[str, object]] = []
    _log(f"主題命名開始：群數={len(clusters)}，每群最多 {max_items_per_topic} 筆")
    # 準備每群的 headlines 與 items
    prepared: List[Dict[str, object]] = []
    for c in clusters:
        indices: List[int] = c["indices"]  # type: ignore[index]
        cluster_items = [items[j] for j in indices][:max_items_per_topic]
        headlines = [str(it.get("title")) for it in cluster_items if it.get("title")]
        prepared.append({
            "indices": indices,
            "items": cluster_items,
            "headlines": headlines,
        })

    # 以執行緒池並行命名，限制最大並行度避免觸發速率限制
    max_workers = int(config.get("runtime", {}).get("naming_max_workers", 4))
    # 單條群（或 headline 不足）不呼叫 LLM，直接用第一個標題
    to_name: List[int] = []
    titles: Dict[int, str] = {}
    skipped = 0
    for i, p in enumerate(prepared):
        heads = p["headlines"]  # type: ignore[index]
        indices = p["indices"]  # type: ignore[index]
        if len(indices) <= 1 or len(heads) <= 1:
            titles[i] = (heads[0] if heads else "未命名主題")
            skipped += 1
        else:
            to_name.append(i)

    _log(f"主題命名並行化：max_workers={max_workers}，需命名={len(to_name)}，直接使用標題（跳過 LLM）={skipped}")
    if to_name:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_title_with_chat, prepared[i]["headlines"], config): i for i in to_name}
            done = 0
            total = len(to_name)
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    t = fut.result(timeout=float(config.get("litellm", {}).get("timeouts", {}).get("chat", 60)))
                except Exception:
                    t = ""
                if not t:
                    heads = prepared[i]["headlines"]  # type: ignore[index]
                    t = (heads[0] if heads else "未命名主題")
                titles[i] = t
                done += 1
                if (done % 5) == 0 or done == total:
                    _log(f"主題命名進度：{done}/{total}")

    # snippet 生成工具
    def _mk_snippet(item: Dict[str, object], max_chars: int) -> str:
        raw = str(item.get("text") or "").strip()
        if not raw:
            fallback = str(item.get("title") or "").strip()
            return fallback[:max_chars] if fallback else ""
        # 基礎清理：去 HTML 標籤與壓縮空白
        try:
            s = html.unescape(raw)
        except Exception:
            s = raw
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s[:max_chars]

    snippet_max = int(config.get("runtime", {}).get("snippet_max_chars", 300))

    for i in range(len(prepared)):
        indices: List[int] = prepared[i]["indices"]  # type: ignore[index]
        cluster_items = prepared[i]["items"]  # type: ignore[index]
        headlines = prepared[i]["headlines"]  # type: ignore[index]
        title = titles.get(i, (headlines[0] if headlines else "未命名主題"))
        rep_text = "；".join(headlines[:2]) if headlines else (cluster_items[0].get("text") if cluster_items else "")
        topic_dicts.append({
            "topic_id": f"topic-{i+1:03d}",
            "title": title,
            "count": len(indices),
            "representative_text": rep_text,
            "items": [
                {
                    "title": it.get("title"),
                    "source": (it.get("source") or None),
                    "url": it.get("url"),
                    "snippet": _mk_snippet(it, snippet_max),
                }
                for it in cluster_items
            ],
        })

    ensure_dir(topics_path)
    topics_path.write_text(json.dumps(topic_dicts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _log(f"[OK] 產生 {len(topic_dicts)} 個主題：{topics_path}，總耗時={time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
