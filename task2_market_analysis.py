"""
Task 2 — Exploratory Analysis of Market and Order Patterns
===========================================================
Goal: Identify the TOP 10 most suspicious markets by combining
      market_daily_snapshots.csv, orders.csv, and trades.csv.

Run from the project root folder:
    python task2_market_analysis.py

Outputs go to: output/task2/
"""

from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # no GUI needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ─────────────────────────────────────────────
# 0.  Setup paths
# ─────────────────────────────────────────────
ROOT     = Path(__file__).resolve().parent
DATA_DIR = ROOT / "polymarket_fraud_seminar_student"
OUT_DIR  = ROOT / "output" / "task2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("TASK 2 — Market & Order Pattern Analysis")
print("=" * 60)

# ─────────────────────────────────────────────
# 1.  Load the three key tables
# ─────────────────────────────────────────────
print("\n[1] Loading data...")

snapshots = pd.read_csv(
    DATA_DIR / "market_daily_snapshots.csv",
    parse_dates=["trade_date"],
)

orders = pd.read_csv(
    DATA_DIR / "orders.csv",
    parse_dates=["created_at", "updated_at"],
)

trades = pd.read_csv(
    DATA_DIR / "trades.csv",
    parse_dates=["trade_ts"],
)

markets = pd.read_csv(
    DATA_DIR / "markets.csv",
    parse_dates=["created_at", "close_time", "resolve_time"],
)

print(f"  snapshots : {len(snapshots):,} rows")
print(f"  orders    : {len(orders):,} rows")
print(f"  trades    : {len(trades):,} rows")
print(f"  markets   : {len(markets):,} rows")

# ─────────────────────────────────────────────
# 2.  Price time-series plot (one line per market)
# ─────────────────────────────────────────────
print("\n[2] Plotting price time-series per market...")

fig, ax = plt.subplots(figsize=(14, 6))
for mid, grp in snapshots.groupby("market_id"):
    grp_sorted = grp.sort_values("trade_date")
    ax.plot(grp_sorted["trade_date"], grp_sorted["last_price"],
            alpha=0.5, linewidth=0.9)

