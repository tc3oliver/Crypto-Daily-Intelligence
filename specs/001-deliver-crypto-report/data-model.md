# Data Model — 加密貨幣每日情報自動化

## RawFeedEntry
- **來源**: Miniflux `/v1/categories/{id}/entries`
- **Primary Key**: `item_id` (`miniflux:{category}:{entry_id}`)
- **欄位**
  - `item_id`: string，唯一識別碼（需保持原始來源）
  - `title`: string，新聞標題
  - `text`: string，原始內文（含 HTML）
  - `source`: string，站台名稱（Miniflux 提供）
  - `published_at`: datetime (ISO 8601, UTC)
  - `url`: string，原始連結
  - `fetched_at`: datetime，系統抓取時間（新增）
- **驗證**
  - `url` 必須為 HTTPS
  - `published_at` 若缺失，使用 `fetched_at`

## NormalizedEntry
- **Primary Key**: `item_id`（沿用 RawFeedEntry）
- **欄位**
  - `item_id`: string
  - `title`: string（去除重複空白）
  - `clean_text`: string（移除 HTML、表情符號、追蹤碼）
  - `source`: string
  - `published_at`: datetime（轉換為 Asia/Taipei）
  - `summary`: string（可選，短摘要）
- **驗證**
  - `clean_text` 長度 > 40 字元，避免空洞內容
  - 同一天重複 `title + source` 視為重複，會跳過

## TopicCluster
- **Primary Key**: `topic_id`（`YYYY-MM-DD-NNN`）
- **欄位**
  - `topic_id`: string
  - `title`: string（LLM 命名）
  - `representative_text`: string（聚類代表段落）
  - `count`: integer（所含文章數）
  - `items`: list of objects
    - `title`: string
    - `source`: string
    - `url`: string
  - `embedding_cache_path`: string（保存向量暫存檔路徑）
- **驗證**
  - `count` ≥1；=1 時標記 `single_article: true`
  - `items` 中 URL 不可重複

## ResearchInsight
- **Primary Key**: `topic_id`
- **欄位**
  - `topic_id`: string
  - `summary`: string
  - `impact`: enum {看多, 中性, 看空}
  - `sentiment`: integer 0–10
  - `watch_symbols`: list[string]，如 ["BTC","ETH"]
  - `recommendation`: string
  - `source_count`: integer
  - `missing_data`: optional list[string]（紀錄缺失欄位，如 metrics N/A）
- **驗證**
  - `sentiment` 限制於 0–10
  - `watch_symbols` 最多 5 個
  - `source_count` 應等於 topic `count`

## MarketMetricsSnapshot
- **Primary Key**: `as_of`（datetime, Asia/Taipei, precision minute）
- **欄位**
  - `as_of`: datetime
  - `btc.price`: float
  - `btc.change_24h`: float (百分比)
  - `eth.price`: float
  - `eth.change_24h`: float
  - `market.total_cap`: float (兆 USD)
  - `market.total_change_24h`: float
  - `derivatives.liq_total_24h_usd`: float (百萬 USD)
  - `derivatives.long_ratio`: float (%)
  - `etf.btc_spot_flow_usd`: float (百萬 USD，可為負)
  - `etf.eth_spot_flow_usd`: float
- **驗證**
  - 缺值以 `null` 表示，後續在報告轉換為 `N/A`
  - 數值欄位保留三位小數

## DailyMarketReport
- **Primary Key**: `report_date` (YYYY-MM-DD)
- **欄位**
  - `report_date`: date
  - `path`: string（`data/reports/YYYY-MM-DD.md`）
  - `sections`: dict（九大章節標題 → 內容）
  - `source_metrics_path`: string
  - `source_research_path`: string
- **驗證**
  - 必須包含九大章節（市場總覽、熱門主題、潛在機會、重大消息與風險、市場情緒、關鍵影響者、AI 綜合洞察、觀察清單、結語）
  - 若部分章節缺資料，內容需標註 `N/A`

## 關聯摘要
- RawFeedEntry 1 → 1 NormalizedEntry  
- NormalizedEntry 多 → 1 TopicCluster  
- TopicCluster 1 → 1 ResearchInsight  
- MarketMetricsSnapshot + ResearchInsight → DailyMarketReport  
- DailyMarketReport 參照對應 `data/logs/YYYY-MM-DD.run.log`，用於追蹤生成狀態
