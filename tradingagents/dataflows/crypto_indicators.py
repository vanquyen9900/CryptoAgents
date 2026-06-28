"""Crypto-native indicator fetchers — Trụ cột D (Crypto Indicators).

Theo research_report.md §3.5:
  Khi asset_type == "crypto", mở rộng vector đặc trưng Market Analyst bằng
  [FNG, DOM, FR, OI]; heuristic cảnh báo đảo chiều khi FNG cực trị ∧ FR lệch
  mạnh ∧ OI tăng nóng (dấu hiệu long/short squeeze).

Sources (all public, no API key needed for basic tiers):
  - FNG  : alternative.me/fng
  - DOM  : api.coingecko.com/api/v3/global
  - FR   : fapi.binance.com/fapi/v1/fundingRate  (USDT-M perpetual)
  - OI   : fapi.binance.com/fapi/v1/openInterest (USDT-M perpetual)

All fetchers degrade gracefully — they return an error key instead of raising,
so the Market Analyst always receives a coherent string even when an API is down.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Internal HTTP helper
# ─────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CryptoAgents/1.0; +https://github.com)",
    "Accept": "application/json",
}
_TIMEOUT = 10  # seconds


def _http_get(url: str) -> Optional[dict | list]:
    """GET ``url``, parse JSON; return None on any error."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("HTTP GET failed (%s): %s", url, exc)
        return None


# ─────────────────────────────────────────────────────────────
# Symbol normalisation
# ─────────────────────────────────────────────────────────────

