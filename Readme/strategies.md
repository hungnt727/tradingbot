# Mô tả các strategy phát hiện tín hiệu

Hệ thống hiện tại hỗ trợ 3 strategy sinh tín hiệu, đều **đa khung thời gian** — các khung phải xác nhận lẫn nhau thì process mới chốt 1 signal, giảm noise so với chạy 1 khung duy nhất.

| Strategy | Class | Handler | Khung | Hướng |
|---|---|---|---|---|
| `EmaRsiReversal` | [strategies/ema_rsi_reversal_strategy.py](../strategies/ema_rsi_reversal_strategy.py) | [worker/strategy_handlers/ema_rsi_reversal.py](../worker/strategy_handlers/ema_rsi_reversal.py) | 1W (filter) + 1D + 1H | SHORT |
| `EmaRsiReversalSimple` | [strategies/ema_rsi_reversal_simple_strategy.py](../strategies/ema_rsi_reversal_simple_strategy.py) | [worker/strategy_handlers/ema_rsi_reversal_simple.py](../worker/strategy_handlers/ema_rsi_reversal_simple.py) | 1W + 1D + 1H | SHORT |
| `VolumeBreakout` | [strategies/volume_breakout_strategy.py](../strategies/volume_breakout_strategy.py) | [worker/strategy_handlers/volume_breakout.py](../worker/strategy_handlers/volume_breakout.py) | 1D + 1H | LONG / SHORT |

Cả 2 đăng ký trong `STRATEGY_REGISTRY` tại [web/schemas/strategy_params.py](../web/schemas/strategy_params.py). Process trên UI dropdown gọi tên đúng bằng `label` của descriptor.

---

## 1. EmaRsiReversal — đảo chiều theo EMA của RSI

### Ý nghĩa

Phát hiện thời điểm momentum đang **suy yếu sau khi RSI vượt vùng quá mua**: 3 đường EMA của RSI (period 5, 10, 20) bắt đầu xếp lớp giảm dần (`ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20`) trong khi `ema_rsi_20` vẫn cao (> 50). Đây là cấu hình "đỉnh đã hình thành nhưng chưa lao xuống" — vào SHORT trước khi đà giảm rõ ràng. Chỉ phát SHORT (không có LONG).

### Logic

**Indicator** (mỗi khung):
- `rsi(period=rsi_period)` trên close
- `ema_rsi_5`, `ema_rsi_10`, `ema_rsi_20` = EMA của RSI ở các period 5/10/20
- `is_reversal[t] = (ema_rsi_5<ema_rsi_10 và ema_rsi_5<ema_rsi_20) tại t` **AND** không thỏa tại `t-1` — đánh dấu nến **bắt đầu** suy yếu
- `bars_since_reversal[t]` = số nến tính từ `is_reversal` gần nhất
- `ema_filter` = EMA-200 của close (dùng cho 1D nếu `use_ema_filter=true`)
- `atr` = ATR-14 (chỉ display trong indicators_snapshot)

**Trigger SHORT trên 1 khung**:
1. `bars_since_reversal < max_distance_candles` — đảo chiều phải còn "tươi"
2. `ema_rsi_20 > min_ema_rsi` (default 50) — RSI vẫn ở vùng cao
3. Hiện tại vẫn duy trì `ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20`
4. (Tùy chọn 1D) `close < ema_filter` — chỉ short khi giá dưới EMA-200
5. (Tùy chọn 1H) `ema_rsi_20 - ema_rsi_5 ≥ min_gap` — yêu cầu khoảng cách EMA-RSI tối thiểu

**Filter 1W (tùy chọn, default BẬT)**:
- Trên nến tuần **mới nhất**: `ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20`.
- Đây là pre-check trước khi xử lý 1D/1H — nếu không thỏa, handler bail luôn, không phí API call cho 1D/1H.
- Yêu cầu ≥ 50 nến tuần (~1 năm). Symbol không đủ data tuần → bị block (an toàn hơn là fire bừa).
- Tắt bằng `use_weekly_filter=false` để giữ behavior cũ chỉ 1D + 1H.

**Trigger SHORT tổng**: 
- (Nếu `use_weekly_filter=true`) `1W[-1]: ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20` **AND**
- `1D[-1].signal == -1` **AND** `1H[-1].signal == -1`.

### Tham số

