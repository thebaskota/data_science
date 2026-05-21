# Task 1 — Data model & join plan

## Three layers

| Layer | Tables | Role |
|-------|--------|------|
| Market | `markets`, `market_daily_snapshots` | Prediction markets & daily metrics |
| Account | `traders`, `sessions`, `transfers`, `account_daily_features` | Users, infra, money flows, daily risk features |
| Execution | `orders`, `trades` | Order intent & matched trades |

## Join keys

```
markets.market_id
  ← orders.market_id
  ← trades.market_id
  ← market_daily_snapshots.market_id

traders.trader_id
  ← orders.trader_id
  ← sessions.trader_id
  ← transfers.trader_id
  ← account_daily_features.trader_id
  ← trades.buyer_trader_id / seller_trader_id

orders.order_id
  ← trades.buy_order_id / sell_order_id
```

## Quality summary (verified)

- All primary keys unique (`order_id`, `trade_id`, `session_id`, etc.)
- Composite keys unique: (`trader_id`, `date`), (`market_id`, `trade_date`)
- **0 foreign-key orphans** across orders/trades
- **0 temporal violations** (`created_at ≤ updated_at`, `session_start ≤ session_end`, market lifecycle order)

## Implication

Fraud suspicion requires **joining** market snapshots + orders/trades + account features + sessions/transfers — not a single table.

See `output/tables/task1_*.csv` for full QC exports.
