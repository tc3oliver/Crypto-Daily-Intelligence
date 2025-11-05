# Repository Guidelines

## Project Structure & Module Organization
The Python entry points live in `scripts/`; `run_daily.py` orchestrates the full pipeline while helpers sit in `utils.py`. Configuration stays in `config/` (`app.yaml` and `report_prompt.md`). Generated artifacts land in `data/` where each subfolder (`raw/`, `normalized/`, `topics/`, `research/`, `metrics/`, `reports/`, `logs/`) stores date-keyed snapshots such as `2024-03-01.jsonl`. Reference material and design notes are in `docs/`, and ready-to-use cron snippets reside in `cron/`.

## Build, Test, and Development Commands
```
python3 -m venv .venv        # create local virtualenv
source .venv/bin/activate    # activate for every session
pip install -r requirements.txt
python scripts/run_daily.py  # execute the end-to-end daily pipeline
python scripts/fetch_metrics.py  # run a single stage when debugging
```
Run commands from the repo root so relative paths resolve correctly.

## Coding Style & Naming Conventions
Target Python 3.10+, four-space indentation, and module-level type hints as seen in `scripts/run_daily.py`. Keep module and function names in `snake_case`, and log/output files in `YYYY-MM-DD.ext` format to match downstream expectations. Prefer small focused scripts and place shared helpers in `scripts/utils.py`. Use `python -m black scripts` before opening a PR to keep formatting consistent.

## Testing Guidelines
Automated tests are not yet in place; add `pytest`-based coverage when touching logic-heavy modules. For now, smoke-test changes by running individual stage scripts against a known date and diffing the outputs under `data/` (e.g., compare `data/reports/YYYY-MM-DD.md`). Record any manual verification steps in your PR description so others can reproduce them.

## Commit & Pull Request Guidelines
Write imperative commit subjects (`Add topic clustering guard`) and keep messages focused on one logical change. Squash housekeeping commits before review. PRs should describe the change, note affected scripts/data folders, link any tracking issues, and include evidence of manual or automated checks (command output snippets or sample report paths).

## Configuration & Operational Notes
API endpoints, tokens, and timezone preferences live in `config/app.yaml`; never commit secrets—use environment-specific overrides instead. Ensure LiteLLM and Miniflux endpoints described in `docs/implementation-guide.md` are reachable before scheduling the cron job. When running unattended, monitor `data/logs/YYYY-MM-DD.run.log` for failures and clear `data/pipeline.lock` only after verifying no process is active.

## Active Technologies
- Python 3.10+（Ubuntu 24.04 既有環境） + requests、pyyaml、python-dateutil、tqdm、scikit-learn、numpy、LiteLLM Proxy、Miniflux API (001-deliver-crypto-report)
- 本地檔案系統 (`data/` 分組目錄，保留 30 日) (001-deliver-crypto-report)

## Recent Changes
- 001-deliver-crypto-report: Added Python 3.10+（Ubuntu 24.04 既有環境） + requests、pyyaml、python-dateutil、tqdm、scikit-learn、numpy、LiteLLM Proxy、Miniflux API
