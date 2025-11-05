# Crypto Daily Intelligence

**Implementation Guide（工程啟動指南）**

版本：1.0
語言：繁體中文
適用對象：要把這套每天自動產報告的工程師 / DevOps

---

## 1. 目標與前置假設

### 1.1 目標

把我們在 SRS / SDD 裡定義好的每日流程，真正落成一套可以在你機器上「每天 08:00 左右」自動跑完並生成：

```text
data/reports/YYYY-MM-DD.md
```

裡面就是你那份「加密市場情報報告 — YYYY/MM/DD」的完整 Markdown。

### 1.2 前置假設

你環境已經有：

1. **LiteLLM Proxy**

   * base url：`http://localhost:9400`
   * chat model：`rag-answer`
   * embedding model：`local-embed`（實際是 `ollama/bge-m3`，你剛剛 curl 成功）
2. **Miniflux**

   * base url：`https://rss.meowcoder.com`
   * 有一個 category（例如 22）專門收集幣圈 RSS
   * 有 API token
3. 機器是 Linux / macOS，可用 `cron`
4. Python ≥ 3.10

---

## 2. 專案目錄與檔案命名規範

在你想放的目錄建專案：

```bash
mkdir -p ~/projects/crypto-daily-report
cd ~/projects/crypto-daily-report
```

建立基本結構：

```bash
mkdir -p config
mkdir -p data/{raw,normalized,topics,research,metrics,reports,logs}
mkdir -p scripts
mkdir -p docs
mkdir -p cron
```

結構長這樣：

```text
crypto-daily-report/
├── config/
│   ├── app.yaml              # 整體設定
│   └── report_prompt.md      # 你的超長報告模板
├── data/
│   ├── raw/                  # Miniflux 原始資料（日檔, jsonl）
│   ├── normalized/           # 清洗後資料（日檔, jsonl）
│   ├── topics/               # 分群後的主題（日檔, json）
│   ├── research/             # 每個 topic 的 LLM 深研結果（日檔, jsonl）
│   ├── metrics/              # 行情指標（日檔, json）
│   ├── reports/              # 最終報告（日檔, md）
│   └── logs/                 # pipeline log
├── scripts/                  # 全部 Python 腳本
├── cron/                     # crontab 範例
└── docs/                     # SRS / SDD / 本指南
```

**命名規則一律用日期：`YYYY-MM-DD.ext`**
這樣你要重跑某一天就很直覺。

---

## 3. 開發環境建立

### 3.1 建立虛擬環境

```bash
cd ~/projects/crypto-daily-report
python3 -m venv .venv
source .venv/bin/activate
```

### 3.2 安裝必要套件

建立 `requirements.txt`：

```text
requests
pyyaml
python-dateutil
tqdm
scikit-learn
numpy
```

安裝：

```bash
pip install -r requirements.txt
```

說明：

* `requests`：呼叫 Miniflux、LiteLLM
* `pyyaml`：讀 config
* `scikit-learn` + `numpy`：算 cosine similarity 做分群
* `tqdm`：之後你要顯示進度也方便

---

## 4. 設定檔與敏感資訊

### 4.1 `config/app.yaml`

這是整個系統的中心設定，放 url、token、每日上限：

```yaml
miniflux:
  base_url: "https://rss.meowcoder.com"
  token: "REPLACE_WITH_YOUR_MINIFLUX_TOKEN"
  categories: [22]           # 可以放多個
  limit: 300                 # 每日最多抓多少
  window_hours: 24           # 只抓最近 24h

litellm:
  base_url: "http://localhost:9400"
  api_key: "sk-admin"
  model_chat: "rag-answer"
  model_embed: "local-embed"
  timeout_seconds: 60
  timeouts:
    chat: 60
    embed: 30
  retries:
    chat:
      max_attempts: 3
      backoff_seconds: 5
    embed:
      max_attempts: 2
      backoff_seconds: 5

output:
  base_dir: "data"
  report_dir: "data/reports"
  report_template: "config/report_prompt.md"
  timezone: "Asia/Taipei"

runtime:
  max_topics_per_day: 40         # 避免一天分群太多，LLM 跑太久
  max_items_per_topic: 15        # 每個主題最多塞多少篇新聞給 LLM
  similarity_threshold: 0.82     # 分群的相似度閾值
```

`timeouts` / `retries` 用來控制 LiteLLM 代理的等待時間與重試策略，避免長時間卡住；`output.report_template` 指向 Markdown 模板，可以換成自己的路徑。

