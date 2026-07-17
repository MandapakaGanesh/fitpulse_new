# ═══════════════════════════════════════════════════════════════
#  FITPULSE WEB · ml_core/report_engine.py
#
#  Stage 4: PDF Report Generation using fpdf2
#  Uses ONLY ASCII-safe text (Helvetica doesn't support Unicode)
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import base64
import io
import datetime
from typing import Any, Dict, List, Optional

from fpdf import FPDF


# ── Strip emojis and unicode chars for Helvetica safety ──────────────────────

def _safe(text: str) -> str:
    """Replace common Unicode characters with ASCII equivalents."""
    replacements = {
        "\u2014": "-",   # em-dash
        "\u2013": "-",   # en-dash
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u00b7": "-",   # middle dot
        "\u2022": "-",   # bullet
        # Emojis in insights causing encoding crashes / ugliness
        "⚠️ ": "",
        "⚠️": "",
        "📉 ": "",
        "📉": "",
        "📈 ": "",
        "📈": "",
        "✅ ": "",
        "✅": "",
        "📌 ": "",
        "📌": "",
        "❌ ": "",
        "❌": "",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Strip emojis and other non-latin1 chars
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


# ── Colour palette (RGB) ────────────────────────────────────────────────────
class C:
    WHITE     = (255, 255, 255)
    BG        = (244, 247, 251)
    BLUE      = ( 37,  99, 235)
    TEAL      = ( 13, 148, 136)
    RED       = (239,  68,  68)
    AMBER     = (245, 158,  11)
    TEXT      = ( 30,  41,  59)
    MUTED     = (100, 116, 139)
    EDGE      = (226, 232, 240)
    BANNER_BG = (236, 253, 245)
    BANNER_BD = (167, 243, 208)


class FitPulseReport(FPDF):
    """Custom FPDF subclass with branded header and footer."""

    def header(self):
        self.set_fill_color(*C.BLUE)
        self.rect(0, 0, 210, 14, style="F")
        self.set_y(3)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*C.WHITE)
        self.cell(0, 8, "  FitPulse - Personal Health Report", align="L")
        self.set_font("Helvetica", "", 8)
        date_str = datetime.datetime.now().strftime("%d %B %Y")
        self.cell(0, 8, f"Generated: {date_str}  ", align="R", ln=True)
        self.set_text_color(*C.TEXT)
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*C.MUTED)
        self.cell(0, 8, "FitPulse Health Analytics  |  Confidential", align="L")
        self.cell(0, 8, f"Page {self.page_no()} / {{nb}}", align="R")


# ── Section helpers ──────────────────────────────────────────────────────────

def _section_heading(pdf: FPDF, title: str):
    pdf.set_fill_color(*C.EDGE)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*C.BLUE)
    pdf.cell(0, 8, f"  {_safe(title)}", fill=True, ln=True, border=0)
    pdf.set_text_color(*C.TEXT)
    pdf.ln(2)


def _stat_card_row(pdf: FPDF, cards: List[Dict]):
    """Render a row of mini stat boxes across the page width."""
    col_w = (pdf.w - 2 * pdf.l_margin) / len(cards)
    col_h = 18
    x_start = pdf.l_margin

    for i, card in enumerate(cards):
        x = x_start + i * col_w
        pdf.set_draw_color(*C.EDGE)
        pdf.set_fill_color(*C.WHITE)
        pdf.rect(x, pdf.get_y(), col_w - 2, col_h, style="FD")
        # Label
        pdf.set_xy(x + 2, pdf.get_y() + 2)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*C.MUTED)
        pdf.cell(col_w - 4, 4, _safe(card["label"]).upper(), align="C", ln=False)
        # Value
        pdf.set_xy(x + 2, pdf.get_y() + 4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*C.BLUE)
        pdf.cell(col_w - 4, 7, _safe(str(card["value"])), align="C", ln=False)

    pdf.ln(col_h + 4)
    pdf.set_text_color(*C.TEXT)


