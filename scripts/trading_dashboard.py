#!/usr/bin/env python3
"""Kalshi Dashboard (original sidebar layout, 30s auto-refresh, read-only).

Restores the original user-facing layout, charts, LLM analytics and full-history
CSV export. No trading routes; Demo BUY/SELL and strategy jobs are untouched.
Exchange metrics are never replaced by local paper/accounting estimates.
"""
import asyncio
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.clients.kalshi_client import KalshiClient
from src.jobs.reconcile_demo import fetch_all
from src.utils.database import DatabaseManager
from src.utils.exchange_dashboard_accounting import summarize_market_positions
from src.utils.market_prices import get_market_prices
from desktop.runtime_state import read_runtime_state
from desktop.paths import get_user_data_dir, get_trading_db_path

st.set_page_config(page_title='Trading System Dashboard', page_icon='📊',
                   layout='wide', initial_sidebar_state='expanded')

st.markdown("""
<style>
.metric-card {background-color:#f0f2f6;padding:1rem;border-radius:0.5rem;margin:0.5rem 0}
.success-metric {background-color:#d4edda;border-left:4px solid #28a745}
.warning-metric {background-color:#fff3cd;border-left:4px solid #ffc107}
.danger-metric {background-color:#f8d7da;border-left:4px solid #dc3545}
.llm-query {background-color:#f8f9fa;border:1px solid #dee2e6;border-radius:.5rem;padding:1rem;margin:.5rem 0}
</style>
""", unsafe_allow_html=True)

REFRESH_SECONDS = 30


def _price(value):
    return 'Unavailable' if value is None else f'${value:,.2f}'


def _number(value):
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Invalid Kalshi numeric field')
    return result


def _arrow_safe(dataframe):
    """Avoid PyArrow mixed object-type Value column errors on Windows.

    Only convert object columns with heterogeneous Python element types;
    preserve numeric columns for Streamlit sorting and formatting.
    """
    df = dataframe.copy()
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col].dtype):
            types = {type(x) for x in df[col].dropna()}
            if len(types) > 1:
                df[col] = df[col].map(lambda v: '' if v is None else str(v)).astype('string')
    return df


def _table(rows, *, key=None):
    frame = pd.DataFrame(rows)
    if not frame.empty:
        st.dataframe(_arrow_safe(frame), hide_index=True, width='stretch', key=key)
    return frame


@st.cache_data(ttl=25, show_spinner=False)
def load_exchange():
    """Exchange-authoritative account snapshot, all paginated fills/orders."""
    async def read():
        async with KalshiClient() as client:
            balance = await client.get_balance()
            positions = await fetch_all(client, '/trade-api/v2/portfolio/positions', 'market_positions')
            orders = await fetch_all(client, '/trade-api/v2/portfolio/orders', 'orders', {'status':'resting'})
            fills = await fetch_all(client, '/trade-api/v2/portfolio/fills', 'fills')
            # Only compute bid estimates from real, valid bid quotes.
            bids = {}
            for p in positions:
                qty = _number(p.get('position_fp', p.get('position', '0')))
                if not qty:
                    continue
                try:
                    market = (await client.get_market(p['ticker'])).get('market', {})
                    yes_bid, _, no_bid, _ = get_market_prices(market)
                    bid = yes_bid if qty > 0 else no_bid
                    if 0 < bid < 1:
                        bids[(p['ticker'], 'YES' if qty > 0 else 'NO')] = str(bid)
                except Exception:
                    # Do NOT claim zero bid or zero P&L if a market quote is missing.
                    continue
            return balance, positions, orders, fills, bids
    return asyncio.run(read())


@st.cache_data(ttl=30, show_spinner=False)
def load_strategy_data():
    """Existing database-based strategy analytics, distinct from account P&L."""
    async def read():
        db = DatabaseManager()
        await db.initialize()
        try:
            return await db.get_performance_by_strategy()
        finally:
            await db.close()
    return asyncio.run(read())


@st.cache_data(ttl=30, show_spinner=False)
def load_llm_data():
    async def read():
        db = DatabaseManager()
        await db.initialize()
        try:
            queries = await db.get_llm_queries(hours_back=24, limit=100)
            stats = await db.get_llm_stats_by_strategy()
            for strategy, values in stats.items():
                if not values.get('total_tokens'):
                    related = [q for q in queries if q.strategy == strategy]
                    values['total_tokens'] = sum(
                        (len(q.prompt or '') + len(q.response or '')) // 4
                        for q in related
                    )
                    values['estimated'] = True
            return queries, stats
        finally:
            await db.close()
    return asyncio.run(read())


