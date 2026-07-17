# ═══════════════════════════════════════════════════════════════
#  FITPULSE WEB · main.py
#
#  FastAPI backend for the rebuilt FitPulse wizard flow:
#    Stage 1: Upload  → Stage 2: Preprocess → Stage 3: Analyze → Stage 4: Report
#
#  No database — session state lives in a per-session temp folder
#  (see ml_core/session_store.py), addressed via a plain session-id
#  cookie. This file currently wires up Stage 1 end-to-end; Stages
#  2-4 are added incrementally on top of this same app.
# ═══════════════════════════════════════════════════════════════

import io
import time
import json
import uuid
from typing import List, Optional
import os

import pandas as pd
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ml_core import session_store, user_store
from ml_core.schema_engine import profile_and_map
from ml_core.mapping_serialize import mapping_to_json, mapping_from_json
from ml_core.analysis_engine import run_analysis
from ml_core.report_engine import generate_pdf

app = FastAPI(title="FitPulse")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SESSION_COOKIE = "fp_session"


# ── Session helper ────────────────────────────────────────────────────────

def check_auth(request: Request) -> bool:
    """
    Check if the user is authenticated by reading the fp_logged_in cookie.
    """
    return request.cookies.get("fp_logged_in") == "true"


def get_username(request: Request) -> str:
    """Retrieves the username from the session cookies."""
    return request.cookies.get("fp_user") or "anonymous"


def get_session_id(request: Request) -> str:
    """
    Read the session id from the cookie. Stage-1 GET routes create a new
    one if absent (via ensure_session_cookie below); API routes require
    it to already exist and raise if it's missing, since that means the
    user skipped the upload step.
    """
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized. Please log in.")
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid or not session_store.session_exists(sid):
        raise HTTPException(status_code=400, detail="No active session. Please start from the Upload page.")
    return sid


# ── Page routes ────────────────────────────────────────────────────────────

@app.get("/auth", response_class=HTMLResponse)
def auth_portal_page(request: Request):
    if check_auth(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "auth_portal.html", {"stage": 0})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if check_auth(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "login.html", {"stage": 0})


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if check_auth(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "register.html", {"stage": 0})


@app.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/auth")
    response.delete_cookie("fp_logged_in")
    response.delete_cookie("fp_user")
    return response


