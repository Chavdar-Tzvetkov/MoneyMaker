# ai/llm_decider.py
from __future__ import annotations
import os, json
from typing import Dict, Any, Optional
import pandas as pd

from openai import OpenAI

_MODEL = os.getenv("LLM_MODEL", "gpt-5")
_API_KEY = os.getenv("OPENAI_API_KEY", "")

# temperature: only send when exactly 1.0; many models force default=1
_TEMP_RAW = (os.getenv("LLM_TEMPERATURE", "").strip() or None)
try:
    _TEMPERATURE: Optional[float] = float(_TEMP_RAW) if _TEMP_RAW is not None else None
except Exception:
    _TEMPERATURE = None

_client: Optional[OpenAI] = None
def _cli() -> Optional[OpenAI]:
    global _client
    if _client is None and _API_KEY:
        _client = OpenAI(api_key=_API_KEY)
    return _client

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "strategy": {"type": "string", "enum": ["SMA", "SCALPING", "RSI_MR", "DONCHIAN", "SUPER", "MACD", "RANGE_MR", "HOLD"]},
        "params":   {"type": "object"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["decision", "strategy", "confidence"]
}

SYS_PROMPT = (
    "You are a conservative trading meta-advisor. Output strict JSON only.\n"
    "Use the numeric features and technical context provided. Do not invent prices.\n"
    "If uncertain, prefer HOLD with lower confidence.\n"
)

def _pack_features(df: pd.DataFrame) -> Dict[str, Any]:
    c = df["Close"].astype(float)
    o = df["Open"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)

    def mom(n: int) -> float:
        if len(c) > n and c.iloc[-n] != 0:
            return float(c.iloc[-1] / c.iloc[-n] - 1.0)
        return 0.0

    ret1  = float(c.pct_change().iloc[-1]) if len(c) > 1 else 0.0
    vol20 = float(c.pct_change().rolling(20).std().iloc[-1] or 0.0) if len(c) > 21 else 0.0
    sma20 = float(c.rolling(20).mean().iloc[-1] or c.iloc[-1]) if len(c) >= 20 else float(c.iloc[-1])
    sma50 = float(c.rolling(50).mean().iloc[-1] or c.iloc[-1]) if len(c) >= 50 else float(c.iloc[-1])
    denom = sma50 if sma50 != 0 else 1.0
    delta = (sma20 - sma50) / denom
    hi    = float(h.rolling(20).max().iloc[-1] if len(h) >= 20 else h.iloc[-1])
    lo    = float(l.rolling(20).min().iloc[-1] if len(l) >= 20 else l.iloc[-1])
    rng   = (hi - lo) / (lo if lo else 1.0) if hi and lo else 0.0

    return {
        "ret1": ret1, "vol20": vol20,
        "m5": mom(5), "m20": mom(20), "m50": mom(50),
        "sma20": sma20, "sma50": sma50, "delta": delta,
        "range20": rng
    }

def _responses_create(cli: OpenAI, payload: Dict[str, Any], temperature: Optional[float]):
    kwargs = dict(
        model=_MODEL,
        input=[
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user",   "content": json.dumps(payload)}
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "TradeDecision", "schema": SCHEMA, "strict": True}
        },
    )
    # Only set temperature if it’s exactly default 1.0; otherwise omit to satisfy models that lock it.
    if temperature is not None and abs(temperature - 1.0) < 1e-12:
        kwargs["temperature"] = temperature
    return cli.responses.create(**kwargs)

def llm_decide(symbol: str, df: pd.DataFrame, candidate_from_quant: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    cli = _cli()
    if cli is None:
        return None

    feats = _pack_features(df)
    user_prompt = {
        "symbol": symbol,
        "features": feats,
        "quant_hint": candidate_from_quant or {},
        "instructions": (
            "Decide BUY/SELL/HOLD and pick a strategy now.\n"
            "If SMA20~SMA50 and vol high -> RANGE_MR or HOLD.\n"
            "If strong, sustained trend -> SMA or MACD.\n"
            "Return strict JSON."
        ),
    }

    # Try with Responses API
    raw = None
    try:
        resp = _responses_create(cli, user_prompt, _TEMPERATURE)
        raw = resp.output_text
    except TypeError:
        # Old SDK: fallback to Chat Completions JSON mode
        try:
            cc_kwargs = dict(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": SYS_PROMPT},
                    {"role": "user",   "content": json.dumps(user_prompt)},
                ],
                response_format={"type": "json_object"},
            )
            if _TEMPERATURE is not None and abs(_TEMPERATURE - 1.0) < 1e-12:
                cc_kwargs["temperature"] = _TEMPERATURE
            resp = cli.chat.completions.create(**cc_kwargs)
            raw = resp.choices[0].message.content
        except Exception as e2:
            print(f"[LLM] decision failed (chat fallback): {e2}")
            return None
    except Exception as e:
        # Retry once without temperature if user set a non-default
        if _TEMPERATURE is not None and abs(_TEMPERATURE - 1.0) > 1e-12:
            try:
                resp = _responses_create(cli, user_prompt, None)
                raw = resp.output_text
                print("[LLM] retried without temperature (model enforces default=1).")
            except Exception as e2:
                print(f"[LLM] decision failed: {e2}")
                return None
        else:
            print(f"[LLM] decision failed: {e}")
            return None

    try:
        data = json.loads(raw)
        return {
            "decision":   (data.get("decision") or "HOLD").upper(),
            "strategy":   (data.get("strategy") or "HOLD"),
            "params":     data.get("params", {}) or {},
            "confidence": float(data.get("confidence", 0.0)),
        }
    except Exception as pe:
        print(f"[LLM] parse failed: {pe} raw={str(raw)[:240]}")
        return None

def combine_llm_with_quant(
    quant_outcome: str,
    llm: Optional[Dict[str, Any]],
    *,
    mode: str = "TIE_BREAK",
    min_conf: float = 0.65
) -> str:
    if mode == "OFF" or llm is None:
        return quant_outcome

    q = (quant_outcome or "HOLD").upper()
    l_dec = (llm.get("decision") or "HOLD").upper()
    conf = float(llm.get("confidence", 0.0))

    if mode == "PRIMARY":
        return l_dec if conf >= min_conf else "HOLD"
    if mode == "VETO":
        return "HOLD" if (q != "HOLD" and conf < min_conf) else q
    if mode == "TIE_BREAK":
        return l_dec if (q == "HOLD" and conf >= min_conf) else q
    return q