def _base_asset(symbol: str) -> str:
    """BTC-USD / ETH-USDT → BTC / ETH for Binance/CoinGecko lookups."""
    s = symbol.upper().strip()
    for suffix in ("-USD", "-USDT", "-USDC", "-BTC", "-ETH", "-BUSD", "-DAI"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


# ─────────────────────────────────────────────────────────────
# 1. Fear & Greed Index (alternative.me)
# ─────────────────────────────────────────────────────────────

def fetch_fng(limit: int = 3) -> dict:
    """Return latest Fear & Greed index and a short history.

    Returns dict with keys:
      value   – int 0-100
      label   – str classification
      history – list[{date, value, label}]
      error   – str | None
    """
    data = _http_get(f"https://api.alternative.me/fng/?limit={limit}&format=json")
    if not data or "data" not in data or not data["data"]:
        return {"error": "FNG API unavailable", "value": 50, "label": "Neutral", "history": []}

    entries = data["data"]
    latest = entries[0]
    history = [
        {
            "date": datetime.fromtimestamp(int(e["timestamp"])).strftime("%Y-%m-%d"),
            "value": int(e["value"]),
            "label": e["value_classification"],
        }
        for e in entries
    ]
    return {
        "value": int(latest["value"]),
        "label": latest["value_classification"],
        "history": history,
        "error": None,
    }


def _fng_text(value: int) -> str:
    if value <= 15:
        return f"Extreme Fear ({value}) — potential capitulation / contrarian buy zone."
    if value <= 30:
        return f"Fear ({value}) — bearish sentiment dominant; accumulation territory."
    if value <= 45:
        return f"Mild Fear ({value}) — cautious market; no strong bias."
    if value <= 55:
        return f"Neutral ({value}) — balanced; await confirming signal."
    if value <= 70:
        return f"Greed ({value}) — bullish momentum; watch for overextension."
    if value <= 85:
        return f"High Greed ({value}) — crowded longs; correction risk rising."
    return f"Extreme Greed ({value}) — historically signals near-term reversal; long-squeeze zone."


# ─────────────────────────────────────────────────────────────
# 2. Bitcoin Dominance (CoinGecko /global)
# ─────────────────────────────────────────────────────────────

def fetch_btc_dominance() -> dict:
    """Return BTC market dominance % and total crypto market cap.

    Returns dict with keys:
      btc_dominance        – float %
      total_market_cap_usd – float | None
      error                – str | None
    """
    data = _http_get("https://api.coingecko.com/api/v3/global")
    if not data or "data" not in data:
        return {"error": "CoinGecko global API unavailable", "btc_dominance": None}

    gd = data["data"]
    dom = gd.get("market_cap_percentage", {}).get("btc")
    if dom is None:
        return {"error": "btc dominance field missing", "btc_dominance": None}

    return {
        "btc_dominance": round(float(dom), 2),
        "total_market_cap_usd": gd.get("total_market_cap", {}).get("usd"),
        "error": None,
    }


def _dominance_text(dom: float, base: str) -> str:
    if base == "BTC":
        if dom >= 55:
            return f"BTC dominance {dom:.1f}% — BTC outperforming altcoins; not altcoin season."
        if dom >= 45:
            return f"BTC dominance {dom:.1f}% — moderate; market balanced across assets."
        return f"BTC dominance {dom:.1f}% — altcoin season signal; risk appetite elevated."
    if dom >= 55:
        return f"BTC dominance {dom:.1f}% — capital concentrated in BTC; headwinds for {base}."
    if dom >= 45:
        return f"BTC dominance {dom:.1f}% — neutral; {base} can trade on own fundamentals."
    return f"BTC dominance {dom:.1f}% — altcoin-favoring environment; tailwind for {base}."


# ─────────────────────────────────────────────────────────────
# 3. Funding Rate (Binance USDT-M perpetual)
# ─────────────────────────────────────────────────────────────

def fetch_funding_rate(symbol: str) -> dict:
    """Return latest perpetual funding rate from Binance USDT-M.

    Returns dict with keys:
      binance_symbol   – str
      funding_rate     – float (e.g. 0.0001 = 0.01 %)
      funding_rate_pct – float
      annualized_pct   – float
      funding_time     – str ISO
      error            – str | None
    """
    base = _base_asset(symbol)
    bn_sym = f"{base}USDT"
    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={bn_sym}&limit=1"
    data = _http_get(url)

    if not data or not isinstance(data, list) or len(data) == 0:
        return {"error": f"Funding rate unavailable for {bn_sym}", "funding_rate": 0.0}

    entry = data[0]
    fr = float(entry.get("fundingRate", 0))
    ft = entry.get("fundingTime")
    ft_str = datetime.fromtimestamp(int(ft) / 1000).isoformat() if ft else "unknown"

    return {
        "binance_symbol": bn_sym,
        "funding_rate": fr,
        "funding_rate_pct": round(fr * 100, 6),
        "annualized_pct": round(fr * 3 * 365 * 100, 2),  # 3 settlements/day × 365
        "funding_time": ft_str,
        "error": None,
    }


def _funding_text(fr: float) -> str:
    pct = fr * 100
    if pct > 0.05:
        return (
            f"Funding {pct:.4f}% — strongly positive: longs paying shorts heavily. "
            "Crowded long trade; elevated long-liquidation risk on price drop."
        )
    if pct > 0.01:
        return f"Funding {pct:.4f}% — mildly positive: healthy bullish bias, no extreme crowding."
    if pct >= -0.01:
        return f"Funding {pct:.4f}% — near-zero: balanced long/short positioning."
    if pct >= -0.05:
        return f"Funding {pct:.4f}% — mildly negative: shorts paying longs; bearish bias."
    return (
        f"Funding {pct:.4f}% — strongly negative: heavy short bias. "
        "Short-squeeze risk on any positive catalyst."
    )


# ─────────────────────────────────────────────────────────────
# 4. Open Interest (Binance USDT-M perpetual)
# ─────────────────────────────────────────────────────────────

def fetch_open_interest(symbol: str) -> dict:
    """Return current open interest from Binance USDT-M.

    Returns dict with keys:
      binance_symbol    – str
      open_interest     – float (contracts)
      open_interest_usd – float | None
      mark_price        – float | None
      error             – str | None
    """
    base = _base_asset(symbol)
    bn_sym = f"{base}USDT"

    oi_data = _http_get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={bn_sym}")
    if not oi_data or "openInterest" not in oi_data:
        return {"error": f"Open interest unavailable for {bn_sym}", "open_interest": None}

    oi = float(oi_data["openInterest"])

    px_data = _http_get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={bn_sym}")
    mark_price = None
    if px_data and "markPrice" in px_data:
        mark_price = float(px_data["markPrice"])

    return {
        "binance_symbol": bn_sym,
        "open_interest": oi,
        "open_interest_usd": round(oi * mark_price, 0) if mark_price else None,
        "mark_price": mark_price,
        "error": None,
    }


# ─────────────────────────────────────────────────────────────
# 5. Squeeze heuristic (report §3.5)
# ─────────────────────────────────────────────────────────────

def evaluate_squeeze_risk(fng_value: int, fr: float, oi_usd: Optional[float]) -> dict:
    """Evaluate long/short-squeeze risk from the three crypto-native signals.

    Heuristic from report §3.5:
      Cảnh báo khi FNG cực trị (<15 or >85)
                AND FR lệch mạnh (|FR| > 0.05%)
                AND OI tăng nóng  (OI_USD > $5B)

    Returns:
      squeeze_type    – "long_squeeze_risk" | "short_squeeze_risk" | "none"
      signal_strength – "high" | "medium" | "none"
      explanation     – str
    """
    pct = fr * 100
    extreme_greed = fng_value >= 85
    extreme_fear = fng_value <= 15
    fr_pos = pct > 0.05
    fr_neg = pct < -0.05
    oi_hot = oi_usd is not None and oi_usd > 5_000_000_000  # $5B threshold

    if extreme_greed and fr_pos:
        strength = "high" if oi_hot else "medium"
        return {
            "squeeze_type": "long_squeeze_risk",
            "signal_strength": strength,
            "explanation": (
                f"WARNING LONG SQUEEZE RISK [{strength.upper()}]: "
                f"FNG={fng_value} (Extreme Greed), FR={pct:.4f}% (strongly positive), "
                + (f"OI=${oi_usd/1e9:.1f}B (elevated)." if oi_hot else "OI data limited.")
                + " Market is over-leveraged long — a price drop could trigger cascading liquidations."
            ),
        }

    if extreme_fear and fr_neg:
        strength = "high" if oi_hot else "medium"
        return {
            "squeeze_type": "short_squeeze_risk",
            "signal_strength": strength,
            "explanation": (
                f"WARNING SHORT SQUEEZE RISK [{strength.upper()}]: "
                f"FNG={fng_value} (Extreme Fear), FR={pct:.4f}% (strongly negative), "
                + (f"OI=${oi_usd/1e9:.1f}B (elevated)." if oi_hot else "OI data limited.")
                + " Market is over-leveraged short — any positive catalyst could spark rapid covering."
            ),
        }

    return {
        "squeeze_type": "none",
        "signal_strength": "none",
        "explanation": "No extreme squeeze conditions detected at this time.",
    }


# ─────────────────────────────────────────────────────────────
# 6. Composite report (entry point for the LangChain tool)
# ─────────────────────────────────────────────────────────────

def get_crypto_native_indicators(symbol: str, curr_date: str) -> str:
    """Fetch FNG + DOM + FR + OI, return a formatted markdown report.

    Called by the ``get_crypto_indicators`` LangChain @tool injected into the
    Market Analyst only when ``asset_type == 'crypto'``.

    Args:
        symbol:    Crypto ticker, e.g. "BTC-USD" or "ETH-USDT"
        curr_date: Analysis date YYYY-MM-DD (for context; APIs return live data)
    """
    base = _base_asset(symbol)
    lines: list[str] = [
        f"## Crypto-native Indicators — {symbol.upper()} | {curr_date}",
        "",
    ]

    # ── FNG ──────────────────────────────────────────────────
    fng = fetch_fng(limit=3)
    fng_value = fng["value"]
    if fng["error"]:
        lines += ["### Fear & Greed Index (FNG)", f"Unavailable: {fng['error']}", ""]
    else:
        trend = " → ".join(
            f"{h['date']}: {h['value']} ({h['label']})" for h in reversed(fng["history"])
        )
        lines += [
            "### Fear & Greed Index (FNG)",
            f"**Current**: {fng_value} — **{fng['label']}**",
            f"**3-day trend**: {trend}",
            f"**Interpretation**: {_fng_text(fng_value)}",
            "",
        ]

    # ── DOM ──────────────────────────────────────────────────
    dom = fetch_btc_dominance()
    dom_value = dom.get("btc_dominance")
    if dom["error"] or dom_value is None:
        lines += ["### Bitcoin Dominance (DOM)", f"Unavailable: {dom.get('error', 'unknown')}", ""]
    else:
        total = dom.get("total_market_cap_usd")
        total_str = f"${total/1e9:.0f}B" if total else "N/A"
        lines += [
            "### Bitcoin Dominance (DOM)",
            f"**BTC Dominance**: {dom_value:.1f}% | Total Market Cap: {total_str}",
            f"**Interpretation**: {_dominance_text(dom_value, base)}",
            "",
        ]

    # ── FR ───────────────────────────────────────────────────
    fr_data = fetch_funding_rate(symbol)
    fr_value = fr_data.get("funding_rate", 0.0)
    if fr_data["error"]:
        lines += ["### Perpetual Funding Rate (FR)", f"Unavailable: {fr_data['error']}", ""]
    else:
        lines += [
            "### Perpetual Funding Rate (FR)",
            f"**Rate**: {fr_data['funding_rate_pct']:.4f}% | Annualised: {fr_data['annualized_pct']:.1f}%",
            f"**Next funding**: {fr_data['funding_time']}",
            f"**Interpretation**: {_funding_text(fr_value)}",
            "",
        ]

    # ── OI ───────────────────────────────────────────────────
    oi_data = fetch_open_interest(symbol)
    oi_usd = oi_data.get("open_interest_usd")
    if oi_data["error"]:
        lines += ["### Open Interest (OI)", f"Unavailable: {oi_data['error']}", ""]
    else:
        oi_usd_str = f"~${oi_usd/1e9:.2f}B" if oi_usd else "N/A"
        mp_str = f"${oi_data['mark_price']:,.2f}" if oi_data.get("mark_price") else "N/A"
        lines += [
            "### Open Interest (OI)",
            f"**OI**: {oi_data['open_interest']:,.0f} contracts | USD value: {oi_usd_str}",
            f"**Mark price**: {mp_str}",
            "",
        ]

    # ── Squeeze heuristic ────────────────────────────────────
    sq = evaluate_squeeze_risk(fng_value, fr_value, oi_usd)
    lines += [
        "### Squeeze Risk Assessment",
        f"**Type**: {sq['squeeze_type']} | **Strength**: {sq['signal_strength']}",
        sq["explanation"],
        "",
        "> Crypto-native indicators reflect live derivatives positioning. "
        "FNG and DOM are BTC-centric; apply judgement for altcoins. "
        "Use these as supplementary signals, weighted alongside price action and HMM regime.",
    ]

    return "\n".join(lines)