> 這支檔不要丟到公共 repo，如果要就加 `.gitignore`。
> 建議把真正的 `app.yaml` 放在本機未版控的路徑，或從 `config/app.example.yaml` 複製後填值。敏感 token 可以透過 `.env` 或部署時的環境變數注入，確保儲存庫裡只保留範例設定。

### 4.2 `config/report_prompt.md`

把你那份「加密市場情報報告 — YYYY/MM/DD」的模板原封不動貼進來，開頭加一句：

> 若輸入資料中缺少報價、ETF 流向、爆倉金額等數值，請保留欄位並標註 N/A，不要刪除段落。

這樣 LLM 才不會擅自刪欄位。

---

## 5. 六支核心腳本

這是整個 pipeline 的核心。先記住它們的角色：

1. `fetch_metrics.py`：抓行情 → `data/metrics/DATE.json`
2. `ingest_miniflux.py`：抓 RSS → `data/raw/DATE.jsonl`
3. `preprocess.py`：清洗 → `data/normalized/DATE.jsonl`
4. `cluster_today.py`：embedding + 分群 + 主題命名 → `data/topics/DATE.json`
5. `deepresearch.py`：逐主題丟 LLM 深研 → `data/research/DATE.jsonl`
6. `build_report.py`：把 metrics + research + 模板 → LLM → `data/reports/DATE.md`

你前面看過程式骨架了，這裡講「落地重點」。

---

### 5.1 fetch_metrics.py（可先做假資料）

* 先產一份合法 JSON 給後面用
* 之後要接真正行情 API（CoinGecko、Coinglass、ETF）再改

關鍵：即使你今天還沒接 API，也要產一份這樣的：

```json
{
  "as_of": "2025-11-04T08:00:00+08:00",
  "btc": {"price": null, "change_24h": null},
  "eth": {"price": null, "change_24h": null},
  "market": {"total_cap": null, "total_change_24h": null},
  "derivatives": {"liq_total_24h_usd": null, "long_ratio": null},
  "etf": {"btc_spot_flow_usd": null, "eth_spot_flow_usd": null}
}
```

報告生成階段會說「沒有就寫 N/A」，所以不會壞掉。

---

### 5.2 ingest_miniflux.py

* 用 `published_after` + 24h timestamp
* 一個 category 一個 request，全部寫到同一個 `.jsonl`

**注意**：Miniflux 回來可能是：

```json
{"total": 12, "entries": [ ... ]}
```

你要記得取 `.get("entries", data)`。

---

### 5.3 preprocess.py

責任：

1. 把 HTML 幹掉
2. 把重複標題幹掉
3. 填上統一欄位名稱（item_id, title, text, source, published_at, url）
4. 一條一行（jsonl）

這一層不用 LLM，跑得要快。

---

### 5.4 cluster_today.py

你已經有 `/v1/embeddings` 可以用了，所以：

1. 把當天所有 normalized 條目丟給 LiteLLM embedding
2. 算 cosine similarity
3. 用相似度閾值（0.82）做簡單分群
4. 取每群前幾個標題丟給 LLM → 幫你生「主題名稱」
5. 寫成一個陣列 JSON → `data/topics/DATE.json`

這一層是你解決「RSS 很多」的關鍵。

---

### 5.5 deepresearch.py

這一層就是「真正的 deep research」：

* 一個 topic 呼叫一次 LLM
* prompt 要求它輸出 JSON，包含：

  * topic_id
  * topic_title
  * summary（綜合剛剛那幾則 RSS）
  * market_impact
  * sentiment(0–10)
  * watch_symbols
* 一個結果一行，寫到 `data/research/DATE.jsonl`

這一層失敗最常見的是「LLM 回的不是 JSON」，你可以先不 parse，先原樣寫檔，build_report 時再粗暴塞進去，至少不會整條壞掉。

---

### 5.6 build_report.py

最終輸出的一層。

1. 讀 `metrics/DATE.json`
2. 讀 `research/DATE.jsonl`（可以只挑前 10 條最重要的，避免 prompt 太長）
3. 讀 `config/report_prompt.md`
4. 組成一個大 user message 丟給 LLM
5. 拿回 Markdown，寫到 `data/reports/DATE.md`

這裡是第一次把三種來源的資料全部聚起來：**結構化數字 + 當日研究 + 你的固定模板**。

---

## 6. Master Pipeline（run_daily.py）

前面我說 cron 一支一支排「比較脆」，所以建議用一支 master 把全部串起來，失敗就停。這樣你就能回答你剛剛問的「其中一個失敗怎麼辦」。

