from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional
import os
import time
import numpy as np
import pandas as pd

from .policy_linucb import LinUCBArm, LinUCBPolicy
from .features import compute_features

ACTIONS = {
    # --- Existing arms ---
    "SMA_conservative": ("SMA", {"fast": 20, "slow": 50, "hold_band": 0.001, "tp": 0.03, "sl": 0.02, "trail": 0.015}),
    "SMA_aggressive":   ("SMA", {"fast": 10, "slow": 30, "hold_band": 0.0,   "tp": 0.05, "sl": 0.03, "trail": 0.02}),
    "RSI_MR":           ("RSI_MR", {"interval": "15m", "rsi_len": 14}),
    "Donchian_Break":   ("DONCHIAN", {"interval": "30m", "ch_len": 20}),
    "MACD_Trend":       ("MACD", {"interval": "15m"}),
    "Supertrend":       ("SUPER", {"interval": "15m", "atr_len": 10, "mult": 3.0}),
    "RangeMR":          ("RANGE_MR", {"interval": "1m", "length": 60, "z_entry": 1.2}),

    # --- NEW: make scalping selectable by the AI ---
    # analyze_scalping() is parameterless in your implementation; we still expose the arm explicitly.
    "Scalping":         ("SCALP", {}),

    # HOLD
    "Hold":             ("HOLD", {}),
}

STATE_DIR = os.path.join("state", "linucb")


@dataclass
class MetaDecision:
    action: str
    strategy: str
    params: Dict[str, Any]
    uncertainty: float