| Group | Tên | Default | Ghi chú |
|---|---|---|---|
| Basic | `rsi_period` | 14 | Period của RSI |
| Basic | `max_distance_candles` | 20 | Bị siêu thị bởi `n1d`/`m1h` per-TF |
| Basic | `min_gap` | 0.0 | Khoảng EMA-RSI tối thiểu (áp 1H) |
| Basic | `use_ema_filter` | false | Bật EMA-200 trend filter cho 1D |
| Basic | `use_weekly_filter` | **true** | Bật filter 1W (yêu cầu nến tuần mới nhất có `ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20`) |
| Basic | `min_ema_rsi` | 50.0 | Ngưỡng `ema_rsi_20` |
| Advanced | `sl_pct` | 0.05 | Stop loss display Telegram (5%) |
| Advanced | `tp1_pct` | 0.10 | Take profit 1 (10%) |
| Advanced | `tp2_pct` | 0.20 | Take profit 2 (20%) |
| Advanced | `lookback` | 250 | Số nến fetch (cần ≥ 200 cho EMA-200) |
| Advanced | `n1d` | 20 | `max_distance_candles` riêng cho 1D |
| Advanced | `m1h` | 3 | `max_distance_candles` riêng cho 1H |

> Cấu hình proven **+710% theo backtest** của tác giả gốc: `use_ema_filter=true` + `min_gap=3.0`. Mặc định form mở ở config trung tính.

### Mẫu Telegram alert

```
🚨 SHORT signal — BTC/USDT (binance)
TF: 1H | Time: 2026-05-30 14:00 UTC

RSI: 72.4 | EMA RSI 20: 58.2
Entry: $42150
SL:    $44257.5  (5%)
TP1:   $37935    (10%)
TP2:   $33720    (20%)

Reason: 1D bars=4.0, 1H bars=1.0 (1W filter ✓)
Process: "EMARSI1" by admin
```

---

## 2. EmaRsiReversalSimple — phiên bản pattern-only của EmaRsiReversal

### Ý nghĩa

Cùng triết lý với `EmaRsiReversal` (3 đường EMA của RSI xếp giảm dần = momentum đang yếu), nhưng đơn giản hơn về tham số và yêu cầu **cả 3 khung 1W + 1D + 1H đồng thuận** chứ không chỉ 2. Chỉ phát SHORT.

### Logic

**Trên mỗi khung trong 3 khung** (1W, 1D, 1H), nến mới nhất `[-1]` phải thỏa:

1. `ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20` (đường EMA-RSI xếp giảm dần — momentum yếu đi)
2. `bars_since_not_desc < max_distance` — khoảng cách từ nến gần nhất mà 3 đường KHÔNG xếp như trên đến nến hiện tại phải < `max_distance` (default 10). Điều kiện này đảm bảo pattern **vừa mới hình thành**, không phải đã ở trạng thái này quá lâu (giảm rủi ro fire muộn).

**Riêng 1H — level guard**: `ema_rsi_5 > min_ema_rsi_5` (default 40). Tránh fire khi RSI đã quá thấp (đã bị bán mạnh trước đó, kèo SHORT muộn).

**Thứ tự fetch**: 1W → 1D → 1H. Nếu 1W không thỏa → bail trước khi fetch 1D/1H, tiết kiệm API call.

### Tham số

| Group | Tên | Default | Ghi chú |
|---|---|---|---|
| Basic | `rsi_period` | 14 | Period của RSI |
| Basic | `max_distance` | 10 | Số nến tối đa kể từ lần gần nhất pattern bị phá vỡ (áp cho cả 3 TF) |
| Basic | `min_ema_rsi_5` | 40.0 | Ngưỡng `ema_rsi_5` (chỉ áp cho 1H) |
| Advanced | `sl_pct` | 0.05 | Stop loss % (display Telegram) |
| Advanced | `tp1_pct` | 0.10 | Take profit 1 |
| Advanced | `tp2_pct` | 0.20 | Take profit 2 |
| Advanced | `lookback` | 250 | Số nến fetch cho 1H/1D (1W dùng 30) |

### Mẫu Telegram alert

