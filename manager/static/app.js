/* =========================================================================
   ThermalBooth Manager — Frontend Logic
   ========================================================================= */

// ---------------------------------------------------------------------------
// Advanced-field classification
// Entire sections listed here go fully into the Advanced accordion.
// Individual dotted keys override for sections that are split.
// ---------------------------------------------------------------------------
const ADVANCED_SECTIONS = new Set(["printer", "gpio"]);

const ADVANCED_FIELDS = new Set([
    // camera: dimension / resolution fields
    "camera.width", "camera.height", "camera.framerate",
    "camera.raw_width", "camera.raw_height",
    "camera.capture_width", "camera.capture_height",
    // display: hardware / layout fields
    "display.width", "display.height", "display.fullscreen", "display.font_size",
    // root: debug fields
    "_root.save_debug_images", "_root.debug_dir",
]);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentConfig = null;
let configSchema  = null;
let logsOpen      = false;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    fetchStatus();
    loadConfig();
    setInterval(fetchStatus, 3000);

    // Ctrl+S → save
    document.addEventListener("keydown", e => {
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
            e.preventDefault();
            saveConfig();
        }
    });
});

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------
async function fetchStatus() {
    try {
        const res  = await fetch("/api/status");
        const data = await res.json();
        updateStatusUI(data);
    } catch {
        updateStatusUI({ state: "unknown" });
    }
}

function updateStatusUI(data) {
    const state = data.state || "unknown";

    const stateMap = {
        active: "active", inactive: "inactive", failed: "failed",
        activating: "activating", deactivating: "deactivating", reloading: "reloading",
    };
    const labels = {
        active: "Running", inactive: "Stopped", failed: "Failed",
        activating: "Starting…", deactivating: "Stopping…", reloading: "Reloading…",
        unknown: "Unknown",
    };

    const visualState = stateMap[state] || "inactive";
    const label       = labels[state] || state;

    // Update both badges (header + sticky bar)
    for (const id of ["status-badge", "sb-status-badge"]) {
        const badge = document.getElementById(id);
        if (!badge) continue;
        badge.className = `status-badge ${visualState}`;
        badge.querySelector(".status-text").textContent = label;
    }

    // PID
    const pidEl = document.getElementById("pid-info");
    if (pidEl) pidEl.textContent = data.pid ? `PID ${data.pid}` : "";

    // Buttons
    const isRunning      = state === "active";
    const isTransitioning = ["activating", "deactivating", "reloading"].includes(state);

    setBtn("btn-start",   isRunning || isTransitioning);
    setBtn("btn-stop",    !isRunning || isTransitioning);
    setBtn("btn-restart", !isRunning || isTransitioning);
}

function setBtn(id, disabled) {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
}

// ---------------------------------------------------------------------------
// Booth controls
// ---------------------------------------------------------------------------
async function controlBooth(action) {
    setBtn(`btn-${action}`, true);
    try {
        const res  = await fetch(`/api/${action}`, { method: "POST" });
        const data = await res.json();
        toast(data.success ? `Booth ${data.message.toLowerCase()}` : `Error: ${data.message}`,
              data.success ? "success" : "error");
    } catch (err) {
        toast(`Failed to ${action}: ${err.message}`, "error");
    }
    setTimeout(fetchStatus, 500);
    setTimeout(fetchStatus, 2000);
}

// ---------------------------------------------------------------------------
// Config — load
// ---------------------------------------------------------------------------
async function loadConfig() {
    const container = document.getElementById("config-form");
    try {
        const res  = await fetch("/api/config");
        const data = await res.json();
        if (data.error) { container.innerHTML = `<div class="loading">Error: ${data.error}</div>`; return; }

        currentConfig = JSON.parse(JSON.stringify(data.config));
        configSchema  = data.schema;
        renderConfigForm(data.config, data.schema, container);
    } catch (err) {
        container.innerHTML = `<div class="loading">Failed to load config: ${err.message}</div>`;
    }
}

// ---------------------------------------------------------------------------
// Config — render form
// ---------------------------------------------------------------------------
function isAdvanced(sectionKey, fieldKey) {
    if (ADVANCED_SECTIONS.has(sectionKey)) return true;
    const dotKey = `${sectionKey}.${fieldKey}`;
    return ADVANCED_FIELDS.has(dotKey);
}

