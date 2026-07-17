# ═══════════════════════════════════════════════════════════════
#  FITPULSE  ·  DYNAMIC PIPELINE  ·  schema_engine.py
#
#  Phase 1  ·  Dataset Profiler   → build_dataset_profile()
#  Phase 2  ·  Column Role Mapper → infer_column_roles()
#
#  This module is dataset-agnostic. It inspects whatever CSV/XLSX
#  file(s) are uploaded, fingerprints every column statistically,
#  and maps columns to a fixed vocabulary of "roles" (heart_rate,
#  steps, sleep_duration, user_id, timestamp, ...) using a blend of
#  name-matching and statistical fit.
#
#  Every later pipeline stage (preprocessing, TSFresh, anomaly
#  detection, clustering, PDF export) should import the
#  ColumnMapping produced here instead of referencing literal
#  column names like "AvgHR" or "TotalSteps".
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import difflib
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class ColumnFingerprint:
    """Statistical + structural fingerprint of a single column."""
    name: str
    semantic_dtype: str          # 'datetime' | 'identifier' | 'categorical' |
                                  # 'numeric_continuous' | 'numeric_discrete' |
                                  # 'boolean' | 'text'
    cardinality_ratio: float     # nunique / n_rows  (0..1)
    null_pct: float              # 0..100
    n_rows: int
    n_unique: int

    # numeric-only stats (None if not numeric)
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    mean_val: Optional[float] = None
    std_val: Optional[float] = None
    is_non_negative: Optional[bool] = None
    looks_like_count: Optional[bool] = None   # non-negative integers

    # datetime-only stats
    datetime_parse_rate: float = 0.0          # fraction of non-null values parseable as datetime
    inferred_granularity: Optional[str] = None  # 'second'|'minute'|'hour'|'day' (best guess)

    sample_values: List[Any] = field(default_factory=list)


@dataclass
class FileProfile:
    """Profile of a single uploaded file."""
    filename: str
    n_rows: int
    n_cols: int
    columns: Dict[str, ColumnFingerprint] = field(default_factory=dict)
    shape_guess: str = "wide"     # 'wide' | 'long'
    long_format_hint_col: Optional[str] = None   # e.g. a 'metric'/'type' column, if long


@dataclass
class DatasetProfile:
    """Profile across all uploaded files."""
    files: Dict[str, FileProfile] = field(default_factory=dict)
    overall_shape: str = "single_wide"   # 'single_wide' | 'single_long' | 'multi_file'
    join_keys: List[str] = field(default_factory=list)   # column names shared across files


@dataclass
class ColumnMapping:
    """
    Result of role inference.

    mapping:     role -> (filename, column_name)   for confidently-assigned roles
    generic_numeric:      [(filename, column_name), ...]  numeric columns not claimed by any role
    generic_categorical:  [(filename, column_name), ...]  categorical columns not claimed by any role
    confidence:  role -> score (0..1)  — useful for a future confirmation UI
    """
    mapping: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    generic_numeric: List[Tuple[str, str]] = field(default_factory=list)
    generic_categorical: List[Tuple[str, str]] = field(default_factory=list)
    confidence: Dict[str, float] = field(default_factory=dict)
    origin: Dict[str, str] = field(default_factory=dict) # role -> 'auto' | 'manual'

    def col(self, role: str) -> Optional[str]:
        """Convenience: get just the column name for a role (None if absent)."""
        entry = self.mapping.get(role)
        return entry[1] if entry else None

    def file_for(self, role: str) -> Optional[str]:
        entry = self.mapping.get(role)
        return entry[0] if entry else None

    def has(self, role: str) -> bool:
        return role in self.mapping


# ═══════════════════════════════════════════════════════════════
#  PHASE 1 · COLUMN-LEVEL FINGERPRINTING
# ═══════════════════════════════════════════════════════════════

_ID_NAME_HINTS = ("id", "user", "participant", "subject", "patient")
_DATE_NAME_HINTS = ("date", "time", "day", "timestamp", "hour")

_MIN_ROWS_FOR_CARDINALITY_TRUST = 15   # below this, don't trust cardinality heuristics much


