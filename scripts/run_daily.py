#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from utils import load_config

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "data" / "logs"
LOCK_FILE = BASE_DIR / "data" / "pipeline.lock"

def build_steps(date_arg: str | None) -> list[tuple[str, list[str]]]:
    def with_date(cmd: list[str]) -> list[str]:
        return cmd + (["--date", date_arg] if date_arg else [])

    return [
        ("fetch_metrics", with_date([sys.executable, str(BASE_DIR / "scripts" / "fetch_metrics.py")])),
        ("ingest_miniflux", with_date([sys.executable, str(BASE_DIR / "scripts" / "ingest_miniflux.py")])),
        ("preprocess", with_date([sys.executable, str(BASE_DIR / "scripts" / "preprocess.py")])),
        ("cluster_today", with_date([sys.executable, str(BASE_DIR / "scripts" / "cluster_today.py")])),
        ("deepresearch", with_date([sys.executable, str(BASE_DIR / "scripts" / "deepresearch.py")])),
        ("build_report", with_date([sys.executable, str(BASE_DIR / "scripts" / "build_report.py")])),
    ]

def write_log(message: str, *, date_str: str | None = None, tag: str = "run_daily") -> None:
    """Append a line to data/logs/YYYY-MM-DD.run.log and print to stdout."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    day = date_str or datetime.now().strftime("%Y-%m-%d")
    logfile = LOG_DIR / f"{day}.run.log"
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{ts} [{tag}] {message}"
    try:
        with logfile.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    finally:
        print(line)


def run_step(name: str, command: list[str], *, date_str: str | None = None) -> bool:
    write_log(f"== RUN {name} ==", date_str=date_str)
    write_log(f"cmd: {' '.join(command)}", date_str=date_str)
    t0 = time.time()
    # stream child output into our log
    try:
        with subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        ) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    write_log(f"[{name}] {line}", date_str=date_str)
            proc.wait()
            rc = proc.returncode or 0
    except FileNotFoundError:
        write_log(f"[ERROR] 無法執行指令：{command[0]}", date_str=date_str)
        return False
    except Exception as e:
        write_log(f"[ERROR] {name} 例外：{type(e).__name__}", date_str=date_str)
        return False

    dt = time.time() - t0
    if rc != 0:
        write_log(f"[ERROR] {name} 失敗（exit={rc}，耗時={dt:.2f}s）", date_str=date_str)
        return False
    write_log(f"[OK] {name} 完成（耗時={dt:.2f}s）", date_str=date_str)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily pipeline end-to-end")
    parser.add_argument("--date", help="Target date YYYY-MM-DD for all steps")
    args = parser.parse_args()

    cfg = load_config()  # 先確保設定檔存在

    # 以指定日期做為日誌檔名，便於追溯
    log_date = args.date

    if LOCK_FILE.exists():
        write_log("偵測到 pipeline.lock，可能有程序執行中，若確認無程序可手動刪除後再試。", date_str=log_date)
        sys.exit("pipeline is running, exit.")

    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text("running", encoding="utf-8")
        write_log("取得 lock，開始日常流程", date_str=log_date)
        write_log(f"執行日期參數：{args.date or '(today)'}", date_str=log_date)

        t_all = time.time()
        for name, command in build_steps(args.date):
            write_log(f"下一步：{name}", date_str=log_date)
            ok = run_step(name, command, date_str=log_date)
            if not ok:
                write_log("流程中止：上一個步驟失敗", date_str=log_date)
                sys.exit(1)
        write_log(f"全部步驟完成，總耗時={time.time()-t_all:.2f}s", date_str=log_date)
    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
            write_log("已釋放 lock", date_str=log_date)


if __name__ == "__main__":
    main()
