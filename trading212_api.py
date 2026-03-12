# trading212_api.py
import os
import time
import random
from typing import Optional, Dict, Any, List, Union, Tuple
import requests
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from datetime import date

from db.db_session import SessionLocal
from db.models import TradeLog
from services.pnl_service import record_equity_close

# for reconciliation + symbol mapping
from services.position_service import upsert_position as db_upsert_position
from utils.symbols import normalize_symbol

load_dotenv()

# ---------------------------------------------------------------------
# Config / env
# ---------------------------------------------------------------------
API_KEY_RAW = os.getenv("TRADING212_API_KEY") or ""
API_KEY = API_KEY_RAW.replace("Bearer ", "").strip()
BASE_URL = (os.getenv("BASE_URL") or "").rstrip("/")  # e.g. https://demo.trading212.com

# Portfolio polling / cache TTL (seconds)
_PORTFOLIO_TTL = float(os.getenv("T212_PORTFOLIO_TTL", "6"))

# Global backoff controls for /equity/portfolio (seconds)
_BACKOFF_INIT = float(os.getenv("T212_BACKOFF_INIT_SEC", "1.7"))
_BACKOFF_MAX  = float(os.getenv("T212_BACKOFF_MAX_SEC",  "18"))

# Turn on extra logs by setting T212_DEBUG=1
T212_DEBUG = os.getenv("T212_DEBUG", "0") == "1"
# Disable metadata/search by default (Demo doesn't support it)
T212_USE_SEARCH = os.getenv("T212_USE_SEARCH", "0") == "1"

HEADERS = {
    "Authorization": API_KEY,
    "Accept": "application/json",
    "User-Agent": "MoneyMakerBot/1.0",
}

MAX_RETRIES = 3
RETRY_DELAY = 1.5  # base seconds; we’ll add jitter on 429 (for non-portfolio calls)
http = requests.Session()

# ---------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------
# Instruments cache (for ticker resolution)
_INSTRUMENTS_CACHE_TS = 0.0
_INSTRUMENTS_CACHE: List[Dict[str, Any]] = []
_INSTRUMENTS_TTL = 60 * 30  # 30 minutes

# Portfolio cache (for live equity qty reads)
_PORTFOLIO_CACHE_TS = 0.0
_PORTFOLIO_CACHE: List[Dict[str, Any]] = []

# Global backoff state for /equity/portfolio
_BACKOFF_UNTIL = 0.0
_BACKOFF_CURR = _BACKOFF_INIT

# manual overrides for tricky dual-class / aliases
_TICKER_OVERRIDES = {
    "GOOGL": "GOOGL_US_EQ",
    "GOOG":  "GOOG_US_EQ",
    "BRK.A": "BRK.A_US_EQ",
    "BRK.B": "BRK.B_US_EQ",
}

# ---------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------
def _is_json_response(resp: requests.Response) -> bool:
    ctype = resp.headers.get("Content-Type", "")
    return "application/json" in ctype.lower()

def _safe_request(method: str, url: str, **kwargs) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
    """
    HTTP with retry/backoff and tolerant JSON handling.
    - Returns JSON for 2xx/3xx.
    - For 4xx with JSON (error bodies), returns that JSON immediately (no retries).
    - 429: backs off and retries with jitter.
    NOTE: Portfolio calls use a separate global backoff; this helper is for other endpoints.
    """
    for attempt in range(MAX_RETRIES):
        try:
            resp = http.request(method, url, headers=HEADERS, timeout=15, **kwargs)

            # Success-ish
            if 200 <= resp.status_code < 400:
                if not resp.content:
                    return None
                return resp.json() if _is_json_response(resp) else {"_non_json": True, "_len": len(resp.content)}

            # Too many requests → backoff + retry
            if resp.status_code == 429:
                wait = RETRY_DELAY * (attempt + 1) + random.uniform(0.25, 0.75)
                print(f"[T212 RATE] 429 on {url}. Backing off {wait:.2f}s...")
                time.sleep(wait)
                continue  # retry

            # 4xx with JSON body → return body so callers can react
            if 400 <= resp.status_code < 500 and _is_json_response(resp):
                data = resp.json()
                print(f"[T212 ERROR] {resp.status_code} {url}: {data}")
                return data

            # auth problems
            if resp.status_code in (401, 403):
                print(f"[T212 AUTH] {resp.status_code} on {url}. Check API key/scopes.")
                return None

            # other errors — log and retry
            print(f"[T212 ERROR] {resp.status_code} {url}: {resp.text[:200]}")

        except requests.RequestException as e:
            print(f"[REQUEST FAIL] ({attempt+1}/{MAX_RETRIES}) {url}: {e}")

        # generic backoff between attempts
        time.sleep(RETRY_DELAY * (attempt + 1))

    return None