def bot_order_ids():
    """Only label Bot when there is a matching durable order journal entry."""
    path = get_trading_db_path().with_name('demo_submission_intents.sqlite3')
    if not path.is_file():
        return set()
    try:
        with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)) as db:
            return {row[0] for row in db.execute(
                'SELECT order_id FROM submission_intents WHERE order_id IS NOT NULL')}
    except sqlite3.Error:
        return set()


def _csv(rows, filename, label, key):
    """Export raw, deduplicated exchange fills, independent of active positions."""
    if not rows:
        st.info('No trade records to export.')
        return
    df = pd.json_normalize(rows)
    if 'fill_id' in df.columns:
        df = df.drop_duplicates(subset=['fill_id'])
    st.download_button(label, data=df.to_csv(index=False).encode('utf-8-sig'),
                       file_name=filename, mime='text/csv', key=key, on_click='ignore')


def _account_numbers(balance):
    cash = _number(balance['balance']) / 100 if 'balance' in balance else None
    portfolio = _number(balance['portfolio_value']) / 100 if 'portfolio_value' in balance else None
    total = cash + portfolio if cash is not None and portfolio is not None else None
    return cash, portfolio, total


def show_overview(balance, report, orders, fills, performance):
    """Original-style overview + graphs with exchange-verified finance metrics."""
    st.header('📈 System Overview')
    cash, portfolio, total = _account_numbers(balance)
    a,b,c,d = st.columns(4)
    a.metric('💰 Portfolio Balance', _price(total))
    b.metric('📈 Executed Fills', len({str(f.get('fill_id')) for f in fills if f.get('fill_id')}))
    c.metric('💹 Realized P&L (Kalshi markets)', _price(report['realized']))
    d.metric('🎯 Active Positions', report['position_count'])
    e,f,g,h = st.columns(4)
    e.metric('💵 Available Cash', _price(cash))
    f.metric('📊 Position Value', _price(portfolio))
    g.metric('📈 Unrealized P&L (bid estimate)', _price(report['unrealized_estimate']))
    h.metric('📋 Open Orders', len(orders))
    st.caption('Realized P&L is Kalshi market_positions.realized_pnl_dollars for returned markets; '
               'not a verified lifetime/settled account figure. Unrealized P&L is a bid estimate '
               'and stays Unavailable when quotes or basis are missing. Trading fees on future exits '
               'are not included.')
    if performance:
        st.subheader('🎯 Strategy Performance Summary (local DB)')
        st.caption('Local strategy statistics may omit manually executed trades and unconfirmed fills.')
        names = [str(name).replace('_',' ').title() for name in performance]
        pnl = [float(performance[name].get('total_pnl') or 0) for name in performance]
        wins = [float(performance[name].get('win_rate_pct') or 0) for name in performance]
        col1,col2 = st.columns(2)
        with col1:
            fig = px.bar(x=names,y=pnl,title='P&L by Strategy (DB)',
                         labels={'x':'Strategy','y':'P&L ($)'}, color=pnl,
                         color_continuous_scale='RdYlGn')
            fig.update_layout(showlegend=False,height=400)
            st.plotly_chart(fig,width='stretch')
        with col2:
            fig = px.bar(x=names,y=wins,title='Win Rate by Strategy (DB)',
                         labels={'x':'Strategy','y':'Win Rate (%)'},color=wins,
                         color_continuous_scale='Blues')
            fig.update_layout(showlegend=False,height=400)
            st.plotly_chart(fig,width='stretch')
    st.subheader('📋 Recent Exchange Positions')
    if report['positions']:
        _table(report['positions'])
    else:
        st.info('No active exchange positions.')


