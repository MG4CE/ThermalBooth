/* =========================================================================
   ThermalBooth Manager — Frontend Logic
   ========================================================================= */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentConfig = null;   // Config as loaded from server
let configSchema = null;    // Schema metadata for building form
let logsOpen = false;
let statusPollTimer = null;

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    fetchStatus();
    loadConfig();
    // Poll status every 3 seconds
    statusPollTimer = setInterval(fetchStatus, 3000);
});

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------
async function fetchStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();
        updateStatusUI(data);
    } catch (err) {
        updateStatusUI({ state: "unknown" });
    }
}

function updateStatusUI(data) {
    const badge = document.getElementById("status-badge");
    const text = badge.querySelector(".status-text");
    const pidInfo = document.getElementById("pid-info");
    const btnStart = document.getElementById("btn-start");
    const btnStop = document.getElementById("btn-stop");
    const btnRestart = document.getElementById("btn-restart");

    const state = data.state || "unknown";

    // Remove all state classes
    badge.className = "status-badge";

    // Map systemd states to visual states
    const stateMap = {
        "active":       "active",
        "inactive":     "inactive",
        "failed":       "failed",
        "activating":   "activating",
        "deactivating": "deactivating",
        "reloading":    "reloading",
    };

    const visualState = stateMap[state] || "inactive";
    badge.classList.add(visualState);

    // Label
    const labels = {
        "active":       "Running",
        "inactive":     "Stopped",
        "failed":       "Failed",
        "activating":   "Starting...",
        "deactivating": "Stopping...",
        "reloading":    "Reloading...",
        "unknown":      "Unknown",
    };
    text.textContent = labels[state] || state;

    // PID info
    if (data.pid) {
        pidInfo.textContent = `PID: ${data.pid}`;
    } else {
        pidInfo.textContent = "";
    }

    // Button states
    const isRunning = state === "active";
    const isTransitioning = ["activating", "deactivating", "reloading"].includes(state);

    btnStart.disabled = isRunning || isTransitioning;
    btnStop.disabled = !isRunning || isTransitioning;
    btnRestart.disabled = !isRunning || isTransitioning;
}

