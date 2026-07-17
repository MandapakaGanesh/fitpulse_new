# ═══════════════════════════════════════════════════════════════
#  FITPULSE WEB · ml_core/analysis_engine.py
#
#  Stage 3 Analysis:
#    – Isolation Forest anomaly detection on numeric columns
#    – Rolling stats (7-day average trend)
#    – Base64 encoded matplotlib chart (activity + anomaly markers)
#    – Plain-English insight generation for the UI
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import io
import base64
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — safe in web context
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from sklearn.ensemble import IsolationForest

ROLE_LABELS = {
    "user_id": "User / Participant ID",
    "timestamp": "Date / Timestamp",
    "heart_rate": "Heart Rate",
    "steps": "Steps",
    "sleep_duration": "Sleep Duration",
    "calories": "Calories",
    "activity_intensity": "Activity Intensity",
    "distance": "Distance",
    "weight": "Weight / BMI",
    "workout_type": "Workout Type",
}


# ── Chart theme (matches hospital UI: white bg, teal/blue palette) ───────────

PALETTE = {
    "normal":  "#3b82f6",   # blue for normal data points
    "anomaly": "#ef4444",   # red for flagged anomalies
    "trend":   "#0d9488",   # teal for rolling average
    "fill":    "#eff6ff",   # light blue fill under the line
    "grid":    "#e2e8f0",
    "text":    "#1e293b",
    "muted":   "#64748b",
}


def _fig_to_b64(fig: plt.Figure) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#ffffff")
    buf.seek(0)
    img_bytes = buf.read()
    plt.close(fig)
    return base64.b64encode(img_bytes).decode("utf-8")