@app.post("/api/login")
async def api_login(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request payload")
    
    username = body.get("username")
    password = body.get("password")
    
    try:
        is_valid = user_store.verify_user(username, password)
    except Exception as e:
        print(f"Database error during authentication: {e}")
        return JSONResponse(
            {"status": "error", "message": "Database connection error. Please verify your MONGO_URI is configured correctly in Render dashboard environment variables."},
            status_code=500
        )
        
    if is_valid:
        response = JSONResponse({"status": "success", "redirect": "/"})
        response.set_cookie("fp_logged_in", "true", httponly=True, samesite="lax")
        response.set_cookie("fp_user", username.strip().lower(), httponly=True, samesite="lax")
        return response
    return JSONResponse({"status": "error", "message": "Invalid username or password"}, status_code=401)


@app.post("/api/register")
async def api_register(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request payload")
    
    username = body.get("username")
    password = body.get("password")
    
    if not username or not password:
        return JSONResponse({"status": "error", "message": "Username and password are required."}, status_code=400)
    
    try:
        success = user_store.register_user(username, password)
    except Exception as e:
        print(f"Database error during registration: {e}")
        return JSONResponse(
            {"status": "error", "message": "Database connection error. Please verify your MONGO_URI is configured correctly in Render dashboard environment variables."},
            status_code=500
        )
        
    if success:
        return JSONResponse({"status": "success", "message": "Registered successfully."})
    else:
        return JSONResponse({"status": "error", "message": "Username already exists."}, status_code=409)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/auth")
    sid = request.cookies.get(SESSION_COOKIE)
    is_new = not sid or not session_store.session_exists(sid)
    response = templates.TemplateResponse(request, "upload.html", {"stage": 1})
    if is_new:
        new_sid = session_store.new_session_id()
        response.set_cookie(SESSION_COOKIE, new_sid, httponly=True, samesite="lax")
    return response


@app.get("/preprocess", response_class=HTMLResponse)
def preprocess_page(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/auth")
    sid = get_session_id(request)
    raw_dfs = session_store.load_df_dict(sid, "raw_uploads") or {}
    
    stats = {"file_count": 0, "total_rows": 0, "total_cols": 0}
    if raw_dfs:
        stats["total_rows"] = sum(df.shape[0] for df in raw_dfs.values())
        stats["total_cols"] = sum(df.shape[1] for df in raw_dfs.values())
        stats["file_count"] = len(raw_dfs)
        
    return templates.TemplateResponse(request, "preprocess.html", {"stage": 2, "stats": stats})


@app.get("/analyze", response_class=HTMLResponse)
def analyze_page(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/auth")
    sid = request.cookies.get(SESSION_COOKIE)
    results = None
    if sid and session_store.session_exists(sid):
        results = session_store.load_json(sid, "analysis_results")
    return templates.TemplateResponse(request, "analyze.html", {"stage": 3, "results": results})


@app.get("/report", response_class=HTMLResponse)
def report_page(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/auth")
    sid = request.cookies.get(SESSION_COOKIE)
    results = None
    if sid and session_store.session_exists(sid):
        results = session_store.load_json(sid, "analysis_results")
    return templates.TemplateResponse(request, "report.html", {"stage": 4, "results": results})


@app.get("/api/download-report")
def api_download_report(request: Request, run_id: Optional[str] = None):
    username = get_username(request)
    
    if run_id:
        pdf_bytes = user_store.get_user_run_pdf(username, run_id)
        if not pdf_bytes:
            raise HTTPException(status_code=404, detail="Requested report PDF not found.")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=fitpulse_health_report_{run_id}.pdf"}
        )
        
    sid = get_session_id(request)
    results = session_store.load_json(sid, "analysis_results")
    if not results:
        raise HTTPException(status_code=400, detail="No analysis results found. Please run analysis first.")

    pdf_bytes = generate_pdf(results)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=fitpulse_health_report.pdf"}
    )


# ── Stage 1 API: upload + schema profiling ─────────────────────────────────

def _compute_quality_report(raw_dfs, mapping):
    report = {"files": {}, "columns": {}}
    for fname, df in raw_dfs.items():
        n_rows = len(df)
        n_dupes = df.duplicated().sum()
        
        report["files"][fname] = {
            "n_rows": n_rows,
            "n_cols": len(df.columns),
            "n_duplicates": int(n_dupes)
        }
        
        # See if there's an inferred timestamp column for this file
        ts_cols = set()
        ts_map = mapping.mapping.get("timestamp")
        if ts_map and ts_map[0] == fname:
            ts_cols.add(ts_map[1])
            
        report["columns"][fname] = {}
        for col in df.columns:
            n_missing = int(df[col].isna().sum())
            missing_pct = round((n_missing / n_rows) * 100, 1) if n_rows > 0 else 0
            
            c_report = {"missing_pct": missing_pct, "date_range": None}
            if col in ts_cols or "date" in col.lower() or "time" in col.lower():
                try:
                    s = pd.to_datetime(df[col], errors='coerce').dropna()
                    if not s.empty:
                        c_report["date_range"] = f"{s.min().strftime('%Y-%m-%d')} to {s.max().strftime('%Y-%m-%d')}"
                except Exception:
                    pass
                    
            report["columns"][fname][col] = c_report
    return report


def _process_upload_dfs(sid: str, raw_dfs: dict) -> dict:
    if not raw_dfs:
        raise HTTPException(status_code=400, detail="No valid files provided.")

    profile, mapping = profile_and_map(raw_dfs)

    session_store.save_df_dict(sid, "raw_uploads", raw_dfs)
    session_store.save_json(sid, "inferred_mapping", mapping_to_json(mapping))
    session_store.save_json(sid, "profile_meta", {
        "overall_shape": profile.overall_shape,
        "join_keys": profile.join_keys,
        "files": {
            fname: {"n_rows": fp.n_rows, "n_cols": fp.n_cols, "shape_guess": fp.shape_guess}
            for fname, fp in profile.files.items()
        },
    })

    quality_report = _compute_quality_report(raw_dfs, mapping)
    columns_by_file = {fname: list(df.columns) for fname, df in raw_dfs.items()}

    return {
        "overall_shape": profile.overall_shape,
        "join_keys": profile.join_keys,
        "columns_by_file": columns_by_file,
        "inferred_mapping": mapping_to_json(mapping),
        "quality_report": quality_report,
    }


@app.post("/api/upload")
async def api_upload(request: Request, files: List[UploadFile] = File(...)):
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        sid = session_store.new_session_id()

    raw_dfs = {}
    for uf in files:
        if not uf.filename:
            continue
        fname_lower = uf.filename.lower()
        if not (fname_lower.endswith(".csv") or fname_lower.endswith(".xlsx") or fname_lower.endswith(".xls")):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format: {uf.filename}. Please upload only CSV (.csv) or Excel (.xlsx, .xls) files."
            )
        content = await uf.read()
        try:
            if fname_lower.endswith((".xlsx", ".xls")):
                df = pd.read_excel(io.BytesIO(content))
            else:
                df = pd.read_csv(io.BytesIO(content))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read {uf.filename}: {e}")
        raw_dfs[uf.filename] = df

    result = _process_upload_dfs(sid, raw_dfs)
    response = JSONResponse(result)
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return response


@app.post("/api/upload-sample")
async def api_upload_sample(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        sid = session_store.new_session_id()

    # Load from sample_data/ directory
    sample_dir = "sample_data"
    if not os.path.exists(sample_dir):
        raise HTTPException(status_code=404, detail="Sample dataset directory not found.")
        
    raw_dfs = {}
    for fname in os.listdir(sample_dir):
        if fname.endswith(".csv"):
            try:
                raw_dfs[fname] = pd.read_csv(os.path.join(sample_dir, fname))
            except Exception as e:
                pass
                
    result = _process_upload_dfs(sid, raw_dfs)
    response = JSONResponse(result)
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return response


@app.get("/api/session-mapping")
def api_session_mapping(request: Request):
    sid = get_session_id(request)
    raw_dfs = session_store.load_df_dict(sid, "raw_uploads")
    if not raw_dfs:
        raise HTTPException(status_code=400, detail="No active session data.")
        
    profile_meta = session_store.load_json(sid, "profile_meta") or {}
    inferred = session_store.load_json(sid, "inferred_mapping") or {}
    confirmed = session_store.load_json(sid, "confirmed_mapping")
    
    mapping_data = confirmed if confirmed else inferred
    
    # generate quality report 
    quality = _compute_quality_report(raw_dfs, mapping_from_json(mapping_data))
    
    return JSONResponse({
        "overall_shape": profile_meta.get("overall_shape", "unknown"),
        "join_keys": profile_meta.get("join_keys", []),
        "columns_by_file": {fname: list(df.columns) for fname, df in raw_dfs.items()},
        "inferred_mapping": mapping_data,
        "quality_report": quality
    })

@app.post("/api/confirm-mapping")
async def api_confirm_mapping(request: Request):
    sid = get_session_id(request)
    body = await request.json()

    # body shape expected: { "mapping": { role: {file, column} or null, ... } }
    confirmed = mapping_from_json({"mapping": body.get("mapping", {})})

    # Preserve the generic buckets from the original inference (frontend
    # doesn't edit these, they're informational only).
    inferred = session_store.load_json(sid, "inferred_mapping")
    if inferred:
        confirmed.generic_numeric = [
            (e["file"], e["column"]) for e in inferred.get("generic_numeric", [])
        ]
        confirmed.generic_categorical = [
            (e["file"], e["column"]) for e in inferred.get("generic_categorical", [])
        ]
        confirmed.confidence = inferred.get("confidence", {})
        
        inferred_map = inferred.get("mapping", {})
        for role, entry in confirmed.mapping.items():
            inf_entry = inferred_map.get(role)
            # compare if the user's selected file/col matches the inferred one
            if inf_entry and inf_entry.get("file") == entry[0] and inf_entry.get("column") == entry[1]:
                confirmed.origin[role] = "auto"
            else:
                confirmed.origin[role] = "manual"

    session_store.save_json(sid, "confirmed_mapping", mapping_to_json(confirmed))
    session_store.save_json(sid, "stage_status", {"upload": "done", "preprocess": "pending"})

    return JSONResponse({"status": "ok", "redirect": "/preprocess"})


@app.post("/api/clean-data")
async def api_clean_data(request: Request):
    sid = get_session_id(request)
    raw_dfs = session_store.load_df_dict(sid, "raw_uploads") or {}
    
    if not raw_dfs:
        raise HTTPException(status_code=400, detail="No raw data found.")
    
    # Very naive demo cleaning: take first dataframe, drop empty cols, forward fill
    df_name = list(raw_dfs.keys())[0]
    df = raw_dfs[df_name].copy()
    
    df = df.dropna(axis=1, how='all')
    df = df.ffill().bfill()
    
    session_store.save_df_dict(sid, "cleaned_data", {"merged": df})
    session_store.save_json(sid, "stage_status", {"upload": "done", "preprocess": "done", "analyze": "pending"})
    
    return JSONResponse({"status": "ok", "redirect": "/analyze"})


@app.post("/api/run-analysis")
async def api_run_analysis(request: Request):
    sid = get_session_id(request)

    cleaned_dfs = session_store.load_df_dict(sid, "cleaned_data") or {}
    if not cleaned_dfs:
        raise HTTPException(status_code=400, detail="No cleaned data found. Please complete preprocessing first.")

    confirmed_mapping = session_store.load_json(sid, "confirmed_mapping")

    results = run_analysis(cleaned_dfs, confirmed_mapping)

    if results.get("error"):
        raise HTTPException(status_code=422, detail=results["error"])

    # chart_b64 is too large for JSON in some edge cases; store separately if needed
    session_store.save_json(sid, "analysis_results", results)
    session_store.save_json(sid, "stage_status", {
        "upload": "done", "preprocess": "done", "analyze": "done", "report": "pending"
    })
    
    # Save run history
    run_id = uuid.uuid4().hex
    meta = {
        "timestamp": time.time(),
        "anomaly_count": results.get("summary_stats", {}).get("anomaly_count", 0),
        "mean": results.get("summary_stats", {}).get("mean", 0),
        "sigma": 2.5,
        "eps": 0.8
    }
    session_store.save_report_file(sid, run_id, "meta.json", json.dumps(meta).encode("utf-8"))

    # Secure persistent user run database
    try:
        pdf_bytes = generate_pdf(results)
    except Exception:
        pdf_bytes = b""
    username = get_username(request)
    user_store.save_user_run(username, run_id, meta, pdf_bytes, results)

    return JSONResponse(results)

@app.post("/api/rerun-anomaly-detection")
async def api_rerun_anomaly(request: Request):
    sid = get_session_id(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
        
    sigma = float(body.get("sigma", 2.5))
    eps = float(body.get("eps", 0.8))
    
    cleaned_dfs = session_store.load_df_dict(sid, "cleaned_data")
    if not cleaned_dfs:
        raise HTTPException(status_code=400, detail="Data required for analysis is missing.")
        
    confirmed_mapping = session_store.load_json(sid, "confirmed_mapping")
    
    try:
        from ml_core.analysis_engine import run_analysis
        results = run_analysis(cleaned_dfs, confirmed_mapping, sigma=sigma, eps=eps)
        session_store.save_json(sid, "analysis_results", results)
        
        # Save run history
        run_id = uuid.uuid4().hex
        meta = {
            "timestamp": time.time(),
            "anomaly_count": results.get("summary_stats", {}).get("anomaly_count", 0),
            "mean": results.get("summary_stats", {}).get("mean", 0),
            "sigma": sigma,
            "eps": eps
        }
        session_store.save_report_file(sid, run_id, "meta.json", json.dumps(meta).encode("utf-8"))
        
        # Secure persistent user run database
        try:
            pdf_bytes = generate_pdf(results)
        except Exception:
            pdf_bytes = b""
        username = get_username(request)
        user_store.save_user_run(username, run_id, meta, pdf_bytes, results)
        
        return JSONResponse(results)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user-comparison")
def api_user_comparison(request: Request, user_id: str):
    sid = get_session_id(request)
    cleaned_dfs = session_store.load_df_dict(sid, "cleaned_data")
    if not cleaned_dfs:
        raise HTTPException(status_code=400, detail="Cleaned data not available.")
        
    df = pd.concat(list(cleaned_dfs.values()), ignore_index=True)
    mapping = session_store.load_json(sid, "confirmed_mapping") or {}
    
    user_col = mapping.get("mapping", {}).get("user_id", {}).get("column")
    if not user_col or user_col not in df.columns:
        raise HTTPException(status_code=400, detail="user_id column not mapped.")
        
    df["__uid"] = df[user_col].astype(str)
    uid = str(user_id)
    
    role_labels = {
        "heart_rate": "Heart Rate", "steps": "Steps", "sleep_duration": "Sleep Duration",
        "calories": "Calories", "activity_intensity": "Activity Intensity", "distance": "Distance"
    }
    
    comparisons = []
    
    for role, label in role_labels.items():
        col_info = mapping.get("mapping", {}).get(role)
        if col_info and col_info.get("column") in df.columns:
            col = col_info["column"]
            if pd.api.types.is_numeric_dtype(df[col]):
                cohort_mean = float(df[col].mean())
                user_mean_dict = df.groupby("__uid")[col].mean()
                if uid in user_mean_dict and pd.notna(user_mean_dict[uid]):
                    user_mean = float(user_mean_dict[uid])
                    pct = float((user_mean_dict < user_mean).mean() * 100)
                    comparisons.append({
                        "metric": label,
                        "user_avg": round(user_mean, 1),
                        "cohort_avg": round(cohort_mean, 1),
                        "percentile": round(pct, 0)
                    })
                    
    return JSONResponse({"comparisons": comparisons})

@app.get("/profile", response_class=HTMLResponse)
def user_profile_page(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/auth")
    return templates.TemplateResponse(request, "profile.html", {"stage": 1, "username": get_username(request)})


@app.get("/api/profile-data")
def api_profile_data(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = get_username(request)
    runs = user_store.list_user_runs(username)
    
    # Calculate stats
    total_runs = len(runs)
    total_anomalies = sum(run.get("anomaly_count", 0) for run in runs)
    
    # Load analysis results for averages
    hr_samples = []
    for run in runs:
        res = user_store.load_user_run_results(username, run.get("run_id", ""))
        if res:
            mean_val = res.get("summary_stats", {}).get("mean", 0)
            if mean_val > 0:
                hr_samples.append(mean_val)
                
    avg_metric = round(sum(hr_samples) / len(hr_samples), 1) if hr_samples else 0.0
    
    return JSONResponse({
        "total_runs": total_runs,
        "total_anomalies": total_anomalies,
        "avg_metric": avg_metric,
        "runs": runs
    })


@app.get("/api/report-runs")
def api_report_runs(request: Request):
    sid = get_session_id(request)
    runs = session_store.list_runs(sid)
    history = []
    for r in runs:
        meta_path = session_store.get_report_file_path(sid, r, "meta.json")
        if meta_path:
            with open(meta_path, "r") as f:
                history.append(json.load(f))
    # Sort history chronologically
    history.sort(key=lambda x: x.get("timestamp", 0))
    return JSONResponse({"history": history})


@app.get("/api/status")
def api_status(request: Request):
    if not check_auth(request):
        return JSONResponse({"active": False})
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid or not session_store.session_exists(sid):
        return JSONResponse({"active": False})
    status = session_store.load_json(sid, "stage_status") or {}
    return JSONResponse({"active": True, "stage_status": status})