# ---------------------------------------------------------------------
# Metadata / search / ticker resolution
# ---------------------------------------------------------------------
def _refresh_instruments_cache(force: bool = False):
    global _INSTRUMENTS_CACHE, _INSTRUMENTS_CACHE_TS
    now = time.time()
    if not force and (now - _INSTRUMENTS_CACHE_TS) < _INSTRUMENTS_TTL and _INSTRUMENTS_CACHE:
        return
    if not BASE_URL or not API_KEY:
        return
    url = f"{BASE_URL}/api/v0/equity/metadata/instruments"
    data = _safe_request("GET", url)
    if isinstance(data, list):
        _INSTRUMENTS_CACHE = data
        _INSTRUMENTS_CACHE_TS = now
    else:
        print("[T212] Failed to refresh instruments metadata; ticker resolution may be limited.")

def _search_ticker(text: str) -> Optional[str]:
    """
    Optional search endpoint. DEMO usually returns 404.
    We only call it when T212_USE_SEARCH=1.
    """
    if not T212_USE_SEARCH:
        return None
    if not BASE_URL or not API_KEY:
        return None

    url = f"{BASE_URL}/api/v0/equity/metadata/search"
    data = _safe_request("GET", url, params={"text": text})
    if not isinstance(data, list):
        return None

    text_up = text.upper()
    # prefer exact ticker match, else first STOCK/ETF containing the text
    for it in data:
        t = (it.get("ticker") or "").upper()
        if t == text_up:
            return t
    for it in data:
        t = (it.get("ticker") or "").upper()
        itype = (it.get("type") or "").upper()
        if itype in ("STOCK", "ETF") and (t.startswith(text_up) or text_up in t):
            return t
    return None


def _resolve_ticker(symbol: str) -> Optional[str]:
    """
    Resolve base symbol (e.g., 'AAPL') to T212 ticker (e.g., 'AAPL_US_EQ').
    Order:
      1) manual overrides
      2) instruments cache exact match on 'ticker'
      3) cache prefix match (STOCK/ETF)
      4) (optional) search endpoint if T212_USE_SEARCH=1
      5) conservative fallback SYMBOL_US_EQ
    """
    base = symbol.strip().upper()

    if base in _TICKER_OVERRIDES:
        return _TICKER_OVERRIDES[base]

    _refresh_instruments_cache()
    instruments = _INSTRUMENTS_CACHE or []

    # exact match on ticker
    for ins in instruments:
        t = (ins.get("ticker") or "").upper()
        if t == base:
            return t

    # prefix match for STOCK/ETF
    for ins in instruments:
        t = (ins.get("ticker") or "").upper()
        itype = (ins.get("type") or "").upper()
        if itype in ("STOCK", "ETF") and t.startswith(base + "_"):
            return t

    # optional search (disabled by default for Demo)
    if T212_USE_SEARCH:
        found = _search_ticker(base)
        if found:
            return found

    # fallback
    guess = f"{base}_US_EQ"
    if T212_DEBUG:
        print(f"[T212 WARN] Using fallback ticker guess: {guess}")
    return guess


def _ticker_to_symbol(ticker: str) -> str:
    """
    Map 'AAPL_US_EQ' -> 'AAPL'. Safe default: split at first '_' and take the left side.
    """
    if not ticker:
        return ""
    base = ticker.split("_", 1)[0].strip().upper()
    # normalize (your DB uses normalized symbols as keys)
    return normalize_symbol(base)

# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------
def get_account_info() -> Optional[Dict[str, Any]]:
    if not BASE_URL or not API_KEY:
        return None
    url = f"{BASE_URL}/api/v0/equity/account/info"
    info = _safe_request("GET", url)
    if isinstance(info, dict) and info.get("_non_json"):
        print("[T212] Account info not available.")
        return None
    return info if isinstance(info, dict) else None

