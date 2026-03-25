"""
Paper Trading Portfolio Manager.
Handles logic for opening and closing trades in the database,
calculating P&L, and managing virtual balance.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from loguru import logger

from data.models.trade import Trade, TradeSide, TradeStatus
from utils.telegram_bot import TelegramBot



class PortfolioManager:
    """
    Manages virtual trading positions using the SQLite/Postgres database.
    """

    def __init__(self, db_url: str, initial_balance: float = 10000.0, fee_rate: float = 0.001, slippage: float = 0.0005):
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        self.initial_balance = initial_balance
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.bot = TelegramBot()

    def get_open_trades(self, exchange: Optional[str] = None, symbol: Optional[str] = None) -> List[Trade]:
        """Get all currently open trades."""
        with self.Session() as session:
            query = select(Trade).where(Trade.status == TradeStatus.OPEN)
            if exchange:
                query = query.where(Trade.exchange == exchange)
            if symbol:
                query = query.where(Trade.symbol == symbol)
            return list(session.scalars(query).all())

    def get_balance(self) -> float:
        """
        Calculate current balance = initial_balance + sum(closed PnL).
        """
        with self.Session() as session:
            query = select(Trade.pnl_usd).where(Trade.status == TradeStatus.CLOSED, Trade.pnl_usd != None)
            closed_pnl = sum(session.scalars(query).all())
            return self.initial_balance + closed_pnl

    def has_open_trade(self, exchange: str, symbol: str, strategy: str) -> bool:
        """Check if a specific strategy already has an open position for a symbol."""
        with self.Session() as session:
            query = select(Trade.id).where(
                Trade.exchange == exchange,
                Trade.symbol == symbol,
                Trade.strategy == strategy,
                Trade.status == TradeStatus.OPEN
            ).limit(1)
            return session.scalar(query) is not None

    def open_trade(
        self,
        exchange: str,
        symbol: str,
        strategy: str,
        timeframe: str,
        side: TradeSide,
        entry_price: float,
        position_size: float,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        tp2_price: Optional[float] = None,
        entry_time: Optional[datetime] = None,
        trade_metadata: Optional[str] = None,
    ) -> Trade:
        """Open a new virtual trade in the database."""
        entry_time = entry_time or datetime.utcnow()
        
        # Apply entry slippage
        slippage_mult = 1 + self.slippage if side == TradeSide.LONG else 1 - self.slippage
        actual_entry_price = entry_price * slippage_mult

        trade = Trade(
            exchange=exchange,
            symbol=symbol,
            strategy=strategy,
            timeframe=timeframe,
            side=side,
            status=TradeStatus.OPEN,
            entry_time=entry_time,
            entry_price=float(actual_entry_price),
            position_size=float(position_size),
            sl_price=float(sl_price) if sl_price is not None else None,
            tp_price=float(tp_price) if tp_price is not None else None,
            tp2_price=float(tp2_price) if tp2_price is not None else None,
            trade_metadata=trade_metadata,
            fee_usd=float(position_size * self.fee_rate)  # Entry fee
        )

        with self.Session() as session:
            session.add(trade)
            session.commit()
            session.refresh(trade)
            logger.info(f"Opened {side.name} {symbol} at {actual_entry_price} (size: ${position_size})")

            # Notification
            self.bot.send_trade_open(
                symbol=symbol,
                strategy=strategy,
                side=side.name,
                price=actual_entry_price,
                size=position_size,
                sl=sl_price,
                tp=tp_price,
                tp2=tp2_price,
            )

            return trade

    def update_trade(self, trade_id: int, sl_price: Optional[float] = None, tp_price: Optional[float] = None) -> bool:
        """Update an open trade's SL or TP price."""
        with self.Session() as session:
            trade = session.get(Trade, trade_id)
            if not trade or trade.status == TradeStatus.CLOSED:
                return False
                
            if sl_price is not None:
                trade.sl_price = sl_price
            if tp_price is not None:
                trade.tp_price = tp_price
                
            session.commit()
            logger.info(f"Updated trade #{trade_id} {trade.symbol}: SL=${trade.sl_price}, TP=${trade.tp_price}")
            return True

    def update_tp1_hit(self, trade_id: int, status: bool = True) -> bool:
        """Mark TP1 as hit for an open trade."""
        with self.Session() as session:
            trade = session.get(Trade, trade_id)
            if not trade or trade.status == TradeStatus.CLOSED:
                return False
            trade.tp1_hit = status
            session.commit()
            return True

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        exit_reason: str,
        exit_time: Optional[datetime] = None,
    ) -> Optional[Trade]:
        """Close an open trade and calculate final P&L."""
        exit_time = exit_time or datetime.utcnow()

        with self.Session() as session:
            trade = session.get(Trade, trade_id)
            if not trade or trade.status == TradeStatus.CLOSED:
                return None

            # Apply exit slippage
            slippage_mult = 1 - self.slippage if trade.side == TradeSide.LONG else 1 + self.slippage
            actual_exit_price = exit_price * slippage_mult

            # Calculate PnL
            if trade.side == TradeSide.LONG:
                pnl_pct = (actual_exit_price - trade.entry_price) / trade.entry_price
            else:
                pnl_pct = (trade.entry_price - actual_exit_price) / trade.entry_price

            exit_fee = trade.position_size * self.fee_rate
            total_fee = trade.fee_usd + exit_fee
            pnl_usd = (trade.position_size * pnl_pct) - total_fee

            trade.status = TradeStatus.CLOSED
            trade.exit_time = exit_time
            trade.exit_price = actual_exit_price
            trade.exit_reason = exit_reason
            trade.pnl_pct = pnl_pct
            trade.pnl_usd = pnl_usd
            trade.fee_usd = total_fee

            session.commit()
            session.refresh(trade)
            logger.info(
                f"Closed {trade.side.name} {trade.symbol} at {actual_exit_price} "
                f"[{exit_reason}] PnL: ${pnl_usd:.2f} ({(pnl_pct*100):.2f}%)"
            )

            # Notification
            self.bot.send_trade_close(
                symbol=trade.symbol,
                strategy=trade.strategy,
                side=trade.side.name,
                price=actual_exit_price,
                pnl_usd=pnl_usd,
                pnl_pct=pnl_pct,
                reason=exit_reason,
            )

            return trade

    def get_hourly_stats(self) -> dict:
        """Fetch trading statistics: overall + last 1 hour with detailed exit reasons."""
        from datetime import timedelta
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        
        def analyze_trades(trades):
            """Phân tích chi tiết các lệnh đã đóng."""
            tp1_count = tp2_count = sl_count = timeout_count = 0
            wins = losses = 0
            total_pnl_usd = total_pnl_pct = 0.0
            
            for trade in trades:
                # Thống kê theo lý do thoát (trong exit_reason, không phải trade_metadata)
                exit_reason = trade.exit_reason or ""
                exit_reason_upper = exit_reason.upper()
                
                if "TP1" in exit_reason_upper:
                    tp1_count += 1
                elif "TP2" in exit_reason_upper or "TP_HIT" in exit_reason_upper:
                    tp2_count += 1
                elif "SL" in exit_reason_upper or "STOPLOSS" in exit_reason_upper:
                    sl_count += 1
                elif "TIMEOUT" in exit_reason_upper:
                    timeout_count += 1
                
                # Thống kê win/loss và PnL
                pnl_usd = trade.pnl_usd or 0
                pnl_pct = trade.pnl_pct or 0
                if pnl_usd > 0:
                    wins += 1
                else:
                    losses += 1
                total_pnl_usd += pnl_usd
                total_pnl_pct += pnl_pct
            
            return {
                "total": len(trades),
                "wins": wins,
                "losses": losses,
                "pnl_usd": total_pnl_usd,
                "pnl_pct": total_pnl_pct,
                "tp1_count": tp1_count,
                "tp2_count": tp2_count,
                "sl_count": sl_count,
                "timeout_count": timeout_count
            }
        
        with self.Session() as session:
            # === TỔNG KẾT TOÀN BỘ ===
            query_all_closed = select(Trade).where(Trade.status == TradeStatus.CLOSED)
            all_closed_trades = session.scalars(query_all_closed).all()
            all_stats = analyze_trades(all_closed_trades)
            
            # === KẾT QUẢ 1 GIỜ QUA ===
            query_hourly_closed = select(Trade).where(
                Trade.status == TradeStatus.CLOSED,
                Trade.exit_time >= one_hour_ago
            )
            hourly_closed_trades = session.scalars(query_hourly_closed).all()
            hourly_stats = analyze_trades(hourly_closed_trades)
            
            # === LỆNH ĐANG MỞ ===
            query_open = select(Trade).where(Trade.status == TradeStatus.OPEN)
            open_trades = session.scalars(query_open).all()
            
            return {
                # Tổng kết toàn bộ
                "all": all_stats,
                "open_count": len(open_trades),
                
                # Kết quả 1 giờ qua
                "hourly": hourly_stats
            }
