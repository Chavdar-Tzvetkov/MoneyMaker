# AI & Learning in MoneyMaker

## Overview

The bot uses two AI layers to self-adjust to market trends and learn from outcomes:

1. **Meta-controller (LinUCB)** – Chooses *which strategy* to run per symbol (SMA, RSI_MR, Donchian, etc.) based on current market features. Learns from **realized PnL** when positions close.
2. **LLM (OpenAI)** – Optional tie-break/veto/primary advisor that can override the quant decision (e.g. force HOLD when uncertain).

## Data flow

- **Features** (`ai/features.py`): 10-dim vector per bar (return, volatility, momentum, SMA delta, range, trend/flat flags, bias). Used by both meta-controller and (in packed form) the LLM.
- **Meta decide**: `meta.decide(df, symbol)` → picks strategy arm by LinUCB; uncertainty gating can force HOLD (low margin, low UCB, or flip cooldown).
- **Reward**:
  - **Immediate** (per bar): `_estimate_reward(df, outcome)` – next-bar return scaled by ATR, used when no position is closed in that step.
  - **Delayed** (on close): When a position closes (FX or equity), the realized PnL is turned into a reward (PnL / 1% of equity, clipped) and fed to `meta.learn(df, action_that_opened, reward, symbol)`. The meta-controller thus learns from **actual profit/loss**, not just price move.
- **LLM**: Gets same-style features + quant hint; returns BUY/SELL/HOLD + confidence. No learning loop; use for conservative override only.

## Improvements made

- **Learn from real PnL**: `_last_open_action[symbol]` stores which meta action opened the position; on any close (FLIP, time-stop, session-flat, PG, equity TP/SL/trailing) we call `_feed_close_reward(meta, symbol, realized_pnl, is_fx)` so the bandit gets reward proportional to closed PnL.
- **MT5 close returns realized PnL**: `close_position_market` now returns `(ok, msg, realized)` so the live loop can feed FX closes into the meta.
- **LLM model**: Default model fixed to a valid name (e.g. `gpt-4o`); was `gpt-5` which may not exist.

## Tuning

- **Meta**: `alpha` (exploration), `min_ucb_margin`, `ucb_floor`, `flip_cooldown_sec` in `MetaController` and env (e.g. `AI_MIN_UCB_MARGIN`, `AI_UCB_FLOOR`).
- **Reward scale**: Delayed reward = `realized_pnl / max(equity*0.01, 1)` then clipped to [-2, 2]. So 1% of equity ≈ 1.0 reward.
- **LLM**: `LLM_MODE` (TIE_BREAK / VETO / PRIMARY), `LLM_MIN_CONF`, `LLM_MODEL`, `OPENAI_API_KEY`.

## Optional next steps

- **LLM outcome log**: Log (symbol, quant_decision, llm_decision, final_decision, next_bar_return) to a file for analysis.
- **Regime features**: Add ATR ratio or volatility regime so the meta can prefer mean-reversion in range and trend-following in trends.
- **Per-symbol state**: Already in place; each symbol has its own LinUCB policy under `state/linucb/<SYMBOL>.npz`.
