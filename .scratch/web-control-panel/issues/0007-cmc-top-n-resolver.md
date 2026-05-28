---
id: "0007"
title: CMC Top N caching + symbols resolver
status: done
type: AFK
blocked_by: ["0006"]
covers_user_stories: ["#17 (top_n mode)", "#37 (dedupe via cache)"]
prd: ../PRD.md
plan: ../../../docs/WEB_CONTROL_PANEL_PLAN.md
---

# 0007 — CMC Top N + symbols resolver

## What to build

Mở rộng worker hỗ trợ symbols mode `top_n` (đã placeholder ở slice 5):

- `cmc_service.fetch_top_n(exchange, n) -> list[str]` (deep module):
  - Check Redis key `cmc:top_n:{exchange}:{n}` trước. Hit → return cached list.
  - Miss → gọi CoinMarketCap API (`/v1/cryptocurrency/listings/latest?limit=N&convert=USDT`). Filter những coin có tradable pair trên exchange đó (qua CCXT markets info hoặc skip filter cho v1 — chỉ lấy symbol BASE/USDT).
  - Set Redis cache TTL 3600s.
  - Return list `["BTC/USDT", "ETH/USDT", ...]` (định dạng ccxt).
- `worker/symbols_resolver.py`: `resolve_symbols(exchange, mode, value) -> list[str]`. Dispatch:
  - `mode='list'` → return `value['list']` as-is.
  - `mode='top_n'` → gọi `cmc_service.fetch_top_n(exchange, value['top_n'])`.
- Update `worker/runner.py` (từ slice 6): thay hardcode list bằng `resolve_symbols(p.exchange, p.symbols_mode, p.symbols_value)`.
- Update form `processes/form.html` (từ slice 5): enable radio `top_n` option. Khi chọn `top_n`, hiện input số `N`. Khi `list`, hiện textarea.
- Update `process_service.create_process` / `update_process`: validate `symbols_value` schema theo `symbols_mode`.

## Acceptance criteria

- [ ] User tạo process với `symbols_mode=top_n, top_n=50` → worker chu kỳ đầu fetch CMC, cache Redis, scan đúng 50 coins.
- [ ] Tạo process thứ 2 với cùng `(exchange, n=50)` trong vòng 1h → KHÔNG gọi CMC lần 2 (verify qua log `cmc_service` hoặc Redis MONITOR).
- [ ] Sau TTL 3600s → cache miss → gọi CMC lần mới.
- [ ] User tạo process với `top_n=100, n=200` → 2 cache key khác nhau, 2 lần gọi CMC.
- [ ] User toggle mode trong form → input field switch đúng (radio + JS minimal hoặc HTMX trigger).
- [ ] Validate sai schema (vd `symbols_mode=top_n` nhưng `symbols_value={"list": [...]}` ) → error rõ ràng từ Pydantic.
- [ ] Test plan cho `cmc_service.fetch_top_n`:
  - First call hits CMC API (mock httpx) + writes Redis.
  - Second call within TTL reads Redis only (CMC mock not called).
  - Cache miss after TTL → fresh CMC call.
- [ ] Test plan cho `resolve_symbols`:
  - `list` mode trả về value as-is.
  - `top_n` mode delegate đúng cmc_service.

## Notes for the agent

- CMC free tier: 10,000 calls/month. Cache 1h → ~720/tháng worst-case → an toàn dưới ngưỡng. Document rõ trong code comment.
- Nếu CMC API down → fallback: log error, raise exception, worker mark `last_run_status='error: CMC unavailable'`. KHÔNG fail silently.

## Blocked by

- 0006 (worker runner — phải có rồi mới swap hardcoded list bằng resolver)
