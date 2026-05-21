"""
Polymarket-style fraud detection seminar — full pipeline (Tasks 1–5).
Run: python fraud_analysis.py
"""

from __future__ import annotations

from pathlib import Path
import json
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "polymarket_fraud_seminar_student"
OUT_FIG = ROOT / "output" / "figures"
OUT_TBL = ROOT / "output" / "tables"
REPORT_DIR = ROOT / "report"

for d in (OUT_FIG, OUT_TBL, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

sns.set_theme(style="whitegrid", palette="muted")
plt.rcParams["figure.figsize"] = (10, 6)
plt.rcParams["figure.dpi"] = 120


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data() -> dict[str, pd.DataFrame]:
    """Load all CSVs with parsed datetimes."""
    parse_markets = ["created_at", "close_time", "resolve_time"]
    parse_orders = ["created_at", "updated_at"]
    parse_sessions = ["session_start", "session_end"]
    parse_trades = ["trade_ts"]
    parse_transfers = ["ts"]
    parse_traders = ["signup_ts"]

    tables = {
        "markets": pd.read_csv(DATA_DIR / "markets.csv", parse_dates=parse_markets),
        "traders": pd.read_csv(DATA_DIR / "traders.csv", parse_dates=parse_traders),
        "sessions": pd.read_csv(DATA_DIR / "sessions.csv", parse_dates=parse_sessions),
        "orders": pd.read_csv(DATA_DIR / "orders.csv", parse_dates=parse_orders),
        "trades": pd.read_csv(DATA_DIR / "trades.csv", parse_dates=parse_trades),
        "transfers": pd.read_csv(DATA_DIR / "transfers.csv", parse_dates=parse_transfers),
        "snapshots": pd.read_csv(
            DATA_DIR / "market_daily_snapshots.csv", parse_dates=["trade_date"]
        ),
        "features": pd.read_csv(DATA_DIR / "account_daily_features.csv", parse_dates=["date"]),
    }
    return tables


# ---------------------------------------------------------------------------
# Task 1 — Data quality & relationship model
# ---------------------------------------------------------------------------
def task1_quality_report(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    markets, traders, orders, trades = (
        tables["markets"],
        tables["traders"],
        tables["orders"],
        tables["trades"],
    )
    market_ids = set(markets["market_id"])
    trader_ids = set(traders["trader_id"])
    order_ids = set(orders["order_id"])

    pk_checks = [
        ("markets", "market_id", tables["markets"]),
        ("traders", "trader_id", tables["traders"]),
        ("sessions", "session_id", tables["sessions"]),
        ("orders", "order_id", tables["orders"]),
        ("trades", "trade_id", tables["trades"]),
        ("transfers", "transfer_id", tables["transfers"]),
    ]
    rows = []
    for name, col, df in pk_checks:
        dup = int(df[col].duplicated().sum())
        rows.append(
            {
                "table": name,
                "rows": len(df),
                "pk_column": col,
                "pk_unique": dup == 0,
                "pk_duplicates": dup,
            }
        )

    rows.append(
        {
            "table": "features",
            "rows": len(tables["features"]),
            "pk_column": "trader_id+date",
            "pk_unique": tables["features"].duplicated(["trader_id", "date"]).sum() == 0,
            "pk_duplicates": int(tables["features"].duplicated(["trader_id", "date"]).sum()),
        }
    )
    rows.append(
        {
            "table": "snapshots",
            "rows": len(tables["snapshots"]),
            "pk_column": "market_id+trade_date",
            "pk_unique": tables["snapshots"]
            .duplicated(["market_id", "trade_date"])
            .sum()
            == 0,
            "pk_duplicates": int(
                tables["snapshots"].duplicated(["market_id", "trade_date"]).sum()
            ),
        }
    )

    fk_rows = [
        ("orders", "market_id", "markets", (~orders["market_id"].isin(market_ids)).sum()),
        ("orders", "trader_id", "traders", (~orders["trader_id"].isin(trader_ids)).sum()),
        ("trades", "market_id", "markets", (~trades["market_id"].isin(market_ids)).sum()),
        ("trades", "buyer_trader_id", "traders", (~trades["buyer_trader_id"].isin(trader_ids)).sum()),
        ("trades", "seller_trader_id", "traders", (~trades["seller_trader_id"].isin(trader_ids)).sum()),
        ("trades", "buy_order_id", "orders", (~trades["buy_order_id"].isin(order_ids)).sum()),
        ("trades", "sell_order_id", "orders", (~trades["sell_order_id"].isin(order_ids)).sum()),
    ]
    fk_df = pd.DataFrame(fk_rows, columns=["child", "fk_col", "parent", "orphan_count"])

    temporal = {
        "orders_created_le_updated": int((orders["created_at"] > orders["updated_at"]).sum()),
        "sessions_start_le_end": int(
            (tables["sessions"]["session_start"] > tables["sessions"]["session_end"]).sum()
        ),
        "markets_created_le_close": int((markets["created_at"] > markets["close_time"]).sum()),
        "markets_close_le_resolve": int((markets["close_time"] > markets["resolve_time"]).sum()),
    }

    qc = pd.DataFrame(rows)
    qc.to_csv(OUT_TBL / "task1_primary_key_checks.csv", index=False)
    fk_df.to_csv(OUT_TBL / "task1_foreign_key_orphans.csv", index=False)
    with open(OUT_TBL / "task1_temporal_violations.json", "w") as f:
        json.dump(temporal, f, indent=2)

    miss = {}
    for name, df in tables.items():
        m = df.isna().mean()
        cols = m[m > 0].sort_values(ascending=False)
        if len(cols):
            miss[name] = cols.head(5).to_dict()
    with open(OUT_TBL / "task1_missing_values.json", "w") as f:
        json.dump({k: {str(c): round(v, 4) for c, v in d.items()} for k, d in miss.items()}, f, indent=2)

    relevance = pd.DataFrame(
        [
            ("markets", "close_time, liquidity_usdc_seeded", "high"),
            ("markets", "weather_temp_c, thumbnail_theme", "irrelevant"),
            ("orders", "status, cancel_reason, is_api_order, cancel_count_15m", "high"),
            ("orders", "coupon_banner_seen", "irrelevant"),
            ("trades", "is_self_trade_flag, signed_price_change_bps", "high"),
            ("sessions", "device_fingerprint_hash, ip_address, vpn_detected", "high"),
            ("sessions", "battery_pct_at_open, avg_scroll_depth_pct", "irrelevant"),
            ("transfers", "source_or_destination_address, aml_screen_hit", "high"),
            ("features", "fill_ratio_mean, top_counterparty_trade_share, self_trade_count", "high"),
            ("snapshots", "news_sentiment_score, social_mentions_1h", "medium (counter-hypothesis)"),
        ],
        columns=["table", "fields", "relevance"],
    )
    relevance.to_csv(OUT_TBL / "task1_field_relevance.csv", index=False)

    print("Task 1 complete — QC tables written.")
    return qc


# ---------------------------------------------------------------------------
# Task 2 — Suspicious markets
# ---------------------------------------------------------------------------
def task2_suspicious_markets(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    markets = tables["markets"]
    snapshots = tables["snapshots"]
    orders = tables["orders"]
    trades = tables["trades"]

    snap_agg = (
        snapshots.groupby("market_id")
        .agg(
            total_price_change_bps=("price_change_bps_sum", "sum"),
            avg_unique_buyers=("unique_buyers", "mean"),
            avg_unique_sellers=("unique_sellers", "mean"),
            avg_trade_count=("trade_count", "mean"),
            avg_volume_usdc=("volume_usdc", "mean"),
            max_news_sentiment=("news_sentiment_score", "max"),
            max_social_mentions=("social_mentions_1h", "max"),
        )
        .reset_index()
    )

    order_stats = orders.groupby("market_id").agg(
        orders_total=("order_id", "count"),
        cancel_count=("status", lambda s: (s == "CANCELED").sum()),
    )
    order_stats["cancel_rate"] = order_stats["cancel_count"] / order_stats["orders_total"]

    trades_m = trades.merge(
        markets[["market_id", "close_time", "question"]], on="market_id", how="left"
    )
    trades_m["near_close_minutes"] = (
        trades_m["close_time"] - trades_m["trade_ts"]
    ).dt.total_seconds() / 60
    near_close = (
        trades_m[trades_m["near_close_minutes"].between(0, 120)]
        .groupby("market_id")
        .agg(
            near_close_trades=("trade_id", "count"),
            near_close_notional=("notional_usdc", "sum"),
            near_close_aggressive_share=(
                "aggressor_side",
                lambda s: (s.isin(["BUY", "SELL"])).mean(),
            ),
        )
        .reset_index()
    )

    # Trader concentration per market
    vol_buyer = trades.groupby(["market_id", "buyer_trader_id"])["notional_usdc"].sum()
    vol_seller = trades.groupby(["market_id", "seller_trader_id"])["notional_usdc"].sum()
    conc_rows = []
    for mid in trades["market_id"].unique():
        b = vol_buyer.get(mid, pd.Series(dtype=float))
        s = vol_seller.get(mid, pd.Series(dtype=float))
        total = trades.loc[trades["market_id"] == mid, "notional_usdc"].sum()
        if total <= 0:
            continue
        top_b = b.max() / total if len(b) else 0
        top_s = s.max() / total if len(s) else 0
        conc_rows.append(
            {
                "market_id": mid,
                "top_buyer_volume_share": top_b,
                "top_seller_volume_share": top_s,
                "trader_concentration": max(top_b, top_s),
            }
        )
    concentration = pd.DataFrame(conc_rows)

    market_scores = (
        snap_agg.merge(order_stats.reset_index(), on="market_id", how="left")
        .merge(near_close, on="market_id", how="left")
        .merge(concentration, on="market_id", how="left")
        .merge(markets[["market_id", "question", "category", "featured_flag", "liquidity_usdc_seeded"]], on="market_id")
    )

    for c in ["cancel_rate", "trader_concentration", "total_price_change_bps", "near_close_notional"]:
        if c in market_scores.columns:
            market_scores[c] = market_scores[c].fillna(0)

    # Participation breadth: low unique buyers/sellers + high price move = suspicious
    market_scores["breadth"] = (
        market_scores["avg_unique_buyers"] + market_scores["avg_unique_sellers"]
    ) / 2
    market_scores["thin_market_move"] = market_scores["total_price_change_bps"] / (
        market_scores["breadth"].replace(0, np.nan) + 1
    )

    # Composite suspicion score (transparent heuristic)
    def zscore(s: pd.Series) -> pd.Series:
        std = s.std()
        if std == 0 or np.isnan(std):
            return pd.Series(0, index=s.index)
        return (s - s.mean()) / std

    market_scores["suspicion_score"] = (
        0.25 * zscore(market_scores["thin_market_move"])
        + 0.25 * zscore(market_scores["cancel_rate"])
        + 0.20 * zscore(market_scores["trader_concentration"])
        + 0.20 * zscore(market_scores["near_close_notional"].fillna(0))
        + 0.10 * zscore(market_scores["total_price_change_bps"].abs())
    )

    top10 = market_scores.nlargest(10, "suspicion_score")[
        [
            "market_id",
            "question",
            "category",
            "suspicion_score",
            "total_price_change_bps",
            "avg_unique_buyers",
            "avg_unique_sellers",
            "cancel_rate",
            "trader_concentration",
            "near_close_trades",
            "max_news_sentiment",
            "featured_flag",
        ]
    ]
    top10["justification"] = top10.apply(
        lambda r: (
            f"Large price move ({r['total_price_change_bps']:.0f} bps sum) with limited "
            f"participation ({r['avg_unique_buyers']:.1f} buyers / {r['avg_unique_sellers']:.1f} sellers), "
            f"cancel rate {r['cancel_rate']:.1%}, concentration {r['trader_concentration']:.1%}."
        ),
        axis=1,
    )
    top10.to_csv(OUT_TBL / "top10_suspicious_markets.csv", index=False)
    market_scores.to_csv(OUT_TBL / "task2_all_market_scores.csv", index=False)

    # Plot 1: price time series for top 3 suspicious markets
    top3_ids = top10["market_id"].head(3).tolist()
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=False)
    for ax, mid in zip(axes, top3_ids):
        sub = snapshots[snapshots["market_id"] == mid].sort_values("trade_date")
        ax.plot(sub["trade_date"], sub["last_price"], marker="o", markersize=3)
        q = markets.loc[markets["market_id"] == mid, "question"].iloc[0][:60]
        ax.set_title(f"{mid}: {q}...")
        ax.set_ylabel("last_price")
    axes[-1].set_xlabel("trade_date")
    fig.suptitle("Task 2 — Price time series (top 3 suspicious markets)", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT_FIG / "task2_price_timeseries_top3.png", bbox_inches="tight")
    plt.close()

    # Plot 2: cancel rate vs price change (all markets)
    fig, ax = plt.subplots(figsize=(9, 6))
    sc = ax.scatter(
        market_scores["total_price_change_bps"],
        market_scores["cancel_rate"],
        c=market_scores["suspicion_score"],
        cmap="YlOrRd",
        s=60,
        alpha=0.8,
    )
    for _, r in top10.head(5).iterrows():
        ax.annotate(r["market_id"], (r["total_price_change_bps"], r["cancel_rate"]), fontsize=7)
    plt.colorbar(sc, label="suspicion_score")
    ax.set_xlabel("Total price change (bps sum)")
    ax.set_ylabel("Order cancel rate")
    ax.set_title("Task 2 — Market cancel rate vs price movement")
    fig.tight_layout()
    fig.savefig(OUT_FIG / "task2_cancel_vs_price_change.png", bbox_inches="tight")
    plt.close()

    print("Task 2 complete — top markets and 2 figures.")
    return top10


# ---------------------------------------------------------------------------
# Task 3 — Account clusters
# ---------------------------------------------------------------------------
def _build_account_edges(tables: dict[str, pd.DataFrame]) -> list[tuple[str, str, str]]:
    sessions = tables["sessions"]
    transfers = tables["transfers"]
    edges = []

    def add_pairs(df: pd.DataFrame, col: str, reason: str):
        grouped = df.dropna(subset=[col]).groupby(col)["trader_id"].apply(lambda x: list(set(x)))
        for key, traders in grouped.items():
            if len(traders) < 2:
                continue
            for i in range(len(traders)):
                for j in range(i + 1, len(traders)):
                    a, b = sorted([traders[i], traders[j]])
                    edges.append((a, b, reason))

    add_pairs(sessions, "device_id", "shared_device")
    add_pairs(sessions, "device_fingerprint_hash", "shared_fingerprint")
    add_pairs(sessions, "ip_address", "shared_ip")
    w = transfers[transfers["direction"] == "withdrawal"]
    add_pairs(w, "source_or_destination_address", "shared_withdraw_addr")
    return edges


def task3_clusters(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    trades = tables["trades"]
    features = tables["features"]

    edges = _build_account_edges(tables)
    G = nx.Graph()
    for a, b, reason in edges:
        if G.has_edge(a, b):
            G[a][b]["reasons"] = G[a][b].get("reasons", set()) | {reason}
        else:
            G.add_edge(a, b, reasons={reason})

    clusters = list(nx.connected_components(G))
    cluster_rows = []
    for idx, members in enumerate(clusters):
        if len(members) < 2:
            continue
        members = list(members)
        sub = G.subgraph(members)
        n_edges = sub.number_of_edges()
        density = (2 * n_edges) / (len(members) * (len(members) - 1)) if len(members) > 1 else 0

        m_trades = trades[
            trades["buyer_trader_id"].isin(members) & trades["seller_trader_id"].isin(members)
        ]
        total_vol = trades[
            trades["buyer_trader_id"].isin(members) | trades["seller_trader_id"].isin(members)
        ]["notional_usdc"].sum()
        internal_share = (
            m_trades["notional_usdc"].sum() / total_vol if total_vol > 0 else 0
        )

        feat_sub = features[features["trader_id"].isin(members)].groupby("trader_id").agg(
            max_shared_device=("shared_device_session_share", "max"),
            max_shared_fp=("shared_fp_session_share", "max"),
            max_shared_withdraw=("shared_withdraw_addr_share", "max"),
            max_counterparty=("top_counterparty_trade_share", "max"),
            total_self_trades=("self_trade_count", "sum"),
            max_vpn=("vpn_share", "max"),
        )
        cluster_rows.append(
            {
                "cluster_id": idx,
                "size": len(members),
                "density": round(density, 4),
                "internal_trade_share": round(internal_share, 4),
                "internal_trade_volume_usdc": round(m_trades["notional_usdc"].sum(), 2),
                "members": ",".join(sorted(members)[:15])
                + ("..." if len(members) > 15 else ""),
                "avg_max_counterparty_share": feat_sub["max_counterparty"].mean(),
                "avg_max_shared_device": feat_sub["max_shared_device"].mean(),
                "total_self_trades": int(feat_sub["total_self_trades"].sum()),
            }
        )

    cluster_df = pd.DataFrame(cluster_rows)
    if cluster_df.empty:
        cluster_df = pd.DataFrame(
            columns=[
                "cluster_id",
                "size",
                "density",
                "internal_trade_share",
                "suspicion_score",
            ]
        )
    else:
        def z(s):
            return (s - s.mean()) / s.std() if s.std() > 0 else 0

        cluster_df["suspicion_score"] = (
            0.30 * z(cluster_df["size"])
            + 0.25 * z(cluster_df["internal_trade_share"])
            + 0.25 * z(cluster_df["avg_max_counterparty_share"].fillna(0))
            + 0.20 * z(cluster_df["total_self_trades"])
        )
        cluster_df = cluster_df.sort_values("suspicion_score", ascending=False)

    cluster_df.to_csv(OUT_TBL / "task3_all_clusters.csv", index=False)
    top3 = cluster_df.head(3).copy()
    top3["narrative"] = top3.apply(
        lambda r: (
            f"Cluster of {int(r['size'])} accounts linked by shared device/IP/withdrawal infra; "
            f"internal trade share {r['internal_trade_share']:.1%}, "
            f"density {r['density']:.2f}, {int(r['total_self_trades'])} self-trade events."
        ),
        axis=1,
    )
    top3.to_csv(OUT_TBL / "top3_suspicious_clusters.csv", index=False)

    # Plot: cluster size vs internal trade share
    if len(cluster_df) > 0:
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.scatter(
            cluster_df["size"],
            cluster_df["internal_trade_share"],
            c=cluster_df["suspicion_score"],
            cmap="Reds",
            s=50,
            alpha=0.8,
        )
        for _, r in top3.iterrows():
            ax.annotate(f"C{int(r['cluster_id'])}", (r["size"], r["internal_trade_share"]), fontsize=9)
        ax.set_xlabel("Cluster size (# accounts)")
        ax.set_ylabel("Internal trade volume share")
        ax.set_title("Task 3 — Account clusters (shared infrastructure)")
        fig.tight_layout()
        fig.savefig(OUT_FIG / "task3_cluster_scatter.png", bbox_inches="tight")
        plt.close()

    print("Task 3 complete — clusters and figure.")
    return top3


# ---------------------------------------------------------------------------
# Task 4 — Heuristic fraud scores
# ---------------------------------------------------------------------------
def task4_fraud_scores(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    features = tables["features"]

    agg = features.groupby("trader_id").agg(
        orders_placed=("orders_placed", "sum"),
        cancel_count=("cancel_count", "sum"),
        fill_ratio_mean=("fill_ratio_mean", "mean"),
        top_counterparty_trade_share=("top_counterparty_trade_share", "max"),
        shared_device_session_share=("shared_device_session_share", "max"),
        shared_fp_session_share=("shared_fp_session_share", "max"),
        shared_withdraw_addr_share=("shared_withdraw_addr_share", "max"),
        api_order_share=("api_order_share", "max"),
        self_trade_count=("self_trade_count", "sum"),
        vpn_share=("vpn_share", "max"),
        tor_share=("tor_share", "max"),
    ).reset_index()

    agg["cancel_to_order_ratio"] = agg["cancel_count"] / agg["orders_placed"].replace(0, np.nan)
    agg["shared_infra_score"] = (
        agg["shared_device_session_share"]
        + agg["shared_fp_session_share"]
        + agg["shared_withdraw_addr_share"]
    )

    # Weights (documented in output)
    weights = {
        "cancel_to_order_ratio": 0.15,
        "fill_ratio_mean_inv": 0.15,  # low fill = bad, invert
        "top_counterparty_trade_share": 0.20,
        "shared_infra_score": 0.20,
        "api_order_share": 0.10,
        "self_trade_count": 0.15,
        "vpn_tor": 0.05,
    }
    with open(OUT_TBL / "task4_score_weights.json", "w") as f:
        json.dump(
            {
                **weights,
                "rationale": {
                    "cancel_to_order_ratio": "Spoofing: many cancels vs orders",
                    "fill_ratio_mean_inv": "Low execution with high activity",
                    "top_counterparty_trade_share": "Collusion: one counterparty dominates",
                    "shared_infra_score": "Multi-account same device/fp/withdraw",
                    "api_order_share": "Automated manipulation patterns",
                    "self_trade_count": "Direct wash/self-trade flag",
                    "vpn_tor": "Obfuscation (weak alone, supports other signals)",
                },
            },
            f,
            indent=2,
        )

    def zscore(col: pd.Series) -> pd.Series:
        if col.std() == 0:
            return pd.Series(0.0, index=col.index)
        return (col - col.mean()) / col.std()

    agg["fill_ratio_mean_inv"] = 1 - agg["fill_ratio_mean"].clip(0, 1)
    agg["vpn_tor"] = agg["vpn_share"] + agg["tor_share"]

    agg["account_fraud_score"] = (
        weights["cancel_to_order_ratio"] * zscore(agg["cancel_to_order_ratio"].fillna(0))
        + weights["fill_ratio_mean_inv"] * zscore(agg["fill_ratio_mean_inv"])
        + weights["top_counterparty_trade_share"]
        * zscore(agg["top_counterparty_trade_share"])
        + weights["shared_infra_score"] * zscore(agg["shared_infra_score"])
        + weights["api_order_share"] * zscore(agg["api_order_share"])
        + weights["self_trade_count"] * zscore(agg["self_trade_count"])
        + weights["vpn_tor"] * zscore(agg["vpn_tor"])
    )

    top_accounts = agg.nlargest(15, "account_fraud_score")
    top_accounts = top_accounts.merge(
        tables["traders"][["trader_id", "kyc_tier", "signup_ts", "home_country"]],
        on="trader_id",
        how="left",
    )
    top_accounts["justification"] = top_accounts.apply(
        lambda r: (
            f"Score {r['account_fraud_score']:.2f}: cancel/order {r['cancel_to_order_ratio']:.2f}, "
            f"fill {r['fill_ratio_mean']:.2f}, counterparty share {r['top_counterparty_trade_share']:.2f}, "
            f"shared infra {r['shared_infra_score']:.2f}, self-trades {int(r['self_trade_count'])}."
        ),
        axis=1,
    )
    top_accounts.to_csv(OUT_TBL / "top_accounts_fraud_score.csv", index=False)
    agg.to_csv(OUT_TBL / "task4_all_account_scores.csv", index=False)

    market_scores = pd.read_csv(OUT_TBL / "task2_all_market_scores.csv")
    top_markets_score = market_scores.nlargest(10, "suspicion_score")[
        ["market_id", "question", "suspicion_score"]
    ]
    top_markets_score.to_csv(OUT_TBL / "top_markets_fraud_score.csv", index=False)

    # Plot: top account score distribution
    fig, ax = plt.subplots(figsize=(10, 5))
    top15 = agg.nlargest(15, "account_fraud_score")
    ax.barh(top15["trader_id"], top15["account_fraud_score"], color="coral")
    ax.set_xlabel("Account fraud score (weighted heuristic)")
    ax.set_title("Task 4 — Top 15 accounts by transparent risk score")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(OUT_FIG / "task4_top_account_scores.png", bbox_inches="tight")
    plt.close()

    print("Task 4 complete — account and market scores.")
    return top_accounts, top_markets_score


# ---------------------------------------------------------------------------
# Task 5 — Management summary
# ---------------------------------------------------------------------------
def task5_management_summary(
    top_markets: pd.DataFrame,
    top_clusters: pd.DataFrame,
    top_accounts: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
) -> str:
    cases = []

    for i, (_, r) in enumerate(top_markets.head(3).iterrows(), 1):
        news = r.get("max_news_sentiment", 0)
        feat = r.get("featured_flag", False)
        cases.append(
            f"""### Case M{i}: {r['market_id']}
- **Pattern:** Market-level — thin participation with large price move; possible manipulation or spoofing.
- **Evidence:** {r.get('justification', r.to_dict())}
- **Counter-hypothesis:** Elevated news sentiment ({news:.2f}) or featured listing ({feat}) could explain volume/price without fraud.
- **Note:** Suspicion ≠ proof; further investigation needed.

"""
        )

    for i, (_, r) in enumerate(top_clusters.head(2).iterrows(), 1):
        cases.append(
            f"""### Case C{i}: Cluster {int(r['cluster_id'])} ({int(r['size'])} accounts)
- **Pattern:** Collusive / multi-account — shared infrastructure and internal trading.
- **Evidence:** {r.get('narrative', '')}
- **Counter-hypothesis:** Household or institutional users sharing IP/device; legitimate market-making between related accounts.
- **Note:** Suspicion ≠ proof.

"""
        )

    for i, (_, r) in enumerate(top_accounts.head(3).iterrows(), 1):
        cases.append(
            f"""### Case A{i}: {r['trader_id']}
- **Pattern:** Account-level — spoofing/collusion signals (cancels, low fill, shared infra, self-trades).
- **Evidence:** {r['justification']}
- **Counter-hypothesis:** Legitimate API market-making (high api_order_share) or new user learning (high cancel rate).
- **KYC:** {r.get('kyc_tier', 'n/a')} | **Country:** {r.get('home_country', 'n/a')}
- **Note:** Suspicion ≠ proof.

"""
        )

    body = f"""# Management Summary — Fraud Detection Seminar

**Objective:** Identify evidence-based *suspicion* of market manipulation, collusion, spoofing, or information-driven abuse — not legal proof.

**Data:** {len(tables['markets'])} markets, {len(tables['traders'])} traders, {len(tables['orders'])} orders, {len(tables['trades'])} trades (synthetic Polymarket-style dataset).

---

## Top findings (ranked)

{chr(10).join(cases)}

---

## Methodology (brief)

1. **Task 1:** Validated joins, primary keys, temporal consistency; tagged high-value vs noise fields.
2. **Task 2:** Flagged markets where price movement did not match participant breadth, cancel rates, or late trading before `close_time`.
3. **Task 3:** Built account graph on shared device, fingerprint, IP, withdrawal address; ranked clusters by size and internal trade share.
4. **Task 4:** Transparent weighted score (no ML black box) using cancel ratio, fill ratio, counterparty concentration, shared infrastructure, API share, self-trades.

## Limitations

- Synthetic data; patterns are pedagogical, not ground truth.
- Shared IP/device does not imply fraud without corroborating trade behavior.
- External news/social fields can explain price moves (always consider counter-hypotheses).

## Recommended next steps

- Manual review of order book around `close_time` for top markets.
- Compliance check on withdrawal address overlap for top clusters.
- Enhanced KYC for highest-scoring accounts with corroborating cluster membership.

---
*Generated by fraud_analysis.py*
"""
    path = REPORT_DIR / "management_summary.md"
    path.write_text(body, encoding="utf-8")
    print(f"Task 5 complete — summary written to {path}")
    return body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Loading data...")
    tables = load_data()
    for name, df in tables.items():
        print(f"  {name}: {len(df):,} rows")

    task1_quality_report(tables)
    top_markets = task2_suspicious_markets(tables)
    top_clusters = task3_clusters(tables)
    top_accounts, _ = task4_fraud_scores(tables)
    task5_management_summary(top_markets, top_clusters, top_accounts, tables)

    print("\nAll tasks complete.")
    print(f"  Figures: {OUT_FIG}")
    print(f"  Tables:  {OUT_TBL}")
    print(f"  Report:  {REPORT_DIR / 'management_summary.md'}")


if __name__ == "__main__":
    main()
