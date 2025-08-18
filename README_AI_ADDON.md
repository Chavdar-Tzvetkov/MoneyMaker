
AI Add-on (Contextual Bandit) for MoneyMaker
============================================

What this adds
--------------
- `ai/policy_linucb.py`: LinUCB contextual bandit that selects actions from: SMA_conservative, SMA_aggressive, Scalp_light, Hold.
- `ai/features.py`: turns recent OHLC bars into a feature vector.
- `ai/meta_controller.py`: wraps the policy and maps chosen actions to strategy + parameters.
- `smart_live_trading.py`: example runner that fetches fresh bars, asks the MetaController for an action, runs the corresponding strategy, then updates the policy with a simple reward.
- `utils/market_data_ext.py`: helper to load recent bars via yfinance (adjust/replace with your internal data sources).

How to run
----------
1) Ensure your environment can import `yfinance` (listed in requirements).
2) `python smart_live_trading.py`
   - It will default to symbols from `config.INSTRUMENTS` or use a small fallback list.

Integration notes
-----------------
- Adapt `run_sma_once` and `run_scalp_once` to match your actual strategy function signatures.
- Replace the toy reward mapping with **realized PnL** pulled from your DB or broker after each trade/exit.
- For MT5/Trading212: log each trade result and compute reward = normalized PnL (e.g., PnL / ATR or % of entry).
- Use a rolling window evaluation; periodically persist the LinUCB A and b matrices if you want policy continuity between sessions.

Safety & Controls
-----------------
- Keep your existing max positions, TP/SL, trailing, and daily loss limits. The AI chooses a mode and params, not your hard risk limits.
- Add "Do not trade" gates when spreads are too wide or liquidity is thin.