def show_positions_trades(report, fills):
    """Restored sidebar positions, filters, selectable rows and full CSV export."""
    st.header('💼 Positions & Trades')
    positions = report['positions']
    st.subheader(f'📊 Active Positions ({len(positions)})')
    if positions:
        df = pd.DataFrame(positions)
        a,b = st.columns(2)
        with a:
            options = sorted(df['Side'].dropna().unique().tolist())
            sides = st.multiselect('Filter by Side', options, default=options)
        with b:
            ticker_text = st.text_input('Search ticker', placeholder='Market ticker')
        filtered = df[df['Side'].isin(sides)]
        if ticker_text:
            filtered = filtered[filtered['Ticker'].astype(str).str.contains(ticker_text,case=False,regex=False)]
        selection = st.dataframe(_arrow_safe(filtered.reset_index(drop=True)), hide_index=True,
                                 width='stretch',on_select='rerun',selection_mode='single-row',
                                 key='active_positions_table')
        selected = selection.selection.rows
        if selected:
            selected_ticker = str(filtered.iloc[selected[0]]['Ticker'])
            st.subheader(f'Trade details — {selected_ticker}')
            selected_fills = [f for f in fills if f.get('ticker') == selected_ticker]
            if selected_fills:
                df_sel = pd.json_normalize(selected_fills)
                if 'fill_id' in df_sel.columns:
                    df_sel = df_sel.drop_duplicates(subset='fill_id')
                st.dataframe(_arrow_safe(df_sel), hide_index=True,width='stretch')
                _csv(selected_fills,'kalshi_'+selected_ticker+'_fills.csv',
                     '⬇ Export selected market fills (CSV)', 'export_selected_fills')
            else:
                st.info('No fills returned for this market.')
        if not filtered.empty:
            st.subheader('📈 Position Analytics')
            col1,col2 = st.columns(2)
            with col1:
                fig = px.pie(names=filtered['Side'].tolist(),
                             title='Position Distribution', values=[1]*len(filtered))
                st.plotly_chart(fig,width='stretch')
            with col2:
                fig = px.bar(x=filtered['Ticker'].tolist(),
                             y=[float(Decimal(str(n))) for n in filtered['Contracts']],
                             labels={'x':'Market','y':'Contracts'}, title='Contracts by Market')
                st.plotly_chart(fig,width='stretch')
    else:
        st.info('No active exchange positions.')
    st.subheader('📥 Trade History Export')
    st.caption('Export all fills, including closed positions and manual trades. Data is fetched '
               'from Kalshi API, not only local SQLite.')
    if st.button('Load complete trade history',key='load_full_history'):
        st.session_state['show_full_history'] = True
    if st.session_state.get('show_full_history'):
        show_trade_history(fills, embedded=True)


def show_open_orders(orders, tracked):
    st.header('📋 Open Orders (Kalshi)')
    st.caption('Exchange resting orders, including partially filled and manual orders.')
    if not orders:
        st.info('No resting orders reported by Kalshi.')
        return
    keys=['order_id','ticker','side','action','status','type',
          'initial_count_fp','remaining_count_fp','fill_count_fp',
          'yes_price_dollars','no_price_dollars','created_time']
    rows=[]
    for o in orders:
        row={key:o.get(key) for key in keys}
        row['Origin']='Bot' if o.get('order_id') in tracked else 'External / unknown'
        rows.append(row)
    st.metric('Resting orders',len(rows))
    _table(rows)
    _csv(rows, 'kalshi_open_orders.csv', '⬇ Export open orders (CSV)', 'export_open_orders')


def show_trade_history(fills, embedded=False):
    if not embedded:
        st.header('📥 Trade History')
    st.caption('All available paginated exchange fills: includes Bot and External / unknown orders.')
    if not fills:
        st.info('No fills returned by Kalshi.')
        return
    tracked=bot_order_ids()
    rows=[];seen=set()
    for f in sorted(fills,key=lambda x:str(x.get('created_time','')),reverse=True):
        fid = f.get('fill_id')
        if fid and fid in seen:
            continue
        if fid:
            seen.add(fid)
        record=dict(f)
        record['Origin']='Bot' if f.get('order_id') in tracked else 'External / unknown'
        rows.append(record)
    st.metric('Executed fills',len(rows))
    _table(rows)
    _csv(rows,'kalshi_all_trades_'+datetime.now(timezone.utc).strftime('%Y%m%d')+'.csv',
         f'⬇ Export {len(rows)} trades (CSV)','export_all_fills_'+('embed' if embedded else 'page'))
    st.caption('Raw fills, not a tax statement or verified lifetime P&L.')