```
🚨 SHORT signal — BTC/USDT (binance)
TF: 1H | Time: 2026-05-30 14:00 UTC

EMA-RSI 5/10/20 (1H): 52.3 / 56.1 / 61.8
Entry: $42150
SL:    $44257.5  (5%)
TP1:   $37935    (10%)
TP2:   $33720    (20%)

Reason: 3 EMA-RSI vừa xếp giảm trên cả 1W (2.0), 1D (3.0), 1H (1.0) nến
Process: "EMARSISimple1" by admin
```

---

## 3. VolumeBreakout — đảo chiều khi vol bùng nổ

### Ý nghĩa

Volume nổ kết hợp giá pump/dump cực mạnh thường là **dấu hiệu kiệt sức**: bên thắng đã "đốt" hết sức trong 1 nến, mean-reversion là kèo đi sau đó. **Đây là tín hiệu ĐẢO CHIỀU**, không phải breakout-continuation:

- Vol spike + giá vọt LÊN → kỳ vọng đảo xuống → emit **SHORT**
- Vol spike + giá lao XUỐNG → kỳ vọng đảo lên → emit **LONG**

Cả 2 TF (1D + 1H) phải fire **cùng hướng** mới chốt signal — tránh trường hợp 1D đang pump nhưng 1H đã quay đầu.

### Logic

**Nến tín hiệu**:
- **1D**: nến `[-2]` (nến đã đóng, ngay trước nến hiện tại). Lý do: nến 1D hiện tại đang form dở, vol/close chưa final.
- **1H**: nến `[-1]` (nến hiện tại). Lý do: 1H đóng nhanh, cần tín hiệu tươi.

**Indicator** (mỗi khung):
- `vol_sma = SMA(volume, vol_lookback).shift(1)` — trung bình vol của N nến **trước** nến tín hiệu (`.shift(1)` để loại nến hiện tại ra khỏi SMA)
- `close_sma = SMA(close, price_lookback).shift(1)` — tương tự cho giá
- `vol_ratio = volume / vol_sma`
- `price_ratio = close / close_sma`

**Trigger trên 1 khung** (ngưỡng `vol_mult` và `price_pct` lấy theo TF tương ứng — `_1d` cho 1D, `_1h` cho 1H):
- **SHORT** khi `vol_ratio > vol_mult` AND `price_ratio > 1 + price_pct` (giá pump quá ngưỡng + vol bùng → đảo xuống)
- **LONG** khi `vol_ratio > vol_mult` AND `price_ratio < 1 - price_pct` (giá dump quá ngưỡng + vol bùng → đảo lên)

**Trigger tổng**: `sign(1D[-2].signal) == sign(1H[-1].signal) != 0`. Phải cùng hướng (LONG+LONG hoặc SHORT+SHORT), không cho phép trộn.

### Tham số

Mỗi TF có ngưỡng vol/price riêng để tuning độc lập (vd 1D đòi spike mạnh hơn 1H). `sma_lookback` chỉ có 1 — dùng chung cho cả vol và price, cả 2 TF.

| Group | Tên | Default | Ghi chú |
|---|---|---|---|
| Basic | `sma_lookback` | 10 | Số nến tính SMA — **dùng chung** cho vol & price, cả 1D & 1H |
| Basic | `vol_mult_1d` | 3.0 | Ngưỡng `vol_ratio` cho **1D** (3 = vol ≥ 3× SMA) |
| Basic | `vol_mult_1h` | 3.0 | Ngưỡng `vol_ratio` cho **1H** |
| Basic | `price_pct_1d` | 0.30 | Ngưỡng độ lệch giá cho **1D** (0.30 = ±30%) |
| Basic | `price_pct_1h` | 0.30 | Ngưỡng độ lệch giá cho **1H** |
| Advanced | `sl_pct` | 0.05 | Stop loss display Telegram (5%) |
| Advanced | `tp1_pct` | 0.10 | Take profit 1 (10%) |
| Advanced | `tp2_pct` | 0.20 | Take profit 2 (20%) |
| Advanced | `lookback` | 50 | Số nến fetch mỗi TF (≥ `sma_lookback` + buffer) |

> SL/TP đảo chiều giữa LONG và SHORT:
> - LONG: SL = `close × (1 - sl_pct)` (dưới entry), TP = `close × (1 + tp_pct)` (trên entry)
> - SHORT: SL = `close × (1 + sl_pct)` (trên entry), TP = `close × (1 - tp_pct)` (dưới entry)

### Mẫu Telegram alert

**LONG** (dump → kỳ vọng đảo lên):

