// ═══════════════════════════════════════════════════════════════
//  FITPULSE WEB · upload.js
//  Handles Stage 1: file drop, upload, and dynamic mapping form.
// ═══════════════════════════════════════════════════════════════

const dropzone   = document.getElementById("dropzone");
const fileInput  = document.getElementById("file-input");
const fileList   = document.getElementById("file-list");
const analyzeBtn = document.getElementById("analyze-btn");
const uploadErr  = document.getElementById("upload-error");

let selectedFiles = [];
let lastColumnsByFile = {};     // for repopulating dropdown options
let lastInferredMapping = null; // keeps generic_numeric/categorical + confidence for confirm step

const ROLE_LABELS = {
    user_id: "User / Participant ID",
    timestamp: "Date / Timestamp",
    heart_rate: "Heart Rate",
    steps: "Steps",
    sleep_duration: "Sleep Duration",
    calories: "Calories",
    activity_intensity: "Activity Intensity",
    distance: "Distance",
    weight: "Weight / BMI",
    workout_type: "Workout Type",
};

// ── Drag & drop wiring ──────────────────────────────────────────
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", (e) => handleFiles(e.target.files));

function handleFiles(fileListObj) {
    const validFiles = [];
    const invalidFiles = [];
    
    Array.from(fileListObj).forEach(f => {
        const ext = f.name.substring(f.name.lastIndexOf('.')).toLowerCase();
        if (ext === '.csv' || ext === '.xlsx' || ext === '.xls') {
            validFiles.push(f);
        } else {
            invalidFiles.push(f.name);
        }
    });
    
    if (invalidFiles.length > 0) {
        uploadErr.textContent = `❌ Rejected unsupported files: ${invalidFiles.join(', ')}. Please select only CSV or Excel files.`;
        uploadErr.style.display = "block";
    } else {
        uploadErr.style.display = "none";
    }
    
    selectedFiles = validFiles;
    renderFileList();
    analyzeBtn.disabled = selectedFiles.length === 0;
}

function renderFileList() {
    fileList.innerHTML = "";
    selectedFiles.forEach((f) => {
        const li = document.createElement("li");
        const sizeKb = (f.size / 1024).toFixed(1);
        li.innerHTML = `<span class="fname">${f.name}</span><span class="fsize">${sizeKb} KB</span>`;
        fileList.appendChild(li);
    });
}