function renderConfigForm(config, schema, container) {
    container.innerHTML = "";

    const advancedGroups = []; // [{label, fields:[domEl, …]}, …]

    for (const [sectionKey, sectionSchema] of Object.entries(schema)) {
        const sectionLabel  = sectionSchema._label || sectionKey;
        const sectionConfig = sectionKey === "_root" ? config : (config[sectionKey] || {});

        // Collect basic and advanced fields for this section
        const basicFields    = [];
        const advancedFields = [];

        for (const [fieldKey, fieldSchema] of Object.entries(sectionSchema)) {
            if (fieldKey === "_label") continue;
            const value   = sectionConfig[fieldKey];
            const fieldEl = createField(sectionKey, fieldKey, fieldSchema, value);
            if (isAdvanced(sectionKey, fieldKey)) {
                advancedFields.push(fieldEl);
            } else {
                basicFields.push(fieldEl);
            }
        }

        // If there are basic fields, render as a normal section
        if (basicFields.length > 0) {
            const sectionEl    = document.createElement("div");
            sectionEl.className = "config-section";

            const toggleBtn    = document.createElement("button");
            toggleBtn.className = "section-toggle";
            toggleBtn.innerHTML = `<span class="toggle-icon">▾</span>${sectionLabel}`;

            const fieldsWrap    = document.createElement("div");
            fieldsWrap.className = "section-fields";
            basicFields.forEach(f => fieldsWrap.appendChild(f));

            toggleBtn.addEventListener("click", () => {
                const hidden = fieldsWrap.classList.toggle("hidden");
                toggleBtn.querySelector(".toggle-icon").textContent = hidden ? "▸" : "▾";
            });

            sectionEl.appendChild(toggleBtn);
            sectionEl.appendChild(fieldsWrap);
            container.appendChild(sectionEl);
        }

        // Queue advanced fields under their section label
        if (advancedFields.length > 0) {
            advancedGroups.push({ label: sectionLabel, fields: advancedFields });
        }
        // Whole-section advanced (no basic fields, has fields)
        if (basicFields.length === 0 && advancedFields.length > 0) {
            // already queued above
        }
    }

    // Build the Advanced accordion at the bottom
    if (advancedGroups.length > 0) {
        const wrapper      = document.createElement("div");
        wrapper.className  = "advanced-wrapper config-section";

        const advBtn       = document.createElement("button");
        advBtn.className   = "advanced-toggle";
        advBtn.innerHTML   = `<span class="toggle-icon">▸</span>Advanced Settings`;

        const advBody      = document.createElement("div");
        advBody.className  = "advanced-body";

        advBtn.addEventListener("click", () => {
            const open = advBody.classList.toggle("open");
            advBtn.querySelector(".toggle-icon").textContent = open ? "▾" : "▸";
        });

        for (const group of advancedGroups) {
            // Sub-section toggle inside advanced
            const subSection   = document.createElement("div");
            subSection.className = "config-section";
            subSection.style.marginTop = "0.75rem";

            const subToggle    = document.createElement("button");
            subToggle.className = "section-toggle";
            subToggle.innerHTML = `<span class="toggle-icon">▾</span>${group.label}`;

            const subFields    = document.createElement("div");
            subFields.className = "section-fields";
            group.fields.forEach(f => subFields.appendChild(f));

            subToggle.addEventListener("click", () => {
                const hidden = subFields.classList.toggle("hidden");
                subToggle.querySelector(".toggle-icon").textContent = hidden ? "▸" : "▾";
            });

            subSection.appendChild(subToggle);
            subSection.appendChild(subFields);
            advBody.appendChild(subSection);
        }

        wrapper.appendChild(advBtn);
        wrapper.appendChild(advBody);
        container.appendChild(wrapper);
    }

    // After form is built, listen for any change to track dirty state
    container.addEventListener("input",  markDirty);
    container.addEventListener("change", markDirty);
}

