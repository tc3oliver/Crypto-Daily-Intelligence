# Quickstart — 加密貨幣每日情報自動化

## 1. 環境準備
1. 安裝 Python 3.10+（建議 Ubuntu 24.04）。  
2. 建立虛擬環境並安裝依賴：
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## 2. 設定檔配置
1. 複製範本並填寫金鑰：
   ```bash
   cp config/app.example.yaml config/app.yaml
   ```
2. 於 `config/app.yaml` 設定：
   - `miniflux.base_url`、`token`、`categories`
   - `litellm.base_url`、`api_key`
   - `output.timezone`（預設 Asia/Taipei）

## 3. 乾運行（Smoke Test）
1. 準備已知日期資料（例如 2025-11-04）或調整 `--date` 為今日。  
2. 執行指令：
   ```bash
   python scripts/run_daily.py --date 2025-11-04
   ```
3. 驗證輸出：
   - `data/raw/2025-11-04.jsonl`
   - `data/topics/2025-11-04.json`
   - `data/reports/2025-11-04.md`
   - `data/logs/2025-11-05.run.log`（檢視 `[OK]`、耗時秒數）

## 4. 單一階段重跑
若某階段失敗，可使用：
```bash
python scripts/deepresearch.py --date 2025-11-04
```
確保僅重新生成該階段工件。

## 5. 測試與驗證
1. 執行單元/功能測試：
   ```bash
   pytest
   ```
2. 如新增邏輯，請更新或新增與 `data/` 比對的煙霧測試腳本。  
3. 在 PR 中附上測試結果或 `data/` 差異截圖。

## 6. 佈署注意事項
- 確認 `data/pipeline.lock` 運行結束後會移除，避免 cron 阻塞。  
- 監控 `data/logs/YYYY-MM-DD.run.log` 初次運行是否在 15 分鐘內完成。  
- 定期清理或封存超過 30 天的資料，遵守憲章保留政策。  
