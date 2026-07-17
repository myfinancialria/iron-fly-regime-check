"""Iron-fly regime check — two-stage go/no-go filter for a short-premium
ATM iron-fly on NIFTY, driven by live Upstox data.

Stage 1 (pre-market, 08:45–09:10): Green / Amber / Red regime verdict.
Stage 2 (09:20, after the first 5-min candle): the entry decision.

The strategy must *earn the right to trade*: first eliminate incompatible
regimes, only then deploy the structure. See README.md for the full rule book.
"""

__version__ = "0.1.0"
