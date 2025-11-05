# 專案待辦清單

## 高優先
- [-] `scripts/fetch_metrics.py`：改為串接實際行情／ETF／清算 API，並標準化單位（價位、百分比、百萬／十億）後寫入 `data/metrics/YYYY-MM-DD.json`。`（部分完成：整合 CoinGecko 價格/總市值；Coinglass 清算/多空比（API key 選用）；ETF 流量 TODO）`
- [-] `scripts/cluster_today.py`：接入 LiteLLM embedding 服務，依 `runtime.similarity_threshold` 做 cosine 分群並以 LLM 產生主題名稱，輸出需符合 `topics` 資料模型（含 `count`、`representative_text`、`max_topics_per_day` 與 `max_items_per_topic` 限制）；補上錯誤重試與無資料的 fallback。`（部分完成：已接 embeddings + chat 命名、並行命名、適應門檻與 singleton 合併、單條群跳過 LLM；待補批次/節流與代表文本優化）`
- [-] `scripts/deepresearch.py`：改用 LiteLLM chat 模型生成 JSON 結果，處理非結構化回應、重試與速率限制，並填寫 `market_impact`、`sentiment`、`watch_symbols`、`recommendation`、`source_count` 等欄位。`（部分完成：已加入日誌與並行、產生結構化 JSON 與寬鬆解析；待補 Schema 驗證與更穩定 prompt）`
- [x] `scripts/build_report.py`：改為以 LLM 依 `config/report_prompt.md` 直接輸出完整 Markdown 報告（不再做佔位符填充），加入輸入大小控制、超時/重試與精簡重試 fallback，支援 `--date`。
- [x] 模板對齊檢查：保留 `scripts/validate_template.py` 作為傳統模板檢查；LLM 模式改以「章節完整性」驗證腳本（見本週計畫）。

## 中優先
- [-] `scripts/ingest_miniflux.py`：加入分頁／游標支持、重複項去除、超時重試與 status 控制（抓完標記為 read 或維持 unread）。`（部分完成：已改用 /v1/categories/{id}/entries、published_after 以 Unix 秒、支援 order/direction/status、增加重試與本地 24 小時過濾、去重完成；分頁/游標（offset/before/after_entry_id）待實作）`
- [-] `scripts/preprocess.py`：統一時間格式（ISO + 時區）、優化重複檢查（以 item_id + url）、針對缺字內容建立防呆。`（部分完成：已用 dateutil 正規化為設定時區 ISO、以 (id,title,url) 去重；缺字/異常內容防呆待補）`
- [-] `config/app.yaml`：補上 LiteLLM 相關 timeout／重試設定、embedding/chat 重試次數、以及自訂 `report_template` 路徑；同步文件化敏感資訊管理方式。`（部分完成：已補 timeouts/retries 並調高 chat 超時/重試、增加 report_* 上限配置與可選 max_tokens；敏感資訊管理說明待補）`
- [-] `scripts/run_daily.py`：新增失敗通知（email/Slack）、可重跑的步驟控制、最終報告大小驗證與日期參數傳遞`（部分完成：已傳遞 --date 至各步驟，新增 lock file；通知/步驟控制/報告大小驗證待補）`。
- [-] `scripts` 各模組：提供 `--date` 選項與統一的 log 寫入（追加至 `data/logs/YYYY-MM-DD.log`），符合 SRS 可追溯性需求`（部分完成：已新增 --date；統一 log 未完成）`。
- [-] `config/report_prompt.md`：確保章節標題與輸出格式清晰，增加「缺值以 N/A 填寫、不得保留 {{...}}」等明確要求（配合 validate_report 腳本）。
- [-] `cron/`：提供 crontab 樣板與安裝說明（含時區），例如 `0 8 * * * /usr/bin/python scripts/run_daily.py`；並在文件中標註相依服務檢查步驟。`（部分完成：已提供 cron/cron.example；安裝說明與相依檢查待補）`
- [x] `.gitignore`：忽略 `data/**`、`.venv/`、`.vscode/`、`__pycache__/`、`*.log` 等，避免把大型或機密資料提交版本庫。
- [x] `README.md`：新增快速啟動、相依服務、主要指令與資料流示意圖。
- [-] `config/app.example.yaml`、`.env.example`：提供不含機密的範例設定，搭配文件說明如何覆蓋正式值。`（部分完成：已有 app.example.yaml；.env.example 待補）`
- [x] `specs/001-deliver-crypto-report`：規格與檢查清單翻譯為繁體中文（保留英文技術詞彙）。
- [ ] Stale lock 防護：`scripts/run_daily.py` 檢查 `data/pipeline.lock` 是否為陳舊（超過 N 分鐘）；支援 `--force` 解除。
- [ ] 資料模型驗證：以 JSON Schema 或 Pydantic 定義 `metrics`／`normalized`／`topics`／`research` 結構，於各步驟寫出前後進行驗證。
- [ ] 開發便捷化：新增 `Makefile` 或 `scripts/dev.sh`（`setup`/`lint`/`test`/`run`）。