ax.set_title("Price time-series — all markets", fontsize=13)
ax.set_xlabel("Date")
ax.set_ylabel("Last price (YES token)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig(OUT_DIR / "fig1_price_timeseries_all_markets.png", dpi=150)
plt.close(fig)
print("  Saved: fig1_price_timeseries_all_markets.png")

# ─────────────────────────────────────────────
# 3.  Per-market aggregates from snapshots
# ─────────────────────────────────────────────
print("\n[3] Computing per-market aggregates from snapshots...")

snap_agg = snapshots.groupby("market_id").agg(
    price_start          = ("last_price",        "first"),
    price_end            = ("last_price",        "last"),
    price_change_abs     = ("price_change_bps_sum", "sum"),
    total_volume_usdc    = ("volume_usdc",        "sum"),
    total_trade_count    = ("trade_count",         "sum"),
    avg_unique_buyers    = ("unique_buyers",       "mean"),
    avg_unique_sellers   = ("unique_sellers",      "mean"),
    avg_spread_bps       = ("avg_spread_bps",      "mean"),
    days_active          = ("trade_date",          "count"),
).reset_index()

# absolute price movement over the whole period
snap_agg["price_move_bps"] = snap_agg["price_change_abs"].abs()

# low-breadth flag: average distinct buyers < 3
snap_agg["low_breadth"]    = (snap_agg["avg_unique_buyers"] < 3).astype(int)

print(snap_agg[["market_id","price_move_bps","avg_unique_buyers",
                "total_trade_count","avg_spread_bps"]].to_string(index=False))

# ─────────────────────────────────────────────
# 4.  Cancel rate per market (from orders)
# ─────────────────────────────────────────────
print("\n[4] Computing cancel rates per market...")

orders["is_canceled"] = (orders["status"] == "CANCELED").astype(int)
orders["fill_ratio"]  = (
    orders["matched_size_shares"] / orders["size_shares"].replace(0, pd.NA)
)

cancel_agg = orders.groupby("market_id").agg(
    total_orders   = ("order_id",    "count"),
    canceled_count = ("is_canceled", "sum"),
    mean_fill_ratio= ("fill_ratio",  "mean"),
    api_order_share= ("is_api_order","mean"),
).reset_index()

cancel_agg["cancel_rate"] = (
    cancel_agg["canceled_count"] / cancel_agg["total_orders"]
)

print(cancel_agg[["market_id","total_orders","cancel_rate",
                  "mean_fill_ratio","api_order_share"]].to_string(index=False))

# ─────────────────────────────────────────────
# 5.  Counterparty concentration per market
# ─────────────────────────────────────────────
print("\n[5] Analysing counterparty concentration...")

# Count distinct buyers and sellers per market from trades table
counterparty = trades.groupby("market_id").agg(
    distinct_buyers  = ("buyer_trader_id",  "nunique"),
    distinct_sellers = ("seller_trader_id", "nunique"),
    self_trade_count = ("is_self_trade_flag","sum"),
    total_trades     = ("trade_id",          "count"),
).reset_index()

counterparty["self_trade_rate"] = (
    counterparty["self_trade_count"] / counterparty["total_trades"]
)

# Top-counterparty concentration: share of volume with the single
# most common (buyer, seller) pair
pair_vol = (
    trades.groupby(["market_id","buyer_trader_id","seller_trader_id"])
    ["notional_usdc"].sum().reset_index()
)
market_vol = trades.groupby("market_id")["notional_usdc"].sum().reset_index()
market_vol.rename(columns={"notional_usdc": "market_total_vol"}, inplace=True)

top_pair = (
    pair_vol.sort_values("notional_usdc", ascending=False)
    .drop_duplicates("market_id")
    .rename(columns={"notional_usdc": "top_pair_vol"})
)
top_pair = top_pair.merge(market_vol, on="market_id")
top_pair["top_pair_share"] = top_pair["top_pair_vol"] / top_pair["market_total_vol"]
counterparty = counterparty.merge(
    top_pair[["market_id","top_pair_share"]], on="market_id", how="left"
)

print(counterparty[["market_id","distinct_buyers","distinct_sellers",
                     "self_trade_rate","top_pair_share"]].to_string(index=False))

# ─────────────────────────────────────────────
# 6.  Trades close to market close_time
# ─────────────────────────────────────────────
print("\n[6] Identifying aggressive late trades (within 60 min of close)...")

close_times = markets[["market_id","close_time"]].copy()
trades_close = trades.merge(close_times, on="market_id", how="left")
trades_close["mins_to_close"] = (
    (trades_close["close_time"] - trades_close["trade_ts"])
    .dt.total_seconds() / 60
)

late_trades = trades_close[
    (trades_close["mins_to_close"] >= 0) &
    (trades_close["mins_to_close"] <= 60)
]

late_agg = late_trades.groupby("market_id").agg(
    late_trade_count   = ("trade_id", "count"),
    late_volume_usdc   = ("notional_usdc", "sum"),
).reset_index()

total_trades_per_market = trades.groupby("market_id")["trade_id"].count().reset_index()
total_trades_per_market.rename(columns={"trade_id": "all_trade_count"}, inplace=True)
late_agg = late_agg.merge(total_trades_per_market, on="market_id", how="left")
late_agg["late_trade_share"] = (
    late_agg["late_trade_count"] / late_agg["all_trade_count"]
)

print(late_agg[["market_id","late_trade_count","late_trade_share"]].to_string(index=False))

# ─────────────────────────────────────────────
# 7.  Build the suspicion score
# ─────────────────────────────────────────────
print("\n[7] Building market suspicion score...")

# Merge all signal tables
score_df = (snap_agg
    .merge(cancel_agg[["market_id","cancel_rate","mean_fill_ratio","api_order_share"]],
           on="market_id", how="left")
    .merge(counterparty[["market_id","distinct_buyers","self_trade_rate","top_pair_share"]],
           on="market_id", how="left")
    .merge(late_agg[["market_id","late_trade_share"]],
           on="market_id", how="left")
)

# Normalise each signal to [0, 1]
def norm(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return series * 0.0
    return (series - mn) / (mx - mn)

# A high score means MORE suspicious
score_df["s_price_move"]     = norm(score_df["price_move_bps"])        # big price swing
score_df["s_low_breadth"]    = norm(1 / score_df["avg_unique_buyers"].replace(0, pd.NA))  # few buyers
score_df["s_cancel_rate"]    = norm(score_df["cancel_rate"])           # many cancels
score_df["s_low_fill"]       = norm(1 - score_df["mean_fill_ratio"].fillna(0))  # low fill ratio
score_df["s_self_trade"]     = norm(score_df["self_trade_rate"].fillna(0))      # self-trading
score_df["s_top_pair"]       = norm(score_df["top_pair_share"].fillna(0))       # concentrated counterparties
score_df["s_late_trade"]     = norm(score_df["late_trade_share"].fillna(0))     # late-hour trades
score_df["s_api"]            = norm(score_df["api_order_share"].fillna(0))      # API automation

# Weighted composite score (weights are transparent and adjustable)
weights = {
    "s_price_move":  0.20,   # suspicious only if breadth is low too
    "s_low_breadth": 0.25,   # few participants is a key red flag
    "s_cancel_rate": 0.15,   # spoofing signal
    "s_low_fill":    0.10,   # spoofing signal
    "s_self_trade":  0.15,   # collusion signal
    "s_top_pair":    0.10,   # concentration signal
    "s_late_trade":  0.05,   # timing manipulation
}

score_df["suspicion_score"] = sum(
    score_df[col] * w for col, w in weights.items()
)

# ─────────────────────────────────────────────
# 8.  Top 10 suspicious markets
# ─────────────────────────────────────────────
top10 = (
    score_df.sort_values("suspicion_score", ascending=False)
    .head(10)
    .merge(markets[["market_id","question","close_time"]], on="market_id", how="left")
)

cols_show = [
    "market_id","question",
    "suspicion_score",
    "price_move_bps","avg_unique_buyers",
    "cancel_rate","self_trade_rate","top_pair_share",
    "late_trade_share",
]
print("\n=== TOP 10 SUSPICIOUS MARKETS ===")
print(top10[cols_show].to_string(index=False))
top10[cols_show].to_csv(OUT_DIR / "top10_suspicious_markets.csv", index=False)

# ─────────────────────────────────────────────
# 9.  Visualisation 1 — Bar chart of suspicion scores
# ─────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 6))
bars = ax.barh(
    top10["market_id"].astype(str),
    top10["suspicion_score"],
    color="crimson", edgecolor="black", linewidth=0.5
)
ax.set_xlabel("Composite suspicion score (0–1)")
ax.set_title("Top 10 Suspicious Markets — Task 2", fontsize=13)
ax.invert_yaxis()
for bar in bars:
    ax.text(bar.get_width() + 0.002, bar.get_y() + bar.get_height()/2,
            f"{bar.get_width():.3f}", va="center", fontsize=9)
fig.tight_layout()
fig.savefig(OUT_DIR / "fig2_top10_suspicion_scores.png", dpi=150)
plt.close(fig)
print("\nSaved: fig2_top10_suspicion_scores.png")

# ─────────────────────────────────────────────
# 10.  Visualisation 2 — Price move vs unique buyers scatter
# ─────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 6))
sc = ax.scatter(
    score_df["avg_unique_buyers"],
    score_df["price_move_bps"] / 100,        # convert bps → %
    c=score_df["suspicion_score"],
    cmap="RdYlGn_r",
    s=60, edgecolors="grey", linewidths=0.4,
)
plt.colorbar(sc, ax=ax, label="Suspicion score")

# Label the top-10
for _, row in top10.iterrows():
    ax.annotate(str(row["market_id"]),
                xy=(row["avg_unique_buyers"], row["price_move_bps"] / 100),
                fontsize=7, color="darkred",
                xytext=(3, 3), textcoords="offset points")

ax.set_xlabel("Avg unique buyers per day")
ax.set_ylabel("Total price change (% equivalent)")
ax.set_title("Price movement vs. Market breadth\n(dark red = high suspicion)", fontsize=12)
fig.tight_layout()
fig.savefig(OUT_DIR / "fig3_price_vs_breadth.png", dpi=150)
plt.close(fig)
print("Saved: fig3_price_vs_breadth.png")

# ─────────────────────────────────────────────
# 11.  Visualisation 3 — Cancel rate per market (top 20)
# ─────────────────────────────────────────────
cancel_top20 = cancel_agg.sort_values("cancel_rate", ascending=False).head(20)
fig, ax = plt.subplots(figsize=(12, 6))
ax.bar(cancel_top20["market_id"].astype(str), cancel_top20["cancel_rate"],
       color="steelblue", edgecolor="black", linewidth=0.5)
ax.set_xlabel("Market ID")
ax.set_ylabel("Cancel rate (cancels / total orders)")
ax.set_title("Cancel Rate — Top 20 Markets", fontsize=12)
ax.tick_params(axis="x", rotation=45)
fig.tight_layout()
fig.savefig(OUT_DIR / "fig4_cancel_rate_top20.png", dpi=150)
plt.close(fig)
print("Saved: fig4_cancel_rate_top20.png")

# ─────────────────────────────────────────────
# 12.  Write a plain-text justification
# ─────────────────────────────────────────────
justification = """
TASK 2 — FINDINGS & JUSTIFICATION
===================================

We combined three tables (market_daily_snapshots, orders, trades)
to build a transparent multi-signal suspicion score for each market.

SIGNALS USED (with weights):
  1. Price movement (bps)               20% — large price swings are suspicious
                                              *if* the market is also illiquid
  2. Low avg unique buyers              25% — few participants = easier manipulation
  3. Cancel rate (cancels/orders)       15% — high cancels suggest spoofing
  4. Low fill ratio                     10% — orders that are rarely filled = spoofing
  5. Self-trade rate                    15% — buyer = seller = strong collusion signal
  6. Top pair concentration             10% — most volume through one counterparty pair
  7. Late-trade share (last 60 min)      5% — last-minute positioning / ramping

COUNTER-HYPOTHESES (why a flagged market might NOT be fraud):
  - Low unique buyers can reflect a genuinely niche/illiquid market
  - High cancel rates can arise from legitimate limit-order strategies
  - API-based trading is not fraud by itself (market makers use APIs)
  - Concentrated counterparties may reflect a small, legitimate user base

See top10_suspicious_markets.csv for the full ranked list.
Figures saved: fig1_price_timeseries_all_markets.png,
               fig2_top10_suspicion_scores.png,
               fig3_price_vs_breadth.png,
               fig4_cancel_rate_top20.png
"""

(OUT_DIR / "task2_findings.txt").write_text(justification.strip())
print(justification)

print(f"\nDone. All Task 2 outputs saved in: {OUT_DIR}")