```
🟢 LONG signal — DOGE/USDT (binance)
TF: 1H | Time: 2026-05-30 14:00 UTC

Vol×: 1H 5.42, 1D 4.10
Price×: 1H 0.612, 1D 0.580
Entry: $0.085
SL:    $0.08075  (5%)
TP1:   $0.0935   (10%)
TP2:   $0.102    (20%)

Reason: bùng vol → kỳ vọng đảo chiều (1D & 1H xác nhận)
Process: "VolumeBreakout1" by admin
```

**SHORT** (pump → kỳ vọng đảo xuống):

```
🔴 SHORT signal — PEPE/USDT (binance)
TF: 1H | Time: 2026-05-30 14:00 UTC

Vol×: 1H 8.20, 1D 6.55
Price×: 1H 1.450, 1D 1.380
Entry: $0.0000142
SL:    $0.0000149  (5%)
TP1:   $0.0000128  (10%)
TP2:   $0.0000114  (20%)

Reason: bùng vol → kỳ vọng đảo chiều (1D & 1H xác nhận)
Process: "VolumeBreakout1" by admin
```

---

## So sánh

| Tiêu chí | EmaRsiReversal | EmaRsiReversalSimple | VolumeBreakout |
|---|---|---|---|
| Khung | 1W (filter) + 1D + 1H | 1W + 1D + 1H (cùng cấp) | 1D + 1H |
| Hướng | Chỉ SHORT | Chỉ SHORT | LONG + SHORT |
| Số param basic | 6 | 3 | 5 (per-TF) |
| Số nến tối thiểu | 200 (EMA-200) | 30 (EMA-20 của RSI) | 30 (SMA-10 + buffer) |
| Lookback default | 250 | 250 | 50 |
| Tốc độ scan | Chậm (cần EMA-200 + 3 TF) | Trung bình (3 TF nhưng EMA nhẹ hơn) | Nhanh (SMA-10) |
| Trigger trên | Pattern EMA-RSI suy yếu kéo dài + filter 1W | Pattern EMA-RSI vừa mới đảo trên cả 3 TF | Nến "bùng nổ" duy nhất (vol × giá) |
| Loại tín hiệu | Trend-following (theo đà giảm) | Trend-confirmation (đa khung) | Mean-reversion (chống xu hướng) |
| Tần suất fire | Trung bình | Hiếm (cần cả 3 TF cùng đảo trong 10 nến) | Hiếm (cần spike rất mạnh) |

---

## Quy trình thêm strategy thứ 3+

Sau refactor [strategies/__init__.py](../strategies/__init__.py) + [worker/strategy_handlers/](../worker/strategy_handlers/) + [web/schemas/strategy_params.py](../web/schemas/strategy_params.py), việc thêm strategy mới gói gọn 4 bước:

1. **Class strategy**: tạo `strategies/<name>_strategy.py` kế thừa `BaseStrategy`, implement `compute_indicators` / `generate_signals` / `get_sl_tp`.
2. **Pydantic model + descriptor**: thêm 2 entry vào `web/schemas/strategy_params.py` — 1 class params, 1 entry trong `STRATEGY_REGISTRY` (gồm `params_model`, `basic_fields`, `advanced_fields`, `tf_high`, `tf_low`, `label`, `handler_module`).
3. **Handler**: tạo `worker/strategy_handlers/<name>.py` export 3 hàm `build(params)`, `scan(strat_high, strat_low, exchange, symbol, params)`, `format_alert(sig, cfg, username)`.
4. **Test**: thêm unit test trong `tests/test_<name>_strategy.py`; `tests/test_strategy_registry.py` đã parametrize tự cover mọi entry trong registry.

**Không cần sửa** [worker/runner.py](../worker/runner.py), [web/routes/processes.py](../web/routes/processes.py), [web/templates/processes/form.html](../web/templates/processes/form.html). Dispatch hoàn toàn qua descriptor.

---

## Liên quan

- [getting-started.md](./getting-started.md) — overview kiến trúc 5 phase.
- [scripts.md](./scripts.md) — quản lý worker + web service.
- [CLAUDE.md](../CLAUDE.md) — quy ước code + cảnh báo về trading code.
- [config/strategies/](../config/strategies/) — YAML config từng strategy cho CLI runner (không liên quan đến process trên Web UI; UI dùng `strategy_params` JSON trong DB).
