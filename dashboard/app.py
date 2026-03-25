"""
Streamlit Dashboard for Paper Trading Portfolio.

Run with:
    streamlit run dashboard/app.py
"""
import os
import sys
from pathlib import Path
from datetime import datetime

# Allow importing from project root
sys.path.append(str(Path(__file__).parent.parent))

# import streamlit as st  # TEMPORARILY COMMENTED OUT DUE TO NUMPY VERSION CONFLICT
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from data.models.trade import Trade, TradeStatus

load_dotenv()

# Basic Page Config
st.set_page_config(
    page_title="Paper Trading Dashboard",
    page_icon="📈",
    layout="wide"
)

# Connect to DB
@st.cache_resource
def get_db_session():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        st.error("DATABASE_URL not found in environment.")
        st.stop()
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return Session()


def load_trades(session, status=None):
    query = select(Trade).order_by(Trade.entry_time.desc())
    if status is not None:
        query = query.where(Trade.status == status)
    
    trades = session.scalars(query).all()
    if not trades:
        return pd.DataFrame()
        
    return pd.DataFrame([{
        "ID": t.id,
        "Exchange": t.exchange,
        "Symbol": t.symbol,
        "Strategy": t.strategy,
        "Side": t.side.name,
        "Entry Time": t.entry_time,
        "Entry Price": t.entry_price,
        "Position Size ($)": t.position_size,
        "Exit Time": t.exit_time,
        "Exit Price": t.exit_price,
        "PnL ($)": t.pnl_usd,
        "PnL (%)": round(t.pnl_pct * 100, 2) if t.pnl_pct is not None else None,
        "Status": t.status.name,
        "Reason": t.exit_reason
    } for t in trades])


def main():
    st.title("📈 Crypto Bot — Paper Trading Dashboard")
    
    session = get_db_session()

    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    df_all = load_trades(session)
    
    if df_all.empty:
        st.info("No trades in database yet. Run cli/run_paper_sync.py to start exploring!")
        return

    df_closed = df_all[df_all["Status"] == "CLOSED"]
    df_open = df_all[df_all["Status"] == "OPEN"]
    
    total_trades = len(df_all)
    active_trades = len(df_open)
    
    total_pnl = df_closed["PnL ($)"].sum() if not df_closed.empty else 0.0
    win_rate = 0.0
    if not df_closed.empty:
        wins = len(df_closed[df_closed["PnL ($)"] > 0])
        win_rate = (wins / len(df_closed)) * 100

    col1.metric("Total PnL (Closed)", f"${total_pnl:.2f}", 
                delta_color="normal" if total_pnl >=0 else "inverse", 
                delta=f"${total_pnl:.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Active Trades", active_trades)
    col4.metric("Total Trades", total_trades)

    st.markdown("---")

    # Chart PnL over time
    st.subheader("Gross PnL Curve (Closed Trades)")
    if not df_closed.empty:
        # Sort chronologically by exit
        df_chart = df_closed.sort_values(by="Exit Time").copy()
        df_chart["Cumulative PnL"] = df_chart["PnL ($)"].cumsum()
        df_chart.set_index("Exit Time", inplace=True)
        st.line_chart(df_chart["Cumulative PnL"])

    # Tabs for tables
    tab1, tab2 = st.tabs(["Active Positions (OPEN)", "Trade History (CLOSED)"])
    
    with tab1:
        st.dataframe(
            df_open.drop(columns=["Exit Time", "Exit Price", "PnL ($)", "PnL (%)", "Status", "Reason"]), 
            use_container_width=True
        )
        
    with tab2:
        # Style PnL coloring
        def color_pnl(val):
            if pd.isna(val):
                return ''
            color = 'green' if val > 0 else 'red'
            return f'color: {color}'
            
        st.dataframe(
            df_closed.style.map(color_pnl, subset=['PnL ($)', 'PnL (%)']),
            use_container_width=True
        )


if __name__ == "__main__":
    main()