// ---------------------------------------------------------------------------
// Config — create a single field element
// ---------------------------------------------------------------------------
function createField(sectionKey, fieldKey, schema, value) {
    const wrapper   = document.createElement("div");
    wrapper.className = "field";
    wrapper.dataset.fieldKey = `${sectionKey}.${fieldKey}`;

    const dataKey = sectionKey === "_root" ? fieldKey : `${sectionKey}.${fieldKey}`;

    // Label
    const labelEl   = document.createElement("div");
    labelEl.className = "field-label";
    labelEl.textContent = schema.label;
    wrapper.appendChild(labelEl);

    // Error message placeholder
    const errEl     = document.createElement("div");
    errEl.className = "field-error-msg";
    // appended at end

    // --- BOOL ---
    if (schema.type === "bool") {
        const toggleWrap = document.createElement("div");
        toggleWrap.className = "toggle-wrap";

        const toggle = document.createElement("label");
        toggle.className = "toggle";

        const input = document.createElement("input");
        input.type    = "checkbox";
        input.checked = !!value;
        input.id      = `cfg-${dataKey}`;
        input.dataset.key  = dataKey;
        input.dataset.type = "bool";

        const slider = document.createElement("span");
        slider.className = "toggle-slider";

        const toggleLabel = document.createElement("span");
        toggleLabel.className = "toggle-label";
        toggleLabel.textContent = input.checked ? "On" : "Off";
        input.addEventListener("change", () => {
            toggleLabel.textContent = input.checked ? "On" : "Off";
        });

        toggle.appendChild(input);
        toggle.appendChild(slider);
        toggleWrap.appendChild(toggle);
        toggleWrap.appendChild(toggleLabel);
        wrapper.appendChild(toggleWrap);

    // --- ENUM → segmented button group ---
    } else if (schema.type === "enum") {
        // Hidden input holds the selected value (for gatherConfig)
        const hidden = document.createElement("input");
        hidden.type         = "hidden";
        hidden.id           = `cfg-${dataKey}`;
        hidden.dataset.key  = dataKey;
        hidden.dataset.type = "enum";
        hidden.value        = value ?? (schema.options[0] || "");

        const group = document.createElement("div");
        group.className = "btn-group";

        for (const opt of schema.options) {
            const btn = document.createElement("button");
            btn.type      = "button";
            btn.className = "btn-group-btn" + (opt === hidden.value ? " active" : "");
            btn.textContent = opt.replace(/_/g, " ");
            btn.dataset.value = opt;

            btn.addEventListener("click", () => {
                hidden.value = opt;
                hidden.dispatchEvent(new Event("change", { bubbles: true }));
                group.querySelectorAll(".btn-group-btn").forEach(b => {
                    b.classList.toggle("active", b.dataset.value === opt);
                });
                markDirty();
            });

            group.appendChild(btn);
        }

        wrapper.appendChild(group);
        wrapper.appendChild(hidden);

    // --- INT / FLOAT with range → slider ---
    } else if ((schema.type === "int" || schema.type === "float")
               && schema.min !== undefined && schema.max !== undefined) {

        const step = schema.step ?? (schema.type === "float" ? 0.05 : 1);
        const val  = value ?? schema.min;

        // Slider row
        const sliderRow  = document.createElement("div");
        sliderRow.className = "slider-row";

        const trackWrap  = document.createElement("div");
        trackWrap.className = "slider-track";

        const rangeInput = document.createElement("input");
        rangeInput.type  = "range";
        rangeInput.className = "filled";
        rangeInput.min   = schema.min;
        rangeInput.max   = schema.max;
        rangeInput.step  = step;
        rangeInput.value = val;

        // Number display
        const numInput   = document.createElement("input");
        numInput.type    = "number";
        numInput.className = "slider-value-input";
        numInput.min     = schema.min;
        numInput.max     = schema.max;
        numInput.step    = step;
        numInput.value   = schema.type === "float" ? Number(val).toFixed(decimalPlaces(step)) : val;
        numInput.id      = `cfg-${dataKey}`;
        numInput.dataset.key  = dataKey;
        numInput.dataset.type = schema.type;
        numInput.dataset.min  = schema.min;
        numInput.dataset.max  = schema.max;

        // Keep slider ↔ number in sync + update fill
        function syncFill(v) {
            const pct = ((v - schema.min) / (schema.max - schema.min)) * 100;
            rangeInput.style.setProperty("--fill", `${pct.toFixed(1)}%`);
        }

        rangeInput.addEventListener("input", () => {
            const v = parseFloat(rangeInput.value);
            numInput.value = schema.type === "float" ? v.toFixed(decimalPlaces(step)) : Math.round(v);
            syncFill(v);
            validateFieldEl(wrapper, numInput, schema);
            markDirty();
        });

        numInput.addEventListener("input", () => {
            const v = parseFloat(numInput.value);
            if (!isNaN(v)) {
                rangeInput.value = Math.min(schema.max, Math.max(schema.min, v));
                syncFill(v);
            }
            validateFieldEl(wrapper, numInput, schema);
            markDirty();
        });

        syncFill(parseFloat(val));

        trackWrap.appendChild(rangeInput);
        sliderRow.appendChild(trackWrap);
        sliderRow.appendChild(numInput);
        wrapper.appendChild(sliderRow);

        // Min/max hint
        const hint = document.createElement("div");
        hint.className = "slider-range-hint";
        hint.innerHTML = `<span>${schema.min}</span><span>${schema.max}</span>`;
        wrapper.appendChild(hint);

    // --- INT / FLOAT without full range → number input with placeholder hint ---
    } else if (schema.type === "int" || schema.type === "float") {
        const step = schema.step ?? (schema.type === "float" ? 0.01 : 1);
        const input = document.createElement("input");
        input.type  = "number";
        input.id    = `cfg-${dataKey}`;
        input.dataset.key  = dataKey;
        input.dataset.type = schema.type;
        input.value = value ?? "";
        input.step  = step;
        if (schema.min !== undefined) { input.min = schema.min; input.dataset.min = schema.min; }
        if (schema.max !== undefined) { input.max = schema.max; input.dataset.max = schema.max; }

        // Build placeholder hint
        const parts = [];
        if (schema.min !== undefined) parts.push(`min ${schema.min}`);
        if (schema.max !== undefined) parts.push(`max ${schema.max}`);
        if (parts.length) input.placeholder = parts.join(", ");

        input.addEventListener("input", () => {
            validateFieldEl(wrapper, input, schema);
            markDirty();
        });

        wrapper.appendChild(input);

    // --- UPLOAD ---
    } else if (schema.type === "upload") {
        const uploadKey = schema.upload_key;

        const preview = document.createElement("img");
        preview.className = "upload-preview";
        preview.alt    = schema.label;
        preview.src    = `/api/media/${uploadKey}?t=${Date.now()}`;
        preview.onerror = function () { this.style.display = "none"; };
        preview.onload  = function () { this.style.display = "block"; };

        const fileInput = document.createElement("input");
        fileInput.type   = "file";
        fileInput.accept = "image/*";
        fileInput.style.display = "none";

        const uploadBtn = document.createElement("button");
        uploadBtn.type      = "button";
        uploadBtn.className = "btn btn-small btn-upload";
        uploadBtn.textContent = value ? "Replace Image" : "Upload Image";

        const statusSpan = document.createElement("span");
        statusSpan.className = "upload-status";
        if (value) statusSpan.textContent = value.split("/").pop();

        uploadBtn.addEventListener("click", () => fileInput.click());

        fileInput.addEventListener("change", async () => {
            const file = fileInput.files[0];
            if (!file) return;
            uploadBtn.disabled    = true;
            uploadBtn.textContent = "Uploading…";

            const formData = new FormData();
            formData.append("file", file);
            try {
                const res  = await fetch(`/api/upload/${uploadKey}`, { method: "POST", body: formData });
                const data = await res.json();
                if (data.error) {
                    toast(`Upload failed: ${data.error}`, "error");
                } else {
                    toast(`${schema.label} uploaded`, "success");
                    statusSpan.textContent = data.filename;
                    uploadBtn.textContent  = "Replace Image";
                    preview.src = `/api/media/${uploadKey}?t=${Date.now()}`;
                    loadConfig();
                }
            } catch (err) {
                toast(`Upload failed: ${err.message}`, "error");
            } finally {
                uploadBtn.disabled = false;
                if (uploadBtn.textContent === "Uploading…") uploadBtn.textContent = value ? "Replace Image" : "Upload Image";
                fileInput.value = "";
            }
        });

        wrapper.appendChild(preview);
        wrapper.appendChild(fileInput);
        wrapper.appendChild(uploadBtn);
        wrapper.appendChild(statusSpan);

    // --- STRING ---
    } else {
        const input = document.createElement("input");
        input.type  = "text";
        input.id    = `cfg-${dataKey}`;
        input.dataset.key  = dataKey;
        input.dataset.type = "string";
        input.value = value ?? "";
        wrapper.appendChild(input);
    }

    wrapper.appendChild(errEl);
    return wrapper;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function decimalPlaces(step) {
    const s = String(step);
    const dot = s.indexOf(".");
    return dot === -1 ? 0 : s.length - dot - 1;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------
function validateFieldEl(wrapper, input, schema) {
    const val = parseFloat(input.value);
    const errEl = wrapper.querySelector(".field-error-msg");
    let msg = "";

    if (input.value !== "" && !isNaN(val)) {
        if (schema.min !== undefined && val < schema.min) msg = `Must be ≥ ${schema.min}`;
        if (schema.max !== undefined && val > schema.max) msg = `Must be ≤ ${schema.max}`;
    }

    errEl.textContent = msg;
    wrapper.classList.toggle("has-error", !!msg);
    return !msg;
}

function validateForm() {
    let valid = true;
    // Only validate numeric inputs that have min/max
    document.querySelectorAll("[data-key][data-min], [data-key][data-max]").forEach(input => {
        const min    = input.dataset.min !== undefined ? parseFloat(input.dataset.min) : undefined;
        const max    = input.dataset.max !== undefined ? parseFloat(input.dataset.max) : undefined;
        const schema = { min, max };
        const wrapper = input.closest(".field");
        if (wrapper) {
            const ok = validateFieldEl(wrapper, input, schema);
            if (!ok) valid = false;
        }
    });
    return valid;
}

// ---------------------------------------------------------------------------
// Dirty tracking
// ---------------------------------------------------------------------------
function markDirty() {
    const saveBtn = document.getElementById("btn-save");
    if (!saveBtn || !currentConfig) return;

    const current = gatherConfig();
    const dirty   = JSON.stringify(current, sortedKeys) !== JSON.stringify(currentConfig, sortedKeys);
    saveBtn.classList.toggle("dirty", dirty);
}

function sortedKeys(key, value) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
        return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
    }
    return value;
}