def _datetime_parse_rate(series: pd.Series, sample_size: int = 200) -> float:
    """Fraction of non-null values that successfully parse as datetimes."""
    non_null = series.dropna()
    if non_null.empty:
        return 0.0
    sample = non_null.sample(min(sample_size, len(non_null)), random_state=42) \
        if len(non_null) > sample_size else non_null
    parsed = pd.to_datetime(sample, format="mixed", errors="coerce")
    return float(parsed.notna().mean())


def _infer_granularity(series: pd.Series) -> Optional[str]:
    """Guess timestamp granularity from median gap between sorted unique values."""
    try:
        dt = pd.to_datetime(series.dropna(), format="mixed", errors="coerce").dropna()
        if len(dt) < 3:
            return None
        diffs = dt.sort_values().diff().dropna()
        if diffs.empty:
            return None
        median_seconds = diffs.dt.total_seconds().median()
        if median_seconds <= 5:
            return "second"
        elif median_seconds <= 300:
            return "minute"
        elif median_seconds <= 5400:
            return "hour"
        else:
            return "day"
    except Exception:
        return None


def _guess_semantic_dtype(series: pd.Series, name: str) -> str:
    """Best-effort classification of a column's semantic type."""
    non_null = series.dropna()
    if non_null.empty:
        return "text"

    # Boolean-like
    unique_vals = set(non_null.unique()[:10])
    if series.dtype == bool or unique_vals.issubset({0, 1, True, False, "True", "False", "true", "false"}):
        if len(non_null.unique()) <= 2:
            return "boolean"

    # Numeric — but check for *numeric identifiers* first (e.g. an integer
    # UserID/participant code). These are common in wearable exports and
    # must not fall through to numeric_continuous/discrete, or they'll be
    # invisible to identifier-based role matching and join-key detection.
    if pd.api.types.is_numeric_dtype(series):
        n_unique = non_null.nunique()
        ratio = n_unique / max(len(non_null), 1)
        name_lower = name.lower()
        name_suggests_id = any(h in name_lower for h in _ID_NAME_HINTS)

        # A numeric column reads as an identifier/grouping-key only when its
        # NAME suggests one — cardinality alone is not trustworthy here,
        # since ordinary measurement columns (step counts, calories) are
        # often just as "unique per row" in a small sample as a real ID
        # would be. Name hint is required in both sub-cases:
        #   (a) low-ish cardinality relative to row count -> a repeating
        #       grouping key (e.g. a handful of user IDs across many rows), or
        #   (b) very high cardinality -> a per-row primary-key-like column.
        if name_suggests_id:
            is_grouping_key = 0 < ratio <= 0.5
            is_pk_like = ratio > 0.95 and len(non_null) >= _MIN_ROWS_FOR_CARDINALITY_TRUST
            if is_grouping_key or is_pk_like:
                return "identifier"

        # High-cardinality float/int -> continuous; low-cardinality small ints -> discrete/categorical-ish
        if pd.api.types.is_float_dtype(series) or ratio > 0.3:
            return "numeric_continuous"
        return "numeric_discrete"

    # Datetime-parseable text
    parse_rate = _datetime_parse_rate(series)
    name_lower = name.lower()
    if parse_rate > 0.85 or any(h in name_lower for h in _DATE_NAME_HINTS) and parse_rate > 0.5:
        return "datetime"

    # Identifier-like (high cardinality, name hints, or looks like a code/UUID)
    ratio = non_null.nunique() / max(len(non_null), 1)
    if any(h in name_lower for h in _ID_NAME_HINTS) and ratio > 0.05:
        return "identifier"
    if ratio > 0.9 and len(non_null) >= _MIN_ROWS_FOR_CARDINALITY_TRUST:
        return "identifier"

    # Low-cardinality text -> categorical, else free text
    if non_null.nunique() <= max(20, int(0.05 * len(non_null))):
        return "categorical"
    return "text"