## 後續優化
- [ ] 撰寫單元／整合測試，涵蓋 Miniflux 偽資料、分群邏輯與報告生成。
- [ ] 建立 `.env` 或 secrets 管理流程，避免 token 直接存在 YAML。
- [ ] 增加資料層快取與再跑策略（例如僅重跑失敗步驟）。
- [ ] 實作 `scripts/check_report.py` 或類似監測腳本，檢查報告存在與大小並可整合外部通知服務。
- [ ] 在 `docs/implementation-guide.md` 補上實際部署與除錯案例章節。
- [ ] CI（GitHub Actions）：在 PR 觸發 `lint`、`type-check`、`tests`，並上傳報告產物大小統計。
- [ ] pre-commit：整合 `black`、`ruff`、`isort`、`mypy`，統一風格與型別檢查。
- [ ] Docker 化：提供 `Dockerfile` 與（可選）`docker-compose.yml`，一鍵啟動 + 排程。
- [ ] 保留與清理策略：新增清理腳本（壓縮或刪除 30/60 天前的 `data/*` 與 `logs`）。
- [ ] 觀測性：記錄每步驟耗時、輸入/輸出筆數與錯誤統計，彙整到 `data/metrics/pipeline-YYYY-MM-DD.json`。
- [ ] 測試夾具：提供最小 `data/raw`/`normalized` 範例，利於本地與 CI 驗證。
- [ ] 文件同步：對齊 `docs/SRS.md`、`docs/SDD.md` 與實作的資料模型與流程圖，維持同歩更新。
- [ ] LLM 結果快取：對主題命名、研究摘要與報告生成引入內容雜湊快取，減少重複支出與等待。
- [ ] 內容強化：在分群結果中加入 `snippet`（自 normalized.text 截取 200–400 字），並於 deepresearch 提示中使用；（可選）引入全文抽取器與快取。
- [ ] 匯出品質檢查：新增 `scripts/validate_report.py`，檢查 LLM 產生的報告包含所有章節、缺值以 N/A、無殘留 `{{...}}`。

---

## 近期執行計畫（本週）
- 高優先
	1) Miniflux 分頁/游標：支援 `offset` 與 `before/after_entry_id`，逐頁取回＋本地去重，確保大量來源仍能完整覆蓋 24 小時視窗。
	2) 報告（LLM）穩定化：新增 `scripts/validate_report.py`，檢查章節齊全、N/A 代填、無 `{{...}}`；必要時支援分批生成（多輪合併）與長文模型開關。
	3) ETF 流量整合：在 `fetch_metrics.py` 增加 ETF 流量供應商（SoSoValue/替代來源），回寫至 metrics，統一單位與欄位。

- 中優先
	4) `deepresearch` 輸出驗證：以 JSON Schema/Pydantic 校驗；無效時回退簡化結果並記錄。
	5) 日誌與觀測性：統一寫入 `data/logs/YYYY-MM-DD.run.log`，並新增每日 pipeline 指標（步驟耗時、筆數、錯誤）至 `data/metrics/pipeline-YYYY-MM-DD.json`。
	6) `preprocess` 防呆：針對缺字/HTML/異常欄位做保護（長度、空值、fallback），減少壞資料外溢。
	7) 主題內容強化：在分群結果中加入 `snippet` 並導入 deepresearch 提示，提升判斷品質與上下文密度。

## 驗收標準（節錄）
- Miniflux 分頁：同一日期重跑，raw 總筆數穩定且時間窗完整；API 失敗自動重試，日誌包含頁次與總計數。
- 報告映射：`validate_template.py` 零缺失；輸出報告關鍵欄位（日期、價格、主題、摘要、建議）皆被替換。
- ETF 指標：metrics 中新增 `etf_flows`（或等價命名）且單位清楚；缺資料時有明確 fallback。
- 研究驗證：無效 JSON 會被攔截與修正；schema 版本與欄位在文件中記載。
