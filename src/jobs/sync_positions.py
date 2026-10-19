"""Exchange-authoritative Kalshi Demo position synchronization.

Does not send orders, infer profits, or attribute manual holdings to the bot.
Preserves unverified local BUY intents so later fills can safely promote them.
"""
import os
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

import aiosqlite

from src.jobs.reconcile_demo import fetch_all, parse_market_position
from src.jobs.order_audit import audit_resting_orders, save_audit
from src.jobs.fills_audit import fetch_all_fills, build_fills_report, save_fills_audit
from src.jobs.replay_audit import replay_fills, save_replay_report
from src.jobs.cost_basis_audit import audit_cost_basis, save_cost_basis_report
from src.jobs.fee_completeness_audit import audit_fees_and_completeness, save_fee_completeness_report
from src.jobs.order_reservation_audit import audit_order_reservations, save_order_reservation_report
from src.jobs.exit_preflight_audit import run_demo_exit_preflight, save_exit_preflight_report
from src.jobs.demo_owned_lots import verified_bot_lot, OwnershipUnverified
import json


def _restore_candidate(old, archived):
    """Return original strategy metadata, not an inferred exchange ownership.

    An archived row may contain a formerly pending strategy that was mistakenly
    changed to exchange_unmanaged by a previous sync. Attribution still requires
    an independently verified bot BUY order and matching fills.
    """
    if old.get("strategy") not in (None, "", "exchange_unmanaged"):
        return old, False
    snapshot = archived.get(old["id"])
    if (isinstance(snapshot, dict)
            and snapshot.get("id") == old["id"]
            and snapshot.get("market_id") == old["market_id"]
            and str(snapshot.get("side", "")).upper() == str(old["side"]).upper()
            and snapshot.get("strategy") not in (None, "", "exchange_unmanaged")
            and snapshot.get("status") in ("open", "pending")):
        return snapshot, True
    return None, False