def list_open_positions(force: bool = False) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch all open T212 equity positions (cached with global backoff).
    Each item usually includes: ticker, quantity, averagePrice/currentPrice, etc.
    During a 429 backoff window we serve the last cached snapshot without re-hitting the API.
    """
    global _PORTFOLIO_CACHE, _PORTFOLIO_CACHE_TS, _BACKOFF_UNTIL, _BACKOFF_CURR

    now = time.time()

    # Serve from cache if TTL not expired and not forced
    if _PORTFOLIO_CACHE and not force and (now - _PORTFOLIO_CACHE_TS) < _PORTFOLIO_TTL:
        return _PORTFOLIO_CACHE

    # If we're in a backoff window, return stale cache (if any) and don't fetch
    if now < _BACKOFF_UNTIL:
        if T212_DEBUG:
            remaining = _BACKOFF_UNTIL - now
            print(f"[T212 RATE] Serving stale portfolio (backoff {remaining:.2f}s left)")
        return _PORTFOLIO_CACHE if _PORTFOLIO_CACHE else None

    if not BASE_URL or not API_KEY:
        return _PORTFOLIO_CACHE if _PORTFOLIO_CACHE else None

    url = f"{BASE_URL}/api/v0/equity/portfolio"
    try:
        resp = http.get(url, headers=HEADERS, timeout=15)

        # 429: set/extend global backoff and return stale cache
        if resp.status_code == 429:
            jitter = random.uniform(0.15, 0.35) * _BACKOFF_CURR
            wait_s = min(_BACKOFF_CURR + jitter, _BACKOFF_MAX)
            _BACKOFF_UNTIL = time.time() + wait_s
            _BACKOFF_CURR = min(_BACKOFF_CURR * 1.6, _BACKOFF_MAX)
            print(f"[T212 RATE] 429 on {url}. Backing off {wait_s:.2f}s...")
            return _PORTFOLIO_CACHE if _PORTFOLIO_CACHE else None

        # Auth issues — don't nuke the cache
        if resp.status_code in (401, 403):
            print(f"[T212 AUTH] {resp.status_code} on {url}. Check API key/scopes.")
            return _PORTFOLIO_CACHE if _PORTFOLIO_CACHE else None

        resp.raise_for_status()
        data = resp.json() if _is_json_response(resp) else None

        if isinstance(data, list):
            _PORTFOLIO_CACHE = data
            _PORTFOLIO_CACHE_TS = now
            _BACKOFF_CURR = _BACKOFF_INIT  # reset backoff on success

            # --- DEBUG: show exactly what T212 returned (first 12) ---
            if T212_DEBUG:
                try:
                    sample = ", ".join(
                        f"{(it.get('ticker') or '').strip()}={it.get('quantity')}"
                        for it in _PORTFOLIO_CACHE[:12]
                    )
                    print(f"[T212 RAW] {len(_PORTFOLIO_CACHE)} items → {sample}")
                except Exception:
                    pass
            # ---------------------------------------------------------
            return _PORTFOLIO_CACHE

        # Unexpected payload, keep last good cache
        if T212_DEBUG:
            print(f"[T212 WARN] Unexpected portfolio payload: {type(data)}")
        return _PORTFOLIO_CACHE if _PORTFOLIO_CACHE else None

    except requests.RequestException as e:
        if T212_DEBUG:
            print(f"[T212] portfolio fetch error: {e}")
        # Keep serving stale until next allowed attempt
        return _PORTFOLIO_CACHE if _PORTFOLIO_CACHE else None

def invalidate_portfolio_cache() -> None:
    """Force a refresh on next call (respects backoff window)."""
    global _PORTFOLIO_CACHE_TS
    _PORTFOLIO_CACHE_TS = 0.0

def list_orders() -> Optional[List[Dict[str, Any]]]:
    if not BASE_URL or not API_KEY:
        return None
    url = f"{BASE_URL}/api/v0/equity/orders"
    data = _safe_request("GET", url)
    return data if isinstance(data, list) else None

def get_current_price(symbol: str) -> Optional[float]:
    # Equity API has no price endpoint; keep returning None so caller uses yfinance.
    return None

def place_market_order(symbol: str, quantity: float) -> bool:
    """
    POST /api/v0/equity/orders/market
    Body: { "ticker": "<AAPL_US_EQ>", "quantity": <number> }
    NOTE: quantity >0 = buy; quantity <0 = sell (must have holdings; equities cannot short).
    """
    if not BASE_URL or not API_KEY:
        print("[T212] place_market_order skipped (no API config).")
        return False

    ticker = _resolve_ticker(symbol)
    if not ticker:
        print(f"[T212] Could not resolve ticker for {symbol}.")
        return False

    url = f"{BASE_URL}/api/v0/equity/orders/market"
    payload = {
        "ticker": ticker,
        "quantity": float(quantity),
    }

    data = _safe_request("POST", url, json=payload)
    # If 4xx JSON was returned, _safe_request already logged it and returned the body.
    if isinstance(data, dict) and "id" in data:
        _log_trade_and_pnl(symbol, "BUY" if quantity > 0 else "SELL", 0.0, int(abs(quantity)))
        # orders affect holdings; nudge cache to refresh next read
        invalidate_portfolio_cache()
        return True

    if isinstance(data, dict) and "code" in data:
        # example: {"code":"InstrumentNotFound","clarification":null}
        print(f"[T212 ORDER ERROR] {data.get('code')} {data.get('clarification')}")
        return False

    if data is None:
        print("[T212] Empty/failed response placing order.")
        return False

    # Unexpected structure
    print(f"[T212 ORDER ERROR] Unexpected response: {data}")
    return False

# ---------------------------------------------------------------------
# Live equity position helpers (for full automation)
# ---------------------------------------------------------------------
def get_equity_position_qty(symbol: str, *, force_refresh: bool = False) -> float:
    """
    Return live quantity for an equity symbol from T212 (uses cached /portfolio).
    - Positive -> long; 0.0 if no open position.
    - This is what the strategy loop should read to compare LIVE vs DB for equities.
    """
    positions = list_open_positions(force=force_refresh) or []
    if not positions:
        return 0.0

    # try to match on resolved ticker first
    ticker = _resolve_ticker(symbol)
    if ticker:
        for p in positions:
            if (p.get("ticker") or "").upper() == ticker.upper():
                try:
                    qty = float(p.get("quantity") or 0.0)
                except (TypeError, ValueError):
                    qty = 0.0
                if T212_DEBUG:
                    print(f"[T212 POSCHK] {symbol}: matched ticker {ticker} qty={qty}")
                return qty

    # fallback: match by base symbol (AAPL from AAPL_US_EQ)
    base = normalize_symbol(symbol)
    for p in positions:
        t_sym = _ticker_to_symbol(p.get("ticker") or "")
        if t_sym == base:
            try:
                qty = float(p.get("quantity") or 0.0)
            except (TypeError, ValueError):
                qty = 0.0
            if T212_DEBUG:
                print(f"[T212 POSCHK] {symbol}: matched base {t_sym} from {p.get('ticker')} qty={qty}")
            return qty

    return 0.0

def reconcile_t212_portfolio_to_db(*, force_refresh: bool = False) -> Tuple[int, int]:
    """
    Pull live equities portfolio from T212 and write into DB with overwrite=True.
    Returns: (updated_count, skipped_count)
    - Only touches equities (FX positions are handled via MT5 elsewhere).
    - If a symbol isn't present in the broker's portfolio, we do NOT zero it here;
      your live loop should detect LIVE=0 vs DB!=0 and call db_upsert_position(..., overwrite=True)
      when reconciling per symbol. (This keeps this function idempotent and safe.)
    """
    positions = list_open_positions(force=force_refresh) or []
    if not positions:
        return (0, 0)

    updated = 0
    skipped = 0
    for p in positions:
        try:
            ticker = (p.get("ticker") or "").strip()
            qty = float(p.get("quantity") or 0.0)
            avg_price = float(p.get("averagePrice") or 0.0)

            if not ticker:
                skipped += 1
                continue

            symbol = _ticker_to_symbol(ticker)
            if not symbol:
                skipped += 1
                continue

            # Overwrite DB with broker truth for this equity symbol
            db_upsert_position(symbol, qty, avg_price if qty != 0 else 0.0, overwrite=True)
            updated += 1
        except Exception as e:
            print(f"[T212 RECON] Skip one ({p}): {e}")
            skipped += 1

    return (updated, skipped)

def debug_dump_portfolio_map():
    """
    Safe debug helper: prints open positions only when T212_DEBUG=1.
    Avoids hitting metadata/search endpoints that are disabled on Demo.
    """
    if not T212_DEBUG:
        return
    try:
        pos = list_open_positions() or []
        tickers = [f"{(p.get('ticker') or '').strip()}={p.get('quantity')}" for p in pos]
        print(f"[T212 DEBUG] {len(pos)} open positions → " + ", ".join(tickers))
    except Exception as e:
        print(f"[T212 DEBUG] skipped (non-critical): {e}")


# ---------------------------------------------------------------------
# DB logging (unchanged)
# ---------------------------------------------------------------------
def _log_trade_and_pnl(symbol: str, action: str, price: float, quantity: int) -> None:
    """
    Lightweight trade logger for T212 equity orders.

    - Persists a TradeLog row with the requested price/quantity.
    - Realized PnL is computed and written via services.pnl_service.record_equity_close
      from the live trading loop, using broker-backed entry prices and current prices.
    """
    session = SessionLocal()
    try:
        session.add(TradeLog(symbol=symbol, action=action, price=price, quantity=quantity))
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"[DB ERROR] {e}")
    finally:
        session.close()
