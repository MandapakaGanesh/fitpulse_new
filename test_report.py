"""Quick test to reproduce the PDF generation error."""
import json
from ml_core.report_engine import generate_pdf

# Simulate realistic analysis results
results = {
    "metric_name": "Stepcount",
    "summary_stats": {
        "mean": 7084.5,
        "max": 9223,
        "min": 4080,
        "std": 1800.0,
        "anomaly_count": 2,
        "total_days": 15,
    },
    "insights": [
        "We analysed 15 data points for your <strong>Stepcount</strong>. Your average is <strong>7,084.5</strong>.",
        "⚠️ We found <strong>2 unusual day(s)</strong> (13.3% of your data).",
        "Your Stepcount has been <strong>📉 decreasing</strong> over time.",
    ],
    "anomalies": [
        {"date": "2023-01-03", "value": 4080, "severity": "Moderate"},
        {"date": "2023-01-04", "value": 9223, "severity": "High"},
    ],
    "chart_b64": None,  # skip chart for quick test
    "error": None,
}

try:
    pdf_bytes = generate_pdf(results)
    print(f"PDF generated OK — {len(pdf_bytes)} bytes")
    with open("test_report.pdf", "wb") as f:
        f.write(pdf_bytes)
    print("Saved to test_report.pdf")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
