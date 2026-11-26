document.addEventListener("DOMContentLoaded", () => {
	if (window.lucide) {
		window.lucide.createIcons();
	}

	const btnLock = document.getElementById("btn-lock");
	const btnUnlock = document.getElementById("btn-unlock");
	const btnAuto = document.getElementById("btn-auto");
	const autoModeHint = document.getElementById("auto-mode-hint");
	const btnInfo = document.getElementById("btn-info");
	const btnCamera = document.getElementById("btn-camera");
	const btnDispenser = document.getElementById("btn-dispenser");
	const btnCloseInfo = document.getElementById("btn-close-info");
	const btnReauth = document.getElementById("btn-reauth");
	if (btnReauth) {
		btnReauth.addEventListener("click", () => {
			window.location.assign(
				"/oauth2/sign_out?rd=%2Foauth2%2Fstart%3Frd%3D%252F",
			);
		});
	}

	// Telemetry drawer elements
	const btnDrawer = document.getElementById("btn-drawer");
	const btnCloseDrawer = document.getElementById("btn-close-drawer");
	const drawerBackdrop = document.getElementById("drawer-backdrop");
	const telemetryDrawer = document.getElementById("telemetry-drawer");
	const drawerMetricsGrid = document.getElementById("drawer-metrics-grid");
	const drawerBucketsList = document.getElementById("drawer-buckets-list");
	const drawerHourlyChart = document.getElementById("drawer-hourly-chart");
	const drawerRecentLocks = document.getElementById("drawer-recent-locks");
	const drawerRecentDetections = document.getElementById(
		"drawer-recent-detections",
	);
	const drawerMetricsRaw = document.getElementById("drawer-metrics-raw");
	const drawerUpdatedAt = document.getElementById("drawer-updated-at");

	const statusBadge = document.getElementById("status-badge");
	const statusDot = document.getElementById("status-dot");
	const statusText = document.getElementById("status-text");
	const toast = document.getElementById("toast");
	const healthPanel = document.getElementById("health-panel");
	const healthGrid = document.getElementById("health-grid");
	const healthRaw = document.getElementById("health-raw");

	const btnDataset = document.getElementById("btn-dataset");
	const btnCloseDataset = document.getElementById("btn-close-dataset");
	const datasetPanel = document.getElementById("dataset-panel");
	const datasetGrid = document.getElementById("dataset-grid");
	const datasetCountBadge = document.getElementById("dataset-count-badge");

	const btnPurgeDataset = document.getElementById("btn-purge-dataset");
	const purgeModal = document.getElementById("purge-modal");
	const purgeConfirmInput = document.getElementById("purge-confirm-input");
	const btnCancelPurge = document.getElementById("btn-cancel-purge");
	const btnConfirmPurge = document.getElementById("btn-confirm-purge");

	const triageModal = document.getElementById("triage-modal");
	const triageStage = document.getElementById("triage-stage");
	const triageImg = document.getElementById("triage-img");
	const triageSvg = document.getElementById("triage-svg");
	const triageLoading = document.getElementById("triage-loading");
	const triageTitle = document.getElementById("triage-title");
	const triageSubtitle = document.getElementById("triage-subtitle");
	const triageMetaBar = document.getElementById("triage-meta-bar");
	const triageMetaJson = document.getElementById("triage-meta-json");
	const btnTriagePrev = document.getElementById("btn-triage-prev");
	const btnTriageNext = document.getElementById("btn-triage-next");
	const btnToggleBoxEdit = document.getElementById("btn-toggle-box-edit");
	const boxEditToolbar = document.getElementById("box-edit-toolbar");
	const boxEditHint = document.getElementById("box-edit-hint");
	const btnRemoveSelectedBox = document.getElementById(
		"btn-remove-selected-box",
	);

	const footerMeta = document.getElementById("footer-meta");
	const footerRepoLink = document.getElementById("footer-repo-link");
	const currentYear = new Date().getFullYear();

	const footerState = {
		appVersion: "",
		firmwareVersion: "",
		modelDate: "",
		repoUrl: "",
	};

	const datasetState = {
		filter: "all",
		items: [],
		activeIndex: -1,
		isLoadingImage: false,
		editMode: false,
		selectedBoxIndex: 0,
		defaultDrawClass: 0,
		drag: null,
	};

	const updateBanner = document.getElementById("update-banner");
	const btnRefreshUi = document.getElementById("btn-refresh-ui");
	const loadedUiVersion = document.body?.dataset?.uiVersion || "";

	const offlineBanner = document.getElementById("offline-banner");
	const offlineBannerText = document.getElementById("offline-banner-text");
	const btnRetryBackend = document.getElementById("btn-retry-backend");

	const BACKOFF_BASE_MS = 1000;
	const BACKOFF_MAX_MS = 15000;
	const backendConnState = {
		online: true,
		attempt: 0,
		retryTimer: null,
		inFlight: false,
	};

	let drawerPollTimer = null;

	function checkUiVersion(serverVersion) {
		if (
			!serverVersion ||
			!loadedUiVersion ||
			loadedUiVersion === "__ASSET_V__" ||
			serverVersion === loadedUiVersion
		) {
			return;
		}
		if (updateBanner) {
			updateBanner.classList.remove("hidden");
		}
	}

	if (btnRefreshUi) {
		btnRefreshUi.addEventListener("click", () => {
			window.location.reload();
		});
	}

	async function apiFetch(url, options = {}) {
		const method = (options.method || "GET").toUpperCase();
		const headers = { ...(options.headers || {}) };
		if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
			headers["X-Requested-With"] = "fetch";
		}
		let resp;
		try {
			resp = await fetch(url, { ...options, headers });
		} catch (err) {
			handleBackendOffline();
			throw err;
		}
		if (resp.status === 502 || resp.status === 503 || resp.status === 504) {
			handleBackendOffline();
		}
		if (resp.status === 401) {
			const rd = encodeURIComponent(
				window.location.pathname + window.location.search,
			);
			window.location.assign(`/oauth2/start?rd=${rd}`);
			return new Promise(() => {});
		}
		return resp;
	}

	function renderFooterMeta() {
		if (footerMeta) {
			footerMeta.replaceChildren();

			const prefixParts = [];
			if (footerState.appVersion) {
				prefixParts.push(`v${footerState.appVersion}`);
			}
			if (footerState.firmwareVersion) {
				prefixParts.push(`fw ${footerState.firmwareVersion}`);
			}
			if (footerState.modelDate) {
				prefixParts.push(`model ${footerState.modelDate}`);
			}
			prefixParts.push("© ");

			footerMeta.appendChild(document.createTextNode(prefixParts.join(" · ")));

			const brandLink = document.createElement("a");
			brandLink.href = "http://belodetek.io";
			brandLink.target = "_blank";
			brandLink.rel = "noopener noreferrer";
			brandLink.className = "hover:text-slate-300 transition-colors";
			brandLink.textContent = "belodetek";
			footerMeta.appendChild(brandLink);

			footerMeta.appendChild(document.createTextNode(` ${currentYear}`));
		}
		if (footerRepoLink && footerState.repoUrl) {
			footerRepoLink.href = footerState.repoUrl;
			footerRepoLink.classList.remove("hidden");
		}
	}

	renderFooterMeta();

	let toastTimer = null;

	function showToast(message, variant = "info", autoDismissMs = 0) {
		if (!toast) {
			return;
		}
		if (toastTimer) {
			clearTimeout(toastTimer);
			toastTimer = null;
		}
		const styles = {
			lock: "bg-rose-950/80 border-rose-700 text-rose-200",
			unlock: "bg-emerald-950/80 border-emerald-700 text-emerald-200",
			auto: "bg-sky-950/80 border-sky-700 text-sky-200",
			error: "bg-red-950/90 border-red-700 text-red-200",
			info: "bg-slate-900 border-slate-700 text-slate-200",
		};
		toast.className = `rounded-xl px-4 py-3 text-sm font-medium border text-center ${styles[variant] || styles.info}`;
		toast.textContent = message;
		toast.classList.remove("hidden");

		if (autoDismissMs > 0) {
			toastTimer = setTimeout(() => {
				toast.classList.add("hidden");
				toastTimer = null;
			}, autoDismissMs);
		}
	}

	function pulseDatasetBadge(totalCount) {
		if (!datasetCountBadge) {
			return;
		}
		datasetCountBadge.textContent = String(totalCount);
		datasetCountBadge.className =
			"text-xs px-2 py-0.5 rounded-full bg-sky-500/25 text-sky-200 ring-2 ring-sky-400 transition-all duration-300";
		setTimeout(() => {
			datasetCountBadge.className =
				"text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 transition-all duration-300";
		}, 2000);
	}

	function connectDatasetEventStream() {
		if (typeof EventSource === "undefined") {
			return;
		}
		const es = new EventSource("/ui/dataset/events", { withCredentials: true });
		let sseOpened = false;
		es.addEventListener("open", () => {
			sseOpened = true;
			if (!backendConnState.online) {
				backendConnState.attempt = 0;
				probeBackendHealth();
			}
		});
		es.addEventListener("error", () => {
			if (!sseOpened) {
				es.close();
				loadUiConfig();
				return;
			}
			if (backendConnState.online) {
				probeBackendHealth();
			}
		});
		es.addEventListener("dataset", (ev) => {
			try {
				const data = JSON.parse(ev.data);
				const total = Number(data.counts?.all ?? 0);
				if (btnPurgeDataset) {
					btnPurgeDataset.disabled = total === 0;
				}
				if (data.action === "created") {
					pulseDatasetBadge(total);
					const kind = data.event_type ? ` (${data.event_type})` : "";
					showToast(`New training capture saved${kind}`, "info", 4000);
				} else if (datasetCountBadge) {
					datasetCountBadge.textContent = String(total);
				}
				// Refresh grid if drawer is open and user isn't mid-triage
				const panelOpen =
					datasetPanel && !datasetPanel.classList.contains("hidden");
				const triageClosed =
					!triageModal || triageModal.classList.contains("hidden");
				if (panelOpen && triageClosed) {
					loadDataset(false);
				}
			} catch (_err) {
				// Ignore malformed SSE frames
			}
		});
		es.addEventListener("version", (ev) => {
			try {
				const data = JSON.parse(ev.data);
				checkUiVersion(data.ui_version);
			} catch (_err) {
				// Ignore malformed SSE frames
			}
		});
		window.addEventListener("beforeunload", () => es.close(), { once: true });
	}

	function setLockControlsEnabled(
		enabled,
		hasOverride = false,
		isLocked = false,
	) {
		const connected = Boolean(enabled);
		const locked = connected && Boolean(isLocked);
		const unlocked = connected && !locked;
		if (btnLock) {
			btnLock.disabled = !connected || locked;
		}
		if (btnUnlock) {
			btnUnlock.disabled = !connected || unlocked;
		}
		if (btnAuto) {
			btnAuto.disabled = !(connected && hasOverride);
		}
		if (autoModeHint) {
			autoModeHint.textContent = !connected
				? ""
				: hasOverride
					? "(Override Active)"
					: "(Auto)";
		}
	}

	function updateStatusBadge(health) {
		const espConnected = Boolean(health.serial_connected);
		const hasOverride = Boolean(health.admin_override);
		const isLocked =
			Boolean(health.lock_engaged) || health.admin_override === "locked";
		setLockControlsEnabled(espConnected, hasOverride, isLocked);

		if (!statusBadge || !statusDot || !statusText) {
			return;
		}

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
			statusDot.className =
				"w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse";
			statusText.textContent =
				health.admin_override === "locked" ? "Locked (Admin)" : "Locked (Prey)";
		} else {
			statusDot.className = "w-2.5 h-2.5 rounded-full bg-emerald-400";
			statusText.textContent =
				health.admin_override === "unlocked" ? "Unlocked (Admin)" : "Unlocked";
		}
	}

	function formatUptime(sec) {
		const total = Math.max(0, Number(sec) || 0);
		const hrs = Math.floor(total / 3600);
		const mins = Math.floor((total % 3600) / 60);
		const rem = Math.floor(total % 60);
		if (hrs > 0) {
			return `${hrs}h ${mins}m`;
		}
		if (mins > 0) {
			return `${mins}m ${rem}s`;
		}
		return `${rem}s`;
	}

	function formatTimestamp(isoStr) {
		if (!isoStr) {
			return "";
		}
		const dt = new Date(isoStr);
		return Number.isNaN(dt.getTime()) ? isoStr : dt.toLocaleTimeString();
	}

	function escapeHtml(str) {
		return String(str ?? "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll('"', "&quot;")
			.replaceAll("'", "&#39;");
	}

	function renderDrawerMetrics(snapshot) {
		const totals = snapshot.totals || {};

		if (drawerMetricsGrid) {
			const cards = [
				["Uptime", formatUptime(snapshot.uptime_sec), "text-slate-100"],
				["Total Locks", totals.locks ?? 0, "text-rose-400"],
				["Total Unlocks", totals.unlocks ?? 0, "text-emerald-400"],
				["Prey Triggers", totals.prey_detections ?? 0, "text-amber-400"],
				[
					"Active Lock",
					`${Number(totals.active_lock_sec || 0).toFixed(1)}s`,
					Number(totals.active_lock_sec || 0) > 0
						? "text-rose-400"
						: "text-slate-300",
				],
			];
			drawerMetricsGrid.innerHTML = cards
				.map(
					([label, val, cls]) => `
            <div class="bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2">
              <div class="text-[11px] text-slate-400">${escapeHtml(label)}</div>
              <div class="font-mono text-sm font-semibold ${cls} mt-0.5">${escapeHtml(val)}</div>
            </div>`,
				)
				.join("");
		}

		if (drawerBucketsList) {
			const buckets = snapshot.duration_buckets || [];
			const maxCount = Math.max(1, ...buckets.map((b) => Number(b.count) || 0));
			drawerBucketsList.innerHTML = buckets
				.map((b) => {
					const count = Number(b.count) || 0;
					const pct =
						count > 0 ? Math.max(4, Math.round((count / maxCount) * 100)) : 0;
					return `
            <div class="space-y-1">
              <div class="flex items-center justify-between text-xs">
                <span class="text-slate-300 font-mono">${escapeHtml(b.label)}</span>
                <span class="text-slate-400 font-mono">${count}</span>
              </div>
              <div class="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
                <div class="h-full bg-sky-500 rounded-full" style="width: ${pct}%"></div>
              </div>
            </div>`;
				})
				.join("");
		}

		if (drawerHourlyChart) {
			const locksArr = snapshot.hourly?.locks || Array(24).fill(0);
			const detsArr = snapshot.hourly?.detections || Array(24).fill(0);
			const maxHourVal = Math.max(
				1,
				...locksArr.map((n) => Number(n) || 0),
				...detsArr.map((n) => Number(n) || 0),
			);
			drawerHourlyChart.innerHTML = Array.from({ length: 24 }, (_, h) => {
				const lVal = Number(locksArr[h]) || 0;
				const dVal = Number(detsArr[h]) || 0;
				const lHeight =
					lVal > 0
						? `${Math.max(8, Math.round((lVal / maxHourVal) * 100))}%`
						: "2px";
				const dHeight =
					dVal > 0
						? `${Math.max(8, Math.round((dVal / maxHourVal) * 100))}%`
						: "2px";
				return `
          <div class="flex flex-col items-center gap-1 min-w-0" title="${String(h).padStart(2, "0")}:00 — ${lVal} locks, ${dVal} detections">
            <div class="h-16 w-full flex items-end justify-center gap-0.5">
              <div class="w-1.5 rounded-t ${lVal > 0 ? "bg-rose-500/90" : "bg-slate-800"}" style="height: ${lHeight}"></div>
              <div class="w-1.5 rounded-t ${dVal > 0 ? "bg-amber-400/90" : "bg-slate-800"}" style="height: ${dHeight}"></div>
            </div>
            <span class="text-[9px] font-mono text-slate-500">${h % 6 === 0 ? String(h).padStart(2, "0") : ""}</span>
          </div>`;
			}).join("");
		}

		if (drawerRecentLocks) {
			const locks = snapshot.recent_locks || [];
			if (!locks.length) {
				drawerRecentLocks.innerHTML =
					'<div class="text-xs text-slate-500 py-2">No completed lock cycles yet.</div>';
			} else {
				drawerRecentLocks.innerHTML = [...locks]
					.reverse()
					.slice(0, 10)
					.map(
						(ev) => `
              <div class="flex items-center justify-between gap-2 bg-slate-950/70 border border-slate-800/80 rounded-lg px-2.5 py-1.5 text-xs">
                <div class="truncate">
                  <span class="font-medium text-rose-300">${escapeHtml(ev.source || "lock")}</span>
                  <span class="text-slate-500">→ ${escapeHtml(ev.unlock_source || "unlock")}</span>
                </div>
                <div class="flex items-center gap-2 shrink-0 font-mono text-[11px]">
                  <span class="text-slate-200">${escapeHtml(ev.duration_sec)}s</span>
                  <span class="text-slate-500">${escapeHtml(formatTimestamp(ev.timestamp))}</span>
                </div>
              </div>`,
					)
					.join("");
			}
		}

		if (drawerRecentDetections) {
			const dets = snapshot.recent_detections || [];
			if (!dets.length) {
				drawerRecentDetections.innerHTML =
					'<div class="text-xs text-slate-500 py-2">No recent prey detections.</div>';
			} else {
				drawerRecentDetections.innerHTML = [...dets]
					.reverse()
					.slice(0, 10)
					.map((ev) => {
						const summary = (ev.detections || [])
							.map(
								(d) =>
									`${escapeHtml(d.class)} (${Math.round((Number(d.confidence) || 0) * 100)}%)`,
							)
							.join(", ");
						return `
              <div class="flex items-center justify-between gap-2 bg-slate-950/70 border border-slate-800/80 rounded-lg px-2.5 py-1.5 text-xs">
                <div class="truncate">
                  <span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-500/20 text-amber-300 mr-1.5">${escapeHtml(ev.event_type || "EVENT")}</span>
                  <span class="text-slate-200">${summary || "Triggered"}</span>
                </div>
                <span class="shrink-0 font-mono text-[11px] text-slate-500">${escapeHtml(formatTimestamp(ev.timestamp))}</span>
              </div>`;
					})
					.join("");
			}
		}

		if (drawerMetricsRaw) {
			drawerMetricsRaw.textContent = JSON.stringify(snapshot, null, 2);
		}
		if (drawerUpdatedAt) {
			drawerUpdatedAt.textContent = `Updated ${new Date().toLocaleTimeString()}`;
		}
	}

	async function fetchDrawerMetrics() {
		try {
			const resp = await apiFetch("/ui/metrics", { cache: "no-store" });
			if (!resp.ok) {
				throw new Error(`HTTP ${resp.status}`);
			}
			const snapshot = await resp.json();
			renderDrawerMetrics(snapshot);
		} catch (err) {
			if (drawerMetricsGrid) {
				drawerMetricsGrid.innerHTML = `<div class="col-span-full text-xs text-rose-400 py-3">Failed to load metrics: ${err.message}</div>`;
			}
		}
	}

	function setDrawerOpen(open) {
		if (!telemetryDrawer) {
			return;
		}
		telemetryDrawer.classList.toggle("hidden", !open);
		telemetryDrawer.setAttribute("aria-hidden", String(!open));
		if (btnDrawer) {
			btnDrawer.setAttribute("aria-expanded", String(open));
		}
		if (drawerBackdrop) {
			drawerBackdrop.classList.toggle("hidden", !open);
		}
		if (drawerPollTimer) {
			clearInterval(drawerPollTimer);
			drawerPollTimer = null;
		}
		if (open) {
			fetchDrawerMetrics();
			fetchHealth(false);
			drawerPollTimer = setInterval(fetchDrawerMetrics, 4000);
		}
	}

	async function loadUiConfig() {
		if (!btnDispenser) {
			return;
		}
		try {
			const resp = await apiFetch("/ui/config", { cache: "no-store" });
			if (!resp.ok) {
				return;
			}

			const cfg = await resp.json();
			footerState.appVersion = cfg.app_version || "";
			footerState.repoUrl = cfg.repo_url || "";
			renderFooterMeta();
			checkUiVersion(cfg.ui_version);
			if (cfg.dispenser_url) {
				btnDispenser.classList.remove("hidden");
				btnDispenser.onclick = () => {
					window.location.assign(cfg.dispenser_url);
				};
			}
		} catch (_err) {
			// Leave dispenser button hidden if config cannot be loaded
		}
	}

	async function fetchHealth(revealPanel = false) {
		try {
			const resp = await apiFetch("/health", { cache: "no-store" });
			if (!resp.ok) {
				throw new Error(`HTTP ${resp.status}`);
			}
			const data = await resp.json();
			const fw = data.esp32_firmware || {};
			const modelMeta = data.model_metadata || {};
			footerState.firmwareVersion = fw.version || "";
			footerState.modelDate = modelMeta.short_date || "";
			renderFooterMeta();
			handleBackendRecovered();
			updateStatusBadge(data);

			if (
				healthPanel &&
				healthGrid &&
				healthRaw &&
				(revealPanel || !healthPanel.classList.contains("hidden"))
			) {
				const espConnected = Boolean(data.serial_connected);
				const serviceHealthy = espConnected && data.status === "healthy";
				const fwMismatch = Boolean(
					fw.version && fw.local_version && fw.version !== fw.local_version,
				);
				const fwBaseLabel = fw.version
					? `${fw.version}${fw.sha256 ? ` (${fw.sha256})` : ""}`
					: "Unknown";
				const fwLabel = fwMismatch
					? `${fwBaseLabel} (local: ${fw.local_version})`
					: fwBaseLabel;
				const modelDetails = [
					modelMeta.version ? `v${modelMeta.version}` : null,
					modelMeta.short_date || null,
				]
					.filter(Boolean)
					.join(" · ");
				const modelLabel = !data.model_loaded
					? "Missing"
					: modelDetails
						? `Loaded (${modelDetails})`
						: "Loaded";
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
						fwMismatch ? "text-amber-400" : "text-slate-100",
					],
					["YOLO Model", modelLabel, "text-slate-100"],
					[
						"Lock Engaged",
						data.lock_engaged ? "Yes (Closed)" : "No (Open)",
						"text-slate-100",
					],
					[
						"Admin Override",
						data.admin_override || "None (Auto)",
						"text-slate-100",
					],
					[
						"Prey Timer",
						`${data.lockout_remaining_seconds}s`,
						"text-slate-100",
					],
				];
				healthGrid.innerHTML = rows
					.map(
						([label, val, valClass]) => `
            <div class="bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2">
              <div class="text-[11px] text-slate-400">${label}</div>
              <div class="font-medium ${valClass}">${val}</div>
            </div>`,
					)
					.join("");
				healthRaw.textContent = JSON.stringify(data, null, 2);
				healthPanel.classList.remove("hidden");
			}
		} catch (err) {
			handleBackendOffline();
			if (revealPanel) {
				showToast(`Failed to fetch /health: ${err.message}`, "error");
			}
		}
	}

	async function sendAdminCommand(endpoint, label, variant) {
		try {
			const resp = await apiFetch(endpoint, { method: "POST" });
			if (!resp.ok) {
				const errBody = await resp.json().catch(() => ({}));
				throw new Error(errBody.detail || `HTTP ${resp.status}`);
			}
			showToast(label, variant);
			await fetchHealth(false);
			if (telemetryDrawer && !telemetryDrawer.classList.contains("hidden")) {
				await fetchDrawerMetrics();
			}
		} catch (err) {
			showToast(`Command failed: ${err.message}`, "error");
		}
	}

	function clamp01(val) {
		return Math.min(1, Math.max(0, val));
	}

	function yoloToCorners(box) {
		return {
			x1: clamp01(box.x - box.w / 2),
			y1: clamp01(box.y - box.h / 2),
			x2: clamp01(box.x + box.w / 2),
			y2: clamp01(box.y + box.h / 2),
		};
	}

	function cornersToYolo(cls, x1, y1, x2, y2) {
		const left = clamp01(Math.min(x1, x2));
		const right = clamp01(Math.max(x1, x2));
		const top = clamp01(Math.min(y1, y2));
		const bottom = clamp01(Math.max(y1, y2));
		const w = Math.max(0.015, right - left);
		const h = Math.max(0.015, bottom - top);
		const cx = clamp01(left + w / 2);
		const cy = clamp01(top + h / 2);
		return {
			cls,
			x: Number(cx.toFixed(6)),
			y: Number(cy.toFixed(6)),
			w: Number(Math.min(1, w).toFixed(6)),
			h: Number(Math.min(1, h).toFixed(6)),
		};
	}

	function clientToNorm(clientX, clientY) {
		const rect = triageSvg.getBoundingClientRect();
		if (!rect.width || !rect.height) {
			return { x: 0, y: 0 };
		}
		return {
			x: clamp01((clientX - rect.left) / rect.width),
			y: clamp01((clientY - rect.top) / rect.height),
		};
	}

	function setTriageImageLoading(loading) {
		datasetState.isLoadingImage = Boolean(loading);
		if (triageLoading) {
			triageLoading.classList.toggle("hidden", !datasetState.isLoadingImage);
		}
		if (triageImg) {
			triageImg.classList.toggle("opacity-40", datasetState.isLoadingImage);
		}
		if (btnTriagePrev) {
			btnTriagePrev.disabled =
				datasetState.isLoadingImage || datasetState.activeIndex <= 0;
		}
		if (btnTriageNext) {
			btnTriageNext.disabled =
				datasetState.isLoadingImage ||
				datasetState.activeIndex >= datasetState.items.length - 1;
		}
	}

	function updateTriageSubtitle() {
		const item = datasetState.items[datasetState.activeIndex];
		if (!item || !triageSubtitle) {
			return;
		}
		const selInfo =
			datasetState.editMode && item.boxes.length
				? ` · Selected #${datasetState.selectedBoxIndex + 1} (${item.boxes[datasetState.selectedBoxIndex]?.cls === 0 ? "Prey" : `Class ${item.boxes[datasetState.selectedBoxIndex]?.cls}`})`
				: "";
		triageSubtitle.textContent = `${datasetState.activeIndex + 1} of ${datasetState.items.length} · ${item.boxes.length} box(es)${selInfo}`;
		if (btnRemoveSelectedBox) {
			btnRemoveSelectedBox.disabled = item.boxes.length === 0;
		}
		if (boxEditHint) {
			boxEditHint.textContent =
				"Draw mode: Prey (0) · Drag empty area or handles";
		}
	}

	function formatMetaSummary(meta) {
		if (!meta || typeof meta !== "object" || Object.keys(meta).length === 0) {
			return "";
		}
		const eventType =
			meta.event_type || meta.alarm_type || meta.alarm?.type || "";
		const dets = Array.isArray(meta.detections)
			? meta.detections
			: Array.isArray(meta.inference?.detections)
				? meta.inference.detections
				: [];
		const topDet = dets[0];
		const confPct =
			topDet && typeof topDet.confidence === "number"
				? `${Math.round(topDet.confidence * 100)}%`
				: "";
		if (eventType && confPct) {
			return `${eventType} · ${confPct}`;
		}
		return eventType || confPct || "META";
	}

	function renderTriageMeta(item) {
		if (!triageMetaBar) {
			return;
		}
		triageMetaBar.replaceChildren();
		if (triageMetaJson) {
			triageMetaJson.classList.add("hidden");
			triageMetaJson.textContent = "";
		}

		const meta = item?.meta;
		if (!meta || typeof meta !== "object" || Object.keys(meta).length === 0) {
			triageMetaBar.classList.add("hidden");
			return;
		}

		const pills = [];
		const evType = meta.event_type || meta.alarm_type || meta.alarm?.type;
		if (evType) {
			const normalizedType = String(evType).toUpperCase();
			pills.push({
				label: String(evType),
				cls:
					normalizedType === "ANIMAL" || normalizedType === "PREY"
						? "px-1.5 py-0.5 rounded bg-rose-950/90 border border-rose-800/80 text-rose-200 font-semibold"
						: "px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-200 font-medium",
			});
		}

		const rawTs = meta.timestamp_utc || meta.captured_at;
		if (rawTs) {
			const dt = new Date(rawTs);
			const tsLabel = Number.isNaN(dt.getTime())
				? String(rawTs)
				: dt.toLocaleString([], {
						month: "short",
						day: "numeric",
						hour: "2-digit",
						minute: "2-digit",
						second: "2-digit",
					});
			pills.push({ label: tsLabel, cls: "text-slate-400 font-mono" });
		}

		const fetchMs = meta.fetch_ms ?? meta.inference?.fetch_ms;
		const inferMs = meta.infer_ms ?? meta.inference?.infer_ms;
		if (fetchMs != null || inferMs != null) {
			const timing = [
				fetchMs != null ? `fetch ${fetchMs}ms` : null,
				inferMs != null ? `infer ${inferMs}ms` : null,
			]
				.filter(Boolean)
				.join(" · ");
			pills.push({ label: timing, cls: "text-sky-300/90 font-mono" });
		}

		if (typeof meta.lock_engaged === "boolean") {
			pills.push({
				label: meta.lock_engaged
					? `Locked (${meta.lockout_duration_sec ?? ""}s)`
					: `Unlocked (${meta.admin_override || "no lock"})`,
				cls: meta.lock_engaged ? "text-rose-300" : "text-slate-400",
			});
		}

		const dets = Array.isArray(meta.detections)
			? meta.detections
			: Array.isArray(meta.inference?.detections)
				? meta.inference.detections
				: [];
		if (dets.length > 0) {
			const detText = dets
				.map((d) => {
					const name = d.class || d.label || `cls ${d.cls}`;
					const pct =
						typeof d.confidence === "number"
							? ` ${Math.round(d.confidence * 100)}%`
							: "";
					return `${name}${pct}`;
				})
				.join(", ");
			pills.push({
				label: `YOLO: ${detText}`,
				cls: "text-amber-300 font-mono",
			});
		}

		for (const pill of pills) {
			const span = document.createElement("span");
			span.className = pill.cls;
			span.textContent = pill.label;
			triageMetaBar.appendChild(span);
		}

		if (triageMetaJson) {
			triageMetaJson.textContent = JSON.stringify(meta, null, 2);
			const toggleBtn = document.createElement("button");
			toggleBtn.type = "button";
			toggleBtn.id = "btn-toggle-meta-json";
			toggleBtn.setAttribute("aria-expanded", "false");
			toggleBtn.className =
				"px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[10px] font-mono text-sky-300 cursor-pointer";
			toggleBtn.textContent = "Meta JSON";
			toggleBtn.addEventListener("click", () => {
				const isHidden = triageMetaJson.classList.toggle("hidden");
				toggleBtn.setAttribute("aria-expanded", String(!isHidden));
			});
			triageMetaBar.appendChild(toggleBtn);
		}

		triageMetaBar.classList.remove("hidden");
	}

	function renderSvgBoxes(boxes) {
		if (!triageSvg) {
			return;
		}
		const list = boxes || [];
		if (datasetState.selectedBoxIndex >= list.length) {
			datasetState.selectedBoxIndex = Math.max(0, list.length - 1);
		}
		triageSvg.innerHTML = list
			.map((box, idx) => {
				const isPrey = box.cls === 0;
				const isSelected =
					datasetState.editMode && idx === datasetState.selectedBoxIndex;
				const stroke = isPrey ? "#f43f5e" : "#38bdf8";
				const fill = isSelected
					? isPrey
						? "rgba(244, 63, 94, 0.16)"
						: "rgba(56, 189, 248, 0.16)"
					: "transparent";
				const { x1, y1, x2, y2 } = yoloToCorners(box);
				const w = x2 - x1;
				const h = y2 - y1;
				const strokeW = isSelected ? "3" : "2";
				const cursorClass = datasetState.editMode ? "cursor-move" : "";

				let handles = "";
				if (isSelected) {
					const corners = [
						["nw", x1, y1, "cursor-nwse-resize"],
						["ne", x2, y1, "cursor-nesw-resize"],
						["sw", x1, y2, "cursor-nesw-resize"],
						["se", x2, y2, "cursor-nwse-resize"],
					];
					handles = corners
						.map(
							([corner, cx, cy, cursor]) => `
              <g data-handle="${corner}" data-box-idx="${idx}" class="${cursor}">
                <circle cx="${cx}" cy="${cy}" r="0.055" fill="transparent" />
                <circle cx="${cx}" cy="${cy}" r="0.018" fill="${stroke}" stroke="#020617" stroke-width="1.5" vector-effect="non-scaling-stroke" />
              </g>`,
						)
						.join("");
				}

				return `
          <g>
            <rect
              data-box-idx="${idx}"
              x="${x1}"
              y="${y1}"
              width="${w}"
              height="${h}"
              fill="${fill}"
              stroke="${stroke}"
              stroke-width="${strokeW}"
              vector-effect="non-scaling-stroke"
              class="${cursorClass}"
            />
            ${handles}
          </g>`;
			})
			.join("");
		updateTriageSubtitle();
	}

	function setBoxEditMode(enabled) {
		datasetState.editMode = Boolean(enabled);
		datasetState.drag = null;
		if (btnToggleBoxEdit) {
			btnToggleBoxEdit.setAttribute(
				"aria-pressed",
				String(datasetState.editMode),
			);
			btnToggleBoxEdit.className = datasetState.editMode
				? "px-3 py-1.5 rounded-lg bg-sky-600 text-white text-xs font-semibold border border-sky-400"
				: "px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700";
		}
		if (boxEditToolbar) {
			boxEditToolbar.classList.toggle("hidden", !datasetState.editMode);
		}
		if (triageSvg) {
			if (datasetState.editMode) {
				triageSvg.classList.remove("pointer-events-none");
				triageSvg.classList.add(
					"pointer-events-auto",
					"touch-none",
					"cursor-crosshair",
				);
			} else {
				triageSvg.classList.add("pointer-events-none");
				triageSvg.classList.remove(
					"pointer-events-auto",
					"touch-none",
					"cursor-crosshair",
				);
			}
		}
		const item = datasetState.items[datasetState.activeIndex];
		if (item) {
			renderSvgBoxes(item.boxes);
		}
	}

	function openTriageAt(index, force = false) {
		if (!triageModal) {
			return;
		}
		if (!force && datasetState.isLoadingImage) {
			return;
		}
		if (index < 0 || index >= datasetState.items.length) {
			setTriageImageLoading(false);
			triageModal.classList.add("hidden");
			datasetState.activeIndex = -1;
			datasetState.drag = null;
			return;
		}
		datasetState.activeIndex = index;
		datasetState.selectedBoxIndex = 0;
		datasetState.drag = null;
		const item = datasetState.items[index];
		if (triageTitle) {
			triageTitle.textContent = item.filename;
		}
		renderSvgBoxes(item.boxes);
		renderTriageMeta(item);
		triageModal.classList.remove("hidden");

		if (triageImg) {
			const targetUrl = new URL(item.image_url, window.location.origin).href;
			if (triageImg.src === targetUrl && triageImg.complete) {
				setTriageImageLoading(false);
			} else {
				setTriageImageLoading(true);
				triageImg.src = item.image_url;
			}
		}
	}

	function renderDatasetGrid() {
		if (!datasetGrid) {
			return;
		}
		if (!datasetState.items.length) {
			datasetGrid.innerHTML =
				'<div class="col-span-full text-center text-xs text-slate-400 py-6">No captures in this filter.</div>';
			return;
		}
		datasetGrid.innerHTML = datasetState.items
			.map((item, idx) => {
				const badge = item.has_prey
					? '<span class="px-1.5 py-0.5 rounded bg-rose-600/90 text-white text-[10px]">Prey</span>'
					: item.boxes.length
						? `<span class="px-1.5 py-0.5 rounded bg-sky-600/90 text-white text-[10px]">Class ${escapeHtml(item.boxes[0].cls)}</span>`
						: '<span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">Empty</span>';
				const metaText = formatMetaSummary(item.meta);
				const metaOverlay = metaText
					? `<div class="ds-meta-pill absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded bg-slate-950/80 border border-slate-800/80 text-[10px] font-mono text-slate-200 backdrop-blur-[1px]">${escapeHtml(metaText)}</div>`
					: "";
				return `
          <button type="button" data-ds-idx="${idx}" class="group relative aspect-video rounded-xl overflow-hidden bg-slate-950 border border-slate-800 text-left">
            <img src="${escapeHtml(item.thumb_url)}" loading="lazy" alt="${escapeHtml(item.filename)}" class="w-full h-full object-cover" />
            ${metaOverlay}
            <div class="absolute inset-x-0 bottom-0 p-1.5 bg-gradient-to-t from-slate-950/90 to-transparent flex items-center justify-between">
              ${badge}
              <span class="text-[10px] text-slate-300 truncate max-w-[65%]">${escapeHtml(item.filename)}</span>
            </div>
          </button>`;
			})
			.join("");
	}

	async function loadDataset(reveal = false) {
		if (!datasetPanel || !datasetGrid) {
			return;
		}
		if (reveal) {
			datasetPanel.classList.remove("hidden");
			datasetGrid.innerHTML =
				'<div class="col-span-full text-center text-xs text-slate-400 py-6">Loading captures...</div>';
			datasetPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
		}
		try {
			const resp = await apiFetch(
				`/ui/dataset/items?filter=${encodeURIComponent(datasetState.filter)}&limit=60`,
				{ cache: "no-store" },
			);
			if (!resp.ok) {
				throw new Error(`HTTP ${resp.status}`);
			}
			const payload = await resp.json();
			datasetState.items = payload.items || [];
			const totalCount = payload.counts?.all ?? datasetState.items.length;
			if (datasetCountBadge) {
				datasetCountBadge.textContent = String(totalCount);
			}
			if (btnPurgeDataset) {
				btnPurgeDataset.disabled = totalCount === 0;
			}
			renderDatasetGrid();
		} catch (err) {
			if (reveal) {
				datasetGrid.innerHTML = `<div class="col-span-full text-center text-xs text-rose-400 py-6">Failed to load captures (${err.message}).</div>`;
				showToast(`Failed to load training images: ${err.message}`, "error");
			}
		}
	}

	function setPurgeModalOpen(open) {
		if (!purgeModal) {
			return;
		}
		purgeModal.classList.toggle("hidden", !open);
		if (purgeConfirmInput) {
			purgeConfirmInput.value = "";
		}
		if (btnConfirmPurge) {
			btnConfirmPurge.disabled = true;
		}
		if (open && purgeConfirmInput) {
			purgeConfirmInput.focus();
		}
	}

	async function executeDatasetPurge() {
		if (!purgeConfirmInput || purgeConfirmInput.value !== "DELETE") {
			return;
		}
		if (btnConfirmPurge) {
			btnConfirmPurge.disabled = true;
		}
		try {
			const resp = await apiFetch("/ui/dataset", {
				method: "DELETE",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ confirm: "DELETE" }),
			});
			if (!resp.ok) {
				const errBody = await resp.json().catch(() => ({}));
				throw new Error(errBody.detail || `HTTP ${resp.status}`);
			}
			const result = await resp.json();
			setPurgeModalOpen(false);
			datasetState.items = [];
			renderDatasetGrid();
			if (datasetCountBadge) {
				datasetCountBadge.textContent = "0";
			}
			if (btnPurgeDataset) {
				btnPurgeDataset.disabled = true;
			}
			showToast(
				`Purged ${result.deleted_images ?? 0} images, ${result.deleted_labels ?? 0} labels, and ${result.deleted_meta ?? 0} metadata files.`,
				"info",
			);
		} catch (err) {
			showToast(`Dataset purge failed: ${err.message}`, "error");
			if (btnConfirmPurge && purgeConfirmInput.value === "DELETE") {
				btnConfirmPurge.disabled = false;
			}
		}
	}

	async function persistBoxes(item, nextBoxes, advanceAfter = false) {
		const resp = await apiFetch(
			`/ui/dataset/labels/${encodeURIComponent(item.filename)}`,
			{
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ boxes: nextBoxes }),
			},
		);
		if (!resp.ok) {
			showToast(`Failed to save labels: HTTP ${resp.status}`, "error");
			return;
		}
		const updated = await resp.json();
		item.boxes = updated.boxes;
		item.has_prey = updated.boxes.some((b) => b.cls === 0);
		renderSvgBoxes(item.boxes);
		renderDatasetGrid();
		if (advanceAfter) {
			openTriageAt(
				Math.min(datasetState.activeIndex + 1, datasetState.items.length - 1),
			);
		}
	}

	async function relabelActiveItem(mode) {
		const item = datasetState.items[datasetState.activeIndex];
		if (!item) {
			return;
		}
		datasetState.defaultDrawClass = 0;

		let nextBoxes = [];
		if (mode === "prey") {
			if (datasetState.editMode && item.boxes.length) {
				nextBoxes = item.boxes.map((b, i) =>
					i === datasetState.selectedBoxIndex ? { ...b, cls: 0 } : b,
				);
			} else {
				nextBoxes = item.boxes.length
					? item.boxes.map((b, i) => ({ ...b, cls: i === 0 ? 0 : b.cls }))
					: [{ cls: 0, x: 0.5, y: 0.5, w: 0.35, h: 0.35 }];
			}
		}

		await persistBoxes(item, nextBoxes, !datasetState.editMode);
	}

	async function removeSelectedBox() {
		const item = datasetState.items[datasetState.activeIndex];
		if (!item?.boxes.length) {
			return;
		}
		const nextBoxes = item.boxes.filter(
			(_b, idx) => idx !== datasetState.selectedBoxIndex,
		);
		datasetState.selectedBoxIndex = Math.max(
			0,
			datasetState.selectedBoxIndex - 1,
		);
		await persistBoxes(item, nextBoxes, false);
	}

	async function deleteActiveItem() {
		const item = datasetState.items[datasetState.activeIndex];
		if (!item) {
			return;
		}
		const resp = await apiFetch(
			`/ui/dataset/items/${encodeURIComponent(item.filename)}`,
			{
				method: "DELETE",
			},
		);
		if (resp.ok) {
			datasetState.items.splice(datasetState.activeIndex, 1);
			renderDatasetGrid();
			if (datasetCountBadge) {
				datasetCountBadge.textContent = String(
					Math.max(0, Number(datasetCountBadge.textContent) - 1),
				);
			}
			openTriageAt(
				Math.min(datasetState.activeIndex, datasetState.items.length - 1),
				true,
			);
		}
	}

	function setBackendFeatureControlsEnabled(enabled) {
		for (const btn of [btnInfo, btnDrawer, btnDataset]) {
			if (btn) {
				btn.disabled = !enabled;
			}
		}
		if (!enabled) {
			setLockControlsEnabled(false);
		}
	}

	function clearBackendRetryTimer() {
		if (backendConnState.retryTimer) {
			clearTimeout(backendConnState.retryTimer);
			backendConnState.retryTimer = null;
		}
	}

	function scheduleBackendRetry() {
		clearBackendRetryTimer();
		const expDelay = Math.min(
			BACKOFF_MAX_MS,
			BACKOFF_BASE_MS * 2 ** backendConnState.attempt,
		);
		// Full jitter (50%..100% of exponential cap) prevents thundering-herd retries
		const delayMs = Math.round(expDelay * (0.5 + Math.random() * 0.5));
		backendConnState.attempt += 1;

		if (offlineBannerText) {
			const sec = Math.max(1, Math.round(delayMs / 1000));
			offlineBannerText.textContent = `Backend offline · retrying in ${sec}s…`;
		}
		backendConnState.retryTimer = setTimeout(() => {
			backendConnState.retryTimer = null;
			probeBackendHealth();
		}, delayMs);
	}

	function handleBackendOffline() {
		const wasOnline = backendConnState.online;
		backendConnState.online = false;
		setBackendFeatureControlsEnabled(false);

		if (statusBadge && statusDot && statusText) {
			statusBadge.className =
				"flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-slate-900/60 border border-slate-800 text-slate-400 opacity-75";
			statusDot.className =
				"w-2.5 h-2.5 rounded-full bg-amber-500 animate-pulse";
			statusText.textContent = "Offline";
		}
		if (offlineBanner) {
			offlineBanner.classList.remove("hidden");
		}
		if (wasOnline && drawerPollTimer) {
			clearInterval(drawerPollTimer);
			drawerPollTimer = null;
		}
		scheduleBackendRetry();
	}

	function handleBackendRecovered() {
		const wasOffline = !backendConnState.online;
		backendConnState.online = true;
		backendConnState.attempt = 0;
		clearBackendRetryTimer();
		setBackendFeatureControlsEnabled(true);

		if (offlineBanner) {
			offlineBanner.classList.add("hidden");
		}
		if (wasOffline) {
			loadUiConfig();
			loadDataset(false);
			if (telemetryDrawer && !telemetryDrawer.classList.contains("hidden")) {
				fetchDrawerMetrics();
				drawerPollTimer = setInterval(fetchDrawerMetrics, 4000);
			}
		}
	}

	async function probeBackendHealth() {
		if (backendConnState.inFlight) {
			return;
		}
		backendConnState.inFlight = true;
		if (offlineBannerText && !backendConnState.online) {
			offlineBannerText.textContent = "Reconnecting to backend…";
		}
		try {
			await fetchHealth(false);
		} finally {
			backendConnState.inFlight = false;
		}
	}

	if (btnRetryBackend) {
		btnRetryBackend.addEventListener("click", () => {
			backendConnState.attempt = 0;
			clearBackendRetryTimer();
			probeBackendHealth();
		});
	}

	window.addEventListener("online", () => {
		if (!backendConnState.online) {
			backendConnState.attempt = 0;
			probeBackendHealth();
		}
	});

	document.addEventListener("visibilitychange", () => {
		if (document.visibilityState === "visible" && !backendConnState.online) {
			backendConnState.attempt = 0;
			probeBackendHealth();
		}
	});

	if (btnLock) {
		btnLock.addEventListener("click", () =>
			sendAdminCommand(
				"/ui/lock",
				"Admin override active: Door forced LOCKED.",
				"lock",
			),
		);
	}

	if (btnUnlock) {
		btnUnlock.addEventListener("click", () =>
			sendAdminCommand(
				"/ui/unlock",
				"Admin override active: Door forced UNLOCKED.",
				"unlock",
			),
		);
	}

	if (btnAuto) {
		btnAuto.addEventListener("click", () =>
			sendAdminCommand(
				"/ui/auto",
				"Admin override cleared: Automatic prey detection resumed.",
				"auto",
			),
		);
	}

	if (btnInfo) {
		btnInfo.addEventListener("click", () => fetchHealth(true));
	}

	if (btnCloseInfo && healthPanel) {
		btnCloseInfo.addEventListener("click", () => {
			healthPanel.classList.add("hidden");
		});
	}

	if (btnDrawer) {
		btnDrawer.addEventListener("click", () => {
			const isHidden =
				!telemetryDrawer || telemetryDrawer.classList.contains("hidden");
			setDrawerOpen(isHidden);
		});
	}

	if (btnCloseDrawer) {
		btnCloseDrawer.addEventListener("click", () => setDrawerOpen(false));
	}

	if (drawerBackdrop) {
		drawerBackdrop.addEventListener("click", () => setDrawerOpen(false));
	}

	if (btnCamera) {
		btnCamera.addEventListener("click", () => {
			window.location.assign("/cctv1/");
		});
	}

	if (btnDataset && datasetPanel && datasetGrid) {
		if (btnPurgeDataset) {
			btnPurgeDataset.addEventListener("click", () => setPurgeModalOpen(true));
		}
		if (btnCancelPurge) {
			btnCancelPurge.addEventListener("click", () => setPurgeModalOpen(false));
		}
		if (purgeModal) {
			purgeModal.addEventListener("click", (ev) => {
				if (ev.target === purgeModal) {
					setPurgeModalOpen(false);
				}
			});
		}
		if (purgeConfirmInput && btnConfirmPurge) {
			purgeConfirmInput.addEventListener("input", () => {
				btnConfirmPurge.disabled = purgeConfirmInput.value !== "DELETE";
			});
			purgeConfirmInput.addEventListener("keydown", (ev) => {
				if (ev.key === "Enter" && purgeConfirmInput.value === "DELETE") {
					ev.preventDefault();
					executeDatasetPurge();
				}
			});
			btnConfirmPurge.addEventListener("click", executeDatasetPurge);
		}

		if (triageImg) {
			triageImg.addEventListener("load", () => setTriageImageLoading(false));
			triageImg.addEventListener("error", () => setTriageImageLoading(false));
		}

		btnDataset.addEventListener("click", () => loadDataset(true));
		if (btnCloseDataset) {
			btnCloseDataset.addEventListener("click", () =>
				datasetPanel.classList.add("hidden"),
			);
		}
		document.querySelectorAll(".ds-filter-btn").forEach((btn) => {
			btn.addEventListener("click", () => {
				datasetState.filter = btn.dataset.dsFilter;
				document.querySelectorAll(".ds-filter-btn").forEach((b) => {
					b.className =
						b.dataset.dsFilter === datasetState.filter
							? "ds-filter-btn px-3 py-1.5 rounded-full text-xs font-medium bg-sky-600 text-white"
							: "ds-filter-btn px-3 py-1.5 rounded-full text-xs font-medium bg-slate-800 text-slate-300";
				});
				loadDataset(false);
			});
		});

		datasetGrid.addEventListener("click", (ev) => {
			const card = ev.target.closest("[data-ds-idx]");
			if (card) {
				openTriageAt(Number(card.dataset.dsIdx), true);
			}
		});

		if (btnToggleBoxEdit) {
			btnToggleBoxEdit.addEventListener("click", () =>
				setBoxEditMode(!datasetState.editMode),
			);
		}
		if (btnRemoveSelectedBox) {
			btnRemoveSelectedBox.addEventListener("click", removeSelectedBox);
		}

		if (triageSvg) {
			// Interactive SVG pointer gestures (draw new box, move box, resize corners)
			triageSvg.addEventListener("pointerdown", (ev) => {
				if (!datasetState.editMode || datasetState.isLoadingImage) {
					return;
				}
				const item = datasetState.items[datasetState.activeIndex];
				if (!item) {
					return;
				}
				ev.preventDefault();
				triageSvg.setPointerCapture(ev.pointerId);
				const pt = clientToNorm(ev.clientX, ev.clientY);

				const handleEl = ev.target.closest("[data-handle]");
				if (handleEl) {
					const idx = Number(handleEl.dataset.boxIdx);
					const box = item.boxes[idx];
					if (!box) {
						return;
					}
					datasetState.selectedBoxIndex = idx;
					datasetState.drag = {
						type: "resize",
						corner: handleEl.dataset.handle,
						boxIdx: idx,
						origCorners: yoloToCorners(box),
						cls: box.cls,
						moved: false,
					};
					renderSvgBoxes(item.boxes);
					return;
				}

				const rectEl = ev.target.closest("rect[data-box-idx]");
				if (rectEl) {
					const idx = Number(rectEl.dataset.boxIdx);
					const box = item.boxes[idx];
					if (!box) {
						return;
					}
					datasetState.selectedBoxIndex = idx;
					datasetState.drag = {
						type: "move",
						boxIdx: idx,
						startPt: pt,
						origBox: { ...box },
						moved: false,
					};
					renderSvgBoxes(item.boxes);
					return;
				}

				// Dragging empty area starts drawing a new bounding box
				const newBox = cornersToYolo(
					datasetState.defaultDrawClass,
					pt.x,
					pt.y,
					pt.x + 0.015,
					pt.y + 0.015,
				);
				item.boxes.push(newBox);
				const newIdx = item.boxes.length - 1;
				datasetState.selectedBoxIndex = newIdx;
				datasetState.drag = {
					type: "draw",
					boxIdx: newIdx,
					startPt: pt,
					cls: datasetState.defaultDrawClass,
					moved: false,
				};
				renderSvgBoxes(item.boxes);
			});

			triageSvg.addEventListener("pointermove", (ev) => {
				const drag = datasetState.drag;
				if (!drag || !datasetState.editMode) {
					return;
				}
				const item = datasetState.items[datasetState.activeIndex];
				if (!item?.boxes[drag.boxIdx]) {
					return;
				}
				const pt = clientToNorm(ev.clientX, ev.clientY);
				drag.moved = true;

				if (drag.type === "move") {
					const dx = pt.x - drag.startPt.x;
					const dy = pt.y - drag.startPt.y;
					const halfW = drag.origBox.w / 2;
					const halfH = drag.origBox.h / 2;
					item.boxes[drag.boxIdx] = {
						...drag.origBox,
						x: Number(
							Math.min(1 - halfW, Math.max(halfW, drag.origBox.x + dx)).toFixed(
								6,
							),
						),
						y: Number(
							Math.min(1 - halfH, Math.max(halfH, drag.origBox.y + dy)).toFixed(
								6,
							),
						),
					};
				} else if (drag.type === "resize") {
					let { x1, y1, x2, y2 } = drag.origCorners;
					if (drag.corner.includes("w")) {
						x1 = pt.x;
					}
					if (drag.corner.includes("e")) {
						x2 = pt.x;
					}
					if (drag.corner.includes("n")) {
						y1 = pt.y;
					}
					if (drag.corner.includes("s")) {
						y2 = pt.y;
					}
					item.boxes[drag.boxIdx] = cornersToYolo(drag.cls, x1, y1, x2, y2);
				} else if (drag.type === "draw") {
					item.boxes[drag.boxIdx] = cornersToYolo(
						drag.cls,
						drag.startPt.x,
						drag.startPt.y,
						pt.x,
						pt.y,
					);
				}

				renderSvgBoxes(item.boxes);
			});

			async function finishBoxDrag(ev) {
				const drag = datasetState.drag;
				if (!drag) {
					return;
				}
				datasetState.drag = null;
				if (triageSvg.hasPointerCapture(ev.pointerId)) {
					triageSvg.releasePointerCapture(ev.pointerId);
				}
				const item = datasetState.items[datasetState.activeIndex];
				if (!item) {
					return;
				}
				// Discard tiny accidental taps when starting a new box
				if (drag.type === "draw") {
					const box = item.boxes[drag.boxIdx];
					if (!box || box.w < 0.025 || box.h < 0.025) {
						item.boxes.splice(drag.boxIdx, 1);
						datasetState.selectedBoxIndex = Math.max(0, item.boxes.length - 1);
						renderSvgBoxes(item.boxes);
						return;
					}
				}
				if (drag.moved || drag.type === "draw") {
					await persistBoxes(item, item.boxes, false);
				}
			}

			triageSvg.addEventListener("pointerup", finishBoxDrag);
			triageSvg.addEventListener("pointercancel", finishBoxDrag);
		}

		const btnCloseTriage = document.getElementById("btn-close-triage");
		if (btnCloseTriage && triageModal) {
			btnCloseTriage.addEventListener("click", () => {
				setBoxEditMode(false);
				setTriageImageLoading(false);
				triageModal.classList.add("hidden");
				datasetState.activeIndex = -1;
			});
		}
		if (btnTriagePrev) {
			btnTriagePrev.addEventListener("click", () =>
				openTriageAt(Math.max(0, datasetState.activeIndex - 1)),
			);
		}
		if (btnTriageNext) {
			btnTriageNext.addEventListener("click", () =>
				openTriageAt(
					Math.min(datasetState.items.length - 1, datasetState.activeIndex + 1),
				),
			);
		}
		const btnLabelPrey = document.getElementById("btn-label-prey");
		if (btnLabelPrey) {
			btnLabelPrey.addEventListener("click", () => relabelActiveItem("prey"));
		}
		const btnLabelClear = document.getElementById("btn-label-clear");
		if (btnLabelClear) {
			btnLabelClear.addEventListener("click", () => relabelActiveItem("clear"));
		}
		const btnTriageDelete = document.getElementById("btn-triage-delete");
		if (btnTriageDelete) {
			btnTriageDelete.addEventListener("click", deleteActiveItem);
		}

		// Mobile horizontal swipe navigation in triage modal (disabled while editing or loading)
		if (triageStage) {
			let touchStartX = 0;
			triageStage.addEventListener(
				"touchstart",
				(ev) => {
					if (datasetState.editMode || datasetState.isLoadingImage) {
						return;
					}
					touchStartX = ev.changedTouches[0].screenX;
				},
				{ passive: true },
			);
			triageStage.addEventListener(
				"touchend",
				(ev) => {
					if (datasetState.editMode || datasetState.isLoadingImage) {
						return;
					}
					const dx = ev.changedTouches[0].screenX - touchStartX;
					if (Math.abs(dx) > 48) {
						openTriageAt(
							dx < 0
								? Math.min(
										datasetState.items.length - 1,
										datasetState.activeIndex + 1,
									)
								: Math.max(0, datasetState.activeIndex - 1),
						);
					}
				},
				{ passive: true },
			);
		}

		loadDataset(false);
		connectDatasetEventStream();
	}

	// Escape closes open modal/drawer first, then triage modal
	document.addEventListener("keydown", (ev) => {
		if (ev.key === "Escape") {
			if (purgeModal && !purgeModal.classList.contains("hidden")) {
				setPurgeModalOpen(false);
				return;
			}
			if (telemetryDrawer && !telemetryDrawer.classList.contains("hidden")) {
				setDrawerOpen(false);
				return;
			}
			if (triageModal && !triageModal.classList.contains("hidden")) {
				setBoxEditMode(false);
				setTriageImageLoading(false);
				triageModal.classList.add("hidden");
				datasetState.activeIndex = -1;
				return;
			}
		}

		if (!triageModal || triageModal.classList.contains("hidden")) {
			return;
		}
		if (ev.key === "ArrowLeft" && !datasetState.isLoadingImage) {
			openTriageAt(Math.max(0, datasetState.activeIndex - 1));
		}
		if (ev.key === "ArrowRight" && !datasetState.isLoadingImage) {
			openTriageAt(
				Math.min(datasetState.items.length - 1, datasetState.activeIndex + 1),
			);
		}
		if (ev.key === "e" || ev.key === "E") {
			setBoxEditMode(!datasetState.editMode);
		}
		if (ev.key === "1" || ev.key === "p" || ev.key === "P") {
			relabelActiveItem("prey");
		}
		if (ev.key === "0") {
			relabelActiveItem("clear");
		}
	});

	// Initial status & config fetch
	loadUiConfig();
	fetchHealth(false);
});
