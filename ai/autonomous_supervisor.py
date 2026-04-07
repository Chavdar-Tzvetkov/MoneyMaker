from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SupervisorOverrides:
    max_uncertainty: float
    atr_min_fx: float
    grace_bps_fx: float
    fx_risk_mult: float
    eq_risk_mult: float


class AutonomousSupervisor:
    """
    Lightweight autonomous tuner for live execution knobs.
    It only moves within bounded ranges to avoid runaway behavior.
    """

    def __init__(
        self,
        *,
        max_uncertainty: float,
        atr_min_fx: float,
        grace_bps_fx: float,
        tune_every_cycles: int = 20,
    ) -> None:
        self.max_uncertainty = max_uncertainty
        self.atr_min_fx = atr_min_fx
        self.grace_bps_fx = grace_bps_fx
        self.fx_risk_mult = 1.0
        self.eq_risk_mult = 1.0
        self.tune_every_cycles = max(5, int(tune_every_cycles))

        self._cycle = 0
        self._fx_order_attempts = 0
        self._fx_order_success = 0
        self._fx_block_model_filters = 0
        self._fx_block_circuit = 0

    def record_metric(self, *, is_fx: bool, blocked_by: str, order_result: str) -> None:
        if not is_fx:
            return
        b = (blocked_by or "").strip().lower()
        o = (order_result or "").strip().lower()

        if b == "circuit_breaker":
            self._fx_block_circuit += 1
        elif b == "model_or_filters":
            self._fx_block_model_filters += 1

        if o and o != "-":
            self._fx_order_attempts += 1
            if ("order ok" in o) or ("order placed" in o):
                self._fx_order_success += 1

    def on_cycle_end(self, *, mt5_eq: float, pnl_fx: float, halted_fx: bool) -> SupervisorOverrides | None:
        self._cycle += 1
        if self._cycle % self.tune_every_cycles != 0:
            return None

        # If account is halted, do not keep loosening in this window.
        if not halted_fx:
            # If we're getting no attempts and mostly blocked by model/filters, relax gently.
            if self._fx_order_attempts == 0 and self._fx_block_model_filters > 0:
                self.atr_min_fx = max(0.00005, self.atr_min_fx * 0.90)
                self.grace_bps_fx = min(180.0, self.grace_bps_fx + 8.0)
                self.max_uncertainty = min(1.0, self.max_uncertainty + 0.01)

        pnl_frac = (pnl_fx / mt5_eq) if mt5_eq > 0 else 0.0
        if pnl_frac <= -0.08:
            self.fx_risk_mult = 0.55
        elif pnl_frac <= -0.04:
            self.fx_risk_mult = 0.75
        elif pnl_frac >= 0.03:
            self.fx_risk_mult = 1.20
        else:
            self.fx_risk_mult = 1.0

        # Keep equities mostly stable from this supervisor.
        self.eq_risk_mult = 1.0

        out = SupervisorOverrides(
            max_uncertainty=self.max_uncertainty,
            atr_min_fx=self.atr_min_fx,
            grace_bps_fx=self.grace_bps_fx,
            fx_risk_mult=self.fx_risk_mult,
            eq_risk_mult=self.eq_risk_mult,
        )

        # Reset per-window counters.
        self._fx_order_attempts = 0
        self._fx_order_success = 0
        self._fx_block_model_filters = 0
        self._fx_block_circuit = 0
        return out
