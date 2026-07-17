# NIFTY Iron-Fly Regime Check

A **two-stage go / no-go filter** that answers one question each morning:

> *Is today sufficiently neutral for a short-premium ATM iron-fly on NIFTY?*

The strategy has to **earn the right to trade**. The premise (from the design
brief) is that losses are dominated by a small number of directional days, so the
filter's whole job is to eliminate incompatible regimes *before* strikes, stops and
exits are ever optimised. It never tries to predict direction — only to detect when
the day is too directional to sell premium into.

- **Stage 1 — pre-market** (run 08:45–09:10 IST): `GREEN` / `AMBER` / `RED`.
- **Stage 2 — 09:20 confirmation** (after the 09:15–09:20 candle closes): the entry
  decision `STANDARD_ENTRY` / `HALF_RISK_ENTRY` / `WAIT_0930` / `SKIP`.

Data comes from the **Upstox v2 API** (NIFTY / BANKNIFTY / India VIX + NIFTY-50
breadth) plus a **GIFT NIFTY** pre-market indication for the expected-gap filter.
The check writes `site/signal.json`, which the static dashboard in `site/` renders —
served free on **GitHub Pages**.

> ⚠️ **Educational / paper-trading tool. Not investment advice.** It reads data and
> emits a verdict; it never places orders.

---

## The rule book (what the check encodes)

### Stage 1 — pre-market scorecard (6 points)

| Condition | Point when |
|---|---|
| No major scheduled event | not an RBI/Budget/election/expiry day |
| Expected gap < 0.40% | `\|GIFT − prev close\| / prev close × 100` |
| India VIX 11–18 | absolute level in band |
| VIX 1-day change < +5% | sudden expansion matters more than the level |
| Prev day not a trend-extreme | `range/ATR20 ≤ 1.20` **or** close not at an extreme |
| Daily structure neutral | price within ~1% of the 20-EMA |

`score ≥ 5 → GREEN`, `= 4 → AMBER`, `≤ 3 → RED`. **Hard-red overrides** (force RED
regardless of score): a scheduled event, NIFTY expiry day, expected gap > 0.70%,
VIX > 21, or VIX 1-day change > +10%.

### Stage 2 — 09:20 scorecard (8 points)

| Condition | Point when |
|---|---|
| Actual gap < 0.35% | from the real 09:15 open |
| OR5 ratio 0.10–0.30 | first-candle range ÷ ATR20 (ATR-normalised, not fixed points) |
| Candle body < 0.45 | `\|close−open\| / range` — long body ⇒ directional |
| Close 25–75% of range | not closing at an extreme |
| VWAP distance < 0.10% | price not already stretched from VWAP |
| Price inside prev-day range | no sustained break of prev high/low |
| No strong NIFTY–BANKNIFTY alignment | broad participation ⇒ trend day |
| Breadth 18–32 advancing | of NIFTY-50; extreme breadth ⇒ skip |

`GREEN premarket + 7–8 → STANDARD_ENTRY`, `6 → HALF_RISK_ENTRY`,
`4–5 → WAIT_0930`, `≤ 3 → SKIP`. An `AMBER` pre-market caps the day at half risk.
**Hard-red at 09:20** (force SKIP): actual gap > 0.60%, OR5 ratio > 0.40, body > 0.75,
a confirmed prev-day breakout, strong NIFTY+BANKNIFTY move, or VIX +10% intraday.

### Structure & sizing (from the same brief)

Risk is defined **from capital, never from lots** (default ₹20 lakh):

| Grade | Day | Structure | Planned risk |
|---|---|---|---|
| A | GREEN + 7–8 | Standard defined-risk iron fly (sell ATM CE/PE, buy OTM hedges; hedge width ≈ 0.75–1.0× the ATM straddle premium) | 0.40% (₹8,000) |
| B | AMBER / score 6 | Half-size iron fly **or** 15–20Δ iron condor | 0.20% (₹4,000) |
| C | score 4–5 | No 09:20 entry; reassess at 09:30 or skip | — |

Absolute daily stop: 0.50% (₹10,000). Lots = `floor(permitted risk ÷ est. loss per
lot at strategy stop)` — never up-sized just because margin is available.

Thresholds live in [`ironfly_check/config.py`](ironfly_check/config.py) and trace
one-to-one to this table.

