# FitPulse - Health Anomaly Detection from Fitness Devices

FitPulse is a high-fidelity, secure wellness telemetry analytics dashboard and automated pattern detection pipeline designed for fitness tracker data. The application features a glassmorphic space-dark design system, multi-stage data cleaning wizard, interactive canvas statistics charting, and automated wellness report compilations.

---

## Technical Stack & Architecture

### 1. Frontend Interface (`templates/` & `static/`)
- **Responsive Layout**: Minimalist CSS Grid and Flexbox base featuring modern glassmorphism (translucent backdrops, fine border-glow gradients, responsive scale actions).
- **Data Cleaning Wizard**: Direct drag-and-drop CSV/Excel dataset uploader supporting automated column classification.
- **Data Visualization**: Real-time Interactive HTML5 `<canvas>` charting unusual activity periods over chronological runs.

### 2. Backend Engine (`main.py` & `ml_core/`)
- **FastAPI Framework**: Session tracking and request routing written for Python 3.13.
- **Data Parsing & Cleaning (`ml_core/schema_engine.py`)**:
  - *Phase 1 (Profiling)*: Analyzes column schemas, statistical spreads, data types.
  - *Phase 2 (Mapping)*: Maps columns to fitness tracker metrics (heart rate, step counts, dates).
  - *Phase 3 (Pattern Engine)*: Configurable clustering and statistical sensitivity filtering to find unusual patterns.
- **Automated Reporter**: Exports styled wellness summary reports in PDF formatting using the `fpdf2` engine.

### 3. Security & Persistent Database (MongoDB)
- **SHA-256 Hashing**: User credentials are encrypted using SHA-256 with unique client-side and server-side random UUID salts.
- **Persistency Model**: Stores metadata, sensitivity parameters, and PDF document files directly in a centralized MongoDB database (`fitpulse` DB).
- **Run Isolation**: Users can partition and access their run histories securely, isolating sensitive wellness data.

---

## Data Schema (MongoDB Collections)

### 1. `users` Collection
Stores credential salts and password hashes.
```json
{
  "_id": "username (lowercase, uniquely indexable)",
  "salt": "random_uuid_salt_string",
  "hash": "sha256_hashed_password"
}
```

### 2. `runs` Collection
Stores historical diagnostics runs, including raw analysis outputs and compiled PDFs.
```json
{
  "_id": "run_id_uuid",
  "username": "associated_analyst",
  "timestamp": 1784280557.871,
  "anomaly_count": 3,
  "mean": 9137.2,
  "sigma": 2.5,
  "eps": 0.5,
  "pdf_report": "<Binary BSON PDF Bytes>",
  "analysis_results": { ... }
}
```

---

## Setup & Starting FitPulse

### Method A: Local Setup (Manual)

#### 1. Prerequisites
- Python 3.13+
- MongoDB running locally (defaults to `mongodb://127.0.0.1:27017/`) or defined in the environment via `MONGO_URI`.

#### 2. Install Packages
```bash
pip install -r requirements.txt
pip install pymongo dnspython
```

#### 3. Running the Server
```bash
uvicorn main:app --reload
```
Navigate to `http://127.0.0.1:8000` to register your credentials and run fitness datasets.

---

### Method B: Containerized Setup (Docker Compose - Recommended)

If you have Docker and Docker Compose installed, you can stand up both the MongoDB database service and the FastAPI web application with a single command:

```bash
docker-compose up --build
```

This automates:
- Spawning a MongoDB container (exposing port `27017` to the host, with persistent volume storage backed by `mongo-data`).
- Building the local project into a Python environment container.
- Setting routing environments and starting uvicorn (exposed on `http://localhost:8000`).

---

### Method C: Cloud Deployment (Render Blueprint)

To deploy FitPulse onto Render cloud:

1. **Host a Free MongoDB Instance**:
   - Create a free cluster on **MongoDB Atlas** (mongodb.com).
   - Add a database user with password credentials.
   - Set Network Access to allow access from anywhere (whitelist IP `0.0.0.0/0` so Rent servers can connect).
   - Copy the Connection String: `mongodb+srv://<username>:<password>@cluster.mongodb.net/fitpulse`

2. **Commit Code to GitHub**:
   - Push this project workspace to a GitHub repository.

3. **Deploy on Render**:
   - Open your **Render Dashboard** (render.com).
   - Navigate to **Blueprints** and click **New Blueprint Instance**.
   - Link your GitHub repository.
   - Render detects `render.yaml` automatically and prompts for user inputs:
     - Set the `MONGO_URI` variable to your copied MongoDB Atlas Connection String.
   - Click **Deploy / Approve**. Render will build the container image and assign you a secure live public web URL!
