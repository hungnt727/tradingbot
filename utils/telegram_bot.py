"""
Telegram Notification Helper.
Sends messages to a Telegram chat using the bot API.
"""
import os
import requests
from datetime import datetime
from loguru import logger
from typing import Optional


class TelegramBot:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            logger.warning("Telegram Bot disabled. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
        else:
            logger.info("Telegram Bot initialized.")

    def send_message(self, message: str) -> bool:
        """Send a markdown-formatted message to the configured chat."""
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def _format_price(self, price: float) -> str:
        """Dynamic price formatting based on value magnitude."""
        if price is None:
            return "N/A"
        if price >= 100:
            return f"{price:.2f}"
        if price >= 1:
            return f"{price:.4f}"
        if price >= 0.01:
            return f"{price:.6f}"
        return f"{price:.8f}"

    def send_trade_open(self, symbol: str, strategy: str, side: str, price: float, size: float, sl: float, tp: float, tp2: Optional[float] = None):
        """Format and send a trade open notification."""
        icon = "🟢" if side == "LONG" else "🔴"
        
        msg = (
            f"<b>{icon} OPEN {side} | {symbol}</b>\n"
            f"Strategy: {strategy}\n"
            f"Entry Price: ${self._format_price(price)}\n"
            f"Size: ${size:.2f}\n"
        )
        if sl:
            msg += f"SL: ${self._format_price(sl)}\n"
        
        # Handle multiple TPs
        if tp2:
            msg += f"TP1: ${self._format_price(tp)}\n"
            msg += f"TP2: ${self._format_price(tp2)}\n"
        elif tp:
            msg += f"TP: ${self._format_price(tp)}\n"

        self.send_message(msg)

    def send_trade_close(self, symbol: str, strategy: str, side: str, price: float, pnl_usd: float, pnl_pct: float, reason: str):
        """Format and send a trade close notification."""
        icon = "✅" if pnl_usd > 0 else "❌"
        # Determine emoji for reason
        if reason == "sl_hit":
            reason_str = "Stop Loss"
        elif reason == "tp_hit":
            reason_str = "Take Profit"
        elif reason == "SL_BREAKEVEN":
            reason_str = "Breakeven"
        else:
            reason_str = reason

        msg = (
            f"<b>{icon} CLOSED {side} | {symbol}</b>\n"
            f"Strategy: {strategy}\n"
            f"Exit Price: ${self._format_price(price)}\n"
            f"Reason: {reason_str}\n"
            f"PnL: <b>${pnl_usd:.2f} ({pnl_pct*100:.2f}%)</b>\n"
        )
        self.send_message(msg)

    def send_summary(self, total_trades: int, open_trades: int, wins: int, losses: int, total_pnl_usd: float, total_pnl_pct: float):
        """Send a summary report of trading performance."""
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        icon = "📊"
        msg = (
            f"<b>{icon} BÁO CÁO GIAO DỊCH (1H VỪA QUA)</b>\n"
            f"--------------------------------\n"
            f"📌 Tổng lệnh đã chốt: {total_trades}\n"
            f"📈 Tỷ lệ thắng: {win_rate:.1f}% ({wins}W / {losses}L)\n"
            f"💰 Tổng PnL: <b>${total_pnl_usd:.2f} ({total_pnl_pct*100:.2f}%)</b>\n"
            f"⏳ Lệnh đang mở: {open_trades}\n"
            f"--------------------------------\n"
            f"<i>Cập nhật lúc: {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        self.send_message(msg)
