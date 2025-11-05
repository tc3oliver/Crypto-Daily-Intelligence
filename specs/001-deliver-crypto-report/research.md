# Research — 加密貨幣每日情報自動化

## Miniflux RSS 擷取與重試策略
- **Decision**: 每次批次抓取限制 300 筆、使用時間窗參數與指數退避重試（三次）。  
- **Rationale**: 與 SDD/SRS 規範一致，可避免遺漏 24 小時內的新聞，同時在臨時 50x/429 情況快速恢復。  
- **Alternatives considered**:  
  - **持續輪詢**：需要常駐程序並增加 API 壓力，不符每日批次模式。  
  - **拉取全部歷史資料後裁剪**：傳輸成本高且不利增量更新。  

## LiteLLM Proxy 併發與超時設定
- **Decision**: embeddings 與 chat 流程皆設定 60 秒超時，序列化呼叫並在日誌記錄耗時；若需平行化先檢查 LiteLLM queue 狀態。  
- **Rationale**: 本地 Proxy 對 GPU/CPU 資源敏感，序列化可確保 2 vCPU / 4 GB RAM 主機穩定，並透過耗時統計追蹤瓶頸。  
- **Alternatives considered**:  
  - **多執行緒平行呼叫**：可能造成模型載入競爭與 OOM。  
  - **外部商用 API**：會引入額外金流與延遲，與專案需求不符。  

## 相似度聚類與快取策略
- **Decision**: 以 cosine similarity >0.82 做閾值群組，並將嵌入向量緩存至 `data/topics/YYYY-MM-DD.json` 旁的暫存檔，便於重跑。  
- **Rationale**: 0.82 來自既有 SDD 調優；快取避免重複向 LiteLLM embeddings 發請求，加速重新執行。  
- **Alternatives considered**:  
  - **KMeans 固定叢數**：無法適應每日主題數量變化。  
  - **無快取**：重跑成本高且易觸發速率限制。  

## 日誌與性能監測欄位
- **Decision**: 在 `data/logs/YYYY-MM-DD.run.log` 中新增起訖時間戳、耗時（秒）與關鍵 API 狀態碼；同時保留 `[OK]` / `[ERROR]` 標記。  
- **Rationale**: 提供量化證據以驗證 15 分鐘 SLA 與 API 健康狀況，支援事後分析。  
- **Alternatives considered**:  
  - **僅保留成功/失敗訊息**：無法追蹤性能回退。  
  - **將指標寫入外部監控系統**：超出目前範圍且增加部署複雜度。  

## 測試與驗證策略
- **Decision**: 建立 pytest 覆蓋資料清洗、聚類與報告模板渲染；另備份一組黃金樣本（2025-11-04）供煙霧測試比對。  
- **Rationale**: 自動化測試確保邏輯穩定，煙霧測試符合憲章要求的驗證證據。  
- **Alternatives considered**:  
  - **僅手動驗證報告**：無法防止回歸。  
  - **整體端對端 e2e 測試**：需大量外部依賴模擬，維護成本高。  
