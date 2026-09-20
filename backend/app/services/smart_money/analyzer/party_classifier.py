"""Party-name normalization + category classification.

Classifies each party into exactly ONE of:
  QUALITY_MF_FPI, VC_PE, PROMOTER, INSIDER_OTHER, PROP_HFT,
  OTHER_FUND, BROKER, CORP_OTHER, INDIVIDUAL

Design principles (per analyzer spec):
- Every rule has a failure mode — documented next to each keyword set.
- Don't backfill missing quality-name classifications with "looks like a
  fund" regex. Either the party is in the curated dictionary or it's
  OTHER_FUND (if it at least looks fund-like) else INDIVIDUAL/CORP_OTHER.
- Classification order matters: PROMOTER/INSIDER wins over fund detection
  when the CSV has a category column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

Category = str  # one of the constants below

QUALITY_MF_FPI = "QUALITY_MF_FPI"
VC_PE = "VC_PE"
PROMOTER = "PROMOTER"
INSIDER_OTHER = "INSIDER_OTHER"
PROP_HFT = "PROP_HFT"
OTHER_FUND = "OTHER_FUND"
BROKER = "BROKER"
CORP_OTHER = "CORP_OTHER"
INDIVIDUAL = "INDIVIDUAL"


# Maintained keyword dictionary. Substring match (case-insensitive) on the
# normalized name. Longer/more-specific keywords should appear first within
# each tier so they win on ties.
QUALITY_MF_FPI_KEYS: list[str] = [
    # Indian MFs — top AMCs
    "sbi mutual fund", "sbi mf", "sbi funds management",
    "hdfc mutual fund", "hdfc mf", "hdfc asset management",
    "icici prudential", "icici pru mutual",
    "nippon india mutual", "nippon life india",
    "aditya birla sun life",
    "kotak mahindra mutual", "kotak mf", "kotak mahindra asset",
    "axis mutual fund", "axis mf", "axis asset management",
    "uti mutual fund", "uti mf", "uti trustee",
    "dsp mutual fund", "dsp mf", "dsp blackrock",
    "mirae asset",
    "tata mutual fund", "tata asset management",
    "franklin templeton",
    "idfc mutual", "idfc asset",
    "bandhan mutual", "bandhan mf",
    "ppfas", "parag parikh",
    "quant mutual fund", "quant money managers",
    "motilal oswal mutual", "motilal oswal mf",
    "edelweiss mutual", "edelweiss mf",
    "canara robeco",
    "hsbc mutual fund", "hsbc asset",
    "bnp paribas mutual",
    "invesco mutual",
    "pgim india mutual",
    "l&t mutual", "lnt mutual",
    "whiteoak capital",
    "360 one",
    # LIC + insurance
    "life insurance corporation", "lic of india", " lic ",
    "sbi life insurance", "hdfc life", "icici prudential life",
    "bajaj allianz",
    "general insurance corporation", "gic of india",
    # Top foreign FPIs (global asset managers with strong India presence)
    "goldman sachs",
    "morgan stanley",
    "jp morgan", "j p morgan", "jpmorgan",
    "government pension fund global", "norges bank",
    "vanguard",
    "blackrock", "black rock",
    "fidelity",
    "t rowe price", "t. rowe price",
    "capital world", "capital income", "capital group", "capital research",
    "abu dhabi investment authority", "adia",
    "government of singapore", "gic private",
    "monetary authority of singapore",
    "qia", "qatar investment authority",
    "kuwait investment authority", "kia kuwait",
    "ontario teachers", "cppib", "canada pension",
    "ca pension", "norwegian government pension",
    "florida retirement", "california public employees",
    "temasek",
    "societe generale",
    "amundi",
    "schroder",
    "aberdeen",
    "eastspring",
    "matthews india",
    "stewart investors",
    "wasatch",
    "pioneer investments",
    "fisher investments",
    "arisaig",
    "genesis emerging",
]

VC_PE_KEYS: list[str] = [
    # Early-stage & growth VCs active in India
    "sequoia capital", "sequoia india",
    "peak xv", "peak 15",
    "accel partners", "accel india",
    "matrix partners", "matrix india",
    "nexus venture", "nexus india",
    "lightspeed",
    "elevation capital",
    "blume ventures",
    "kalaari",
    "saif partners",
    "chiratae",
    "sistema asia",
    "venture east",
    "prime venture",
    "3one4",
    "tiger global",
    "sofina",
    "steadview",
    "dst global",
    "naspers", "prosus",
    "softbank", "soft bank",
    # Growth / PE
    "tpg growth", "tpg capital", "tpg asia",
    "blackstone",
    "kkr", "kohlberg kravis roberts",
    "carlyle",
    "bain capital",
    "warburg pincus",
    "general atlantic",
    "apax partners",
    "advent international",
    "baring private equity", "baring asia", "ebenezer",
    "cvc capital",
    "everstone",
    "chryscapital",
    "kedaara",
    "true north",
    "multiples alternate",
    "partners group",
    "westbridge",
    "gaja capital",
    "morgan stanley private equity",  # distinct from MS FPI
    "ivy capital",
    "premji invest",
]

PROP_HFT_KEYS: list[str] = [
    # Global HFTs
    "jane street",
    "citadel securities",
    "tower research",
    "jump trading", "jump capital",
    "optiver",
    "imc trading", "imc financial",
    "virtu financial",
    "flow traders",
    "hudson river",
    "two sigma securities",
    "de shaw",
    "millennium management",
    # Indian prop / HFT names seen repeatedly in bulk filings
    "graviton research",
    "gravitation research",
    "microcurves",
    "nk securities",
    "hrti ",  # HRTI Private Limited
    "hrti private",
    "junomoneta",
    "neomile",
    "arthkumbh",
    "ishaan tradefin",
    "gdn ventures",
    "crony vyapar",
    "darshana mitesh",  # repeat prop-style individual trader
    "msb e trade",
    "neo apex share",
    "junomoneta finsol",
    "anantroop financial",
    "jump trading financial india",
    # Addendum A1c — generic patterns. These are heuristic and lose to
    # `OVERRIDES` / `known_sharks` / quality-MF dictionary matches when
    # both apply. Specific names should be added to the lists above
    # when seen.
    "securities research",   # NK Securities Research, etc.
    "puma securities",
    "qe securities",
    "irage broking",
    "jainam broking",
    "silverleaf capital",
    "arihant capital market",
]

BROKER_KEYS: list[str] = [
    "motilal oswal securities", "motilal oswal financial services",
    "kotak securities", "kotak mahindra securities",
    "icici securities",
    "sharekhan",
    "angel broking", "angel one",
    "zerodha",
    "edelweiss securities",
    "hdfc securities",
    "axis securities",
    "sbi securities",
    "religare broking",
    "iifl securities",
    "jm financial institutional",
    "centrum broking",
    "emkay",
    "b&k securities", "batlivala",
    "anand rathi",
    "ifast financial",
    " securities ",  # trailing catch — must be last-tier
]

# "Looks like a fund" cautious keywords — assigned to OTHER_FUND only
# when no other category hit. Per spec, we DO NOT use regex to elevate
# unknown funds to QUALITY_MF_FPI.
OTHER_FUND_KEYS: list[str] = [
    "mutual fund", " mf ", " fund", "asset management", "capital partners",
    "investment fund", "advisors fund", "opportunities fund", "scheme",
    "pension fund", "endowment", "sovereign fund",
    "insurance company", "life insurance", "general insurance",
    "fund pvt", "fund private",
]


# Honorifics / hints that the party is a natural person.
INDIVIDUAL_HINTS: list[str] = [
    "mr ", "mrs ", "ms ", "shri ", "smt ", "dr ",
    "huf",
]


# Generic-corporate tell-tales
CORP_HINTS: list[str] = [
    " pvt ltd", " pvt. ltd", " private limited", " private ltd",
    " limited", " ltd.", " ltd ", " plc", " llp", " inc", " corp",
    " corporation", " enterprises", " ventures", " holdings",
    " trading", " investments",
]


# Curated promoter and insider overrides — empty by default. Grow over
# time as you identify promoter HUFs / founder trusts for specific names
# you follow. Keys are NORMALIZED substrings (lower-case, compressed).
PROMOTER_OVERRIDES: set[str] = set()
INSIDER_OTHER_OVERRIDES: set[str] = set()


# Upgrade overrides: force a party to a specific category regardless of
# other rules. Format: { "normalized substring": Category }.
OVERRIDES: dict[str, str] = {}


# -------- Normalization -----------

_STRIP_TOKENS = [
    r"\brevised\b",
    r"\bcorrigendum\b",
    r"\brevision\b",
]


def normalize_party(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, drop common
    annotation tokens. Returns a stable key for dictionary matching."""
    if not raw:
        return ""
    s = raw.lower()
    s = re.sub(r"[\.,;:_\-\/\(\)\[\]&]+", " ", s)
    for tok in _STRIP_TOKENS:
        s = re.sub(tok, " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# -------- Classification -----------

@dataclass
class PartyClassification:
    category: Category
    normalized: str
    hint: str  # which keyword matched (for auditability)


def classify(raw: str, csv_category: str | None = None) -> PartyClassification:
    """Assign a party to exactly one category. `csv_category` is the
    optional hint from the CSV (e.g. "Promoter", "Director") when present
    — takes precedence over name-based classification.
    """
    norm = normalize_party(raw)

    # CSV-provided category wins when it encodes role
    if csv_category:
        c = csv_category.strip().lower()
        if "promoter" in c:
            return PartyClassification(PROMOTER, norm, f"csv_category:{csv_category}")
        if "director" in c or "kmp" in c or "key management" in c or "dp&sap" in c or "designated" in c:
            return PartyClassification(INSIDER_OTHER, norm, f"csv_category:{csv_category}")

    # Curated overrides
    for key, cat in OVERRIDES.items():
        if key in norm:
            return PartyClassification(cat, norm, f"override:{key}")
    for key in PROMOTER_OVERRIDES:
        if key in norm:
            return PartyClassification(PROMOTER, norm, f"promoter_override:{key}")
    for key in INSIDER_OTHER_OVERRIDES:
        if key in norm:
            return PartyClassification(INSIDER_OTHER, norm, f"insider_override:{key}")

    # Substring dictionary matches in priority order
    for key in QUALITY_MF_FPI_KEYS:
        if key in norm:
            return PartyClassification(QUALITY_MF_FPI, norm, key)
    for key in VC_PE_KEYS:
        if key in norm:
            return PartyClassification(VC_PE, norm, key)
    for key in PROP_HFT_KEYS:
        if key in norm:
            return PartyClassification(PROP_HFT, norm, key)
    for key in BROKER_KEYS:
        if key in norm:
            return PartyClassification(BROKER, norm, key)
    for key in OTHER_FUND_KEYS:
        if key in norm:
            return PartyClassification(OTHER_FUND, norm, key)

    # Individual vs corp heuristics. Individual hints first (HUF, titles)
    for key in INDIVIDUAL_HINTS:
        if key in norm:
            return PartyClassification(INDIVIDUAL, norm, f"hint:{key}")
    for key in CORP_HINTS:
        if key in norm:
            return PartyClassification(CORP_OTHER, norm, f"hint:{key}")

    # No strong signal — default to INDIVIDUAL if the name looks human
    # (2-4 words, no corp suffix). Otherwise CORP_OTHER.
    word_count = len(norm.split())
    if 2 <= word_count <= 4 and not any(h in norm for h in CORP_HINTS):
        return PartyClassification(INDIVIDUAL, norm, "heuristic:human_shape")
    return PartyClassification(CORP_OTHER, norm, "default")
