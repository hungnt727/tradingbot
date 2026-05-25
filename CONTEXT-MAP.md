# Context Map

Crypto Trading Bot framework. Single bounded context — toàn bộ repo là 1 domain "trading" duy nhất, nhưng được tách thành 5 phase ghép nối qua **OHLCV** (data) và **Signal/Trade** (logic).

## Contexts

- [TradingBot](./CONTEXT.md) — domain language cho data crawling, strategy engine, backtest, paper trading và live trading.

## Relationships

- (Single context — file này tồn tại để khi project mở rộng có chỗ đăng ký thêm bounded context, vd `analytics/`, `ml-models/`...)
