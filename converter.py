"""Conversion logic for Way of the Stonefist."""
import json
import math
import re
import sys
from pathlib import Path


def _get_base_path() -> Path:
    """Return the directory that contains bundled files.
    When frozen by PyInstaller this is sys._MEIPASS; otherwise the source dir.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent


DATA_DIR = _get_base_path() / "data"

# Load conversion table once at module level
_conversion_table: dict = {}

def _load_conversion_table():
    global _conversion_table
    path = DATA_DIR / "conversion_table.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Remove meta key
        _conversion_table = {k: v for k, v in data.items() if not k.startswith("_")}
    else:
        _conversion_table = {}

_load_conversion_table()


def _normalize(stat: str) -> str:
    """Strip numeric values from a stat string for pattern matching.
    'Adds (2-3) to (4-6) Physical Damage to Attacks' → 'adds physical damage to attacks'
    'Adds 10 to 14 Physical Damage to Attacks'       → 'adds physical damage to attacks'
    """
    s = stat.lower()
    # Remove poedb-style parenthesised ranges paired with "to":
    #   "(2-3) to (4-6)"  /  "(1-2) to 3"  /  "1 to (3-5)"
    s = re.sub(r'\(\d+[-\u2013]\d+\)\s+to\s+\(\d+[-\u2013]\d+\)', '', s)
    s = re.sub(r'\(\d+[-\u2013]\d+\)\s+to\s+\d+', '', s)
    s = re.sub(r'\d+\s+to\s+\(\d+[-\u2013]\d+\)', '', s)
    # Remove remaining plain "X to Y" ranges
    s = re.sub(r"\d+\s+to\s+\d+", "", s)
    # Remove remaining (X-Y) parenthesised ranges
    s = re.sub(r'\(\d+[-\u2013]\d+\)', '', s)
    # Remove standalone numbers and % signs
    s = re.sub(r"[\+\-]?\d+(\.\d+)?%?", "", s)
    # Remove leftover empty parentheses
    s = re.sub(r'[()]+', '', s)
    # Collapse whitespace
    return " ".join(s.split())


def find_conversion(stat: str) -> dict | None:
    """
    Look up conversion for a stat text string.
    Tries two passes: raw substring match, then normalized (numbers stripped) match.
    Prefers the longest matching key (most specific).
    Returns conversion dict or None if no match found.
    """
    stat_lower = stat.lower()
    stat_norm = _normalize(stat)
    best_match = None
    best_match_len = 0

    for key, conv in _conversion_table.items():
        key_lower = key.lower()
        # Try direct substring match first
        if key_lower in stat_lower and len(key_lower) > best_match_len:
            best_match = conv
            best_match_len = len(key_lower)
        # Try normalized match (numbers stripped from both sides)
        elif key_lower in stat_norm and len(key_lower) > best_match_len:
            best_match = conv
            best_match_len = len(key_lower)

    return best_match


def _predict_value(stat: str, conversion: dict) -> str | None:
    """
    If conversion has a predict_formula, extract the numeric range from stat
    and apply the ratio to return a human-readable predicted output string.
    Returns None if prediction is not possible.
    """
    pf = conversion.get("predict_formula")
    if not pf:
        return None

    ratio = pf.get("ratio", 1.0)
    round_to = pf.get("round_to")
    pattern = pf.get("output_pattern", "~{value}")

    def _apply(n: float) -> int:
        v = n * ratio
        if round_to:
            if pf.get("round_mode") == "ceil":
                v = math.ceil(v / round_to) * round_to
            else:
                v = round(v / round_to) * round_to
        return int(round(v))

    # Look for a range like (10-20) or (10–20)
    range_m = re.search(r'\((\d+)\s*[-\u2013]\s*(\d+)\)', stat)
    if range_m:
        lo = _apply(float(range_m.group(1)))
        hi = _apply(float(range_m.group(2)))
        val_str = str(lo) if lo == hi else f"{lo}-{hi}"
    else:
        # Single number (skip sign before +, take first digit run)
        single_m = re.search(r'\+?(\d+(?:\.\d+)?)', stat)
        if not single_m:
            return None
        val_str = str(_apply(float(single_m.group(1))))

    return pattern.format(value=val_str)


def _get_conversion_status(stat: str) -> str:
    """Return 'known', 'predicted', 'partial', or 'unknown' for a stat string."""
    conversion = find_conversion(stat)
    if conversion is None:
        return "unknown"
    unknown = conversion.get("unknown", True)
    confirmed = conversion.get("confirmed", False)
    if not unknown and confirmed:
        return "known"
    if unknown and _predict_value(stat, conversion) is not None:
        return "predicted"
    if conversion.get("converted_stat", "?") != "?":
        return "partial"
    return "unknown"


def convert_mod(mod: dict) -> dict:
    """
    Convert a single modifier to its Fists of Stone equivalent.

    Returns a result dict. If the conversion splits into 2 mods (split=true),
    the result has `split=True` and `split_outputs` list.
    """
    stat = mod.get("stat", "")
    conversion = find_conversion(stat)

    if conversion is None:
        return {
            "original": stat,
            "converted": "?",
            "split": False,
            "unknown": True,
            "predicted": False,
            "confirmed": False,
            "note": "No conversion data found",
        }

    unknown = conversion.get("unknown", True)
    confirmed = conversion.get("confirmed", False)

    # Always try predict_formula if available — works for both confirmed and estimated entries.
    # is_predicted=True only for uncertain (unknown) entries; confirmed entries apply the
    # formula silently and keep their "confirmed" (green) status.
    predicted_str = _predict_value(stat, conversion)
    is_predicted = predicted_str is not None and unknown

    base = {
        "original": stat,
        "converted": predicted_str if predicted_str is not None else conversion.get("converted_stat", "?"),
        "split": conversion.get("split", False),
        "split_outputs": conversion.get("split_outputs", []),
        "unknown": unknown and predicted_str is None,
        "predicted": is_predicted,
        "confirmed": confirmed,
        "formula": conversion.get("formula", ""),
        "note": conversion.get("example") or conversion.get("note", ""),
    }
    return base


def get_all_mods_for_type(glove_type: str) -> dict:
    """Return prefixes and suffixes for a glove type, including desecrated mods."""
    path = DATA_DIR / "modifiers" / f"{glove_type}.json"
    if not path.exists():
        return {"prefix": [], "suffix": []}

    with open(path, encoding="utf-8") as f:
        mods = json.load(f)

    prefixes = [m for m in mods if m.get("type") == "Prefix"]
    suffixes = [m for m in mods if m.get("type") == "Suffix"]

    # Desecrated mods apply to all glove types
    desecrated_path = DATA_DIR / "desecrated_mods.json"
    if desecrated_path.exists():
        with open(desecrated_path, encoding="utf-8") as f:
            desecrated = json.load(f)
        prefixes += [m for m in desecrated if m.get("type") == "Prefix"]
        suffixes += [m for m in desecrated if m.get("type") == "Suffix"]

    # Add normalized_key and conversion_status for JS-side collapsing and grouping
    for m in prefixes + suffixes:
        m["normalized_key"] = _normalize(m.get("stat", ""))
        m["conversion_status"] = _get_conversion_status(m.get("stat", ""))

    return {"prefix": prefixes, "suffix": suffixes}


def load_base_gloves() -> list:
    """Load base glove types."""
    path = DATA_DIR / "gloves_base.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def reload_conversion_table():
    """Reload conversion table from disk (useful after updates)."""
    _load_conversion_table()


def load_unique_gloves() -> list:
    """Load unique glove data including mods."""
    path = DATA_DIR / "gloves_unique.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)