// ---------------------------------------------------------------------------
// Booth Controls
// ---------------------------------------------------------------------------
async function controlBooth(action) {
    const btn = document.getElementById(`btn-${action}`);
    btn.disabled = true;

    try {
        const res = await fetch(`/api/${action}`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
            toast(`Booth ${data.message.toLowerCase()}`, "success");
        } else {
            toast(`Error: ${data.message}`, "error");
        }
    } catch (err) {
        toast(`Failed to ${action}: ${err.message}`, "error");
    }

    // Refresh status quickly
    setTimeout(fetchStatus, 500);
    setTimeout(fetchStatus, 2000);
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
async function loadConfig() {
    const container = document.getElementById("config-form");

    try {
        const res = await fetch("/api/config");
        const data = await res.json();

        if (data.error) {
            container.innerHTML = `<div class="loading">Error: ${data.error}</div>`;
            return;
        }

        currentConfig = JSON.parse(JSON.stringify(data.config)); // deep clone
        configSchema = data.schema;

        renderConfigForm(data.config, data.schema, container);
    } catch (err) {
        container.innerHTML = `<div class="loading">Failed to load config: ${err.message}</div>`;
    }
}

function renderConfigForm(config, schema, container) {
    container.innerHTML = "";

    // Render each section
    for (const [sectionKey, sectionSchema] of Object.entries(schema)) {
        const sectionLabel = sectionSchema._label || sectionKey;

        // Determine the config values for this section
        let sectionConfig;
        if (sectionKey === "_root") {
            // Root-level fields
            sectionConfig = config;
        } else {
            sectionConfig = config[sectionKey] || {};
        }

        const sectionEl = document.createElement("div");
        sectionEl.className = "config-section";

        // Section toggle header
        const toggleBtn = document.createElement("button");
        toggleBtn.className = "section-toggle";
        toggleBtn.innerHTML = `
            <span class="toggle-icon">-</span>
            ${sectionLabel}
        `;

        const fieldsContainer = document.createElement("div");
        fieldsContainer.className = "section-fields";

        toggleBtn.addEventListener("click", () => {
            const isHidden = fieldsContainer.classList.toggle("hidden");
            toggleBtn.querySelector(".toggle-icon").textContent = isHidden ? "+" : "-";
        });

        // Render each field
        for (const [fieldKey, fieldSchema] of Object.entries(sectionSchema)) {
            if (fieldKey === "_label") continue;

            const value = sectionConfig[fieldKey];
            const fieldEl = createField(sectionKey, fieldKey, fieldSchema, value);
            fieldsContainer.appendChild(fieldEl);
        }

        sectionEl.appendChild(toggleBtn);
        sectionEl.appendChild(fieldsContainer);
        container.appendChild(sectionEl);
    }
}

function createField(sectionKey, fieldKey, schema, value) {
    const wrapper = document.createElement("div");
    wrapper.className = "field";

    const dataKey = sectionKey === "_root" ? fieldKey : `${sectionKey}.${fieldKey}`;

    if (schema.type === "bool") {
        // Toggle switch
        const label = document.createElement("label");
        label.textContent = schema.label;
        label.setAttribute("for", `cfg-${dataKey}`);

        const toggleWrap = document.createElement("div");
        toggleWrap.className = "toggle-wrap";

        const toggle = document.createElement("label");
        toggle.className = "toggle";

        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = !!value;
        input.id = `cfg-${dataKey}`;
        input.dataset.key = dataKey;
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

        wrapper.appendChild(label);
        wrapper.appendChild(toggleWrap);

    } else if (schema.type === "enum") {
        const label = document.createElement("label");
        label.textContent = schema.label;
        label.setAttribute("for", `cfg-${dataKey}`);

        const select = document.createElement("select");
        select.id = `cfg-${dataKey}`;
        select.dataset.key = dataKey;
        select.dataset.type = "enum";

        for (const opt of schema.options) {
            const option = document.createElement("option");
            option.value = opt;
            option.textContent = opt;
            if (opt === value) option.selected = true;
            select.appendChild(option);
        }

        wrapper.appendChild(label);
        wrapper.appendChild(select);

    } else if (schema.type === "int" || schema.type === "float") {
        const label = document.createElement("label");
        label.textContent = schema.label;
        label.setAttribute("for", `cfg-${dataKey}`);

        const input = document.createElement("input");
        input.type = "number";
        input.id = `cfg-${dataKey}`;
        input.dataset.key = dataKey;
        input.dataset.type = schema.type;
        input.value = value ?? "";

        if (schema.min !== undefined) input.min = schema.min;
        if (schema.max !== undefined) input.max = schema.max;
        if (schema.step !== undefined) input.step = schema.step;
        else if (schema.type === "float") input.step = "0.01";
        else input.step = "1";

        wrapper.appendChild(label);
        wrapper.appendChild(input);

    } else if (schema.type === "upload") {
        // Image upload with preview
        const label = document.createElement("label");
        label.textContent = schema.label;
        wrapper.appendChild(label);

        const uploadKey = schema.upload_key; // "header" or "footer"

        // Preview image
        const preview = document.createElement("img");
        preview.className = "upload-preview";
        preview.id = `preview-${uploadKey}`;
        preview.alt = `${schema.label} preview`;
        preview.src = `/api/media/${uploadKey}?t=${Date.now()}`;
        preview.onerror = function () { this.style.display = "none"; };
        preview.onload = function () { this.style.display = "block"; };
        wrapper.appendChild(preview);

        // File input (hidden) + styled button
        const fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.accept = "image/*";
        fileInput.id = `upload-${uploadKey}`;
        fileInput.style.display = "none";

        const uploadBtn = document.createElement("button");
        uploadBtn.type = "button";
        uploadBtn.className = "btn btn-small btn-upload";
        uploadBtn.textContent = value ? "Replace Image" : "Upload Image";

        const statusSpan = document.createElement("span");
        statusSpan.className = "upload-status";
        if (value) {
            statusSpan.textContent = value.split("/").pop();
        }

        uploadBtn.addEventListener("click", () => fileInput.click());

        fileInput.addEventListener("change", async () => {
            const file = fileInput.files[0];
            if (!file) return;

            uploadBtn.disabled = true;
            uploadBtn.textContent = "Uploading...";

            const formData = new FormData();
            formData.append("file", file);

            try {
                const res = await fetch(`/api/upload/${uploadKey}`, {
                    method: "POST",
                    body: formData,
                });
                const data = await res.json();

                if (data.error) {
                    toast(`Upload failed: ${data.error}`, "error");
                } else {
                    toast(`${schema.label} uploaded`, "success");
                    statusSpan.textContent = data.filename;
                    uploadBtn.textContent = "Replace Image";
                    // Refresh preview
                    preview.src = `/api/media/${uploadKey}?t=${Date.now()}`;
                    // Reload config so the path field stays in sync
                    loadConfig();
                }
            } catch (err) {
                toast(`Upload failed: ${err.message}`, "error");
            } finally {
                uploadBtn.disabled = false;
                if (uploadBtn.textContent === "Uploading...") {
                    uploadBtn.textContent = value ? "Replace Image" : "Upload Image";
                }
                fileInput.value = "";
            }
        });

        wrapper.appendChild(fileInput);
        wrapper.appendChild(uploadBtn);
        wrapper.appendChild(statusSpan);

    } else {
        // String / path
        const label = document.createElement("label");
        label.textContent = schema.label;
        label.setAttribute("for", `cfg-${dataKey}`);

        const input = document.createElement("input");
        input.type = "text";
        input.id = `cfg-${dataKey}`;
        input.dataset.key = dataKey;
        input.dataset.type = "string";
        input.value = value ?? "";

        wrapper.appendChild(label);
        wrapper.appendChild(input);
    }

    return wrapper;
}

function gatherConfig() {
    /**
     * Walk all form inputs and build the JSON structure.
     * Keys follow "section.field" or just "field" for root-level.
     */
    const config = {};
    const inputs = document.querySelectorAll("[data-key]");

    for (const el of inputs) {
        const key = el.dataset.key;
        const type = el.dataset.type;
        let value;

        switch (type) {
            case "bool":
                value = el.checked;
                break;
            case "int":
                value = el.value === "" ? 0 : parseInt(el.value, 10);
                break;
            case "float":
                value = el.value === "" ? 0 : parseFloat(el.value);
                break;
            default:
                value = el.value;
        }

        if (key.includes(".")) {
            const [section, field] = key.split(".", 2);
            if (!config[section]) config[section] = {};
            config[section][field] = value;
        } else {
            config[key] = value;
        }
    }

    // Preserve upload-managed fields from current config
    if (currentConfig) {
        const uploadFields = ["header_image", "footer_image"];
        for (const field of uploadFields) {
            const val = currentConfig.image_settings && currentConfig.image_settings[field];
            if (val !== undefined) {
                if (!config.image_settings) config.image_settings = {};
                if (config.image_settings[field] === undefined) {
                    config.image_settings[field] = val;
                }
            }
        }
    }

    return config;
}

async function saveConfig() {
    const btn = document.getElementById("btn-save");
    btn.disabled = true;
    btn.textContent = "Saving...";

    try {
        const newConfig = gatherConfig();
        const res = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(newConfig),
        });

        const data = await res.json();

        if (data.error) {
            toast(`Error: ${data.error}`, "error");
        } else if (!data.changed) {
            toast("No changes detected", "info");
        } else if (data.restarted) {
            toast("Config saved — booth restarting", "success");
            setTimeout(fetchStatus, 1000);
            setTimeout(fetchStatus, 3000);
        } else {
            toast("Config saved", "success");
        }

        // Update our stored reference
        currentConfig = JSON.parse(JSON.stringify(newConfig));

    } catch (err) {
        toast(`Save failed: ${err.message}`, "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "Save Config";
    }
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------
function toggleLogs() {
    const body = document.getElementById("logs-body");
    const chevron = document.getElementById("logs-chevron");
    logsOpen = !logsOpen;

    if (logsOpen) {
        body.classList.add("open");
        chevron.textContent = "-";
        loadLogs();
    } else {
        body.classList.remove("open");
        chevron.textContent = "+";
    }
}

async function loadLogs() {
    const output = document.getElementById("logs-output");
    output.textContent = "Loading logs...";

    try {
        const res = await fetch("/api/logs");
        const data = await res.json();
        output.textContent = data.logs || "No logs available";

        // Auto-scroll to bottom
        const logsBody = document.getElementById("logs-body");
        logsBody.scrollTop = logsBody.scrollHeight;
    } catch (err) {
        output.textContent = `Failed to load logs: ${err.message}`;
    }
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function toast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);

    // Remove after animation
    setTimeout(() => {
        if (el.parentNode) el.parentNode.removeChild(el);
    }, 3200);
}