def _insight_box(pdf: FPDF, text: str, bg: tuple = (239, 246, 255)):
    """Light-blue insight box with left accent stripe."""
    clean = _safe(text)

    x = pdf.l_margin
    y = pdf.get_y()

    # Measure height needed
    pdf.set_font("Helvetica", "", 9)
    line_w = pdf.w - 2 * pdf.l_margin - 10
    # Estimate lines (rough: 1 line per ~90 chars at font size 9)
    n_lines = max(1, len(clean) // 80 + 1)
    box_h = max(12, n_lines * 5 + 4)

    # Blue left stripe
    pdf.set_fill_color(*C.BLUE)
    pdf.rect(x, y, 3, box_h, style="F")

    # Box body
    pdf.set_fill_color(*bg)
    pdf.rect(x + 3, y, pdf.w - 2 * pdf.l_margin - 3, box_h, style="F")

    pdf.set_xy(x + 6, y + 2)
    pdf.set_text_color(*C.TEXT)
    pdf.multi_cell(line_w, 4, clean, border=0)
    pdf.set_y(y + box_h + 2)


def _anomaly_table(pdf: FPDF, anomalies: List[Dict], metric_name: str):
    col_widths = [55, 55, 55]
    headers = ["Date", _safe(metric_name), "Severity"]

    # Header row
    pdf.set_fill_color(*C.BLUE)
    pdf.set_text_color(*C.WHITE)
    pdf.set_font("Helvetica", "B", 9)
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 8, f"  {h}", border=0, fill=True)
    pdf.ln()

    # Data rows
    for i, a in enumerate(anomalies):
        bg = C.WHITE if i % 2 == 0 else C.BG
        pdf.set_fill_color(*bg)
        pdf.set_text_color(*C.TEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(col_widths[0], 7, f"  {a['date']}", border=0, fill=True)
        pdf.cell(col_widths[1], 7, f"  {a['value']:,}", border=0, fill=True)

        sev = a.get("severity", "Moderate")
        color = C.RED if sev == "High" else C.AMBER
        pdf.set_text_color(*color)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(col_widths[2], 7, f"  {sev}", border=0, fill=True)
        pdf.ln()

        reason = a.get("reason")
        if reason:
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(*C.MUTED)
            # Indented sub-row
            pdf.cell(5, 5, "", border=0, fill=True) 
            pdf.multi_cell(0, 5, f"->  {_safe(reason)}", border=0, fill=True)
            
        pdf.set_text_color(*C.TEXT)

    pdf.ln(4)


# ── Public entry point ───────────────────────────────────────────────────────

def generate_pdf(
    results: Dict[str, Any],
    session_meta: Optional[Dict] = None,
) -> bytes:
    pdf = FitPulseReport()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    metric_name = _safe(results.get("metric_name", "Health Metric"))
    stats       = results.get("summary_stats", {})
    insights    = results.get("insights", [])
    anomalies   = results.get("anomalies", [])
    chart_b64   = results.get("chart_b64", "")

    # ── 1. Title block ────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*C.TEXT)
    pdf.cell(0, 10, f"{metric_name} - Health Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*C.MUTED)
    pdf.cell(0, 6, f"Analysed {stats.get('total_days', '?')} data points  |  "
                   f"FitPulse Anomaly Detection Pipeline", ln=True)
    pdf.ln(6)

    # ── 2. Key stats cards ────────────────────────────────────────────────────
    _section_heading(pdf, "At a Glance")
    cards = [
        {"label": "Days",          "value": stats.get("total_days", "-")},
        {"label": "Average",       "value": f"{stats.get('mean', '-'):,}"},
        {"label": "Peak",          "value": f"{stats.get('max', '-'):,}"},
        {"label": "Lowest",        "value": f"{stats.get('min', '-'):,}"},
        {"label": "Unusual Days",  "value": stats.get("anomaly_count", 0)},
    ]
    _stat_card_row(pdf, cards)

    # ── 3. Insights ───────────────────────────────────────────────────────────
    _section_heading(pdf, "What We Found")
    for insight in insights:
        _insight_box(pdf, insight)
    pdf.ln(2)

    # ── 4. Chart (if available) ───────────────────────────────────────────────
    if chart_b64:
        _section_heading(pdf, "Activity Chart")
        try:
            img_bytes = base64.b64decode(chart_b64)
            img_buf = io.BytesIO(img_bytes)
            img_w = pdf.w - 2 * pdf.l_margin
            pdf.image(img_buf, x=pdf.l_margin, w=img_w)
            pdf.ln(4)
        except Exception:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*C.MUTED)
            pdf.cell(0, 6, "(Chart could not be embedded)", ln=True)
            pdf.ln(2)

    # ── 5. Anomaly table ──────────────────────────────────────────────────────
    if anomalies:
        _section_heading(pdf, f"Flagged Unusual Days ({len(anomalies)} total)")
        _anomaly_table(pdf, anomalies, metric_name)
    else:
        _section_heading(pdf, "Anomaly Check")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(7, 150, 100)
        pdf.cell(0, 7, "  No unusual readings were detected in your data.", ln=True)
        pdf.set_text_color(*C.TEXT)
        pdf.ln(2)

    # ── 6. Disclaimer ─────────────────────────────────────────────────────────
    pdf.ln(6)
    pdf.set_fill_color(*C.BANNER_BG)
    pdf.set_draw_color(*C.BANNER_BD)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*C.MUTED)
    pdf.multi_cell(0, 5,
        "This report was automatically generated by FitPulse. Results are based on "
        "statistical pattern detection and are intended for personal wellness tracking only. "
        "Always consult a qualified healthcare professional for medical decisions.",
        border=1, fill=True
    )

    return bytes(pdf.output())
