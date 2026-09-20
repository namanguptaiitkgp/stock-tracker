"""Flexible CSV parser for bulk/block/insider disclosures.

Supports at minimum:
- NSE bulk deals CSV     — Date, Symbol, Security Name, Client Name, Buy/Sell,
                            Quantity Traded, Trade Price / Wght. Avg. Price, [Remarks]
- NSE block deals CSV    — same minus Remarks
- BSE bulk/block (CSV export from bseindia.com)
- SEBI insider disclosure CSVs (Reg 7 of PIT) — different columns, we map
  acquirer/seller name + transaction type + value + date + symbol.

Caller provides one or more files; parser returns a list of DealRow plus
warnings for unparseable rows.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime
from typing import Iterable

from app.services.smart_money.analyzer.models import DealRow
from app.services.smart_money.analyzer.party_classifier import classify

logger = logging.getLogger(__name__)


# Column-name variants mapped to canonical keys. Lowercased, punctuation-
# stripped when matching.
_COLUMN_SYNONYMS: dict[str, list[str]] = {
    "date": [
        "date", "trade date", "tradedate", "dt of acquisition", "date of trade",
        "transaction date", "date of transaction",
    ],
    "symbol": [
        "symbol", "scrip code", "security", "company", "stock", "stocks", "nse symbol",
        "scrip", "name of company", "company name",
    ],
    "security_name": ["security name", "security", "scripname", "stock name"],
    "party": [
        "client name", "client", "name of acquirer/disposer", "acquirer/disposer name",
        "name", "party", "name of person", "name of the person",
        "name of the acquirer", "name of the seller",
    ],
    "side": [
        "buy/sell", "buy sell", "buysell", "transaction type", "type of transaction",
        "acquisition/disposal", "acquisition or disposal",
    ],
    "quantity": [
        "quantity traded", "quantity", "no of shares", "no. of shares", "shares traded",
        "no of shares traded", "number of shares", "shares",
    ],
    "price": [
        "trade price / wght. avg. price", "trade price", "price", "wght. avg. price",
        "weighted avg price", "avg price", "average price", "price per share",
        "average trade price", "average trade price(rs)", "average trade price (rs)",
        "average trade price(inr)",
    ],
    "value": [
        "total value", "trade value", "value", "value of transaction", "value(in rs)",
        "value (in rs)", "value(inr)", "value in rs", "total trade value",
        "value traded", "value traded (rs)", "value traded(rs)",
        "value traded(inr)", "value traded (inr)",
    ],
    # Role hint (Promoter/Director/KMP in SEBI PIT disclosures). "category" on its
    # own is overloaded in third-party exports (Tickertape uses it for Bulk/Block)
    # so we detect value type at parse time and fall back to mode_category.
    "category": [
        "category of person", "type of person", "role",
        "category of the person", "promoter/non-promoter", "category",
    ],
    # Bulk/Block/Market/Off-market mode — sometimes labelled "Category",
    # "Mode", "Deal Type", etc.
    "mode_category": [
        "mode", "mode of transaction", "deal type", "transaction mode",
        "type", "deal category",
    ],
    "holdings_change_pct": [
        "% of shareholding", "% shareholding", "change in %", "% change",
        "change in shareholding%", "% holding change", "change %",
        "holdings change", "holdings change(%)", "holdings change (%)",
        "change in shareholding %", "% change in holdings",
    ],
}


# Values that indicate a "Category" column is actually carrying mode info,
# not role info.
_MODE_VALUES = {"bulk", "block", "market", "off market", "off-market", "offmarket"}
_ROLE_VALUES = {
    "promoter", "director", "kmp", "key managerial personnel",
    "designated person", "dp&sap", "promoter group", "insider",
}


def _lower_nopunct(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _build_column_index(header: list[str]) -> dict[str, int]:
    """Return a mapping from canonical key -> column index in this header."""
    normalized = [_lower_nopunct(h) for h in header]
    out: dict[str, int] = {}
    for key, variants in _COLUMN_SYNONYMS.items():
        for v in variants:
            vn = _lower_nopunct(v)
            if vn in normalized:
                out[key] = normalized.index(vn)
                break
    return out


_DATE_FORMATS = (
    "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
    "%d-%b-%y", "%d/%m/%y", "%d %b %Y",
)


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _parse_side(raw: str) -> str | None:
    if not raw:
        return None
    s = raw.strip().upper()
    if s.startswith("B") or "ACQU" in s or "PURCHASE" in s:
        return "BUY"
    if s.startswith("S") or "DISP" in s or "SALE" in s:
        return "SELL"
    return None


def _parse_num(raw: str) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if not s or s in {"-", "N.A.", "NA", "—"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _looks_like_insider(header_keys: dict[str, int]) -> bool:
    """Insider disclosures carry 'category' + 'holdings_change_pct'."""
    return "category" in header_keys and "holdings_change_pct" in header_keys


def _infer_mode(
    filename: str | None,
    header_keys: dict[str, int],
) -> str:
    fn = (filename or "").lower()
    if "insider" in fn or "sast" in fn or "pit" in fn or "reg7" in fn or "reg_7" in fn:
        return "INSIDER"
    if _looks_like_insider(header_keys):
        return "INSIDER"
    if "block" in fn:
        return "BLOCK"
    if "bulk" in fn:
        return "BULK"
    return "BULK"  # default


REQUIRED_KEYS_FOR_ANALYSIS = ("date", "symbol", "party", "side")


def parse_csv(
    csv_bytes: bytes,
    *,
    filename: str | None = None,
) -> tuple[list[DealRow], list[str]]:
    """Parse a single CSV blob into DealRows. Returns (rows, warnings)."""
    warnings: list[str] = []
    rows: list[DealRow] = []

    try:
        text = csv_bytes.decode("utf-8-sig", errors="replace")
    except Exception as e:
        warnings.append(f"{filename or 'file'}: decode error {e}")
        return rows, warnings

    # Strip BOM / leading comments; CSV header may be pushed down by a title row
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    header_keys: dict[str, int] = {}
    best_header: list[str] | None = None  # best header we saw even if rejected

    for raw_row in reader:
        if not raw_row:
            continue
        stripped = [c.strip() for c in raw_row]
        # Skip until we find a plausible header
        if header is None:
            cand = _build_column_index(stripped)
            # Track the first row that looks header-ish for diagnostics
            if best_header is None and any(cand):
                best_header = stripped
            if "date" in cand and ("party" in cand or "symbol" in cand):
                header = stripped
                header_keys = cand
                continue
            else:
                continue

        if not any(stripped):
            continue

        # Pull fields by canonical key; tolerate missing
        def col(key: str) -> str | None:
            ix = header_keys.get(key)
            if ix is None or ix >= len(stripped):
                return None
            v = stripped[ix]
            return v if v else None

        d = _parse_date(col("date") or "")
        sym_raw = (col("symbol") or "").strip()
        party = col("party")
        side = _parse_side(col("side") or "")
        qty = _parse_num(col("quantity") or "")
        price = _parse_num(col("price") or "")
        value = _parse_num(col("value") or "")
        csv_cat_raw = col("category")
        mode_cat_raw = col("mode_category")
        hpct = _parse_num(col("holdings_change_pct") or "")

        # Disambiguate the "Category" column. Many exports (Tickertape,
        # BSE) put Bulk/Block in a "Category" column; SEBI PIT files put
        # Promoter/Director. Inspect the value.
        csv_cat: str | None = None
        mode_cat: str | None = mode_cat_raw
        if csv_cat_raw:
            lower = csv_cat_raw.strip().lower()
            if lower in _MODE_VALUES:
                mode_cat = csv_cat_raw
            elif any(r in lower for r in _ROLE_VALUES):
                csv_cat = csv_cat_raw
            else:
                # Unknown — treat as role hint for safety
                csv_cat = csv_cat_raw

        # Symbol handling — keep the raw string (company-name or ticker).
        # Resolution to NSE symbol happens upstream (after parse) via the
        # stocks table.
        if not sym_raw:
            continue
        symbol = sym_raw.upper() if len(sym_raw) <= 20 and " " not in sym_raw else sym_raw

        # Layer 1 — drop rows missing Party, Side, or Symbol
        if not (d and symbol and party and side):
            continue

        # Derive value if missing
        if value is None and qty is not None and price is not None:
            value = qty * price

        if qty is None or qty <= 0 or (value is None and price is None):
            continue

        if price is None and value is not None and qty:
            price = value / qty

        classification = classify(party, csv_category=csv_cat)

        if mode_cat:
            mc = mode_cat.strip().upper()
            if mc.startswith("B") and "OCK" in mc:
                mode = "BLOCK"
            elif mc.startswith("B"):
                mode = "BULK"
            elif mc.startswith("OFF") or "OFF" in mc:
                mode = "OFFMARKET"
            else:
                mode = mc
        else:
            mode = _infer_mode(filename, header_keys)

        rows.append(DealRow(
            symbol=symbol,
            trade_date=d,
            party_raw=party.strip(),
            party_norm=classification.normalized,
            category=classification.category,
            side=side,
            quantity=int(qty),
            price=float(price or 0.0),
            value_inr=float(value or 0.0),
            mode=mode,
            source_file=filename,
            csv_category=csv_cat,
            holdings_change_pct=hpct,
        ))

    fname = filename or "file"

    if header is None:
        seen = ", ".join(best_header[:12]) if best_header else "(no obvious header)"
        warnings.append(
            f"{fname}: this doesn't look like a bulk/block/insider disclosure CSV. "
            f"Required columns: Date + Symbol + Party/Client + Buy/Sell + Quantity + Price. "
            f"Columns seen: {seen}. "
            f"Tip: download NSE bulk deals from nseindia.com/market-data/large-deals, "
            f"or a SEBI PIT Reg 7 insider disclosure."
        )
        return rows, warnings

    # Header parsed but maybe missing side/quantity — flag it
    missing = [k for k in REQUIRED_KEYS_FOR_ANALYSIS if k not in header_keys]
    if missing:
        warnings.append(
            f"{fname}: header recognized but missing required column(s): {', '.join(missing)}. "
            f"Rows will be dropped. Saw columns: {', '.join(header[:12])}"
        )
    elif not rows:
        warnings.append(
            f"{fname}: header matched but every data row was dropped "
            f"(missing Date/Party/Side/Symbol or non-numeric Quantity/Price)."
        )

    return rows, warnings


def parse_many(files: Iterable[tuple[str, bytes]]) -> tuple[list[DealRow], list[str]]:
    """Parse multiple (filename, bytes) pairs, concatenate, return warnings."""
    all_rows: list[DealRow] = []
    all_warnings: list[str] = []
    for fname, blob in files:
        rows, warnings = parse_csv(blob, filename=fname)
        all_rows.extend(rows)
        all_warnings.extend(warnings)
    return all_rows, all_warnings