`scripts/run_daily.py` 可以長這樣：

```python
#!/usr/bin/env python3
import subprocess, sys, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
LOG_DIR = BASE / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
today = datetime.datetime.now().strftime("%Y-%m-%d")
logfile = LOG_DIR / f"{today}.run.log"

STEPS = [
    ("fetch_metrics", ["python", "scripts/fetch_metrics.py"]),
    ("ingest_miniflux", ["python", "scripts/ingest_miniflux.py"]),
    ("preprocess", ["python", "scripts/preprocess.py"]),
    ("cluster_today", ["python", "scripts/cluster_today.py"]),
    ("deepresearch", ["python", "scripts/deepresearch.py"]),
    ("build_report", ["python", "scripts/build_report.py"]),
]

LOCK_FILE = BASE / "data" / "pipeline.lock"

def run_step(name, cmd):
    with logfile.open("a", encoding="utf-8") as f:
        f.write(f"== RUN {name} ==\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        with logfile.open("a", encoding="utf-8") as f:
            f.write(f"[ERROR] {name} failed with code {result.returncode}\n")
        return False
    return True

def main():
    if LOCK_FILE.exists():
        # 避免上一輪還在跑又被叫一次
        sys.exit("pipeline is running, exit.")
    try:
        LOCK_FILE.write_text("running", encoding="utf-8")

        for name, cmd in STEPS:
            ok = run_step(name, cmd)
            if not ok:
                sys.exit(1)
    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()

if __name__ == "__main__":
    main()
```

cron 只要排這一支就好。

---

## 7. 排程（cron）

編輯 crontab：

```bash
crontab -e
```

加這一行（每天 07:55 跑一次）：

```cron
55 7 * * * /bin/bash -lc 'cd ~/projects/crypto-daily-report && source .venv/bin/activate && python scripts/run_daily.py >> data/logs/cron.log 2>&1'
```

說明：

* `cd ...`：確保在專案目錄
* `source .venv/...`：用你專案的 venv
* `>> ... 2>&1`：標準輸出跟錯誤都寫到同一個 log
* 跑的是 **master**，不是一堆小腳本

---

## 8. 錯誤處理與重跑策略

這一點很重要，我整理成幾條規則：

### 8.1 每一層都寫檔

所以你可以只重跑後面的層級。

比如今天 08:02 deepresearch 壞了，前面都好了，你下午只要：

```bash
python scripts/deepresearch.py
python scripts/build_report.py
```

就補回來，不用再抓一次 RSS。

### 8.2 每一層都要檢查前置檔案

在腳本開頭加這種：

```python
if not Path("data/topics/2025-11-04.json").exists():
    raise SystemExit("topics not found")
```

這樣你一看 log 就知道是上一層沒成功。

### 8.3 master 裡失敗就停

run_daily.py 裡我們已經這樣做了，任何一個 `subprocess.run(...)` 回傳非 0，就停。

### 8.4 避免重複執行

靠 `pipeline.lock` 避免 cron 重疊。

### 8.5 監控成功

最簡單的成功條件就是「今天這個檔案存在而且大於 10KB」：

```text
data/reports/2025-11-04.md
```

你可以寫一支超短的 `check_report.py`，讓 n8n 打，如果不存在就通知你。

---

## 9. 驗證流程（手動跑一遍）

初次部署一定要自己跑一次，順序是：

```bash
source .venv/bin/activate

python scripts/fetch_metrics.py
python scripts/ingest_miniflux.py
python scripts/preprocess.py
python scripts/cluster_today.py
python scripts/deepresearch.py
python scripts/build_report.py
```

最後：

```bash
cat data/reports/2025-11-04.md
```

有內容、有九大段，就成功。

---

## 10. 之後要接真正行情 API 的位置

你現在的 `fetch_metrics.py` 是空的 / 假資料，之後要變成真的，只要在那支檔案裡：

1. 打 CoinGecko 拿 BTC、ETH 價格 + 24h
2. 打 Coinglass 拿爆倉
3. 打你喜歡的 ETF 來源
4. 組成我們前面說的那個 JSON

因為我們的報告生成階段本來就會把這個 JSON 原樣塞進去，所以你不用改 `build_report.py`，只要讓 JSON 裡真的有數字就好。

---

## 11. 小提醒

* LiteLLM 如果有時候慢，你可以把 `timeout_seconds` 改長一點
* 分群的 `similarity_threshold` 是最常調的參數，群太碎調低，群太混調高
* 每天的 log 都寫 `data/logs/DATE.run.log`，排錯就看這個