def _fingerprint_column(series: pd.Series, name: str) -> ColumnFingerprint:
    n_rows = len(series)
    non_null = series.dropna()
    n_unique = non_null.nunique()
    null_pct = round(100 * (1 - len(non_null) / n_rows), 2) if n_rows else 0.0
    cardinality_ratio = round(n_unique / max(len(non_null), 1), 4) if len(non_null) else 0.0

    semantic = _guess_semantic_dtype(series, name)

    fp = ColumnFingerprint(
        name=name,
        semantic_dtype=semantic,
        cardinality_ratio=cardinality_ratio,
        null_pct=null_pct,
        n_rows=n_rows,
        n_unique=n_unique,
        sample_values=list(non_null.unique()[:5]),
    )

    if semantic in ("numeric_continuous", "numeric_discrete"):
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if not numeric.empty:
            fp.min_val = float(numeric.min())
            fp.max_val = float(numeric.max())
            fp.mean_val = float(numeric.mean())
            fp.std_val = float(numeric.std()) if len(numeric) > 1 else 0.0
            fp.is_non_negative = bool((numeric >= 0).all())
            fp.looks_like_count = bool(
                fp.is_non_negative and (numeric.dropna() % 1 == 0).mean() > 0.98
            )

    if semantic == "datetime":
        fp.datetime_parse_rate = _datetime_parse_rate(series)
        fp.inferred_granularity = _infer_granularity(series)

    return fp


# ═══════════════════════════════════════════════════════════════
#  PHASE 1 · FILE-LEVEL SHAPE DETECTION
# ═══════════════════════════════════════════════════════════════