// ---------------------------------------------------------------------------
// Gather config from form
// ---------------------------------------------------------------------------
function gatherConfig() {
    const config = {};
    const inputs = document.querySelectorAll("[data-key]");

    for (const el of inputs) {
        // Skip hidden range inputs (slider's range element has no data-key — only the number input does)
        if (el.type === "range") continue;

        const key  = el.dataset.key;
        const type = el.dataset.type;
        let value;

        switch (type) {
            case "bool":  value = el.checked; break;
            case "int":   value = el.value === "" ? 0 : parseInt(el.value, 10); break;
            case "float": value = el.value === "" ? 0 : parseFloat(el.value); break;
            default:      value = el.value;
        }

        if (key.includes(".")) {
            const [section, field] = key.split(".", 2);
            if (!config[section]) config[section] = {};
            config[section][field] = value;
        } else {
            config[key] = value;
        }
    }

    // Preserve upload-managed paths from currentConfig
    if (currentConfig) {
        for (const field of ["header_image", "footer_image"]) {
            const val = currentConfig.image_settings?.[field];
            if (val !== undefined) {
                if (!config.image_settings) config.image_settings = {};
                if (config.image_settings[field] === undefined) config.image_settings[field] = val;
            }
        }
    }

    return config;
}

// ---------------------------------------------------------------------------
// Save config
// ---------------------------------------------------------------------------
async function saveConfig() {
    if (!validateForm()) {
        toast("Fix validation errors before saving", "error");
        return;
    }

    const btn = document.getElementById("btn-save");
    btn.disabled = true;

    try {
        const newConfig = gatherConfig();
        const res  = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(newConfig),
        });
        const data = await res.json();

        if (data.error) {
            toast(`Error: ${data.error}`, "error");
        } else if (!data.changed) {
            toast("No changes detected", "info");
            btn.classList.remove("dirty");
        } else if (data.restarted) {
            toast("Saved — booth restarting", "success");
            btn.classList.remove("dirty");
            setTimeout(fetchStatus, 1000);
            setTimeout(fetchStatus, 3000);
        } else {
            toast("Config saved", "success");
            btn.classList.remove("dirty");
        }

        currentConfig = JSON.parse(JSON.stringify(newConfig));
    } catch (err) {
        toast(`Save failed: ${err.message}`, "error");
    } finally {
        btn.disabled = false;
    }
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------
function toggleLogs() {
    const body    = document.getElementById("logs-body");
    const chevron = document.getElementById("logs-chevron");
    logsOpen = !logsOpen;
    body.classList.toggle("open", logsOpen);
    chevron.textContent = logsOpen ? "▾" : "▸";
    if (logsOpen) loadLogs();
}

async function loadLogs() {
    const output = document.getElementById("logs-output");
    output.textContent = "Loading…";
    try {
        const res  = await fetch("/api/logs");
        const data = await res.json();
        output.textContent = data.logs || "No logs available";
        document.getElementById("logs-body").scrollTop = 99999;
    } catch (err) {
        output.textContent = `Failed to load logs: ${err.message}`;
    }
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function toast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const el        = document.createElement("div");
    el.className    = `toast ${type}`;
    el.textContent  = message;
    container.appendChild(el);
    setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, 3200);
}
