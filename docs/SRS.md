# 🧾 Software Requirements Specification (SRS)

**Project Name**：Crypto Daily Intelligence System
**Version**：1.0
**Author**：Oliver Yu
**Date**：2025-11-04
**Status**：Implementation Ready

---

## 1. 系統總覽（System Overview）

### 1.1 目的（Purpose）

本系統旨在每日自動生成《加密市場情報報告》，整合多來源幣圈新聞、行情指標、ETF 流向及情緒數據，並透過本地大型語言模型（LiteLLM Proxy）進行智能摘要與洞察分析，輸出結構化 Markdown 報告。

### 1.2 範圍（Scope）

系統每天定時執行：

1. 從 **Miniflux** 抓取 RSS 資訊源。
2. 經 **文本清洗與去重**，再以 **BGE-M3 模型** 生成 embeddings。
3. 使用 **相似度分群** 聚合同主題事件。
4. 以 **LiteLLM (`rag-answer`)** 對每主題進行深度研究。
5. 自外部 API 獲取行情資料（BTC、ETH、爆倉、ETF 流向等）。
6. 綜合所有資料生成 Markdown 格式報告。

最終產出將每日自動儲存於：

```
data/reports/YYYY-MM-DD.md
```

---

## 2. 系統架構（System Architecture）

```
┌───────────────────────────────────────────────────────────────┐
│                    Crypto Daily Intelligence                  │
│                                                               │
│  ┌───────────────┐   ┌────────────┐   ┌───────────────┐       │
│  │ Miniflux RSS  │→ │Preprocess  │→ │Embedding+Cluster│───┐   │
│  └───────────────┘   └────────────┘   └───────────────┘   │   │
│                                                          │   │
│                    ┌──────────────┐                      │   │
│                    │Deep Research │←──LiteLLM (rag-answer)│  │
│                    └──────────────┘                      │   │
│                                                          ↓   │
│  ┌────────────┐     ┌────────────┐    ┌────────────────────┐│
│  │ Metrics API│→→→ │Build Report│→→→│Markdown Output (報告)││
│  └────────────┘     └────────────┘    └────────────────────┘│
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. 系統功能（Functional Requirements）

| 模組                      | 功能名稱            | 說明                                                            |
| ----------------------- | --------------- | ------------------------------------------------------------- |
| **Ingestion Layer**     | Miniflux RSS 收集 | 透過 API 抓取指定分類 RSS 條目（24h 內），並以 JSONL 格式儲存                     |
| **Preprocess Layer**    | 清洗與標準化          | 去除 HTML、重複與噪音，產生 `normalized/YYYY-MM-DD.jsonl`                |
| **Clustering Layer**    | 相似度分群           | 使用 `/v1/embeddings` + cosine similarity 將相似內容合併為主題            |
| **Topic Labeling**      | 主題命名            | 呼叫 LiteLLM，根據每群標題生成一句簡短主題名稱                                   |
| **Deep Research Layer** | 主題深研            | 每個 topic 呼叫 LiteLLM，生成 JSON 格式的研究結果（summary、impact、sentiment） |
| **Metrics Collector**   | 行情資料查詢          | 透過外部 API 取得 BTC、ETH、總市值、ETF 流向、爆倉數據                           |
| **Report Builder**      | 報告生成            | 將 metrics + research + 模板送入 LLM 生成 Markdown 報告                |
| **Scheduler (cron)**    | 定時執行            | 每日 07:55–08:05 自動執行全流程                                        |

---

## 4. 非功能性需求（Non-functional Requirements）

| 類別       | 要求                                           |
| -------- | -------------------------------------------- |
| **可靠性**  | 每日報告產生成功率需 ≥ 95%。失敗時可人工重跑指定日期。               |
| **可追溯性** | 每一階段均輸出 timestamped JSON / JSONL，方便回溯。       |
| **延遲**   | 從 ingest → 報告生成不超過 5 分鐘（不含 LLM 回覆時間）。        |
| **擴展性**  | 可支援多分類 RSS、加 Twitter/X、Telegram feed。        |
| **安全性**  | Token 儲存在 `.env` 或 `config/app.yaml`，不入 Git。 |
| **可維護性** | 模組分層、每支 script 可獨立重跑。                        |
| **資料儲存** | 本地 `data/` 目錄；可同步至 MinIO 或 Git 歸檔。           |

---

## 5. 系統流程（System Flow）

### 5.1 Pipeline

| 順序 | 任務                   | 輸入                          | 輸出                                 |
| -- | -------------------- | --------------------------- | ---------------------------------- |
| 1  | `fetch_metrics.py`   | 外部 API                      | `data/metrics/YYYY-MM-DD.json`     |
| 2  | `ingest_miniflux.py` | Miniflux API                | `data/raw/YYYY-MM-DD.jsonl`        |
| 3  | `preprocess.py`      | raw JSONL                   | `data/normalized/YYYY-MM-DD.jsonl` |
| 4  | `cluster_today.py`   | normalized                  | `data/topics/YYYY-MM-DD.json`      |
| 5  | `deepresearch.py`    | topics                      | `data/research/YYYY-MM-DD.jsonl`   |
| 6  | `build_report.py`    | metrics + research + prompt | `data/reports/YYYY-MM-DD.md`       |

---

## 6. API 與模型配置（API & Model Integration）

### 6.1 LiteLLM Chat API

```bash
POST http://localhost:9400/v1/chat/completions
Authorization: Bearer sk-admin
Content-Type: application/json
```

**用途：**

* topic 命名 (`cluster_today.py`)
* 深研 (`deepresearch.py`)
* 最終報告生成 (`build_report.py`)

**模型：**
`"model": "rag-answer"`

---

### 6.2 LiteLLM Embedding API

```bash
POST http://localhost:9400/v1/embeddings
Authorization: Bearer sk-admin
Content-Type: application/json
{
  "model": "local-embed",
  "input": ["text1", "text2", ...]
}
```

**模型：**
`"model": "local-embed"`（實際對應 `ollama/bge-m3`）

**輸出：**

```json
{"data":[{"embedding":[-0.0316,...]}]}
```

---

### 6.3 Miniflux API

```bash
GET https://rss.meowcoder.com/v1/categories/{category_id}/entries
?limit=300
&published_after={timestamp}
&direction=asc
```

Header:

```
X-Auth-Token: ${MINIFLUX_TOKEN}
```

---

### 6.4 外部行情 API（示例）

| 指標         | API 範例                                           | 備註                |
| ---------- | ------------------------------------------------ | ----------------- |
| BTC/ETH 價格 | CoinGecko `/api/v3/simple/price`                 | 免費、穩定             |
| 爆倉金額       | Coinglass `/api/v1/liquidation`                  | 需註冊 key           |
| ETF 流向     | SoSoValue / Farside                              | 有延遲、可選            |
| 總市值        | CoinMarketCap `/v1/global-metrics/quotes/latest` | 可統一單位 Billion USD |

---

## 7. 報告模板（Report Template）

`config/report_prompt.md`
內容為你原提供的完整版 prompt，開頭加註一行：

> 若輸入資料中缺少報價、ETF 流向、爆倉金額等數值，請保留欄位並標註 N/A，不要刪除段落。

---

## 8. 輸出與儲存格式（Data Outputs）

```
data/
├── raw/2025-11-04.jsonl
├── normalized/2025-11-04.jsonl
├── topics/2025-11-04.json
├── research/2025-11-04.jsonl
├── metrics/2025-11-04.json
└── reports/2025-11-04.md
```

---

## 9. 系統設定檔（config/app.yaml）

```yaml
miniflux:
  base_url: "https://rss.meowcoder.com"
  token: "YOUR_MINIFLUX_TOKEN"
  categories: [22]
  limit: 300
  window_hours: 24