def _detect_file_shape(df: pd.DataFrame, columns: Dict[str, ColumnFingerprint]) -> Tuple[str, Optional[str]]:
    """
    Guess whether a file is 'wide' (one row per entity/time, many metric
    columns) or 'long' (repeated rows keyed by a metric-name column + a
    single value column).

    Heuristic: long-format files typically have very few columns overall,
    one column with low-to-moderate cardinality that looks like it names a
    metric ('type', 'metric', 'value_type', 'logtype' ...), and a single
    generic numeric 'value' column.
    """
    n_cols = df.shape[1]
    categorical_cols = [c for c, fp in columns.items() if fp.semantic_dtype == "categorical"]
    numeric_cols = [c for c, fp in columns.items()
                    if fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")]

    long_name_hints = ("type", "metric", "logtype", "category", "name", "value")
    candidate_metric_col = None
    for c in categorical_cols:
        cl = c.lower()
        if any(h in cl for h in long_name_hints):
            candidate_metric_col = c
            break

    is_narrow = n_cols <= 5
    has_single_value_col = len(numeric_cols) <= 1

    if is_narrow and candidate_metric_col is not None and has_single_value_col:
        return "long", candidate_metric_col

    return "wide", None


# ═══════════════════════════════════════════════════════════════
#  PHASE 1 · JOIN-KEY DETECTION (multi-file case)
# ═══════════════════════════════════════════════════════════════

def _detect_join_keys(files: Dict[str, FileProfile], raw_dfs: Dict[str, pd.DataFrame]) -> List[str]:
    """
    Find column names that appear in 2+ files, share a compatible semantic
    dtype (identifier or datetime), and have overlapping value sets — these
    are candidate merge keys (replacing hardcoded on=["Id","Date"] merges).
    """
    if len(files) < 2:
        return []

    name_to_files: Dict[str, List[str]] = {}
    for fname, fp in files.items():
        for cname, cfp in fp.columns.items():
            if cfp.semantic_dtype in ("identifier", "datetime"):
                name_to_files.setdefault(cname, []).append(fname)

    join_keys = []
    for cname, fnames in name_to_files.items():
        if len(fnames) < 2:
            continue
        # Check value overlap between the first two files that share this column
        f1, f2 = fnames[0], fnames[1]
        try:
            s1 = set(raw_dfs[f1][cname].dropna().unique()[:500])
            s2 = set(raw_dfs[f2][cname].dropna().unique()[:500])
            overlap = len(s1 & s2) / max(min(len(s1), len(s2)), 1)
            if overlap > 0.3:
                join_keys.append(cname)
        except Exception:
            continue

    return join_keys


# ═══════════════════════════════════════════════════════════════
#  PHASE 1 · PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def build_dataset_profile(uploaded_files: Dict[str, pd.DataFrame]) -> DatasetProfile:
    """
    Phase 1 entry point.

    Parameters
    ----------
    uploaded_files : dict[str, pd.DataFrame]
        Mapping of filename -> raw DataFrame, exactly as read from the
        Streamlit file_uploader (one entry even for a single-file upload).

    Returns
    -------
    DatasetProfile
    """
    file_profiles: Dict[str, FileProfile] = {}

    for fname, df in uploaded_files.items():
        col_fps = {c: _fingerprint_column(df[c], c) for c in df.columns}
        shape_guess, long_col = _detect_file_shape(df, col_fps)
        file_profiles[fname] = FileProfile(
            filename=fname,
            n_rows=df.shape[0],
            n_cols=df.shape[1],
            columns=col_fps,
            shape_guess=shape_guess,
            long_format_hint_col=long_col,
        )

    if len(file_profiles) == 1:
        only_fp = next(iter(file_profiles.values()))
        overall_shape = "single_long" if only_fp.shape_guess == "long" else "single_wide"
        join_keys: List[str] = []
    else:
        overall_shape = "multi_file"
        join_keys = _detect_join_keys(file_profiles, uploaded_files)

    return DatasetProfile(files=file_profiles, overall_shape=overall_shape, join_keys=join_keys)


# ═══════════════════════════════════════════════════════════════
#  PHASE 2 · ROLE VOCABULARY
# ═══════════════════════════════════════════════════════════════

# Each role: name_hints (substrings, checked against normalized column name)
# and a fingerprint_filter(fp) -> bool that must hold for a column to even
# be eligible, used to keep obviously-wrong matches (e.g. a "Sleep_Notes"
# text column) out of numeric roles.

def _is_plausible_range(fp: ColumnFingerprint, lo: float, hi: float, tolerance: float = 0.15) -> bool:
    """True if most of the column's value range plausibly falls in [lo, hi]."""
    if fp.mean_val is None:
        return False
    span = hi - lo
    return (lo - tolerance * span) <= fp.mean_val <= (hi + tolerance * span)


ROLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "user_id": {
        "name_hints": ("id", "user", "participant", "subject", "patient"),
        "filter": lambda fp: fp.semantic_dtype == "identifier",
    },
    "timestamp": {
        "name_hints": ("date", "time", "day", "timestamp", "hour", "activityhour", "activitydate"),
        "filter": lambda fp: fp.semantic_dtype == "datetime",
    },
    "heart_rate": {
        "name_hints": ("heartrate", "heart_rate", "hr", "bpm", "pulse"),
        "filter": lambda fp: fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")
                              and _is_plausible_range(fp, 30, 220),
    },
    "steps": {
        "name_hints": ("step", "stepcount", "steptotal", "totalsteps"),
        "filter": lambda fp: fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")
                              and bool(fp.is_non_negative) and bool(fp.looks_like_count),
    },
    "sleep_duration": {
        "name_hints": ("sleep", "asleep", "sleepminutes", "totalsleepminutes", "sleepduration"),
        "filter": lambda fp: fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")
                              and bool(fp.is_non_negative)
                              and _is_plausible_range(fp, 0, 600, tolerance=0.2),
    },
    "calories": {
        "name_hints": ("calorie", "kcal", "energy"),
        "filter": lambda fp: fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")
                              and bool(fp.is_non_negative),
    },
    "activity_intensity": {
        "name_hints": ("active", "activeminutes", "intensity", "sedentary", "veryactive",
                       "fairlyactive", "lightlyactive"),
        "filter": lambda fp: fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")
                              and bool(fp.is_non_negative)
                              and _is_plausible_range(fp, 0, 1440, tolerance=0.5),
    },
    "distance": {
        "name_hints": ("distance", "km", "miles", "meter"),
        "filter": lambda fp: fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")
                              and bool(fp.is_non_negative),
    },
    "weight": {
        "name_hints": ("weight", "bmi"),
        "filter": lambda fp: fp.semantic_dtype in ("numeric_continuous", "numeric_discrete")
                              and _is_plausible_range(fp, 10, 300, tolerance=0.5),
    },
    "workout_type": {
        "name_hints": ("workout", "activitytype", "exercisetype"),
        "filter": lambda fp: fp.semantic_dtype == "categorical",
    },
}

# Roles that should only ever have ONE column assigned across the whole
# dataset (as opposed to something like generic_numeric which is a list).
_SINGLE_ASSIGN_ROLES = set(ROLE_DEFINITIONS.keys())


