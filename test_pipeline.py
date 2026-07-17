from fastapi.testclient import TestClient
from main import app
import os

client = TestClient(app)

print("Starting pipeline test...")

# Test 1: Upload Stage
print("Testing Stage 1: /api/upload")
with open("test_data.csv", "rb") as f:
    response = client.post("/api/upload", files={"files": ("test_data.csv", f, "text/csv")})

if response.status_code == 200:
    print("Stage 1 Upload successful.")
    data = response.json()
    print("Schema profiling result keys:", data.keys())
    
    # Test 2: Confirm Mapping
    print("\nTesting Confirm Mapping...")
    cookie = response.cookies.get("fp_session")
    if cookie:
        client.cookies.set("fp_session", cookie)
        
    confirm_res = client.post("/api/confirm-mapping", json={"mapping": {}})
    if confirm_res.status_code == 200:
        print("Mapping confirmed successfully.")
        print(confirm_res.json())
    else:
        print("Mapping confirm failed:", confirm_res.status_code, confirm_res.json())
        
else:
    print("Upload failed:", response.status_code, response.text)

# Test 3: Status
print("\nTesting /api/status")
status_res = client.get("/api/status")
print("Status:", status_res.status_code, status_res.json())

# Check HTML endpoints
print("\nVerifying UI endpoints...")
for endpoint in ["/", "/preprocess", "/analyze", "/report"]:
    html_res = client.get(endpoint)
    if html_res.status_code == 200:
        print(f"GET {endpoint} loaded successfully.")
    else:
        print(f"GET {endpoint} failed with status {html_res.status_code}")

print("\nPipeline test complete.")
