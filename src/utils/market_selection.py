"""Diverse, bounded AI candidate preselection; no orders, no LLM requests.

Selects up to a configurable count of already-eligible markets. Keeps event
concentration bounded when alternatives exist; otherwise uses the remaining
eligible markets to fill the requested count. Does not weaken trading filters.
"""

from collections import defaultdict
from math import isfinite
from typing import Any, Sequence

from src.utils.market_prices import get_market_prices, is_tradeable_market


def _market_volume(market: Any) -> float:
    try:
        v = float(getattr(market, 'volume', 0) or 0)
        return v if isfinite(v) and v >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _category(market: Any) -> str:
    category = str(getattr(market, 'category', '') or '').strip().lower()
    if category and category not in {'unknown', 'none', 'other', 'uncategorized'}:
        return category
    return str(getattr(market, 'market_id', '')).split('-', 1)[0].lower()


def _event(market: Any) -> str:
    """Use a ticker's event prefix; e.g. KXPRESNOMD-28-XX -> KXPRESNOMD-28."""
    ticker = str(getattr(market, 'market_id', '')).upper()
    return ticker.rsplit('-', 1)[0] if '-' in ticker else ticker


def select_diverse_markets(markets: Sequence[Any], max_count: int = 30, per_event: int = 2) -> list[Any]:
    """Volume-rank within each category, then round-robin across categories.

    First pass prioritizes at most `per_event` markets from the same event.
    Second pass fills any remaining budget from all eligible markets; a portfolio
    with just one event is not artificially starved. Market IDs are deduplicated.
    """
    if max_count < 1 or per_event < 1:
        raise ValueError('max_count and per_event must both be >= 1')

    sorted_all = sorted(
        markets, key=lambda m: (-_market_volume(m), str(getattr(m, 'market_id', '')))
    )
    unique = []
    seen = set()
    for m in sorted_all:
        ticker = str(getattr(m, 'market_id', '')).strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            unique.append(m)

    categories = defaultdict(list)
    for m in unique:
        categories[_category(m)].append(m)
    category_names = sorted(categories, key=lambda k: (-_market_volume(categories[k][0]), k))

    selected, selected_ids = [], set()
    event_counts = defaultdict(int)
    # Fixed passes: at most the length of the largest category, no while-spin.
    for _ in range(max((len(v) for v in categories.values()), default=0)):
        progress = False
        for key in category_names:
            for m in categories[key]:
                ticker = m.market_id
                if ticker in selected_ids or event_counts[_event(m)] >= per_event:
                    continue
                selected.append(m)
                selected_ids.add(ticker)
                event_counts[_event(m)] += 1
                progress = True
                break
            if len(selected) == max_count:
                return selected
        if not progress:
            break

    # If there are fewer independent events than the budget, fill the remainder
    # in volume order rather than analyzing fewer markets for no good reason.
    for m in unique:
        if m.market_id not in selected_ids:
            selected.append(m)
            selected_ids.add(m.market_id)
            if len(selected) == max_count:
                break
    return selected


def quoted_yes_probability(market_info: dict) -> float | None:
    """Return a valid quoted YES midpoint; never fabricate the old 0.50 default.

    Quotes use dollar values normalized by src.utils.market_prices. An opposite
    NO-side book can supply the YES quote if the YES book is unavailable.
    Markets without a genuine two-sided quote are not suitable for edge scoring.
    """
    if not isinstance(market_info, dict) or not is_tradeable_market(market_info):
        return None
    try:
        yes_bid, yes_ask, no_bid, no_ask = get_market_prices(market_info)
        if all(isfinite(x) for x in (yes_bid, yes_ask)) and 0 < yes_bid <= yes_ask < 1:
            return (yes_bid + yes_ask) / 2
        if all(isfinite(x) for x in (no_bid, no_ask)) and 0 < no_bid <= no_ask < 1:
            return 1 - (no_bid + no_ask) / 2
    except (TypeError, ValueError, OverflowError):
        pass
    return None