def _tokenize(name: str) -> List[str]:
    """
    Split a column name or hint into lowercase word tokens, breaking on
    camelCase transitions, underscores, spaces, and other punctuation.
    e.g. 'Heart_Rate (bpm)' -> ['heart','rate','bpm'];
         'SedentaryMinutes' -> ['sedentary','minutes'];
         'bpm' -> ['bpm']
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s)
    return [t.lower() for t in s.split("_") if t]


def _normalize_col_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _name_match_score(col_name: str, hints: Tuple[str, ...]) -> float:
    """
    Score 0..1 for how well a column name matches a role's name hints.

    Matching is word-tokenized rather than raw-character fuzzy matching,
    because whole-string character similarity produces false positives on
    compound names that merely share a common suffix/prefix word (e.g.
    'SedentaryMinutes' vs a 'sleepminutes' hint both end in "minutes" but
    mean unrelated things). Precedence, strongest first:
      1. Exact whole-token overlap (e.g. 'bpm' token == 'bpm' hint)
      2. Abbreviation-style substring match on the fully-joined forms
         (handles single-token hints like 'hr', 'kcal' against compound
         names where tokenization would otherwise miss them)
      3. Fuzzy match, but only between individual tokens of comparable
         length, and only above a high similarity bar — catches minor
         spelling variants without reviving coincidental compound overlaps
    """
    name_tokens = _tokenize(col_name)
    if not name_tokens:
        return 0.0
    name_token_set = set(name_tokens)
    name_joined = "".join(name_tokens)

    best = 0.0
    for hint in hints:
        hint_tokens = _tokenize(hint)
        if not hint_tokens:
            continue
        hint_joined = "".join(hint_tokens)

        # 1. Exact token overlap — reward matches proportional to how much
        #    of the (usually short) hint was matched.
        overlap = set(hint_tokens) & name_token_set
        if overlap:
            score = len(overlap) / len(hint_tokens)
            best = max(best, score)
            continue

        # 2. Abbreviation / substring match on joined forms (e.g. 'hr' or
        #    'kcal' inside a longer compound column name).
        if hint_joined in name_joined or name_joined in hint_joined:
            score = len(hint_joined) / max(len(name_joined), len(hint_joined), 1)
            best = max(best, score * 0.9)
            continue

        # 3. Conservative fuzzy fallback — only compare tokens of similar
        #    length, and only accept a high similarity ratio, so this
        #    catches things like 'Stpes' (typo) but not coincidental
        #    shared substrings between unrelated compound words.
        for nt in name_tokens:
            if abs(len(nt) - len(hint_joined)) <= 2:
                ratio = difflib.SequenceMatcher(None, nt, hint_joined).ratio()
                if ratio > 0.82:
                    best = max(best, ratio * 0.6)

    return min(best, 1.0)


def _fingerprint_match_score(fp: ColumnFingerprint, role: str) -> float:
    """1.0 if the role's statistical filter passes, else 0.0 (binary gate)."""
    role_def = ROLE_DEFINITIONS[role]
    try:
        return 1.0 if role_def["filter"](fp) else 0.0
    except Exception:
        return 0.0


# Weights for combining name-match vs fingerprint-match into one score.
_NAME_WEIGHT = 0.6
_FINGERPRINT_WEIGHT = 0.4
_MIN_CONFIDENCE_TO_ASSIGN = 0.35