def _anchor_level(level, proposed_entry, actual_entry):
    """Keep the original percentage-based exit levels, using filled price."""
    if level is None:
        return None
    proposed = Decimal(str(proposed_entry))
    actual = Decimal(str(actual_entry))
    target = Decimal(str(level))
    if not (proposed.is_finite() and actual.is_finite() and target.is_finite()
            and proposed > 0 and actual > 0):
        raise ValueError("Unsafe original TP/SL metadata")
    value = (actual * target / proposed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(max(Decimal("0.01"), min(Decimal("0.99"), value)))


async def sync_demo_positions(db_manager, client):
    """Atomically update the local inventory after a complete Demo API snapshot.

    Returns counts. Raises on API, format, or database errors; never partially
    writes when an exchange snapshot is incomplete or ambiguous.
    """
    if os.getenv('KALSHI_ENV', '').lower() != 'demo':
        raise RuntimeError('Automatic position synchronization requires Demo environment')
    if 'demo-api.kalshi.co' not in str(client.base_url).lower():
        raise RuntimeError('Refusing synchronization outside Kalshi Demo API')

    raw_positions = await fetch_all(client, '/trade-api/v2/portfolio/positions', 'market_positions')
    # Require a complete resting-order snapshot as well: don't claim we know the
    # account state if one of the essential API reads failed.
    resting = await fetch_all(client, '/trade-api/v2/portfolio/orders', 'orders', {'status': 'resting'})
    inventory = {}
    for row in raw_positions:
        ticker, side, count = parse_market_position(row)
        if not count:
            continue
        key = (ticker, side)
        if key in inventory:
            raise ValueError(f'Duplicate exchange position: {ticker} {side}')
        inventory[key] = count

    # Fills are evidence of ownership; if missing, import holdings as unmanaged.
    # Do not crash the whole bot on a stale local Paper/demo collision.
    try:
        exchange_fills = await fetch_all_fills(client)
    except Exception:
        exchange_fills = None

    def storage_quantity(q):
        if not isinstance(q, Decimal) or not q.is_finite() or q < 0:
            raise ValueError(f'Invalid exchange quantity: {q!r}')
        return int(q) if q == q.to_integral_value() else float(q)

    now = datetime.now(timezone.utc).isoformat()
    added = updated = closed = unmanaged = 0
    managed = waiting_for_fills = restored_from_archive = 0
    ownership_notes = []
    async with aiosqlite.connect(db_manager.db_path) as db:
        await db.execute('BEGIN IMMEDIATE')
        try:
            await db.execute('''CREATE TABLE IF NOT EXISTS position_reconciliation_archive (
                archive_id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER NOT NULL,
                archived_at TEXT NOT NULL, reason TEXT NOT NULL, previous_row_json TEXT NOT NULL
            )''')
            db.row_factory = aiosqlite.Row
            current_rows = await (await db.execute('SELECT * FROM positions')).fetchall()
            by_key = {(r['market_id'], str(r['side']).upper()): dict(r) for r in current_rows}
            if len(by_key) != len(current_rows):
                raise RuntimeError('Duplicate local position identity; no writes applied')

            # Most recent suitable archived strategy for each row ID. Archives
            # are preserved; this SELECT never changes historic records.
            archived = {}
            cursor = await db.execute('''SELECT position_id, previous_row_json
                FROM position_reconciliation_archive ORDER BY archive_id DESC''')
            for record in await cursor.fetchall():
                if record['position_id'] in archived:
                    continue
                try:
                    candidate = json.loads(record['previous_row_json'])
                except (TypeError, ValueError):
                    continue
                if isinstance(candidate, dict) and candidate.get('strategy') not in (
                        None, '', 'exchange_unmanaged'):
                    archived[record['position_id']] = candidate

            for (ticker, side), qty in inventory.items():
                old = by_key.get((ticker, side))
                if old is None:
                    # Exchange inventory without a durable bot intent is NOT
                    # evidence that the strategy owns this lot.
                    await db.execute('''INSERT INTO positions
                        (market_id, side, entry_price, quantity, timestamp, rationale, live, status, strategy)
                        VALUES (?, ?, 0, ?, ?, 'Exchange inventory (unknown entry basis)',
                                1, 'open', 'exchange_unmanaged')''',
                        (ticker, side, storage_quantity(qty), now))
                    added += 1
                    unmanaged += 1
                    ownership_notes.append({'ticker': ticker, 'side': side,
                                            'state': 'unmanaged', 'reason': 'No local bot intent'})
                    await db.execute('UPDATE markets SET has_position=1 WHERE market_id=?', (ticker,))
                    continue

                original, from_archive = _restore_candidate(old, archived)
                owned = None
                reason = ''
                if original is not None:
                    try:
                        owned = verified_bot_lot(db_manager.db_path, old['id'],
                                                 ticker, side, qty, exchange_fills)
                    except (OwnershipUnverified, sqlite3.Error, OSError) as exc:
                        reason = str(exc)[:180]
                else:
                    reason = 'Original strategy metadata unavailable'

                if owned is not None and original is not None:
                    # Account inventory exactly matches this bot's BUY fills.
                    # Restore a previous original strategy only if archival
                    # identity agrees with the durable journal + exchange fills.
                    actual_entry = owned['entry_price']
                    try:
                        proposed_entry = original['entry_price']
                        stop = _anchor_level(original.get('stop_loss_price'), proposed_entry,
                                             actual_entry)
                        target = _anchor_level(original.get('take_profit_price'), proposed_entry,
                                               actual_entry)
                        if not (Decimal(0) < Decimal(str(actual_entry)) < Decimal(1)):
                            raise ValueError('Invalid confirmed entry price')
                    except (ValueError, TypeError, KeyError) as exc:
                        owned = None
                        reason = f'Exit metadata not verifiable: {exc}'[:180]

                if owned is not None and original is not None:
                    await db.execute('''UPDATE positions SET live=1, status='open',
                        quantity=?, entry_price=?, strategy=?, stop_loss_price=?,
                        take_profit_price=?, max_hold_hours=?, target_confidence_change=?,
                        rationale=?, confidence=?, timestamp=? WHERE id=?''',
                        (storage_quantity(qty), float(owned['entry_price']),
                         original['strategy'], stop, target, original.get('max_hold_hours'),
                         original.get('target_confidence_change'), original.get('rationale'),
                         original.get('confidence'), original['timestamp'], old['id']))
                    updated += 1
                    managed += 1
                    if from_archive:
                        restored_from_archive += 1
                    ownership_notes.append({'ticker': ticker, 'side': side,
                                            'state': 'managed',
                                            'reason': 'Verified matching bot BUY fills' +
                                            ('; recovered archived strategy' if from_archive else '')})
                elif original is not None and (
                        old['status'] == 'pending' or
                        (bool(old['live']) and old['status'] == 'open'
                         and old['strategy'] != 'exchange_unmanaged')):
                    # DO NOT permanently erase the pending bot intent on a
                    # missing/delayed fill snapshot. A non-open status prevents
                    # both TP/SL paths from selling before we re-verify fills.
                    await db.execute("UPDATE positions SET status='pending' WHERE id=?",
                                     (old['id'],))
                    waiting_for_fills += 1
                    ownership_notes.append({'ticker': ticker, 'side': side,
                                            'state': 'waiting_for_fills', 'reason': reason})
                else:
                    # Legacy/non-attributable inventory: archive any previous
                    # strategy before removing automatic sell permissions.
                    changed = (not old['live'] or old['strategy'] != 'exchange_unmanaged'
                               or old['entry_price'] != 0 or old['status'] != 'open')
                    if changed:
                        await db.execute('''INSERT INTO position_reconciliation_archive
                            (position_id, archived_at, reason, previous_row_json)
                            VALUES (?,?,?,?)''', (old['id'], now,
                            'Exchange inventory cannot be attributed to a verified bot BUY',
                            json.dumps(old, default=str, ensure_ascii=False)))
                    await db.execute('''UPDATE positions SET live=1,status='open',
                        quantity=?,entry_price=0,strategy='exchange_unmanaged',
                        stop_loss_price=NULL,take_profit_price=NULL,max_hold_hours=NULL,
                        target_confidence_change=NULL WHERE id=?''',
                        (storage_quantity(qty), old['id']))
                    updated += 1
                    unmanaged += 1
                    ownership_notes.append({'ticker': ticker, 'side': side,
                                            'state': 'unmanaged', 'reason': reason})

                # Exchange holdings block a new BUY even when entry fills are
                # still being reconciled and local state is pending.
                await db.execute('UPDATE markets SET has_position=1 WHERE market_id=?', (ticker,))

            # Close ONLY exchange-absent live inventory rows. Pending intents
            # remain pending: a zero current position is NOT proof that a
            # submitted limit BUY has been cancelled or failed.
            exchange_tickers = {ticker for ticker, side in inventory}
            for old in current_rows:
                key = (old['market_id'], str(old['side']).upper())
                if bool(old['live']) and old['status'] in ('open', 'pending') and key not in inventory:
                    await db.execute("UPDATE positions SET status='closed' WHERE id=?", (old['id'],))
                    # The other side may still be owned, or a different pending
                    # intent may exist for the same ticker. Do not unblock it.
                    if old['market_id'] not in exchange_tickers and not any(
                            r['market_id'] == old['market_id'] and r['status'] == 'pending'
                            for r in current_rows):
                        await db.execute('UPDATE markets SET has_position=0 WHERE market_id=?',
                                         (old['market_id'],))
                    closed += 1
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    # Report only; an audit failure must not undo an already committed inventory sync.
    snapshot_inventory = {}
    for row in raw_positions:
        ticker, side, qty = parse_market_position(row)
        if qty:
            snapshot_inventory[(ticker, side)] = qty
    reservation_status = 'ok'
    try:
        reservation_report = audit_order_reservations(resting, snapshot_inventory)
        save_order_reservation_report(reservation_report, db_manager.db_path)
    except Exception as exc:
        reservation_status = f'failed: {type(exc).__name__}: {str(exc)[:160]}'

    audit_status = 'ok'
    try:
        report = audit_resting_orders(resting, snapshot_inventory)
        save_audit(report, db_manager.db_path)
    except Exception as exc:
        audit_status = f'failed: {type(exc).__name__}'

    fills_status = 'ok'
    replay_status = 'not_run'
    cost_basis_status = 'not_run'
    fee_audit_status = 'not_run'
    try:
        raw_fills = exchange_fills if exchange_fills is not None else await fetch_all_fills(client)
        fills_report = build_fills_report(raw_fills, snapshot_inventory, resting)
        save_fills_audit(fills_report, db_manager.db_path)
        try:
            replay_report = replay_fills(raw_fills, snapshot_inventory)
            save_replay_report(replay_report, db_manager.db_path)
            replay_status = 'ok'
            try:
                cost_report = audit_cost_basis(raw_fills, snapshot_inventory)
                save_cost_basis_report(cost_report, db_manager.db_path)
                cost_basis_status = 'ok'
                try:
                    fee_report = audit_fees_and_completeness(raw_fills, snapshot_inventory, resting, cost_report)
                    save_fee_completeness_report(fee_report, db_manager.db_path)
                    fee_audit_status = 'ok'
                except Exception as exc:
                    fee_audit_status = f'failed: {type(exc).__name__}: {str(exc)[:160]}' 
            except Exception as exc:
                cost_basis_status = f'failed: {type(exc).__name__}: {str(exc)[:160]}'
        except Exception as exc:
            replay_status = f'failed: {type(exc).__name__}: {str(exc)[:160]}'
    except Exception as exc:
        fills_status = f'failed: {type(exc).__name__}: {str(exc)[:160]}'

    preflight_status = 'ok'
    try:
        preflight_report = await run_demo_exit_preflight(client)
        save_exit_preflight_report(preflight_report, db_manager.db_path)
    except Exception as exc:
        preflight_status = f'failed: {type(exc).__name__}: {str(exc)[:160]}'

    return {'added': added, 'updated': updated, 'closed': closed,
            'exchange_positions': len(raw_positions), 'resting_orders': len(resting),
            'order_audit': audit_status, 'fills_audit': fills_status,
            'replay_audit': replay_status, 'cost_basis_audit': cost_basis_status,
            'fee_completeness_audit': fee_audit_status,
            'order_reservation_audit': reservation_status,
            'exit_preflight_audit': preflight_status, 'unmanaged_positions': unmanaged,
            'managed_positions': managed, 'waiting_for_fills': waiting_for_fills,
            'restored_from_archive': restored_from_archive,
            'ownership_notes': ownership_notes[:25]}