def show_bot_activity():
    st.header('📝 Bot Activity')
    path=Path.cwd()/'logs'/'latest.log'
    if not path.is_file():
        st.info('No recent bot log found.')
        return
    with path.open('rb') as f:
        f.seek(0,2)
        f.seek(max(0,f.tell()-250_000))
        lines=f.read().decode('utf-8',errors='replace').splitlines()
    keys=('SUBMITTED','FILLED','BLOCKED','ERROR','WARNING','Trading Cycle',
          'position','SELL','BUY','sync:','STOP','TAKE')
    events=[line for line in lines if any(k.lower() in line.lower() for k in keys)]
    st.code('\n'.join(events[-80:]) or 'No trading events yet',language='text')

def show_strategy_performance(performance_data):
    """Show detailed strategy performance analysis."""
    
    st.header("🎯 Strategy Performance Analysis")
    
    if not performance_data:
        st.warning("No strategy performance data available yet.")
        return
    
    # Strategy selector
    strategies = list(performance_data.keys())
    selected_strategy = st.selectbox(
        "Select Strategy for Detailed Analysis",
        ["All Strategies"] + strategies
    )
    
    if selected_strategy == "All Strategies":
        # Compare all strategies
        st.subheader("📊 Strategy Comparison")
        
        # Create comparison table
        comparison_data = []
        for strategy, stats in performance_data.items():
            comparison_data.append({
                'Strategy': strategy.replace('_', ' ').title(),
                'Completed Trades': stats['completed_trades'],
                'Local DB P&L': f"${stats['total_pnl']:.2f}",
                'Avg P&L per Trade': f"${stats['avg_pnl_per_trade']:.2f}",
                'Win Rate': f"{stats['win_rate_pct']:.1f}%",
                'Best Trade': f"${(stats.get('best_trade') or 0):.2f}",
                'Worst Trade': f"${(stats.get('worst_trade') or 0):.2f}",
                'Open Positions': stats['open_positions'],
                'Capital Deployed': f"${stats['capital_deployed']:.2f}"
            })
        
        df = pd.DataFrame(comparison_data)
        st.dataframe(df, width="stretch", hide_index=True)
        
        # Performance charts
        col1, col2 = st.columns(2)
        
        with col1:
            # Risk-return scatter
            fig_risk = go.Figure()
            
            for strategy, stats in performance_data.items():
                if stats['completed_trades'] > 0:
                    fig_risk.add_trace(go.Scatter(
                        x=[stats['avg_pnl_per_trade']],
                        y=[stats['win_rate_pct']],
                        mode='markers+text',
                        text=[strategy.replace('_', ' ').title()],
                        textposition="top center",
                        marker=dict(
                            size=stats['completed_trades'] * 2,
                            color=stats['total_pnl'],
                            colorscale='RdYlGn',
                            showscale=True
                        ),
                        name=strategy
                    ))
            
            fig_risk.update_layout(
                title="Risk-Return Analysis (Bubble size = Trade count)",
                xaxis_title="Average P&L per Trade ($)",
                yaxis_title="Win Rate (%)",
                height=500
            )
            st.plotly_chart(fig_risk, width="stretch")
        
        with col2:
            # Capital deployment
            fig_capital = px.pie(
                values=[stats['capital_deployed'] for stats in performance_data.values()],
                names=[strategy.replace('_', ' ').title() for strategy in performance_data.keys()],
                title="Capital Deployment by Strategy"
            )
            fig_capital.update_layout(height=500)
            st.plotly_chart(fig_capital, width="stretch")
    
    else:
        # Show individual strategy details
        stats = performance_data[selected_strategy]
        
        st.subheader(f"📋 {selected_strategy.replace('_', ' ').title()} Performance")
        
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Local DB P&L", f"${stats['total_pnl']:.2f}")
        with col2:
            st.metric("Win Rate", f"{stats['win_rate_pct']:.1f}%")
        with col3:
            st.metric("Completed Trades", stats['completed_trades'])
        with col4:
            st.metric("Open Positions", stats['open_positions'])
        
        # Detailed metrics
        if stats['completed_trades'] > 0:
            st.subheader("📈 Detailed Metrics")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Trade Performance:**")
                st.write(f"- Average P&L per Trade: ${stats['avg_pnl_per_trade']:.2f}")
                st.write(f"- Best Trade: ${(stats.get('best_trade') or 0):.2f}")
                st.write(f"- Worst Trade: ${(stats.get('worst_trade') or 0):.2f}")
                st.write(f"- Winning Trades: {stats['winning_trades']}")
                st.write(f"- Losing Trades: {stats['losing_trades']}")
            
            with col2:
                st.write("**Capital Allocation:**")
                st.write(f"- Capital Deployed: ${stats['capital_deployed']:.2f}")
                st.write(f"- Open Positions: {stats['open_positions']}")
                if stats['capital_deployed'] > 0:
                    avg_position_size = stats['capital_deployed'] / max(stats['open_positions'], 1)
                    st.write(f"- Avg Position Size: ${avg_position_size:.2f}")