class MetaController:
    """
    LinUCB meta-controller with:
      - per-symbol policies (+ persistence to ./state/linucb)
      - uncertainty gating (margin + floor -> HOLD)
      - flip cooldown to avoid rapid strategy churn

    Backward compatible:
      decide(df) / learn(df, action, reward) -> global policy
      Prefer: decide(df, symbol) / learn(df, action, reward, symbol)
    """
    def __init__(
        self,
        alpha: float = 0.6,
        d: int = 10,
        *,
        min_ucb_margin: float = 0.05,     # require top-2 margin >= this
        ucb_floor: float = -0.10,         # require best UCB >= this
        flip_cooldown_sec: int = 90,      # min seconds between action flips per symbol
        save_every_sec: int = 60          # persistence cadence
    ):
        self.alpha = alpha
        self.d = d

        # per-symbol state
        self._policies: Dict[str, LinUCBPolicy] = {}
        self._last_action: Dict[str, str] = {}
        self._last_action_ts: Dict[str, float] = {}
        self._last_save_ts: Dict[str, float] = {}

        # gating / persistence
        self.min_ucb_margin = float(min_ucb_margin)
        self.ucb_floor = float(ucb_floor)
        self.flip_cooldown_sec = int(flip_cooldown_sec)
        self.save_every_sec = int(save_every_sec)

        os.makedirs(STATE_DIR, exist_ok=True)

        # global (back-compat) policy
        self._global_policy = self._new_policy()
        self._load_policy_from_disk("__GLOBAL__", self._global_policy)

    # ---------------- internal: policy management & persistence ---------------

    def _new_policy(self) -> LinUCBPolicy:
        arms = {name: LinUCBArm(d=self.d, alpha=self.alpha) for name in ACTIONS.keys()}
        return LinUCBPolicy(arms)

    def _state_path(self, key: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in key.upper())
        return os.path.join(STATE_DIR, f"{safe}.npz")

    def _get_policy(self, symbol: Optional[str]) -> LinUCBPolicy:
        if not symbol:
            return self._global_policy
        if symbol not in self._policies:
            pol = self._new_policy()
            self._load_policy_from_disk(symbol, pol)
            self._policies[symbol] = pol
        return self._policies[symbol]

    def _load_policy_from_disk(self, key: str, policy: LinUCBPolicy) -> None:
        path = self._state_path(key)
        if not os.path.exists(path):
            return
        try:
            data = np.load(path, allow_pickle=False)
            for name, arm in policy.arms.items():
                A_key = f"A__{name}"
                B_key = f"b__{name}"
                if A_key in data and B_key in data:
                    arm.A = data[A_key]
                    arm.b = data[B_key]
            # print(f"[AI] Loaded LinUCB state for {key} from {path}")
        except Exception as e:
            print(f"[AI] Failed to load LinUCB state for {key}: {e}")

    def _maybe_save_policy(self, symbol: Optional[str], policy: LinUCBPolicy) -> None:
        key = symbol or "__GLOBAL__"
        now = time.time()
        last = self._last_save_ts.get(key, 0.0)
        if now - last < self.save_every_sec:
            return
        try:
            payload = {}
            for name, arm in policy.arms.items():
                payload[f"A__{name}"] = arm.A
                payload[f"b__{name}"] = arm.b
            np.savez_compressed(self._state_path(key), **payload)
            self._last_save_ts[key] = now
        except Exception as e:
            print(f"[AI] Failed to save LinUCB state for {key}: {e}")

    # ---------------- internal: decision gating -------------------------------

    def _scores(self, policy: LinUCBPolicy, x: np.ndarray) -> Dict[str, float]:
        return {name: arm.ucb(x) for name, arm in policy.arms.items()}

    def _apply_uncertainty_gate(self, symbol: str, best_name: str, scores: Dict[str, float]) -> str:
        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_action, best_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else -1e9

        # --- Cold-start: if all arms have ~identical scores, allow exploration instead of HOLD ---
        try:
            import numpy as _np
            vals = _np.array(list(scores.values()), dtype=float)
            if _np.nanstd(vals) < 1e-9:
                return best_name
        except Exception:
            pass

        # Margin / floor gates
        if (best_score - second_score) < self.min_ucb_margin:
            return "Hold"
        if best_score < self.ucb_floor:
            return "Hold"

        # Flip cooldown
        last = self._last_action.get(symbol)
        last_ts = self._last_action_ts.get(symbol, 0.0)
        if last and last != best_action and (time.time() - last_ts) < self.flip_cooldown_sec:
            return "Hold"

        return best_name

    def _uncertainty_value(self, scores: Dict[str, float]) -> float:
        # 0 = confident, 1 = uncertain (based on top-2 spread)
        ordered = sorted(scores.values(), reverse=True)
        if not ordered:
            return 1.0
        best = ordered[0]
        second = ordered[1] if len(ordered) > 1 else best - 1e-6
        denom = abs(best) + abs(second) + 1e-9
        margin = (best - second) / denom
        u = float(max(0.0, 1.0 - margin))
        return min(1.0, u)

    # ---------------- public API ----------------------------------------------

    def decide(self, df: pd.DataFrame, symbol: Optional[str] = None) -> MetaDecision:
        """
        Choose an action. Pass `symbol` to enable per-symbol learning (recommended).
        """
        x = compute_features(df)
        policy = self._get_policy(symbol)
        scores = self._scores(policy, x)
        best_name = max(scores, key=scores.get)

        gated = self._apply_uncertainty_gate(symbol or "__GLOBAL__", best_name, scores)
        # Map action to strategy/params
        strategy, params = ACTIONS[gated]
        uncertainty = self._uncertainty_value(scores)
        return MetaDecision(action=gated, strategy=strategy, params=params, uncertainty=uncertainty)

    def learn(self, df: pd.DataFrame, action: str, reward: float, symbol: Optional[str] = None) -> None:
        """
        Update the policy with observed reward. Pass `symbol` to learn per-symbol.
        """
        x = compute_features(df)
        policy = self._get_policy(symbol)
        # Ensure the action exists (if we forced HOLD)
        if action not in policy.arms:
            action = "Hold"
        policy.update(action, x, reward)

        key = symbol or "__GLOBAL__"
        self._last_action[key] = action
        self._last_action_ts[key] = time.time()
        self._maybe_save_policy(symbol, policy)

    # Convenience wrappers, if you prefer explicit names
    def decide_for_symbol(self, symbol: str, df: pd.DataFrame) -> MetaDecision:
        return self.decide(df, symbol=symbol)

    def learn_for_symbol(self, symbol: str, df: pd.DataFrame, action: str, reward: float) -> None:
        self.learn(df, action, reward, symbol=symbol)