# ═══════════════════════════════════════════════════════════════
#  PHASE 2 · PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def infer_column_roles(profile: DatasetProfile) -> ColumnMapping:
    """
    Phase 2 entry point.

    Scores every (file, column) pair against every role in
    ROLE_DEFINITIONS, assigns each role to its single best-scoring
    column (above a minimum confidence), and buckets everything else
    into generic_numeric / generic_categorical so it's still usable
    downstream even without a named role.
    """
    # Flatten (filename, column_name, fingerprint) across all files
    all_columns: List[Tuple[str, str, ColumnFingerprint]] = []
    for fname, file_profile in profile.files.items():
        for cname, fp in file_profile.columns.items():
            all_columns.append((fname, cname, fp))

    mapping: Dict[str, Tuple[str, str]] = {}
    confidence: Dict[str, float] = {}
    claimed: set = set()   # (filename, column_name) pairs already assigned to a role

    # Cache per-file name-match scores so we don't recompute the filename
    # score against every role's hints for every single column repeatedly.
    file_stem_cache: Dict[str, str] = {
        fname: re.sub(r"\.[a-zA-Z0-9]+$", "", fname) for fname in profile.files
    }

    for role in ROLE_DEFINITIONS:
        hints = ROLE_DEFINITIONS[role]["name_hints"]
        best_score, best_col = 0.0, None

        for fname, cname, fp in all_columns:
            key = (fname, cname)
            if key in claimed:
                continue

            col_name_score = _name_match_score(cname, hints)
            # Filename context matters most for multi-file uploads where a
            # column is genuinely generic (e.g. a bare 'Value' column in
            # heartrate_seconds_merged.csv) — treat it as secondary
            # evidence, capped below a perfect column-name match.
            file_name_score = _name_match_score(file_stem_cache[fname], hints) * 0.85
            name_score = max(col_name_score, file_name_score)
            fp_score = _fingerprint_match_score(fp, role)

            # Hard floor: a column with essentially no name relation to the
            # role must never be admitted, no matter how well its fingerprint
            # fits — otherwise loosely-defined numeric filters (e.g. "any
            # non-negative value in a plausible range") will happily claim
            # unrelated columns (a sleep-stage code column "fitting" calories,
            # etc). Below this floor we skip regardless of fingerprint.
            if name_score < 0.25:
                continue

            # Beyond the floor: still require at least some statistical
            # plausibility OR a strong name match — a column with a
            # decent-but-not-great name and a failing fingerprint is rejected.
            if fp_score == 0.0 and name_score < 0.55:
                continue

            combined = _NAME_WEIGHT * name_score + _FINGERPRINT_WEIGHT * fp_score
            if combined > best_score:
                best_score, best_col = combined, key

        if best_col is not None and best_score >= _MIN_CONFIDENCE_TO_ASSIGN:
            mapping[role] = best_col
            confidence[role] = round(best_score, 3)
            claimed.add(best_col)

    # Bucket everything unclaimed into generic numeric / categorical
    generic_numeric: List[Tuple[str, str]] = []
    generic_categorical: List[Tuple[str, str]] = []

    for fname, cname, fp in all_columns:
        key = (fname, cname)
        if key in claimed:
            continue
        if fp.semantic_dtype in ("numeric_continuous", "numeric_discrete"):
            generic_numeric.append(key)
        elif fp.semantic_dtype == "categorical":
            generic_categorical.append(key)
        # datetime/identifier/text/boolean leftovers are intentionally
        # dropped from generic buckets — they're not useful as ML signals.

    return ColumnMapping(
        mapping=mapping,
        generic_numeric=generic_numeric,
        generic_categorical=generic_categorical,
        confidence=confidence,
    )


# ═══════════════════════════════════════════════════════════════
#  CONVENIENCE WRAPPER
# ═══════════════════════════════════════════════════════════════

def profile_and_map(uploaded_files: Dict[str, pd.DataFrame]) -> Tuple[DatasetProfile, ColumnMapping]:
    """Run Phase 1 + Phase 2 in one call."""
    profile = build_dataset_profile(uploaded_files)
    mapping = infer_column_roles(profile)
    return profile, mapping


# ═══════════════════════════════════════════════════════════════
#  DEBUG / INSPECTION HELPER
# ═══════════════════════════════════════════════════════════════

def summarize_mapping(mapping: ColumnMapping) -> pd.DataFrame:
    """
    Human-readable summary of the inferred mapping — useful for a Phase 3
    confirmation UI (e.g. st.dataframe(summarize_mapping(mapping))) or for
    debugging in a notebook/console.
    """
    rows = []
    for role, (fname, cname) in mapping.mapping.items():
        rows.append({
            "role": role,
            "file": fname,
            "column": cname,
            "confidence": mapping.confidence.get(role, None),
        })
    for fname, cname in mapping.generic_numeric:
        rows.append({"role": "generic_numeric", "file": fname, "column": cname, "confidence": None})
    for fname, cname in mapping.generic_categorical:
        rows.append({"role": "generic_categorical", "file": fname, "column": cname, "confidence": None})
    return pd.DataFrame(rows)
