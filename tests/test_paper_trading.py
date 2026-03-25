"""
Unit tests for Paper Trading (Portfolio & Engine logic).
Uses an in-memory SQLite database.
"""
import os
from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.models.base import Base
from data.models.trade import Trade, TradeSide, TradeStatus
from paper_trading.portfolio import PortfolioManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_url():
    # Use SQLite in-memory for testing
    return "sqlite:///:memory:"

@pytest.fixture
def db_session(sqlite_url):
    engine = create_engine(sqlite_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)

@pytest.fixture
def portfolio(sqlite_url, db_session):
    # Pass sqlite_url to PortfolioManager which creates its own engine
    # But for the test to share data we need Base.metadata.create_all
    engine = create_engine(sqlite_url)
    Base.metadata.create_all(engine)
    pm = PortfolioManager(db_url=sqlite_url, initial_balance=1000.0, fee_rate=0.001, slippage=0.0)
    # Patch manager to use the same engine pool (SQLite in memory drops if connection lost,
    # so we use a StaticPool or file-based memory)
    # Actually, easiest is a temporary file db for pytest
    temp_db = "sqlite:///test_paper.db"
    temp_eng = create_engine(temp_db)
    Base.metadata.create_all(temp_eng)
    pm = PortfolioManager(db_url=temp_db, initial_balance=1000.0, fee_rate=0.001, slippage=0.0)
    yield pm
    Base.metadata.drop_all(temp_eng)
    if os.path.exists("test_paper.db"):
        try:
            os.remove("test_paper.db")
        except:
            pass


# ---------------------------------------------------------------------------
# Portfolio Tests
# ---------------------------------------------------------------------------

class TestPortfolioManager:
    def test_open_trade_long(self, portfolio):
        trade = portfolio.open_trade(
            exchange="binance",
            symbol="BTC/USDT",
            strategy="SonicRStrategy",
            timeframe="1h",
            side=TradeSide.LONG,
            entry_price=40000.0,
            position_size=100.0,
            sl_price=39000.0,
            tp_price=42000.0
        )
        assert trade.id is not None
        assert trade.status == TradeStatus.OPEN
        assert trade.fee_usd == 100.0 * 0.001  # $0.1 fee
        assert trade.entry_price == 40000.0

        open_trades = portfolio.get_open_trades()
        assert len(open_trades) == 1
        
        has_trade = portfolio.has_open_trade("binance", "BTC/USDT", "SonicRStrategy")
        assert has_trade is True

    def test_close_trade_long_win(self, portfolio):
        trade = portfolio.open_trade(
            exchange="binance", symbol="BTC/USDT", strategy="Test", timeframe="1h",
            side=TradeSide.LONG, entry_price=100.0, position_size=1000.0
        )
        
        # Close at 110 (10% profit = $100 gain)
        # Entry fee = 1.0, Exit fee = 1.0 -> Total fee = 2.0
        # PnL USD = 100.0 - 2.0 = 98.0
        closed = portfolio.close_trade(trade.id, exit_price=110.0, exit_reason="tp_hit")
        
        assert closed.status == TradeStatus.CLOSED
        assert closed.exit_price == 110.0
        assert closed.pnl_pct == pytest.approx(0.1)
        assert closed.fee_usd == pytest.approx(2.0)
        assert closed.pnl_usd == pytest.approx(98.0)
        
        assert portfolio.get_balance() == pytest.approx(1098.0)

    def test_close_trade_short_loss(self, portfolio):
        trade = portfolio.open_trade(
            exchange="binance", symbol="BTC/USDT", strategy="Test", timeframe="1h",
            side=TradeSide.SHORT, entry_price=100.0, position_size=1000.0
        )
        
        # Close at 110 (Short loss 10% = -$100)
        # Fee = 2.0
        # PnL USD = -100.0 - 2.0 = -102.0
        closed = portfolio.close_trade(trade.id, exit_price=110.0, exit_reason="sl_hit")
        
        assert closed.status == TradeStatus.CLOSED
        assert closed.pnl_pct == pytest.approx(-0.1)
        assert closed.fee_usd == pytest.approx(2.0)
        assert closed.pnl_usd == pytest.approx(-102.0)
        
        assert portfolio.get_balance() == pytest.approx(898.0)

    def test_slippage_applied(self):
        temp_db = "sqlite:///test_slip.db"
        eng = create_engine(temp_db)
        Base.metadata.create_all(eng)
        pm = PortfolioManager(db_url=temp_db, initial_balance=1000.0, fee_rate=0.0, slippage=0.01) # 1%
        
        trade = pm.open_trade(
            exchange="binance", symbol="BTC/USDT", strategy="Test", timeframe="1h",
            side=TradeSide.LONG, entry_price=100.0, position_size=100.0
        )
        # Entry slippage pushes price up 1% to 101.0
        assert trade.entry_price == 101.0
        
        closed = pm.close_trade(trade.id, exit_price=150.0, exit_reason="tp")
        # Exit slippage pushes sell price down 1% to 148.5
        assert closed.exit_price == 148.5
        
        Base.metadata.drop_all(eng)
        try: os.remove("test_slip.db")
        except: pass
