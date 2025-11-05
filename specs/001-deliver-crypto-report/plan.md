# Implementation Plan: 加密貨幣每日情報自動化

**Branch**: `001-deliver-crypto-report` | **Date**: 2025-11-05 | **Spec**: [specs/001-deliver-crypto-report/spec.md](specs/001-deliver-crypto-report/spec.md)  
**Input**: Feature specification from `specs/001-deliver-crypto-report/spec.md`

**說明**: 本計畫文件對應 `/speckit.plan` 流程，涵蓋研究、設計與 Phase 2 前的執行步驟。

## 總結

此功能旨在將加密貨幣每日情報管道全面自動化，確保從 Miniflux RSS 取得的新聞、行情 API 指標與 LiteLLM 深研結果能於每日 08:10（Asia/Taipei）前產出結構化報告。方案維持既有 `scripts/` 模組化設計，強化錯誤復原（單一階段可重跑）、執行日誌結構化與性能監控。技術重點包括：Miniflux 與 LiteLLM 的穩定串接、聚類門檻調校、資料快取重用，以及以 pytest + 煙霧測試覆蓋各階段。

## 技術脈絡（Technical Context）

**Language/Version**: Python 3.10+（Ubuntu 24.04 既有環境）  
**Primary Dependencies**: requests、pyyaml、python-dateutil、tqdm、scikit-learn、numpy、LiteLLM Proxy、Miniflux API  
**Storage**: 本地檔案系統 (`data/` 分組目錄，保留 30 日)  
**Testing**: pytest（單元/功能測試）＋ 指令煙霧測試（比對 `data/` 工件）  
**Target Platform**: Linux (2 vCPU / 4 GB RAM)  
**Project Type**: 單一 CLI 數據管道專案  
**Performance Goals**: 全流程 ≤15 分鐘；每階段記錄開始/結束時間；單一日期 ≤300 RSS 條目、≤40 主題  
**Constraints**: LiteLLM 本地 Proxy（需控制併發與超時）；外部 API 速率限制；檔案系統存取僅限內部  
**Scale/Scope**: 每日一次批次處理；RSS 300 筆、主題 40 筆、研究輸出 ≈40 JSONL 條目

## 憲章檢核（Constitution Check）

- **Code Quality Fidelity**: 維持 `scripts/` 模組小型化、型別註記與 `python -m black scripts`；重構共用邏輯於 `scripts/utils.py`，並清除任何廢棄參數或未用常數。  
- **Testing Discipline**: 規劃 pytest 覆蓋聚類、指標解析與報告生成；若外部依賴難以模擬，於 PR 提供 `python scripts/run_daily.py --date <sample>` 煙霧結果與 `data/` 差異。  
- **Consistent User Experience**: 堅守 `data/<stage>/YYYY-MM-DD.*` 命名；如調整報告段落或 CLI 參數，對應更新 `config/report_prompt.md`、`README.md`。  
- **Performance Guardrails**: 透過重用快取檔案、LiteLLM 批次化、日誌寫入耗時資訊確保 15 分鐘 SLA；若監測到風險即提早建立追蹤議題。  

**Gate Result**: 無違規事項，進入 Phase 0。

## 專案結構（Project Structure）

### 文檔產出

```text
specs/001-deliver-crypto-report/
├── plan.md          # 本文件
├── research.md      # Phase 0 研究輸出
├── data-model.md    # Phase 1 資料模型
├── quickstart.md    # Phase 1 操作指南
├── contracts/       # Phase 1 API/CLI 契約
└── tasks.md         # Phase 2 由 /speckit.tasks 產生
```

### 原始碼與資源

```text
scripts/
├── run_daily.py
├── fetch_metrics.py
├── ingest_miniflux.py
├── preprocess.py
├── cluster_today.py
├── deepresearch.py
├── build_report.py
├── utils.py
└── validate_template.py

config/
├── app.example.yaml
└── report_prompt.md

data/
├── raw/
├── normalized/
├── topics/
├── research/
├── metrics/
├── reports/
└── logs/
```

**Structure Decision**: 維持單一 CLI 專案；所有流程以 `scripts/` Python 模組為核心，配合 `data/` 分類資料夾與 `config/` 設定檔。

## 複雜度追蹤（Complexity Tracking）

目前無需額外例外授權；如後續需新增第三方服務或改寫架構再補充。

## Phase 0（研究與決策）

1. 研讀 Miniflux API 速率限制與錯誤處理模式，確認 300 筆提要的安全擷取策略。  
2. 評估 LiteLLM Proxy（chat + embeddings）最佳實務：超時、重試、併發上限。  
3. 驗證 `scikit-learn` 聚類流程（相似度閾值 0.82）與向量快取策略，確保可重跑。  
4. 制定日誌與性能監測欄位（啟動/完成時間、API 呼叫耗時）。  
5. 統整結果於 `research.md`，並更新本計畫任何需調整之處。

## Phase 1（設計與契約）

1. 根據規格與研究輸出 `data-model.md`：列出 RawFeedEntry、NormalizedEntry、TopicCluster、ResearchInsight 等欄位／驗證規則／關聯。  
2. 產出 `contracts/pipeline.yaml` OpenAPI：涵蓋 daily run 觸發、單一階段重跑、報告查詢。  
3. 編寫 `quickstart.md`：環境建置（venv）、設定檔、乾運行與驗證步驟。  
4. 檢閱 Phase 1 結果，重新套用「憲章檢核」確保各原則仍通過。  
5. 執行 `.specify/scripts/bash/update-agent-context.sh codex`，將技術堆疊與準則同步至代理配置。

## Phase 2（高層任務規劃前置）

- 彙整 Phase 0/1 輸出，為 `/speckit.tasks` 定義獨立可交付的實作任務（依使用者故事切分）。  
- 確認測試策略（pytest、煙霧測試）與文檔更新清單，作為後續執行依據。