def show_llm_analysis(llm_queries, llm_stats):
    """Show LLM query analysis and review."""
    
    st.header("🤖 LLM Analysis & Review")
    st.markdown("**Review all AI queries and responses for insights and improvements**")
    
    if not llm_queries and not llm_stats:
        st.warning("No LLM query data available yet. LLM logging will start with new queries.")
        st.info("💡 **Tip:** The system will automatically log all future Grok queries for analysis.")
        return
    
    # LLM usage stats
    if llm_stats:
        st.subheader("📊 LLM Usage Statistics (Last 7 Days)")
        
        # Create stats summary
        total_queries = sum(stats['query_count'] for stats in llm_stats.values())
        total_cost = sum(stats['total_cost'] for stats in llm_stats.values())
        total_tokens = sum(stats['total_tokens'] for stats in llm_stats.values())
        has_estimated_tokens = any(stats.get('estimated', False) for stats in llm_stats.values())
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Queries", total_queries)
        with col2:
            st.metric("Total Cost", f"${total_cost:.2f}")
        with col3:
            token_label = "Total Tokens*" if has_estimated_tokens else "Total Tokens"
            token_help = "Estimated from response lengths (some token data missing)" if has_estimated_tokens else "Actual token usage"
            st.metric(
                token_label, 
                f"{total_tokens:,}",
                help=token_help
            )
        with col4:
            avg_cost_per_query = total_cost / max(total_queries, 1)
            st.metric("Avg Cost/Query", f"${avg_cost_per_query:.3f}")
        
        if has_estimated_tokens:
            st.caption("*Token counts marked with * are estimated from response text length due to missing usage data")
        
        # Usage by strategy
        if len(llm_stats) > 1:
            fig_usage = px.bar(
                x=list(llm_stats.keys()),
                y=[stats['query_count'] for stats in llm_stats.values()],
                title="LLM Queries by Strategy",
                labels={'x': 'Strategy', 'y': 'Query Count'},
                color=[stats['total_cost'] for stats in llm_stats.values()],
                color_continuous_scale='Blues'
            )
            st.plotly_chart(fig_usage, width="stretch")
    
    # Query filters
    st.subheader("🔍 Query Analysis")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        strategies = list(set(query.strategy for query in llm_queries)) if llm_queries else []
        selected_strategy = st.selectbox(
            "Filter by Strategy",
            ["All"] + strategies
        )
    
    with col2:
        query_types = list(set(query.query_type for query in llm_queries)) if llm_queries else []
        selected_type = st.selectbox(
            "Filter by Query Type",
            ["All"] + query_types
        )
    
    with col3:
        hours_back = st.selectbox(
            "Time Range",
            [6, 12, 24, 48, 168],  # Last 6h, 12h, 24h, 48h, 7 days
            index=2,  # Default to 24h
            format_func=lambda x: f"Last {x} hours" if x < 168 else "Last 7 days"
        )
    
    # Filter queries
    filtered_queries = llm_queries
    
    if llm_queries:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        filtered_queries = [
            q for q in llm_queries 
            if q.timestamp >= cutoff_time
        ]
        
        if selected_strategy != "All":
            filtered_queries = [q for q in filtered_queries if q.strategy == selected_strategy]
        
        if selected_type != "All":
            filtered_queries = [q for q in filtered_queries if q.query_type == selected_type]
        
        st.write(f"**Showing {len(filtered_queries)} queries**")
        
        # Display queries
        for i, query in enumerate(filtered_queries[:20]):  # Show latest 20
            with st.expander(
                f"🤖 {query.strategy} | {query.query_type} | {query.timestamp.strftime('%H:%M:%S')}",
                expanded=(i < 3)  # Expand first 3
            ):
                
                # Query metadata
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**Strategy:** {query.strategy}")
                with col2:
                    st.write(f"**Type:** {query.query_type}")
                with col3:
                    if query.market_id:
                        st.write(f"**Market:** {query.market_id[:20]}...")
                
                if query.cost_usd:
                    st.write(f"**Cost:** ${query.cost_usd:.4f}")
                
                # Prompt and response
                st.markdown("**🔤 Prompt:**")
                st.code(query.prompt, language="text")
                
                st.markdown("**🤖 Response:**")
                st.code(query.response, language="text")
                
                # Extracted data
                if query.confidence_extracted:
                    st.write(f"**Confidence Extracted:** {query.confidence_extracted:.2%}")
                
                if query.decision_extracted:
                    st.write(f"**Decision Extracted:** {query.decision_extracted}")
    
    else:
        st.info("No LLM queries found for the selected filters.")