def _pick_primary_metric(df: pd.DataFrame, mapping: Optional[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """
    Choose the best numeric column to analyse. Returns (column_name, role).
    Priority: confirmed mapping roles first, then any numeric column.
    """
    role_priority = ["steps", "heart_rate", "calories", "distance",
                     "activity_intensity", "sleep_duration", "weight"]

    if mapping:
        m = mapping.get("mapping", {})
        for role in role_priority:
            entry = m.get(role)
            if entry and entry.get("column") and entry["column"] in df.columns:
                return entry["column"], role

    # Fallback: first numeric column that isn't obviously an ID
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) and df[col].nunique() > 5:
            return col, None
    return None, None


def _pick_date_column(df: pd.DataFrame, mapping: Optional[Dict]) -> Optional[str]:
    """Find the date/timestamp column from the mapping or by dtype inspection."""
    if mapping:
        m = mapping.get("mapping", {})
        ts_entry = m.get("timestamp")
        if ts_entry and ts_entry.get("column") and ts_entry["column"] in df.columns:
            return ts_entry["column"]

    # Fallback: first datetime-parseable column
    for col in df.columns:
        tried = pd.to_datetime(df[col], errors="coerce")
        if tried.notna().mean() > 0.7:
            return col
    return None


# ── Core analysis function ───────────────────────────────────────────────────

def run_analysis(
    cleaned_dfs: Dict[str, pd.DataFrame],
    confirmed_mapping: Optional[Dict] = None,
    sigma: float = 2.5,
    eps: float = 0.8,
) -> Dict[str, Any]:
    """
    Run Stage 3 analysis on cleaned data.

    Returns a dict with:
        chart_b64       – base64 PNG for the main activity chart
        anomalies       – list of dicts {date, value, severity_label}
        summary_stats   – {mean, max, min, std, anomaly_count, total_days}
        insights        – list of plain-English insight strings for the UI
        metric_name     – human-readable label for the analysed metric
        error           – error string if something failed (else None)
    """

    # ── 1. Merge all frames into one ──────────────────────────────────────────
    if not cleaned_dfs:
        return _error_result("No cleaned data available.")

    df = pd.concat(list(cleaned_dfs.values()), ignore_index=True)

    # ── 2. Identify the metric and date columns ───────────────────────────────
    metric_col, metric_role = _pick_primary_metric(df, confirmed_mapping)
    date_col   = _pick_date_column(df, confirmed_mapping)

    if metric_col is None:
        return _error_result("Could not find a numeric health metric column to analyse.")

    metric_series = pd.to_numeric(df[metric_col], errors="coerce").dropna()
    metric_label  = metric_col.replace("_", " ").title()

    # ── 3. Build a clean time-indexed series if we have dates ─────────────────
    if date_col:
        try:
            df["__date"] = pd.to_datetime(df[date_col], errors="coerce")
            tdf = df[["__date", metric_col]].dropna().sort_values("__date")
            tdf = tdf.rename(columns={metric_col: "value", "__date": "date"})
            tdf["value"] = pd.to_numeric(tdf["value"], errors="coerce")
            tdf = tdf.dropna()
        except Exception:
            tdf = _make_index_frame(metric_series)
    else:
        tdf = _make_index_frame(metric_series)

    if len(tdf) < 3:
        return _error_result("Not enough data points to run analysis (need at least 3 rows).")

    # ── 4. Anomaly detection (3 layers) ──────────────────────────────────
    from sklearn.cluster import DBSCAN

    tdf = tdf.copy()
    overall_mean = tdf["value"].mean()
    overall_std = tdf["value"].std()

    window = min(7, max(2, len(tdf) // 5))
    tdf["rolling_avg"] = tdf["value"].rolling(window=window, center=True, min_periods=1).mean()
    tdf["rolling_med"] = tdf["value"].rolling(window=window, center=True, min_periods=1).median()
    tdf["residual"] = np.abs(tdf["value"] - tdf["rolling_med"])
    residual_std = tdf["residual"].std()

    X = tdf[["value"]].values
    X_std = (X - overall_mean) / (overall_std if overall_std > 0 else 1)
    # n_jobs=1 to avoid issues in some environments
    db = DBSCAN(eps=eps, min_samples=3).fit(X_std)
    tdf["dbscan_cluster"] = db.labels_

    anomaly_reasons = []
    
    for idx, row in tdf.iterrows():
        reasons = []
        val = row["value"]
        
        # Layer 1: Threshold
        if abs(val - overall_mean) > sigma * overall_std:
            bound = "above" if val > overall_mean else "below"
            reasons.append(f"Threshold: {val:.1f} is unusually {bound} normal historic range.")
            
        # Layer 2: Residual 
        res = row["residual"]
        if pd.notna(res) and residual_std > 0 and res > 3.0 * residual_std:
            sigma_val = res / residual_std
            reasons.append(f"Trend break: {sigma_val:.1f} standard deviations from rolling median.")
            
        # Layer 3: DBSCAN
        if row["dbscan_cluster"] == -1:
            reasons.append(f"Clustering: Isolated value distinctly far from typical day patterns.")
            
        anomaly_reasons.append(reasons)
        
    tdf["reasons"] = anomaly_reasons
    tdf["is_anomaly"] = tdf["reasons"].apply(len) > 0

    anomaly_rows = tdf[tdf["is_anomaly"]].copy()
    anomalies = []
    
    for _, row in anomaly_rows.iterrows():
        severity = "High" if len(row["reasons"]) >= 2 else "Moderate"
        reason_str = " ".join(row["reasons"])
        anomalies.append({
            "date":  str(row["date"])[:10],
            "value": round(float(row["value"]), 1),
            "severity": severity,
            "reason": reason_str,
        })

    # ── 6. Summary statistics ─────────────────────────────────────────────────
    summary_stats = {
        "mean":          round(float(tdf["value"].mean()), 1),
        "max":           round(float(tdf["value"].max()),  1),
        "min":           round(float(tdf["value"].min()),  1),
        "std":           round(float(tdf["value"].std()),  1),
        "anomaly_count": int(tdf["is_anomaly"].sum()),
        "total_days":    len(tdf),
    }

    # ── 7. Chart ──────────────────────────────────────────────────────────────
    chart_b64 = _build_chart(tdf, metric_label, anomaly_rows, summary_stats, window)

    # ── 8. Plain-English insights ─────────────────────────────────────────────
    insights = _generate_insights(summary_stats, anomalies, metric_label, tdf)
    
    if confirmed_mapping and metric_role:
        conf = confirmed_mapping.get("confidence", {}).get(metric_role, 0)
        origin = confirmed_mapping.get("origin", {}).get(metric_role, "auto")
        if origin == "manual":
            insights.insert(0, f"📌 Note: This analysis is based on the column '{metric_col}', which was manually assigned by you.")
        elif conf < 0.6:
            insights.insert(0, f"📌 Note: This analysis is based on '{metric_col}' (auto-mapped with low confidence, {int(conf*100)}%). Please verify this is correct.")

    # ── 9. Correlation Insights ───────────────────────────────────────────────
    corr_insights = generate_correlation_insights(df, confirmed_mapping)

    # ── 10. Distinct Users (for cohort comparison) ────────────────────────────
    user_ids = []
    if confirmed_mapping:
        user_col = confirmed_mapping.get("mapping", {}).get("user_id", {}).get("column")
        if user_col and user_col in df.columns:
            user_ids = sorted(df[user_col].dropna().unique().tolist())

    return {
        "chart_b64":    chart_b64,
        "anomalies":    anomalies,
        "summary_stats": summary_stats,
        "insights":     insights,
        "correlation_insights": corr_insights,
        "user_ids":     user_ids,
        "metric_name":  metric_label,
        "error":        None,
    }


# ── Chart builder ───────────────────────────────────────────────────────────

def _build_chart(
    tdf: pd.DataFrame,
    metric_label: str,
    anomaly_rows: pd.DataFrame,
    stats: Dict,
    window: int,
) -> str:
    fig, ax = plt.subplots(figsize=(9, 4))
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    dates = tdf["date"]
    vals  = tdf["value"]
    roll  = tdf["rolling_avg"]

    # Filled area under the line
    ax.fill_between(dates, vals, alpha=0.08, color=PALETTE["normal"])

    # Normal data line
    ax.plot(dates, vals, color=PALETTE["normal"], linewidth=1.4,
            alpha=0.7, label=metric_label, zorder=2)

    # Rolling average
    ax.plot(dates, roll, color=PALETTE["trend"], linewidth=2.2,
            linestyle="--", label=f"{window}-pt Rolling Avg", zorder=3)

    # Anomaly markers
    if not anomaly_rows.empty:
        ax.scatter(anomaly_rows["date"], anomaly_rows["value"],
                   color=PALETTE["anomaly"], s=70, zorder=5,
                   label=f"Unusual Days ({len(anomaly_rows)})", edgecolors="white", linewidth=1)

    # Styling
    ax.set_title(f"{metric_label} Over Time — Anomaly Detection",
                 fontsize=13, fontweight="bold", color=PALETTE["text"], pad=12)
    ax.set_ylabel(metric_label, fontsize=10, color=PALETTE["muted"])
    ax.tick_params(colors=PALETTE["muted"], labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(PALETTE["grid"])
    ax.grid(True, color=PALETTE["grid"], linewidth=0.6, linestyle="-", alpha=0.8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    # X-axis: auto-format based on range
    import matplotlib.dates as mdates
    try:
        date_range = (pd.to_datetime(dates.max()) - pd.to_datetime(dates.min())).days
        if date_range > 365:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        elif date_range > 60:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        fig.autofmt_xdate(rotation=30, ha="right")
    except Exception:
        pass

    ax.legend(fontsize=9, framealpha=0.9, edgecolor=PALETTE["grid"],
              loc="upper right", fancybox=True)

    plt.tight_layout(pad=1.5)
    return _fig_to_b64(fig)


# ── Plain-English insight generator ─────────────────────────────────────────

def _generate_insights(
    stats: Dict,
    anomalies: List[Dict],
    metric_label: str,
    tdf: pd.DataFrame,
) -> List[str]:
    insights: List[str] = []
    n = stats["total_days"]
    mean = stats["mean"]
    acount = stats["anomaly_count"]

    # General summary
    insights.append(
        f"We analysed {n} data points for your <strong>{metric_label}</strong>. "
        f"Your average is <strong>{mean:,.1f}</strong>, ranging from "
        f"{stats['min']:,.1f} to {stats['max']:,.1f}."
    )

    # Anomaly insight
    pct = round(100 * acount / n, 1) if n > 0 else 0
    if acount == 0:
        insights.append("✅ No unusual readings were detected — your data looks consistent!")
    elif acount <= 2:
        insights.append(
            f"⚠️ We found <strong>{acount} unusual day(s)</strong> ({pct}% of your data). "
            "These are days where your reading was significantly higher or lower than your normal pattern."
        )
    else:
        insights.append(
            f"⚠️ We flagged <strong>{acount} unusual days</strong> ({pct}% of your data). "
            "This could mean a period of illness, high-stress events, or data recording issues."
        )

    # Trend insight
    try:
        first_half = tdf["value"].iloc[:len(tdf)//2].mean()
        second_half = tdf["value"].iloc[len(tdf)//2:].mean()
        change_pct = ((second_half - first_half) / first_half) * 100 if first_half else 0
        if abs(change_pct) > 10:
            direction = "📈 increasing" if change_pct > 0 else "📉 decreasing"
            insights.append(
                f"Your {metric_label} has been <strong>{direction}</strong> over time "
                f"(approximately {abs(change_pct):.0f}% change from your earlier readings)."
            )
        else:
            insights.append(
                f"Your {metric_label} has been <strong>fairly stable</strong> — "
                "no major upward or downward trend detected."
            )
    except Exception:
        pass

    return insights


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_index_frame(series: pd.Series) -> pd.DataFrame:
    """Fallback: create a simple index-based frame when no date column exists."""
    return pd.DataFrame({
        "date":  pd.date_range(start="2024-01-01", periods=len(series), freq="D"),
        "value": series.values,
    })


def _error_result(msg: str) -> Dict[str, Any]:
    return {
        "chart_b64":     None,
        "anomalies":     [],
        "summary_stats": {},
        "insights":      [f"❌ {msg}"],
        "metric_name":   "Unknown",
        "error":         msg,
    }

ROLE_LABELS = {
    "metric": "Metric",
    "date": "Date",
    "category": "Category"
}

def generate_correlation_insights(df: pd.DataFrame, mapping: Optional[Dict]) -> List[str]:
    insights = []
    
    numeric_cols = df.select_dtypes(include='number').columns
    # filter out typical IDs
    numeric_cols = [c for c in numeric_cols if not c.lower().endswith("id")]
    
    if len(numeric_cols) < 2:
        return ["Not enough numeric data to detect correlations."]
        
    col_to_label = {}
    if mapping:
        m = mapping.get("mapping", {})
        for role, entry in m.items():
            if entry and entry.get("column"):
                col_to_label[entry["column"]] = ROLE_LABELS.get(role, entry["column"])
                
    for col in numeric_cols:
        if col not in col_to_label:
            col_to_label[col] = col.replace("_", " ").title()
            
    corr = df[numeric_cols].corr()
    
    pairs = []
    for i in range(len(corr.columns)):
        for j in range(i + 1, len(corr.columns)):
            c1, c2 = corr.columns[i], corr.columns[j]
            val = corr.iloc[i, j]
            if pd.notna(val) and abs(val) > 0.5:
                pairs.append((c1, c2, val))
                
    pairs.sort(key=lambda x: abs(x[2]), reverse=True)
    
    if not pairs:
        return ["No strong correlations detected in this dataset."]
        
    for c1, c2, r in pairs[:3]:
        label1 = col_to_label.get(c1, c1)
        label2 = col_to_label.get(c2, c2)
        direction = "positively" if r > 0 else "negatively"
        if r > 0:
            desc = f"higher {label1} tends to align with higher {label2}"
        else:
            desc = f"higher {label1} tends to align with lower {label2}"
        
        insights.append(f"<strong>{label1}</strong> and <strong>{label2}</strong> are strongly {direction} correlated (r={r:.2f}) — {desc}.")
        
    return insights
