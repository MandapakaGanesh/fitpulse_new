# ═══════════════════════════════════════════════════════════════
#  FITPULSE WEB · session_store.py
#
#  No database. Each browser session gets a temp folder on disk:
#     /tmp/fitpulse_sessions/{session_id}/
#  DataFrames are pickled there; small metadata (schema mapping,
#  stage status, report run history) is stored as JSON. Everything
#  is wiped when cleanup_session() is called or the OS reclaims
#  /tmp. This is intentionally NOT a database — no schema, no
#  migrations, nothing survives beyond the session's lifetime.
# ═══════════════════════════════════════════════════════════════

import os
import json
import pickle
import shutil
import tempfile
import uuid
from typing import Any, Optional

import pandas as pd

BASE_DIR = os.path.join(tempfile.gettempdir(), "fitpulse_sessions")
os.makedirs(BASE_DIR, exist_ok=True)


def new_session_id() -> str:
    return uuid.uuid4().hex


def _session_dir(session_id: str) -> str:
    path = os.path.join(BASE_DIR, session_id)
    os.makedirs(path, exist_ok=True)
    return path


def session_exists(session_id: str) -> bool:
    return os.path.isdir(os.path.join(BASE_DIR, session_id))


def cleanup_session(session_id: str) -> None:
    path = os.path.join(BASE_DIR, session_id)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


# ── DataFrame storage (pickled — preserves dtypes exactly, unlike CSV) ───────

def save_df(session_id: str, name: str, df: pd.DataFrame) -> None:
    path = os.path.join(_session_dir(session_id), f"{name}.pkl")
    with open(path, "wb") as f:
        pickle.dump(df, f)


def load_df(session_id: str, name: str) -> Optional[pd.DataFrame]:
    path = os.path.join(_session_dir(session_id), f"{name}.pkl")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def save_df_dict(session_id: str, name: str, dfs: dict) -> None:
    """Store a dict of {filename: DataFrame} as one pickle."""
    path = os.path.join(_session_dir(session_id), f"{name}.pkl")
    with open(path, "wb") as f:
        pickle.dump(dfs, f)


def load_df_dict(session_id: str, name: str) -> Optional[dict]:
    path = os.path.join(_session_dir(session_id), f"{name}.pkl")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


# ── JSON metadata storage (mapping, stage status, report history) ───────────

def save_json(session_id: str, name: str, data: Any) -> None:
    path = os.path.join(_session_dir(session_id), f"{name}.json")
    with open(path, "w") as f:
        json.dump(data, f, default=str, indent=2)


def load_json(session_id: str, name: str) -> Optional[Any]:
    path = os.path.join(_session_dir(session_id), f"{name}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


# ── Generic file storage (generated PDFs/CSVs, keyed by run_id) ─────────────

def reports_dir(session_id: str) -> str:
    path = os.path.join(_session_dir(session_id), "reports")
    os.makedirs(path, exist_ok=True)
    return path


def save_report_file(session_id: str, run_id: str, filename: str, content_bytes: bytes) -> str:
    run_dir = os.path.join(reports_dir(session_id), run_id)
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, filename)
    with open(path, "wb") as f:
        f.write(content_bytes)
    return path


def get_report_file_path(session_id: str, run_id: str, filename: str) -> Optional[str]:
    path = os.path.join(reports_dir(session_id), run_id, filename)
    return path if os.path.isfile(path) else None


def list_runs(session_id: str) -> list:
    """List all report run_ids generated in this session, most recent first."""
    rd = reports_dir(session_id)
    runs = [d for d in os.listdir(rd) if os.path.isdir(os.path.join(rd, d))]
    runs.sort(key=lambda r: os.path.getmtime(os.path.join(rd, r)), reverse=True)
    return runs
