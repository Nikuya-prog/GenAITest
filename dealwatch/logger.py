import csv
import os
from datetime import datetime

# Always save inside dealwatch/logs, no matter where you run the script from
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "dealwatch_log.csv")

FIELDS = [
    "timestamp", "record_type", "record_name", "record_id",
    "rank", "score", "reasons",
    "task_status", "task_id", "email_status", "error",
]


def log_action(record, priority, task_status, task_id="", email_status="", error=""):
    """Add one row to the DealWatch log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(LOG_FILE)

    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "record_type": record["type"],
            "record_name": record["name"],
            "record_id": record["id"],
            "rank": priority.rank,
            "score": priority.score,
            "reasons": "; ".join(record.get("reasons", [])),
            "task_status": task_status,
            "task_id": task_id or "",
            "email_status": email_status,
            "error": error,
        })