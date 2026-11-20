document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  const btnLock = document.getElementById("btn-lock");
  const btnUnlock = document.getElementById("btn-unlock");
  const btnInfo = document.getElementById("btn-info");
  const btnCamera = document.getElementById("btn-camera");
  const btnDispenser = document.getElementById("btn-dispenser");
  const btnCloseInfo = document.getElementById("btn-close-info");

  const statusBadge = document.getElementById("status-badge");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const toast = document.getElementById("toast");
  const healthPanel = document.getElementById("health-panel");
  const healthGrid = document.getElementById("health-grid");
  const healthRaw = document.getElementById("health-raw");

  const footerMeta = document.getElementById("footer-meta");
  const footerRepoLink = document.getElementById("footer-repo-link");
  const currentYear = new Date().getFullYear();

  const footerState = {
    appVersion: "",
    firmwareVersion: "",
    repoUrl: "",
  };

  function renderFooterMeta() {
    if (footerMeta) {
      const parts = [];
      if (footerState.appVersion) {
        parts.push(`v${footerState.appVersion}`);
      }
      if (footerState.firmwareVersion) {
        parts.push(`fw ${footerState.firmwareVersion}`);
      }
      parts.push(`© belodetek ${currentYear}`);
      footerMeta.textContent = parts.join(" · ");
    }
    if (footerRepoLink && footerState.repoUrl) {
      footerRepoLink.href = footerState.repoUrl;
      footerRepoLink.classList.remove("hidden");
    }
  }

  renderFooterMeta();

  function showToast(message, variant = "info") {
    const styles = {
      lock: "bg-rose-950/80 border-rose-700 text-rose-200",
      unlock: "bg-emerald-950/80 border-emerald-700 text-emerald-200",
      error: "bg-red-950/90 border-red-700 text-red-200",
      info: "bg-slate-900 border-slate-700 text-slate-200",
    };
    toast.className = `rounded-xl px-4 py-3 text-sm font-medium border text-center ${styles[variant] || styles.info}`;
    toast.textContent = message;
    toast.classList.remove("hidden");
  }

  function setLockControlsEnabled(enabled) {
    btnLock.disabled = !enabled;
    btnUnlock.disabled = !enabled;
  }

  function updateStatusBadge(health) {
    const espConnected = Boolean(health.serial_connected);
    setLockControlsEnabled(espConnected);

    if (!espConnected) {
      statusBadge.className =
        "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-900/60 border border-slate-800 text-slate-400 opacity-75";
      statusDot.className = "w-2.5 h-2.5 rounded-full bg-amber-400";
      statusText.textContent = "Disabled (Open)";
      return;
    }

    statusBadge.className =
      "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-900 border border-slate-800 text-slate-300";

    if (health.lock_engaged) {
      statusDot.className = "w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse";
      statusText.textContent =
        health.admin_override === "locked" ? "Locked (Admin)" : "Locked (Prey)";
    } else {
      statusDot.className = "w-2.5 h-2.5 rounded-full bg-emerald-400";
      statusText.textContent =
        health.admin_override === "unlocked" ? "Unlocked (Admin)" : "Unlocked";
    }
  }

  async function loadUiConfig() {
    if (!btnDispenser) {
      return;
    }
    try {
      const resp = await fetch("/ui/config", { cache: "no-store" });
      if (!resp.ok) {
        return;
      }
      const cfg = await resp.json();
      footerState.appVersion = cfg.app_version || "";
      footerState.repoUrl = cfg.repo_url || "";
      renderFooterMeta();
      if (cfg.dispenser_url) {
        btnDispenser.classList.remove("hidden");
        btnDispenser.addEventListener("click", () => {
          window.location.assign(cfg.dispenser_url);
        });
      }
    } catch (_err) {
      // Leave dispenser button hidden if config cannot be loaded
    }
  }

  async function fetchHealth(revealPanel = false) {
    try {
      const resp = await fetch("/health", { cache: "no-store" });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const fw = data.esp32_firmware || {};
      footerState.firmwareVersion = fw.version || "";
      renderFooterMeta();
      updateStatusBadge(data);

      if (revealPanel || !healthPanel.classList.contains("hidden")) {
        const espConnected = Boolean(data.serial_connected);
        const serviceHealthy = espConnected && data.status === "healthy";
        const fwLabel = fw.version
          ? `${fw.version}${fw.sha256 ? ` (${fw.sha256})` : ""}`
          : "Unknown";
        const rows = [
          [
            "Service Status",
            espConnected ? data.status : `${data.status} (degraded)`,
            serviceHealthy ? "text-emerald-400" : "text-amber-400",
          ],
          [
            "ESP32 Serial",
            espConnected ? "Connected" : "Disconnected",
            espConnected ? "text-emerald-400" : "text-amber-400",
          ],
          [
            "ESP32 Firmware",
            fwLabel,
            "text-slate-100",
          ],
          ["YOLO Model", data.model_loaded ? "Loaded" : "Missing", "text-slate-100"],
          ["Lock Engaged", data.lock_engaged ? "Yes (Closed)" : "No (Open)", "text-slate-100"],
          ["Admin Override", data.admin_override || "None (Auto)", "text-slate-100"],
          ["Prey Timer", `${data.lockout_remaining_seconds}s`, "text-slate-100"],
        ];
        healthGrid.innerHTML = rows
          .map(
            ([label, val, valClass]) => `
            <div class="bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2">
              <div class="text-[11px] text-slate-400">${label}</div>
              <div class="font-medium ${valClass}">${val}</div>
            </div>`
          )
          .join("");
        healthRaw.textContent = JSON.stringify(data, null, 2);
        healthPanel.classList.remove("hidden");
      }
    } catch (err) {
      setLockControlsEnabled(false);
      statusBadge.className =
        "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-900/60 border border-slate-800 text-slate-400 opacity-75";
      statusDot.className = "w-2.5 h-2.5 rounded-full bg-amber-500";
      statusText.textContent = "Offline";
      if (revealPanel) {
        showToast(`Failed to fetch /health: ${err.message}`, "error");
      }
    }
  }

  async function sendAdminCommand(endpoint, label, variant) {
    try {
      const resp = await fetch(endpoint, { method: "POST" });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${resp.status}`);
      }
      showToast(label, variant);
      await fetchHealth(false);
    } catch (err) {
      showToast(`Command failed: ${err.message}`, "error");
    }
  }

  btnLock.addEventListener("click", () =>
    sendAdminCommand("/ui/lock", "Admin override active: Door forced LOCKED.", "lock")
  );

  btnUnlock.addEventListener("click", () =>
    sendAdminCommand("/ui/unlock", "Admin override active: Door forced UNLOCKED.", "unlock")
  );

  btnInfo.addEventListener("click", () => fetchHealth(true));

  btnCloseInfo.addEventListener("click", () => {
    healthPanel.classList.add("hidden");
  });

  btnCamera.addEventListener("click", () => {
    window.location.assign("/cctv1/");
  });

  // Initial status & config fetch
  loadUiConfig();
  fetchHealth(false);
});