litellm:
  base_url: "http://localhost:9400"
  api_key: "sk-admin"
  model_chat: "rag-answer"
  model_embed: "local-embed"

output:
  base_dir: "data"
  report_dir: "data/reports"
  timezone: "Asia/Taipei"

runtime:
  max_topics_per_day: 40
  max_items_per_topic: 15
  similarity_threshold: 0.82
```

---

## 10. 系統時序（Timing & Scheduling）

| 時間 (Asia/Taipei) | 任務                   |
| ---------------- | -------------------- |
| 07:55            | `fetch_metrics.py`   |
| 07:57            | `ingest_miniflux.py` |
| 08:00            | `preprocess.py`      |
| 08:01            | `cluster_today.py`   |
| 08:02            | `deepresearch.py`    |
| 08:05            | `build_report.py`    |
| 08:10            | 報告存檔 / webhook 通知    |

---

## 11. 例外與錯誤處理（Error Handling）

| 模組           | 錯誤類型            | 處理方式                  |
| ------------ | --------------- | --------------------- |
| Miniflux     | 網路錯誤 / Token 錯誤 | 重試 3 次，失敗記 log        |
| Embedding    | Timeout         | 跳過該篇，標記 `_embed_fail` |
| Clustering   | 少於 2 篇          | 自動合併為 “單篇主題”          |
| DeepResearch | LLM Timeout     | 略過該 topic，log warning |
| BuildReport  | LLM 生成錯誤        | 自動 retry 1 次          |
| Metrics      | API 回 null      | 用 `"N/A"` 取代          |

---

## 12. 擴充規劃（Future Extensions）

| 項目     | 說明                                   |
| ------ | ------------------------------------ |
| 多來源擴充  | 接入 Twitter/X、Telegram、On-chain 事件    |
| RAG 儲存 | 將 topics/research 向量化後入 Qdrant 供回溯分析 |
| UI 儀表板 | FastAPI 前端 Dashboard 展示每日報告          |
| 多語輸出   | 產出英文報告（EN.md）供國際通訊使用                 |
| 自動週報   | 每週自動彙整七日報告生成週報                       |

---

## 13. 驗收準則（Acceptance Criteria）

| 項目   | 驗收條件                                                          |
| ---- | ------------------------------------------------------------- |
| 日報產出 | 每日 08:10 前自動生成 `.md` 報告                                       |
| 主題分群 | 同日不同新聞正確歸為同 topic                                             |
| 指標填入 | 報告「一、大盤概況」欄位填入實際數值或 N/A                                       |
| 格式一致 | 報告章節固定，Markdown 渲染正確                                          |
| 可重跑  | 任意日期可手動 `python scripts/build_report.py --date=YYYY-MM-DD` 生成 |

---

## 14. 安全與維運（Security & Maintenance）

* 所有 API Key 儲存在 `.env` 或 `config/`，禁止 commit。
* 每個模組執行完後紀錄 log 至 `data/logs/YYYY-MM-DD.log`。
* 可用 Prometheus 或 FastAPI Endpoint 提供健康狀態。

---

## ✅ 結語

> 本 SRS 描述之系統為一個自動化、多層級、具可擴充性的「加密市場情報報告系統」。
> 實作時可逐步完成以下優先級：
>
> 1. Metrics + Miniflux ingest
> 2. Preprocess + Cluster
> 3. DeepResearch
> 4. BuildReport
>    全部模組完成後，即可於本地自動每日生成一份完整的專業級市場報告。
