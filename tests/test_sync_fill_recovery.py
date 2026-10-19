"""Offline regression tests for src.jobs.sync_positions (Kalshi Demo only).

Run: python -m unittest discover -s tests -p test_sync_fill_recovery.py -v
Uses normal project aiosqlite; no external API requests, no trading actions.
"""
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.jobs import sync_positions as sync

TICKER = 'DEMO-TEST-MO'
ORDER_ID = 'TEST-BUY-ORDER-01'


def fill(qty='2.00', oid=ORDER_ID, action='buy', fid='F1'):
    return {'fill_id': fid, 'order_id': oid, 'ticker': TICKER, 'side': 'no',
            'action': action, 'count_fp': qty, 'no_price_dollars': '0.5000',
            'fee_cost': '0.0042', 'created_time': '2026-10-16T09:00:00Z'}


async def fake_fetch(client, endpoint, key, params=None):
    if key == 'market_positions':
        return client.positions
    if key == 'orders':
        return client.orders
    raise AssertionError(key)


async def fake_fills(client):
    if client.fills is None:
        raise OSError('Temporary API failure')
    return client.fills


async def fake_preflight(client):
    return {'automatic_exit_safe': False}


class SyncRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'trading_system_demo.db'
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('''CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT NOT NULL,
                side TEXT NOT NULL, entry_price REAL NOT NULL, quantity INTEGER NOT NULL,
                timestamp TEXT NOT NULL, rationale TEXT, confidence REAL,
                live INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open',
                strategy TEXT, stop_loss_price REAL, take_profit_price REAL,
                max_hold_hours INTEGER, target_confidence_change REAL,
                UNIQUE(market_id, side))''')
            con.execute('CREATE TABLE markets (market_id TEXT PRIMARY KEY, has_position INTEGER)')
            con.execute("INSERT INTO markets VALUES (?,1)", (TICKER,))
            con.execute('''INSERT INTO positions (market_id,side,entry_price,quantity,
                timestamp,rationale,confidence,live,status,strategy,stop_loss_price,
                take_profit_price,max_hold_hours,target_confidence_change)
                VALUES (?,?,0.4,2,'2026-10-16T08:00:00','AI original',0.85,
                        0,'pending','portfolio_optimization',0.35,0.50,24,0.2)''', (TICKER, 'NO'))
            con.commit()
        self.client = SimpleNamespace(base_url='https://demo-api.kalshi.co',
                positions=[{'ticker': TICKER, 'position_fp': '-2.00'}],
                orders=[], fills=[])
        self.env = patch.dict(os.environ, {'KALSHI_ENV': 'demo'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def journal(self):
        p = Path(self.temp.name)/'demo_submission_intents.sqlite3'
        with closing(sqlite3.connect(p)) as con:
            con.execute('''CREATE TABLE submission_intents (
                intent_key TEXT PRIMARY KEY, client_order_id TEXT NOT NULL UNIQUE,
                ticker TEXT NOT NULL, side TEXT NOT NULL, count TEXT NOT NULL,
                price_cents INTEGER NOT NULL, state TEXT NOT NULL,
                order_id TEXT, error TEXT, updated_at TEXT NOT NULL)''')
            con.execute('INSERT INTO submission_intents VALUES (?,?,?,?,?,?,?,?,?,?)',
                        ('original_strategy_position_1', 'testcid', TICKER,
                         'NO', '2', 50, 'ACKNOWLEDGED', ORDER_ID, None, 'now'))
            con.commit()

    def row(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.row_factory = sqlite3.Row
            return dict(con.execute('SELECT * FROM positions WHERE id=1').fetchone())

    def archive_count(self):
        with closing(sqlite3.connect(self.db)) as con:
            return con.execute('SELECT COUNT(*) FROM position_reconciliation_archive').fetchone()[0]

    def run_sync(self):
        with patch.multiple(sync, fetch_all=fake_fetch, fetch_all_fills=fake_fills,
                audit_order_reservations=lambda *x: {},
                save_order_reservation_report=lambda *x: None,
                audit_resting_orders=lambda *x: {}, save_audit=lambda *x: None,
                build_fills_report=lambda *x: {}, save_fills_audit=lambda *x: None,
                replay_fills=lambda *x: {}, save_replay_report=lambda *x: None,
                audit_cost_basis=lambda *x: {}, save_cost_basis_report=lambda *x: None,
                audit_fees_and_completeness=lambda *x: {},
                save_fee_completeness_report=lambda *x: None,
                run_demo_exit_preflight=fake_preflight,
                save_exit_preflight_report=lambda *x: None):
            return asyncio.run(sync.sync_demo_positions(
                SimpleNamespace(db_path=str(self.db)), self.client))

    def test_missing_fill_preserves_pending_and_strategy(self):
        self.journal()
        result = self.run_sync()
        row = self.row()
        self.assertEqual((row['live'], row['status'], row['strategy']),
                         (0, 'pending', 'portfolio_optimization'))
        self.assertAlmostEqual(row['stop_loss_price'], 0.35)
        self.assertEqual(result['waiting_for_fills'], 1)
        self.assertEqual(self.archive_count(), 0)

    def test_later_fill_promotes_and_anchors_tp_sl(self):
        self.journal()
        self.run_sync()
        self.client.fills = [fill()]
        result = self.run_sync()
        row = self.row()
        self.assertEqual((row['live'], row['status'], row['strategy']),
                         (1, 'open', 'portfolio_optimization'))
        self.assertAlmostEqual(row['entry_price'], 0.5)
        self.assertAlmostEqual(row['stop_loss_price'], 0.44)
        self.assertAlmostEqual(row['take_profit_price'], 0.63)
        self.assertEqual(result['managed_positions'], 1)
        # No drift after repeated syncs.
        self.run_sync()
        self.assertAlmostEqual(self.row()['take_profit_price'], 0.63)

    def test_recover_strategy_from_previous_archive(self):
        self.journal()
        original = self.row()
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('''CREATE TABLE position_reconciliation_archive (
                archive_id INTEGER PRIMARY KEY AUTOINCREMENT,position_id INTEGER NOT NULL,
                archived_at TEXT NOT NULL,reason TEXT NOT NULL,
                previous_row_json TEXT NOT NULL)''')
            con.execute('INSERT INTO position_reconciliation_archive (position_id,archived_at,reason,previous_row_json) VALUES (1,?,?,?)',
                        ('now', 'Legacy sync demoted pending BUY', json.dumps(original)))
            con.execute('''UPDATE positions SET live=1,status='open',
                         entry_price=0,strategy='exchange_unmanaged',
                         stop_loss_price=NULL,take_profit_price=NULL,
                         max_hold_hours=NULL,target_confidence_change=NULL''')
            con.commit()
        self.client.fills = [fill()]
        result = self.run_sync()
        row = self.row()
        self.assertEqual(row['strategy'], 'portfolio_optimization')
        self.assertAlmostEqual(row['entry_price'], 0.5)
        self.assertEqual(row['max_hold_hours'], 24)
        self.assertEqual(result['restored_from_archive'], 1)
        self.assertEqual(self.archive_count(), 1)

    def test_manual_sell_cannot_promote_to_managed(self):
        self.journal()
        self.client.fills = [fill(), fill('1.00', 'MANUAL', 'sell', 'F2')]
        result = self.run_sync()
        self.assertEqual(self.row()['status'], 'pending')
        self.assertEqual(result['managed_positions'], 0)

    def test_live_managed_quarantined_on_transient_fills_outage(self):
        self.journal()
        self.client.fills = [fill()]
        self.run_sync()
        self.client.fills = None
        result = self.run_sync()
        row = self.row()
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['strategy'], 'portfolio_optimization')
        self.assertEqual(result['waiting_for_fills'], 1)
        self.client.fills = [fill()]
        self.run_sync()
        self.assertEqual(self.row()['status'], 'open')

    def test_legacy_paper_collision_is_unmanaged_and_archived_once(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("UPDATE positions SET status='open'")
            con.commit()
        self.run_sync()
        self.assertEqual(self.row()['strategy'], 'exchange_unmanaged')
        self.assertEqual(self.archive_count(), 1)
        self.run_sync()
        self.assertEqual(self.archive_count(), 1)

    def test_rejects_production(self):
        self.client.base_url='https://api.kalshi.com'
        with self.assertRaises(RuntimeError):
            self.run_sync()

    def test_rejects_incomplete_orders_snapshot(self):
        async def bad_fetch(client, endpoint, key, params=None):
            if key=='orders':
                raise RuntimeError('API incomplete')
            return client.positions
        with patch.object(sync,'fetch_all',bad_fetch):
            with self.assertRaises(RuntimeError):
                asyncio.run(sync.sync_demo_positions(SimpleNamespace(db_path=str(self.db)),self.client))
        self.assertEqual(self.row()['status'], 'pending')

    def test_exchange_zero_closes_previously_managed_pending_recheck(self):
        self.journal()
        self.client.fills = [fill()]
        self.run_sync()
        self.client.fills = None
        self.run_sync()
        self.assertEqual(self.row()['status'], 'pending')
        self.client.positions = []
        result = self.run_sync()
        self.assertEqual(self.row()['status'], 'closed')
        self.assertEqual(result['closed'], 1)

    def test_empty_exchange_inventory_closes_live_without_fabricated_pnl(self):
        self.journal()
        self.client.fills=[fill()]
        self.run_sync()
        self.client.positions=[]
        result=self.run_sync()
        self.assertEqual(self.row()['status'],'closed')
        self.assertEqual(result['closed'],1)


if __name__ == '__main__':
    unittest.main()
