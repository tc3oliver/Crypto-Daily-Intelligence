# Crypto Daily Intelligence System

一個自動化的加密市場每日情報管線：從 Miniflux 讀取 RSS 新聞，清洗與分群主題，針對重點主題做輕量研究，並輸出最終 Markdown 市場報告到 `data/reports/YYYY-MM-DD.md`。

## 特色
- 端到端每日流程：指標 → 內容蒐集 → 清洗 → 分群 → 研究 → 報告
- 可重複、可追溯：所有中間產物以日期為鍵存放在 `data/*`
- 易於排程與除錯：每個步驟皆可獨立重跑；具備簡單的日誌與鎖檔機制
- 輕量依賴：Python 3.10+ 與少量常用套件，外部只需 Miniflux 與 LiteLLM Proxy

## 架構與每日流程
每日執行順序與對應腳本如下（預設日期為今天；也可用 `--date YYYY-MM-DD` 指定）：
1) 指標擷取：`scripts/fetch_metrics.py`
2) 取得 RSS：`scripts/ingest_miniflux.py`
3) 內容清洗：`scripts/preprocess.py`
4) 主題分群：`scripts/cluster_today.py`
5) 輕量研究：`scripts/deepresearch.py`
6) 生成報告：`scripts/build_report.py`
7) 模板驗證：`scripts/validate_template.py`

完整流程可由 `scripts/run_daily.py` 一鍵完成。

## 需求與前置作業
- Python 3.10+（建議使用虛擬環境）
- 外部服務：Miniflux（RSS）與 LiteLLM Proxy（詳見 `docs/implementation-guide.md`）

## 快速開始
在專案根目錄執行下列指令（zsh）：

```zsh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/app.example.yaml config/app.yaml  # 填入 Miniflux/LiteLLM 連線與 Token
```

一次跑完今日全流程：

```zsh
python scripts/run_daily.py
```

或分步執行（以 2025-11-04 為例）：

```zsh
# 1) 指標
python scripts/fetch_metrics.py --date 2025-11-04

# 2) 取得 RSS 並清洗
python scripts/ingest_miniflux.py --date 2025-11-04
python scripts/preprocess.py --date 2025-11-04

# 3) 分群與研究
python scripts/cluster_today.py --date 2025-11-04
python scripts/deepresearch.py --date 2025-11-04

# 4) 生成報告與模板驗證
python scripts/build_report.py --date 2025-11-04
python scripts/validate_template.py --date 2025-11-04
```

### 各腳本常見參數
- `--date YYYY-MM-DD`：處理指定日期（未提供則預設今天）
- 其他服務位址與金鑰設定請於 `config/app.yaml` 中調整

## 設定
- 編修 `config/app.yaml`（由 `config/app.example.yaml` 複製而來）
- 別將祕密提交到版本庫。以本機覆蓋或環境變數管理機敏資訊
- 端點與時區等細節可參考 `docs/implementation-guide.md`

## 資料目錄與輸出
- `data/raw/`：原始 RSS 條目（JSONL）
- `data/normalized/`：清洗後項目（JSONL）
- `data/topics/`：主題分群結果（JSON）
- `data/research/`：每個主題的研究結論（JSONL）
- `data/metrics/`：市場指標（JSON）
- `data/reports/`：最終 Markdown 報告（MD）
- `data/logs/`：執行日誌（`YYYY-MM-DD.run.log`）

## 排程（Cron）
參考 `cron/cron.example`，每日於本地時間約 08:00 執行。若發現 `data/pipeline.lock` 殘留，請先確認無程序在跑，再行移除。

## 疑難排解
- 確認 `config/app.yaml` 中外部端點可連線（Miniflux / LiteLLM）
- 重跑單一步驟以縮小問題範圍；對照 `data/*` 的中間產物
- 報告模板佔位符位於 `config/report_prompt.md`，由 `scripts/build_report.py` 套用
- 觀察 `data/logs/` 中對應日期的 `.run.log`

## 專案結構
```
AGENTS.md
README.md
requirements.txt
run_and_publish.sh
config/
	app.example.yaml
	app.yaml
	report_prompt.md
cron/
	cron.example
data/
	logs/
	metrics/
	normalized/
	raw/
	reports/
	research/
	topics/
docs/
	implementation-guide.md
	SDD.md
	SRS.md
	todo.md
scripts/
	build_report.py
	cluster_today.py
	deepresearch.py
	fetch_metrics.py
	ingest_miniflux.py
	preprocess.py
	run_daily.py
	utils.py
	validate_template.py
specs/
	001-deliver-crypto-report/
		data-model.md
		plan.md
		quickstart.md
		research.md
		spec.md
		checklists/requirements.md
		contracts/pipeline.yaml
```

## 開發與貢獻
- Python 3.10+，四空白縮排，模組層級型別註解（參考 `scripts/run_daily.py`）
- 模組/函式使用 snake_case；輸出檔名採 `YYYY-MM-DD.ext`
- 共同程式請放在 `scripts/utils.py`；提交前可執行 `black scripts`
- 尚未建立自動化測試；變更邏輯時建議加入 `pytest` 並至少做 smoke test
- 更多作業準則見 `AGENTS.md`

## 路線圖（建議）
- 新增 `pytest` 覆蓋關鍵流程，並導入 CI（例如 GitHub Actions）
- 加入健康檢查與重試策略（對 Miniflux / LiteLLM）
- 產出報告的可視化增強（圖表/指標趨勢）

—

如需細節與部署說明，請先閱讀 `docs/implementation-guide.md`；有任何問題或建議，歡迎開 Issue 討論。
