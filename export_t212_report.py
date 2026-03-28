from __future__ import annotations

"""
Export Trading212 data snapshot to Reports/.

What it exports:
- account info JSON
- open positions CSV
- orders CSV (if API returns any)

Usage:
    python export_t212_report.py
"""

from datetime import datetime
from pathlib import Path
import csv
import json

from trading212_api import get_account_info, list_open_positions, list_orders


def _write_csv(path: Path, rows: list[dict], headers: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h) for h in headers})


def main() -> None:
    root = Path(__file__).resolve().parent
    reports_dir = root / "Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    account = get_account_info(force=True) or {}
    positions = list_open_positions(force=True) or []
    orders = list_orders() or []

    # 1) Account JSON
    account_path = reports_dir / f"T212_account_{ts}.json"
    account_path.write_text(json.dumps(account, indent=2, ensure_ascii=False), encoding="utf-8")

    # 2) Positions CSV
    pos_headers = [
        "ticker",
        "quantity",
        "averagePrice",
        "currentPrice",
        "ppl",
        "result",
        "initialFillDate",
        "frontend",
        "currencyCode",
    ]
    positions_path = reports_dir / f"T212_positions_{ts}.csv"
    _write_csv(positions_path, positions, pos_headers)

    # 3) Orders CSV (payload-dependent columns, best-effort)
    order_headers = [
        "id",
        "ticker",
        "type",
        "status",
        "quantity",
        "filledQuantity",
        "created",
        "filledDate",
        "limitPrice",
        "stopPrice",
        "timeValidity",
    ]
    orders_path = reports_dir / f"T212_orders_{ts}.csv"
    _write_csv(orders_path, orders, order_headers)

    print("[T212 REPORT] Export complete:")
    print(f"  account:   {account_path}")
    print(f"  positions: {positions_path} (rows={len(positions)})")
    print(f"  orders:    {orders_path} (rows={len(orders)})")
    if len(orders) == 0:
        print("[T212 REPORT] Note: /equity/orders returned 0 rows in this snapshot.")


if __name__ == "__main__":
    main()

