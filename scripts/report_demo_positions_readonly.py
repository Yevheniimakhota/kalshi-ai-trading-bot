"""Read-only local Demo position status report. Does not call API or submit orders."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _rows(db, table, columns, where='', args=()):
    query = f'SELECT {columns} FROM {table} {where}'
    return [dict(zip([col[0] for col in cur.description], rec))
            for cur in [db.execute(query, args)] for rec in cur.fetchall()]


def _table_exists(db, table):
    return db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',
                      (table,)).fetchone() is not None


def _readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def report(db_path):
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f'Demo DB not found: {db_path}')
    result = {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'type': 'LOCAL_READONLY_SQLITE', 'exchange_api_checked': False,
              'warning': 'OPEN in DB does not independently prove exchange inventory'}
    with closing(_readonly(db_path)) as db:
        if not _table_exists(db, 'positions'):
            raise RuntimeError('Expected positions table not found')
        result['positions'] = _rows(db, 'positions',
            'id,market_id,side,quantity,entry_price,live,status,strategy,'
            'stop_loss_price,take_profit_price,max_hold_hours', 'ORDER BY market_id,side')
        if _table_exists(db, 'position_reconciliation_archive'):
            result['archive'] = []
            for row in _rows(db, 'position_reconciliation_archive',
                             'position_id,archived_at,reason,previous_row_json',
                             'ORDER BY archive_id DESC LIMIT 100'):
                try:
                    p = json.loads(row.pop('previous_row_json'))
                    row['previous_state'] = {k: p.get(k) for k in (
                        'market_id','side','status','live','strategy','entry_price',
                        'stop_loss_price','take_profit_price')}
                except (TypeError, ValueError):
                    row['previous_state'] = 'invalid_archive_json'
                result['archive'].append(row)
        else:
            result['archive'] = []
    journal = db_path.with_name('demo_submission_intents.sqlite3')
    if journal.is_file():
        with closing(_readonly(journal)) as db:
            result['bot_order_intents'] = (_rows(db, 'submission_intents',
                'intent_key,ticker,side,count,price_cents,state,order_id',
                'ORDER BY updated_at DESC LIMIT 100') if _table_exists(db,'submission_intents') else [])
    else:
        result['bot_order_intents'] = []
    return result


def main():
    default = Path(os.environ.get('LOCALAPPDATA', '.'))/'KalshiBot'/'trading_system_demo.db'
    p = argparse.ArgumentParser(description='Read-only local Kalshi Demo status report')
    p.add_argument('--db', default=str(default))
    p.add_argument('--output', default='demo_sync_report.json')
    args = p.parse_args()
    result = report(args.db)
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(f'OK: {output.resolve()}')
    print(f'Local rows: {len(result["positions"])}; journal entries: {len(result["bot_order_intents"])}')
    for row in result['positions']:
        print(f'  {row["market_id"]} {row["side"]}: status={row["status"]}, '
              f'live={row["live"]}, strategy={row["strategy"]}, qty={row["quantity"]}')
    print('No API keys or private key material are read by this script.')


if __name__ == '__main__':
    main()