---

## Data sources & honest limitations

| Input | Source | Notes |
|---|---|---|
| Prev-day OHLC, ATR20, EMA5/EMA20 | Upstox daily candles | solid |
| India VIX level + 1-day change | Upstox `market-quote/quotes` | solid |
| 09:15–09:20 candle, VWAP | Upstox intraday 1-min candles | VWAP on the index has no volume, so it falls back to a typical-price mean — at 09:20 (one candle) VWAP-distance is near-zero by design |
| NIFTY-50 breadth | Upstox quotes over 50 constituents (keys resolved from Upstox's instrument master, cached daily) | degrades to "unavailable" if the master can't be fetched; that scorecard point is then skipped |
| **GIFT NIFTY** (expected gap) | **scrape + manual override** | Upstox does **not** carry GIFT NIFTY; public levels are JS-rendered and fragile to scrape. **Set `IFC_GIFT_NIFTY` each morning** for a reliable expected-gap point. If unavailable, the day is scored on the actual 09:20 gap alone (one pre-market point unscored). |
| Scheduled events / expiry | `config.SCHEDULED_EVENTS` + `EXPIRY_WEEKDAY` | maintain from RBI/exchange circulars |

Any missing input degrades gracefully (the condition is marked "couldn't evaluate"
and simply doesn't earn its point) rather than crashing the check.

---

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env        # fill UPSTOX_API_KEY / SECRET / REDIRECT_URI

# One-time-per-day Upstox token (tokens expire ~03:30 IST):
python -m ironfly_check login url          # prints the authorize URL
python -m ironfly_check login "<redirect-url-you-land-on>"

# Optional: paste today's GIFT NIFTY level for the expected-gap filter
echo "IFC_GIFT_NIFTY=24040" >> .env

python -m ironfly_check selftest           # offline logic check (no network)
python -m ironfly_check premarket          # Stage 1 (08:45–09:10 IST)
python -m ironfly_check confirm            # Stage 2 (after 09:20 IST)
python -m ironfly_check show               # print the latest signal.json
```

Each run writes `site/signal.json` (published) and archives `data/signal_<date>.json`.

### Local preview of the site

```bash
cd site && python -m http.server 8000     # open http://localhost:8000
```

---

## Deployment (Oracle VM cron → GitHub Pages)

The check needs the daily Upstox token, so it runs where the token lives (the same
Always-Free VM that hosts the paper-trader), commits the refreshed `signal.json`, and
GitHub Pages serves the dashboard.

```bash
# on the VM
git clone git@github.com:myfinancialria/iron-fly-regime-check.git
cd iron-fly-regime-check && pip install -r requirements.txt && cp .env.example .env
# fill .env, then:
crontab -e   # paste deploy/crontab.example (08:50 premarket, 09:21 confirm)
```

`deploy/run_check.sh <stage>` runs the stage and pushes only when the signal
changes. See [`deploy/crontab.example`](deploy/crontab.example). The token still
needs a daily refresh before 08:50 (Upstox has no headless login).

---

## Layout

```
ironfly_check/
  config.py         all thresholds, capital, event calendar, expiry weekday
  calendar.py       NSE holidays / trading-day / expiry-day helpers
  upstox_client.py  live client: daily+intraday candles, quotes, LTP
  giftnifty.py      GIFT NIFTY resolver (override → scrape → unavailable)
  constituents.py   NIFTY-50 symbols → Upstox keys (via instrument master)
  indicators.py     ATR, EMA, VWAP, body/close-location ratios (pure)
  data.py           fetch + assemble PremarketData / OpeningData snapshots
  stage1.py         pre-market scorecard  → GREEN/AMBER/RED
  stage2.py         09:20 scorecard       → STANDARD/HALF/WAIT/SKIP
  signal.py         combine + structure + sizing → signal.json
  selftest.py       offline scenario tests
  cli.py            login / premarket / confirm / selftest / show
site/
  index.html        static dashboard (fetches signal.json; theme-aware)
  signal.json       latest published signal
deploy/
  run_check.sh      run a stage + commit/push the signal
  crontab.example   VM schedule
```

---

*Rule book derived from the two-stage iron-fly design brief. Numbers are starting
points to be validated by backtest — do not treat any threshold as final.*