#LIVE REFRESH 30 seconds, as in the original version.
@st.fragment(run_every='30s')
def render_live_dashboard(page):
    runtime=read_runtime_state(get_user_data_dir()/'runtime_state.json')
    running=bool(runtime.get('running'))
    env=str(runtime.get('environment') or os.getenv('KALSHI_ENV') or 'Unknown').upper()
    status_col,env_col,mode_col,strategy_col = st.columns(4)
    status_col.metric('Bot status','Running' if running else 'Stopped')
    env_col.metric('Kalshi environment',env)
    mode_col.metric('Trading mode',str(runtime.get('mode','Unknown')))
    strategy_col.metric('Strategy',str(runtime.get('strategy','Unknown')))

    try:
        balance,raw_positions,orders,fills,bids=load_exchange()
        report=summarize_market_positions(raw_positions,bids)
    except Exception as exc:
        st.error(f'Kalshi exchange data unavailable: {exc}')
        st.info('No missing values were replaced with zero. Verify Demo API connection.')
        if page == '📝 Bot Activity':
            show_bot_activity()
        return
    cash, portfolio, total=_account_numbers(balance)
    st.sidebar.markdown('---')
    st.sidebar.markdown('**📊 Data Status:**')
    st.sidebar.metric('Active Positions',report['position_count'])
    st.sidebar.metric('Open Orders',len(orders))
    st.sidebar.metric('Portfolio Balance',_price(total))
    st.sidebar.caption('Auto refresh: 30 seconds')

    if page == '📈 Overview':
        try:
            performance=load_strategy_data()
        except Exception as exc:
            st.warning(f'Local DB strategy history unavailable: {exc}')
            performance={}
        show_overview(balance,report,orders,fills,performance)
    elif page == '🎯 Strategy Performance':
        try:
            performance=load_strategy_data()
            st.caption('Based on local confirmed trade logs; distinct from Kalshi account P&L.')
            show_strategy_performance(performance)
        except Exception as exc:
            st.error(f'Cannot load local strategy history: {exc}')
    elif page == '🤖 LLM Analysis':
        try:
            queries, stats=load_llm_data()
            show_llm_analysis(queries,stats)
        except Exception as exc:
            st.error(f'Cannot load LLM history: {exc}')
    elif page == '💼 Positions & Trades':
        show_positions_trades(report,fills)
    elif page == '📋 Open Orders':
        show_open_orders(orders,bot_order_ids())
    elif page == '📥 Trade History':
        show_trade_history(fills)
    elif page == '📝 Bot Activity':
        show_bot_activity()


def main():
    st.title('🚀 Trading System Dashboard')
    st.markdown('**Real-time monitoring and analysis of your automated trading system**')
    if st.button('🔄 Refresh Data',help='Clear cached exchange and DB reads and reload'):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.title('📊 Dashboard')
    page=st.sidebar.selectbox('Select View', [
        '📈 Overview',
        '🎯 Strategy Performance',
        '🤖 LLM Analysis',
        '💼 Positions & Trades',
        '📋 Open Orders',
        '📥 Trade History',
        '📝 Bot Activity',
    ])
    render_live_dashboard(page)


if __name__ == '__main__':
    main()
