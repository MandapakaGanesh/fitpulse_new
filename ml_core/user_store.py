# ═══════════════════════════════════════════════════════════════
#  FITPULSE WEB · user_store.py
#
#  Handles secure persistent user accounts and user-specific reports.
#  Stored in: MongoDB (fitpulse DB)
# ═══════════════════════════════════════════════════════════════

import os
import time
import hashlib
import uuid
from typing import Any, Optional, Dict, List
from pymongo import MongoClient
import bson

# Connection settings
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
db = client["fitpulse"]
users_col = db["users"]
runs_col = db["runs"]


def check_connection() -> bool:
    try:
        client.admin.command('ismaster')
        return True
    except Exception:
        return False


# For warning at import
if not check_connection():
    print("+----------------------------------------------------------+")
    print("| WARNING: MongoDB is not responding on 127.0.0.1:27017    |")
    print("| Please ensure MongoDB is running or set MONGO_URI.       |")
    print("+----------------------------------------------------------+")


def _generate_salt() -> str:
    return uuid.uuid4().hex


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def seed_admin_user() -> None:
    try:
        if users_col.count_documents({"_id": "admin"}) == 0:
            salt = _generate_salt()
            hashed = _hash_password("fitpulse2026", salt)
            users_col.insert_one({"_id": "admin", "salt": salt, "hash": hashed})
    except Exception:
        # DB connection could be inactive during import
        pass


# Seed admin automatically on import
seed_admin_user()


def register_user(username: str, password: str) -> bool:
    """
    Registers a new user inside MongoDB with hashed credentials.
    Returns: True if success, False if user exists.
    Raises: PyMongoError on database connection failures or issues.
    """
    username = username.strip().lower()
    if not username or not password:
        return False
        
    if users_col.count_documents({"_id": username}) > 0:
        return False
        
    salt = _generate_salt()
    hashed = _hash_password(password, salt)
    users_col.insert_one({"_id": username, "salt": salt, "hash": hashed})
    return True


def verify_user(username: str, password: str) -> bool:
    """
    Verifies that the username and password match database records.
    Returns: True if credentials match, False if user doesn't exist or password mismatch.
    Raises: PyMongoError on database connection failures.
    """
    username = username.strip().lower()
    if not username or not password:
        return False
        
    user_info = users_col.find_one({"_id": username})
    if not user_info:
        return False
        
    salt = user_info.get("salt")
    stored_hash = user_info.get("hash")
    
    return _hash_password(password, salt) == stored_hash


# ── Mongo PDF and Results Storage ─────────────────────────────────

def save_user_run(username: str, run_id: str, metadata: dict, pdf_bytes: bytes, analysis_results: dict) -> None:
    """
    Persist all assets from an analysis run to the MongoDB run collection.
    """
    username = username.strip().lower()
    
    doc = {
        "_id": run_id,
        "username": username,
        "timestamp": metadata.get("timestamp", time.time()),
        "anomaly_count": metadata.get("anomaly_count", 0),
        "mean": metadata.get("mean", 0.0),
        "sigma": metadata.get("sigma", 2.5),
        "eps": metadata.get("eps", 0.8),
        "pdf_report": bson.Binary(pdf_bytes) if pdf_bytes else None,
        "analysis_results": analysis_results,
        "metadata": metadata
    }
    
    try:
        runs_col.replace_one({"_id": run_id}, doc, upsert=True)
    except Exception as e:
        print(f"Error saving run to MonogDB: {e}")


def get_user_run_pdf(username: str, run_id: str) -> Optional[bytes]:
    """Retrieve binary PDF data for a run."""
    try:
        doc = runs_col.find_one({"_id": run_id, "username": username.strip().lower()})
        if doc and doc.get("pdf_report"):
            return bytes(doc["pdf_report"])
    except Exception as e:
        print(f"Error retrieving PDF from MongoDB: {e}")
    return None


def load_user_run_results(username: str, run_id: str) -> Optional[dict]:
    """Retrieve run analytics dictionary."""
    try:
        doc = runs_col.find_one({"_id": run_id, "username": username.strip().lower()})
        if doc:
            return doc.get("analysis_results")
    except Exception as e:
        print(f"Error loading run results from MongoDB: {e}")
    return None


def list_user_runs(username: str) -> List[Dict[str, Any]]:
    """
    List all report metadata objects for a user from MongoDB.
    """
    username = username.strip().lower()
    history = []
    
    try:
        cursor = runs_col.find({"username": username}).sort("timestamp", -1)
        for doc in cursor:
            meta = doc.get("metadata") or {}
            meta["run_id"] = doc["_id"]
            history.append(meta)
    except Exception as e:
        print(f"Error listing user runs from MongoDB: {e}")
        
    return history
