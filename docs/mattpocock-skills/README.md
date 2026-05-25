# Matt Pocock Skills — Giới thiệu & Hướng dẫn sử dụng

> **Nguồn**: [mattpocock/skills](https://github.com/mattpocock/skills) (MIT-licensed)
> **Cài đặt tại**: [`.claude/skills/`](../../.claude/skills/) (mirror tại [`.agents/skills/`](../../.agents/skills/)) — 13 skill đã được cài sẵn cho repo `TradingBot`. Khoá tại [`skills-lock.json`](../../skills-lock.json).
>
> Đây là bộ "agent skill" do Matt Pocock biên soạn, biến những **thói quen tốt khi làm việc với LLM coding** (think before coding, TDD, surgical changes, …) thành những **shortcut có thể gọi bằng `/<skill-name>`** trong Claude Code.

---

## Skill là gì?

Một skill là một bộ hướng dẫn (`SKILL.md`) Claude Code load vào prompt khi bạn gọi `/<skill-name>`. Nó thay đổi **cách Claude tư duy và phản hồi** trong session đó — ví dụ:

- `/grill-me` → Claude chuyển sang **chế độ phỏng vấn**, đặt câu hỏi đào sâu thay vì code ngay.
- `/tdd` → Claude **bắt buộc viết test trước**, không cho phép skip qua red-green-refactor.
- `/caveman` → Claude **cắt 75% token** mỗi câu trả lời.

Skill khác với prompt thông thường ở chỗ nó **persistent trong session** và có thể bundle thêm resource (template, checklist, script).

---

## Cách gọi skill

Trong Claude Code, gõ:

```
/<skill-name>
```

Ví dụ:

```
/grill-with-docs
/tdd
/diagnose
```

Sau khi gõ, Claude sẽ load `SKILL.md` của skill đó và tuân thủ theo. Có thể tham số:

```
/loop 10m /to-issues
```

(chạy `/to-issues` lặp mỗi 10 phút)

---

## Tổng quan 13 skill đã cài

> Phân nhóm theo **giai đoạn làm việc**:

### 🧠 Trước khi code — "Think Before Coding"

| Skill | Khi nào dùng |
|---|---|
| [`/grill-me`](#grill-me) | Stress-test 1 plan/design. Claude đóng vai interviewer, đặt câu hỏi đến khi mọi nhánh quyết định được giải quyết |
| [`/grill-with-docs`](#grill-with-docs) | Như `/grill-me` nhưng đối chiếu với `CONTEXT.md` + ADR của project; cập nhật docs inline |
| [`/zoom-out`](#zoom-out) | Yêu cầu Claude giải thích 1 file/module trong **bối cảnh hệ thống lớn hơn** trước khi đụng vào |
| [`/to-prd`](#to-prd) | Biến cuộc thảo luận hiện tại thành 1 **PRD** (Product Requirements Doc) và lưu vào issue tracker |
| [`/to-issues`](#to-issues) | Bẻ 1 plan/PRD thành nhiều **issue dọc (vertical slice)** độc lập, có thể giao cho từng session/agent xử lý |

### ⌨️ Trong khi code — "Simplicity First" + "Goal-Driven Execution"

| Skill | Khi nào dùng |
|---|---|
| [`/tdd`](#tdd) | Bắt buộc **red → green → refactor**. Cho mỗi feature mới hoặc bug fix |
| [`/diagnose`](#diagnose) | Bug khó / regression hiệu năng. Loop: reproduce → minimise → hypothesise → instrument → fix → regression-test |
| [`/prototype`](#prototype) | Thử nghiệm 1 thiết kế **chưa chắc chắn** — build prototype throw-away (CLI app hoặc UI variants) trước khi commit |

### 🧹 Sau khi code — "Surgical Changes"

| Skill | Khi nào dùng |
|---|---|
| [`/improve-codebase-architecture`](#improve-codebase-architecture) | Tìm cơ hội refactor / deepen architecture, có tham chiếu `CONTEXT.md` + ADR. Chạy **định kỳ vài ngày 1 lần** |

### 🔧 Workflow helper (không gắn với giai đoạn nào)

| Skill | Khi nào dùng |
|---|---|
| [`/caveman`](#caveman) | Bật chế độ siêu nén — Claude trả lời cụt lủn, cắt ~75% token. Tiết kiệm context + tiền |
| [`/handoff`](#handoff) | Cuối session — compact toàn bộ conversation thành 1 handoff doc cho session/agent kế tiếp |
| [`/write-a-skill`](#write-a-skill) | Khi bạn lặp lại cùng 1 workflow ≥ 3 lần → biến nó thành skill mới |

### ⚙️ Setup (1 lần / repo)

| Skill | Khi nào dùng |
|---|---|
| [`/setup-matt-pocock-skills`](#setup-matt-pocock-skills) | Chạy **1 lần duy nhất** khi mới mở repo. Cấu hình issue tracker, triage label, vị trí lưu docs/ADRs |

---

## Chi tiết từng skill

### `/caveman`

**Mode**: Ultra-compressed communication.

**Hiệu ứng**: Cắt ~75% token mỗi response.

- Bỏ: articles (a/an/the), filler (just/really/basically), hedging, pleasantries (sure/certainly).
- Pattern: `[thing] [action] [reason]. [next step].`
- Code block + error message giữ nguyên.
- Tự **tắt tạm** khi cần cảnh báo destructive op hoặc clarify yêu cầu.

**Ví dụ**:

```
> Why React component re-render?
< Inline obj prop -> new ref -> re-render. `useMemo`.
```

**Bật**: `/caveman` hoặc nói "caveman mode", "be brief", "less tokens".
**Tắt**: nói "stop caveman" hoặc "normal mode".

---

### `/diagnose`

**Khi dùng**: bug khó / "tự dưng chậm" / "code chạy nhưng output sai".

**Loop bắt buộc**:

1. **Reproduce** — viết test/command tái hiện lỗi 100%.
2. **Minimise** — cắt bỏ mọi yếu tố không cần đến khi vẫn còn lỗi.
3. **Hypothesise** — đoán nguyên nhân *gốc*, không patch triệu chứng.
4. **Instrument** — thêm log/print để confirm/refute hypothesis.
5. **Fix** — sửa nhỏ nhất có thể.
6. **Regression test** — viết test bảo vệ, đảm bảo bug không quay lại.

**Ví dụ trigger**: "paper trade không khớp backtest cùng config", "indicator EMA RSI ra giá trị lệch sau khi update pandas-ta", "backtest tự dưng chạy chậm gấp 3".

---

### `/grill-me`

**Khi dùng**: Bạn có 1 plan nhưng chưa chắc nó vững. Muốn Claude **thẩm vấn** đến khi mọi nhánh quyết định được giải đáp.

**Claude sẽ**:
- Hỏi từng câu hỏi đào sâu (không nhiều câu cùng lúc).
- Chỉ chuyển sang câu tiếp khi câu trước có câu trả lời rõ.
- Không code, không implement — chỉ phỏng vấn.
- Kết thúc khi cây quyết định không còn nhánh mơ hồ.

**Trigger**: "grill me on this plan", "stress test design".

> 🚀 **Đây là skill quan trọng nhất**. Workspace `CLAUDE.md` (mục Karpathy) khuyên dùng *mỗi lần* trước khi viết code không tầm thường.

---

### `/grill-with-docs`

**Khi dùng**: Như `/grill-me` nhưng:
- Đối chiếu plan với `CONTEXT.md` (domain language) của project.
- Đối chiếu với ADR trong `docs/adr/`.
- **Cập nhật trực tiếp** `CONTEXT.md` hoặc tạo ADR mới nếu quyết định mới làm thay đổi domain language.

**Lý do tồn tại**: tránh tình trạng plan mới dùng từ ngữ mâu thuẫn với mô hình domain hiện có.

**Trigger**: "grill with docs", "stress test against context", hoặc bất kỳ lúc nào thay đổi đụng vào kiến trúc / domain hiện hành.

> Trong repo này, domain language nằm trong [`CONTEXT.md`](../../CONTEXT.md). Ví dụ đã phân biệt rõ **Signal** (tín hiệu trong DataFrame, chưa execute) vs **Trade** (vị thế đã mở), **Backtest** vs **Paper Trading** vs **Live Trading** — nếu PR mới dùng "bot" mà không clarify (signal bot? paper bot? live bot?), `/grill-with-docs` sẽ chặn lại.

---

### `/handoff`

**Khi dùng**: Cuối 1 session dài (sắp tắt máy, sắp đi họp, context window gần đầy).

**Claude sẽ**:
- Compact toàn bộ conversation thành 1 file markdown.
- Bao gồm: mục tiêu, đã làm gì, đã quyết gì, còn lại gì, file/file:line liên quan.
- Lưu vào nơi quy ước (thường `.scratch/` hoặc `docs/handoffs/`).

**Lợi ích**: session/agent kế tiếp đọc handoff doc là pick up được ngay, không phải đọc lại 200 message.

**Trigger**: `/handoff` hoặc "compact this conversation".

---

### `/improve-codebase-architecture`

**Khi dùng**: Định kỳ, không phải khi đã rotten.

**Claude sẽ**:
- Đọc `CONTEXT.md` + ADR.
- Quét codebase tìm:
  - Module ghép cứng có thể tách (tightly-coupled).
  - Code không testable (hard-to-mock dependency).
  - Nơi nên có abstraction nhưng chưa có.
  - Trùng lặp có thể consolidate.
- Trả về **danh sách cơ hội refactor**, không tự refactor.

**Repo `CLAUDE.md` khuyến nghị**: chạy **vài ngày 1 lần** khi đang active phát triển. Không đợi tới khi codebase đã rotten.

**Trigger**: `/improve-codebase-architecture`, "find refactor opportunities", "deepen architecture".

---

### `/prototype`

**Khi dùng**: Bạn chưa biết hình thù đúng của 1 feature là gì.

**2 nhánh tự động chọn**:

1. **State / business logic chưa rõ** → build 1 **CLI app chạy được**, người dùng nhập input thấy output ngay.
2. **UI chưa rõ** → tạo nhiều **variant UI** toggleable từ 1 route, người dùng so sánh trực quan.

**Đặc trưng**: code throw-away, không commit thật. Mục tiêu là "play with it" để chốt design.

**Ví dụ trong repo**: "thử 1 filter mới cho SonicR trước khi commit vào YAML", "prototype 3 mô hình SL/TP khác nhau và so sánh Win Rate", "thử 1 indicator mới qua CLI ăn DataFrame".

**Trigger**: `/prototype`, "let me play with it", "try a few designs".

---

### `/setup-matt-pocock-skills`

**Khi dùng**: **1 lần duy nhất** khi clone repo mới về.

**Claude sẽ hỏi & cấu hình**:
- Issue tracker: file markdown local? GitHub Issues? Linear?
- Triage label vocabulary: dùng default (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`)?
- Vị trí lưu docs/ADRs (`docs/adr/`?).

→ Tạo `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `docs/agents/domain.md`.

> Trong repo `TradingBot` chưa chạy — `docs/agents/` chưa tồn tại. Chạy `/setup-matt-pocock-skills` 1 lần để khởi tạo.

---

### `/tdd`

**Khi dùng**: Mỗi feature mới hoặc bug fix.

**Loop bắt buộc — red → green → refactor**:

1. **Red** — viết test **trước**, chạy thấy fail.
2. **Green** — viết **code tối thiểu** để test pass. Không over-engineer.
3. **Refactor** — chỉ khi test xanh, dọn dẹp code (DRY, naming, …). Test vẫn phải pass sau refactor.

**Bug fix workflow**:
1. Viết test reproduce bug → đỏ.
2. Fix → xanh.
3. Refactor.

**Trigger**: `/tdd`, "use TDD", "red-green-refactor".

> 🚀 Repo `CLAUDE.md` ghi rõ: "If you only remember two skills, use **`/grill-with-docs`** before coding and **`/tdd`** while coding." Đặc biệt cần cho indicator/signal code — bug trong logic này có thể làm mất tiền thật ở phase Live.

---

### `/to-issues`

**Khi dùng**: Có 1 plan/PRD lớn, muốn bẻ thành **nhiều issue nhỏ, độc lập** có thể giao cho từng session/người làm.

**Nguyên tắc**: **vertical slice (tracer bullet)** — mỗi issue đi xuyên tất cả các layer (UI → API → DB) chứ không phải 1 issue/lớp. Lý do: mỗi issue release được giá trị nhỏ, ngay lập tức.

**Claude sẽ**:
- Đọc plan/PRD.
- Xác định slice dọc.
- Tạo từng issue trong issue tracker (file md hoặc GitHub Issues — tuỳ setup).
- Mỗi issue: title + summary + acceptance criteria.

**Trigger**: `/to-issues`, "break this into issues", "create implementation tickets".

---

### `/to-prd`

**Khi dùng**: Sau 1 cuộc thảo luận dài, muốn **chốt và lưu thành tài liệu**.

**Claude sẽ**:
- Đọc toàn bộ context thảo luận.
- Tổng hợp thành PRD: motivation, scope, non-goals, success criteria, decisions.
- Lưu vào issue tracker theo setup.

**Trigger**: `/to-prd`, "create PRD from this", "write down what we just decided".

---

### `/write-a-skill`

**Khi dùng**: Bạn nhận ra mình lặp lại cùng 1 workflow ≥ 3 lần → đã đến lúc biến nó thành skill.

**Claude sẽ**:
- Hỏi mục tiêu của skill, trigger, hành vi mong muốn.
- Tạo folder `.claude/skills/<name>/SKILL.md` với frontmatter chuẩn.
- Bundle thêm resource nếu cần (template, script, checklist).
- Test mental model: skill có rõ trigger không? Có persistent không? Có exit-condition không?

**Ví dụ**: nếu bạn hay phải "download data → chạy backtest → so sánh với baseline → đọc HTML report", có thể wrap thành `/bt-smoke-test`. Hoặc nếu hay làm "thêm strategy → tạo YAML → đăng ký trong factory → viết test cơ bản", wrap thành `/new-strategy`.

**Trigger**: `/write-a-skill`, "create a new skill".

---

### `/zoom-out`

**Khi dùng**: Trước khi đụng vào 1 file/module bạn **chưa nắm rõ vị trí của nó trong hệ thống**.

**Claude sẽ**:
- Đọc file đó.
- Đọc file gọi đến nó.
- Đọc file nó gọi đến.
- Giải thích: file này là gì, ai dùng, dùng để làm gì, nếu thay đổi thì cái gì hỏng.

**Ví dụ trong repo**: "/zoom-out trên [`paper_trading/engine.py`](../../paper_trading/engine.py)" → Claude sẽ giải thích vị trí của Paper Engine giữa Strategy, TimescaleClient và PortfolioManager. Hoặc "/zoom-out trên [`backtest/trade_simulator.py`](../../backtest/trade_simulator.py)" trước khi đụng vào mô hình phí/slippage.

**Trigger**: `/zoom-out`, "explain this in context".

---

## Khi nào dùng skill nào — flow gợi ý

Repo `CLAUDE.md` đề xuất flow chuẩn cho 1 feature trong TradingBot (vd: thêm strategy mới, thêm filter, đổi mô hình SL/TP):

```
1. /grill-with-docs        → align về what + why, cập nhật CONTEXT.md nếu cần
2. /to-prd                 → ghi lại agreement
3. /to-issues              → bẻ thành vertical slices
4. Với mỗi slice:
   /tdd                    → red → green → refactor (đặc biệt với indicator/signal logic)
5. Định kỳ:
   /improve-codebase-architecture  → keep entropy in check
```

Trong session đặc biệt:
- Bug khó: `/diagnose`
- Không hiểu module: `/zoom-out` trước
- Chưa chắc design: `/prototype` thay vì cãi nhau trên giấy
- Hết phiên: `/handoff`
- Token đắt / cần gọn: `/caveman`

---

## Mapping với 4 nguyên tắc Karpathy

Repo `CLAUDE.md` chốt 4 nguyên tắc Karpathy. Đây là cặp đôi giữa nguyên tắc và skill thực thi:

| Karpathy principle | Skill thực thi |
|---|---|
| 1. **Think Before Coding** | `/grill-me`, `/grill-with-docs`, `/zoom-out` |
| 2. **Simplicity First** | `/prototype` (throwaway trước khi commit) |
| 3. **Surgical Changes** | `/improve-codebase-architecture`, `/zoom-out` |
| 4. **Goal-Driven Execution** | `/tdd`, `/diagnose` (verifiable loop) |

> Nếu chỉ nhớ 2: **`/grill-with-docs`** trước khi code và **`/tdd`** trong khi code.

---

## Cấu trúc file skill

Mỗi skill là 1 folder trong `.claude/skills/` chứa **ít nhất** 1 file `SKILL.md`:

```yaml
---
name: skill-name
description: >
  Mô tả ngắn skill làm gì + khi nào dùng + alias trigger.
  Càng cụ thể càng dễ Claude tự pick.
---

# Nội dung markdown:
- Quy tắc skill
- Persistence (skill còn active đến khi nào?)
- Exit condition
- Examples
```

Có thể thêm:
- `templates/` — file mẫu skill sinh ra.
- `scripts/` — script đi kèm.
- `checklists/` — checklist Claude phải tick qua.

Xem ví dụ ngắn nhất: [`.claude/skills/caveman/SKILL.md`](../../.claude/skills/caveman/SKILL.md).

---

## Tham khảo

- Repo gốc: https://github.com/mattpocock/skills
- Inspiration cho rules: [Karpathy on LLM coding pitfalls](https://x.com/karpathy/status/2015883857489522876)
- Repo conventions: [`CLAUDE.md`](../../CLAUDE.md) — phần "Available skills (Matt Pocock)"
- Domain language: [`CONTEXT.md`](../../CONTEXT.md)
- Skill folder: [`.claude/skills/`](../../.claude/skills/) (mirror: [`.agents/skills/`](../../.agents/skills/))
- Cách tạo skill mới: chạy `/write-a-skill`