// ── Upload + profile ─────────────────────────────────────────────
analyzeBtn.addEventListener("click", async () => {
    uploadErr.style.display = "none";
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "Analyzing...";

    const formData = new FormData();
    selectedFiles.forEach((f) => formData.append("files", f));

    try {
        const res = await fetch("/api/upload", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Upload failed");

        lastColumnsByFile = data.columns_by_file;
        renderMappingForm(data);

        document.getElementById("mapping-section").style.display = "block";
        document.getElementById("mapping-section").scrollIntoView({ behavior: "smooth" });
    } catch (err) {
        uploadErr.textContent = "❌ " + err.message;
        uploadErr.style.display = "block";
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = "Analyze Columns";
    }
});

// ── Sample data ──────────────────────────────────────────────────
const sampleBtn = document.getElementById("sample-data-btn");
if (sampleBtn) {
    sampleBtn.addEventListener("click", async () => {
        uploadErr.style.display = "none";
        sampleBtn.disabled = true;
        sampleBtn.textContent = "Loading sample data...";

        try {
            const res = await fetch("/api/upload-sample", { method: "POST" });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to load sample data");

            lastColumnsByFile = data.columns_by_file;
            renderMappingForm(data);

            document.getElementById("mapping-section").style.display = "block";
            document.getElementById("mapping-section").scrollIntoView({ behavior: "smooth" });
        } catch (err) {
            uploadErr.textContent = "❌ " + err.message;
            uploadErr.style.display = "block";
        } finally {
            sampleBtn.disabled = false;
            sampleBtn.textContent = "Don't have a file? Try with sample data instead";
        }
    });
}

// ── Render the editable mapping confirmation form ────────────────
function renderMappingForm(data) {
    lastInferredMapping = data.inferred_mapping; // stash for confirm step

    const meta = document.getElementById("mapping-meta");
    meta.innerHTML = `Detected shape: <strong>${data.overall_shape}</strong>` +
        (data.join_keys.length ? ` · Join keys: <strong>${data.join_keys.join(", ")}</strong>` : "");

    const tbody = document.getElementById("mapping-tbody");
    tbody.innerHTML = "";

    const allOptions = [];
    for (const [fname, cols] of Object.entries(data.columns_by_file)) {
        cols.forEach((c) => allOptions.push({ file: fname, column: c }));
    }

    for (const role of Object.keys(ROLE_LABELS)) {
        const entry = data.inferred_mapping.mapping[role];
        const confidence = data.inferred_mapping.confidence[role];

        const row = document.createElement("tr");

        const roleCell = document.createElement("td");
        roleCell.textContent = ROLE_LABELS[role];
        row.appendChild(roleCell);

        const selectCell = document.createElement("td");
        const select = document.createElement("select");
        select.dataset.role = role;

        const noneOpt = document.createElement("option");
        noneOpt.value = "";
        noneOpt.textContent = "— None / Not present —";
        select.appendChild(noneOpt);

        allOptions.forEach((opt) => {
            const o = document.createElement("option");
            o.value = JSON.stringify({ file: opt.file, column: opt.column });
            const label = Object.keys(data.columns_by_file).length > 1
                ? `${opt.column}  (${opt.file})`
                : opt.column;
            o.textContent = label;
            if (entry && entry.file === opt.file && entry.column === opt.column) {
                o.selected = true;
            }
            select.appendChild(o);
        });

        selectCell.appendChild(select);
        row.appendChild(selectCell);

        const qualCell = document.createElement("td");
        row.appendChild(qualCell);

        const confCell = document.createElement("td");
        if (confidence !== undefined && confidence !== null) {
            const badgeClass = confidence >= 0.7 ? "confidence-high"
                : confidence >= 0.45 ? "confidence-med"
                : "confidence-low";
            confCell.innerHTML = `<span class="confidence-badge ${badgeClass}">${(confidence * 100).toFixed(0)}%</span>`;
        } else {
            confCell.innerHTML = `<span class="confidence-badge confidence-none">—</span>`;
        }
        row.appendChild(confCell);
        
        // Update quality cell on dropdown change
        const updateQualCell = () => {
            qualCell.innerHTML = "";
            if (select.value) {
                const opt = JSON.parse(select.value);
                const qual = data.quality_report?.columns?.[opt.file]?.[opt.column];
                if (qual) {
                    const badgeClass = qual.missing_pct < 5 ? "confidence-high" 
                                     : qual.missing_pct <= 20 ? "confidence-med" 
                                     : "confidence-low";
                    qualCell.innerHTML = `<span class="confidence-badge ${badgeClass}" style="opacity: 0.8; font-size: 11px;">Missing: ${qual.missing_pct}%</span>`;
                }
            } else {
                qualCell.innerHTML = `<span class="confidence-badge confidence-none">—</span>`;
            }
        };
        select.addEventListener("change", updateQualCell);
        updateQualCell(); // init

        tbody.appendChild(row);
    }

    // Generic (unmapped) columns — read-only display
    const genericDiv = document.getElementById("generic-columns");
    genericDiv.innerHTML = "";
    
    // ── Build Data Health Panel ──
    const healthPanel = document.getElementById("data-health-panel");
    const qr = data.quality_report?.files;
    if (healthPanel && qr) {
        let totalRows = 0;
        let totalDupes = 0;
        for (const f of Object.values(qr)) {
            totalRows += f.n_rows;
            totalDupes += f.n_duplicates;
        }
        
        let dateRange = "—";
        // Attempt to find an overall date range from columns
        const allRanges = [];
        if (data.quality_report?.columns) {
            for (const f of Object.values(data.quality_report.columns)) {
                for (const c of Object.values(f)) {
                    if (c.date_range) allRanges.push(c.date_range);
                }
            }
        }
        if (allRanges.length > 0) dateRange = allRanges[0]; // just pick the first detected
        
        healthPanel.innerHTML = `
            <div style="font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 12px;">🏥 Data Health Overview</div>
            <div style="display: flex; gap: 16px; flex-wrap: wrap;">
                <div style="flex:1; min-width: 140px; background: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0;">
                    <div style="font-size: 12px; color: var(--dim); text-transform: uppercase;">Total Rows</div>
                    <div style="font-size: 18px; font-weight: 700; color: #2563eb;">${totalRows.toLocaleString()}</div>
                </div>
                <div style="flex:1; min-width: 140px; background: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0;">
                    <div style="font-size: 12px; color: var(--dim); text-transform: uppercase;">Duplicate Rows</div>
                    <div style="font-size: 18px; font-weight: 700; color: ${totalDupes > 0 ? '#ef4444' : '#10b981'};">${totalDupes.toLocaleString()}</div>
                </div>
                <div style="flex:1; min-width: 140px; background: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0;">
                    <div style="font-size: 12px; color: var(--dim); text-transform: uppercase;">Date Range (Est)</div>
                    <div style="font-size: 14px; font-weight: 600; color: #0f172a; margin-top:4px;">${dateRange}</div>
                </div>
            </div>
        `;
        healthPanel.style.display = "block";
    }
    const generics = [
        ...data.inferred_mapping.generic_numeric.map((e) => ({ ...e, type: "numeric" })),
        ...data.inferred_mapping.generic_categorical.map((e) => ({ ...e, type: "categorical" })),
    ];
    if (generics.length === 0) {
        genericDiv.innerHTML = `<span style="color:var(--dim)">None — every column was mapped.</span>`;
    } else {
        generics.forEach((g) => {
            const chip = document.createElement("span");
            chip.className = "generic-chip";
            chip.textContent = `${g.column} (${g.type})`;
            genericDiv.appendChild(chip);
        });
    }
}

// ── Confirm mapping → advance to Stage 2 ─────────────────────────
document.getElementById("confirm-btn").addEventListener("click", async () => {
    const btn = document.getElementById("confirm-btn");
    btn.disabled = true;
    btn.textContent = "Saving...";

    const selects = document.querySelectorAll("#mapping-tbody select");
    const mapping = {};
    selects.forEach((sel) => {
        const role = sel.dataset.role;
        mapping[role] = sel.value ? JSON.parse(sel.value) : null;
    });

    // Carry forward generic columns + confidence from the original inferred
    // mapping — the confirm step only lets the user edit named roles, so
    // this data would otherwise be silently dropped on every save.
    const payload = {
        mapping,
        generic_numeric: lastInferredMapping ? lastInferredMapping.generic_numeric : [],
        generic_categorical: lastInferredMapping ? lastInferredMapping.generic_categorical : [],
        confidence: lastInferredMapping ? lastInferredMapping.confidence : {},
    };

    try {
        const res = await fetch("/api/confirm-mapping", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Could not save mapping");
        window.location.href = data.redirect;
    } catch (err) {
        alert("❌ " + err.message);
        btn.disabled = false;
        btn.textContent = "Confirm & Continue →";
    }
});

window.addEventListener("DOMContentLoaded", async () => {
    // Dismiss welcome screen overlay
    const welcomeOverlay = document.getElementById("welcome-overlay");
    const welcomeCta = document.getElementById("welcome-cta");
    if (welcomeOverlay && welcomeCta) {
        welcomeCta.addEventListener("click", () => {
            welcomeOverlay.classList.add("fade-out");
            sessionStorage.setItem("fp_welcome_seen", "true");
            setTimeout(() => {
                welcomeOverlay.remove();
            }, 600);
        });
    }

    // Check if edit mid-session was requested
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('edit')) {
        try {
            const res = await fetch("/api/session-mapping");
            if (res.ok) {
                const data = await res.json();
                handleUploadSuccess(data);
                // hide upload dropzone layout and proceed to mapping layout
                document.getElementById("upload-panel").style.display = "none";
                document.getElementById("mapping-panel").style.display = "block";
            }
        } catch(e) {
            console.error("Failed to fetch session mapping for edit", e);
        }
    }
});