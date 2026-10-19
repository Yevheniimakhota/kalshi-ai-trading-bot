"""Read-only preview of Demo ownership verification from saved fills and DB.

Does not use the API, change local DB files, or send orders. Run from project root.
"""
import argparse
import csv
import json
import os
from pathlib import Path

from src.jobs.demo_owned_lots import verified_bot_lot, OwnershipUnverified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_db = (Path(os.environ.get('LOCALAPPDATA', '.')) / 'KalshiBot' /
                  'trading_system_demo.db')
    parser.add_argument('--db', default=str(default_db))
    parser.add_argument('--report', required=True, help='demo_sync_after.json')
    parser.add_argument('--fills', required=True, help='CSV exported from Trades')
    args = parser.parse_args()
    if not Path(args.db).is_file():
        parser.error('Trading DB not found: ' + args.db)
    report = json.loads(Path(args.report).read_text(encoding='utf-8-sig'))
    if report.get('exchange_api_checked') is not False:
        parser.error('Expected a local read-only DB report')
    with open(args.fills, newline='', encoding='utf-8-sig') as f:
        fills = list(csv.DictReader(f))
    managed = 0
    for position in report.get('positions', []):
        if not position.get('live') or position.get('status') != 'open':
            continue
        label = f"{position['market_id']} {position['side']}"
        try:
            verified = verified_bot_lot(
                args.db, position['id'], position['market_id'],
                position['side'], position['quantity'], fills)
        except OwnershipUnverified as exc:
            print(f'UNVERIFIED {label}: {exc}')
        else:
            managed += 1
            print(f"VERIFIED   {label}: qty={verified['quantity']} "
                  f"entry=${verified['entry_price']:.4f} "
                  f"fees=${verified['buy_fees']:.6f}")
    print(f'Verified lots in supplied snapshot: {managed}')
    print('Offline preview only. CSV/report may be stale; the bot must recheck current exchange state.')


if __name__ == '__main__':
    main()
