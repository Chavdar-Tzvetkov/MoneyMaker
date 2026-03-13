# AI add-on (contextual bandit) – see main docs

The AI layer is now fully integrated into the main bot and documented in:

- **README.md** – **“AI and strategies”** section: meta-controller, platform-specific strategy sets, regime filter, profit-oriented options, LLM.
- **ai/README_AI_LEARNING.md** – Detailed AI & learning: features, reward flow (immediate + delayed from PnL), tuning, per-symbol state.

**How to run:** Use the main entry point (`python Main.py` or `start_bot.bat`). The live loop is in `live_trading.py`; it uses the meta-controller, regime filter, and feeds realized PnL back into the bandit. No separate “smart” runner is required.

**Key modules:** `ai/meta_controller.py`, `ai/policy_linucb.py`, `ai/features.py`, `ai/regime.py`, `ai/llm_decider.py`.
