# ═══════════════════════════════════════════════════════════════
#  FITPULSE WEB · mapping_serialize.py
#
#  ColumnMapping (from schema_engine.py) holds tuples as dict values
#  ((filename, column_name)), which JSON can't represent directly.
#  These helpers convert it to/from a plain JSON-safe structure so
#  it can be stored in the session and sent to/from the browser.
# ═══════════════════════════════════════════════════════════════

from typing import Any, Dict

from ml_core.schema_engine import ColumnMapping


def mapping_to_json(mapping: ColumnMapping) -> Dict[str, Any]:
    return {
        "mapping": {
            role: {"file": fname, "column": cname}
            for role, (fname, cname) in mapping.mapping.items()
        },
        "generic_numeric": [
            {"file": fname, "column": cname} for fname, cname in mapping.generic_numeric
        ],
        "generic_categorical": [
            {"file": fname, "column": cname} for fname, cname in mapping.generic_categorical
        ],
        "confidence": mapping.confidence,
        "origin": mapping.origin,
    }


def mapping_from_json(data: Dict[str, Any]) -> ColumnMapping:
    # Roles left as "None / Not present" arrive as a bare `null` in the
    # JSON payload (not as {"column": null}), so `entry` itself can be
    # None here. Must check that before calling .get() on it.
    mapping = {
        role: (entry["file"], entry["column"])
        for role, entry in data.get("mapping", {}).items()
        if entry is not None and entry.get("column") is not None
    }
    generic_numeric = [
        (entry["file"], entry["column"])
        for entry in data.get("generic_numeric", [])
        if entry is not None
    ]
    generic_categorical = [
        (entry["file"], entry["column"])
        for entry in data.get("generic_categorical", [])
        if entry is not None
    ]
    confidence = data.get("confidence", {}) or {}
    origin = data.get("origin", {}) or {}
    return ColumnMapping(
        mapping=mapping,
        generic_numeric=generic_numeric,
        generic_categorical=generic_categorical,
        confidence=confidence,
        origin=origin,
    )