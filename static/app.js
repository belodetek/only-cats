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

	const btnDataset = document.getElementById("btn-dataset");
	const btnCloseDataset = document.getElementById("btn-close-dataset");
	const datasetPanel = document.getElementById("dataset-panel");
	const datasetGrid = document.getElementById("dataset-grid");
	const datasetCountBadge = document.getElementById("dataset-count-badge");

	const triageModal = document.getElementById("triage-modal");
	const triageStage = document.getElementById("triage-stage");
	const triageImg = document.getElementById("triage-img");
	const triageSvg = document.getElementById("triage-svg");
	const triageTitle = document.getElementById("triage-title");
	const triageSubtitle = document.getElementById("triage-subtitle");

	const footerMeta = document.getElementById("footer-meta");
	const footerRepoLink = document.getElementById("footer-repo-link");
	const currentYear = new Date().getFullYear();

	const footerState = {
		appVersion: "",
		firmwareVersion: "",
		repoUrl: "",
	};

	const datasetState = {
		filter: "all",
		items: [],
		activeIndex: -1,
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
				const fwMismatch = Boolean(
					fw.version && fw.local_version && fw.version !== fw.local_version,
				);
				const fwBaseLabel = fw.version
					? `${fw.version}${fw.sha256 ? ` (${fw.sha256})` : ""}`
					: "Unknown";
				const fwLabel = fwMismatch
					? `${fwBaseLabel} (local: ${fw.local_version})`
					: fwBaseLabel;
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
					[
						"YOLO Model",
						data.model_loaded ? "Loaded" : "Missing",
						"text-slate-100",
					],
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

	function renderSvgBoxes(boxes) {
		triageSvg.innerHTML = (boxes || [])
			.map((box) => {
				const isPrey = box.cls === 1;
				const stroke = isPrey ? "#f43f5e" : "#34d399";
				const x = Math.max(0, box.x - box.w / 2);
				const y = Math.max(0, box.y - box.h / 2);
				return `<rect x="${x}" y="${y}" width="${box.w}" height="${box.h}" fill="none" stroke="${stroke}" stroke-width="0.008" />`;
			})
			.join("");
	}

	function openTriageAt(index) {
		if (index < 0 || index >= datasetState.items.length) {
			triageModal.classList.add("hidden");
			datasetState.activeIndex = -1;
			return;
		}
		datasetState.activeIndex = index;
		const item = datasetState.items[index];
		triageTitle.textContent = item.filename;
		triageSubtitle.textContent = `${index + 1} of ${datasetState.items.length} · ${item.boxes.length} box(es)`;
		triageImg.src = item.image_url;
		renderSvgBoxes(item.boxes);
		triageModal.classList.remove("hidden");
	}

	function renderDatasetGrid() {
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
						? '<span class="px-1.5 py-0.5 rounded bg-emerald-600/90 text-white text-[10px]">Cat</span>'
						: '<span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">Empty</span>';
				return `
          <button type="button" data-ds-idx="${idx}" class="group relative aspect-video rounded-xl overflow-hidden bg-slate-950 border border-slate-800 text-left">
            <img src="${item.thumb_url}" loading="lazy" alt="${item.filename}" class="w-full h-full object-cover" />
            <div class="absolute inset-x-0 bottom-0 p-1.5 bg-gradient-to-t from-slate-950/90 to-transparent flex items-center justify-between">
              ${badge}
              <span class="text-[10px] text-slate-300 truncate max-w-[65%]">${item.filename}</span>
            </div>
          </button>`;
			})
			.join("");
	}

	async function loadDataset(reveal = false) {
		try {
			const resp = await fetch(
				`/ui/dataset/items?filter=${encodeURIComponent(datasetState.filter)}&limit=60`,
				{ cache: "no-store" },
			);
			if (!resp.ok) {
				return;
			}
			const payload = await resp.json();
			datasetState.items = payload.items || [];
			if (datasetCountBadge && payload.counts) {
				datasetCountBadge.textContent = String(payload.counts.all ?? 0);
			}
			renderDatasetGrid();
			if (reveal) {
				datasetPanel.classList.remove("hidden");
			}
		} catch (_err) {
			// Ignore if dataset endpoint unavailable
		}
	}

	async function relabelActiveItem(mode) {
		const item = datasetState.items[datasetState.activeIndex];
		if (!item) {
			return;
		}
		let nextBoxes = [];
		if (mode === "cat") {
			nextBoxes = item.boxes.length
				? item.boxes.map((b) => ({ ...b, cls: 0 }))
				: [{ cls: 0, x: 0.5, y: 0.5, w: 0.5, h: 0.5 }];
		} else if (mode === "prey") {
			nextBoxes = item.boxes.length
				? item.boxes.map((b, i) => ({ ...b, cls: i === 0 ? 1 : b.cls }))
				: [{ cls: 1, x: 0.5, y: 0.5, w: 0.35, h: 0.35 }];
		}
		const resp = await fetch(
			`/ui/dataset/labels/${encodeURIComponent(item.filename)}`,
			{
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ boxes: nextBoxes }),
			},
		);
		if (resp.ok) {
			const updated = await resp.json();
			item.boxes = updated.boxes;
			item.has_prey = updated.boxes.some((b) => b.cls === 1);
			renderSvgBoxes(item.boxes);
			renderDatasetGrid();
			openTriageAt(
				Math.min(datasetState.activeIndex + 1, datasetState.items.length - 1),
			);
		}
	}

	async function deleteActiveItem() {
		const item = datasetState.items[datasetState.activeIndex];
		if (!item) {
			return;
		}
		const resp = await fetch(
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
			);
		}
	}

	btnLock.addEventListener("click", () =>
		sendAdminCommand(
			"/ui/lock",
			"Admin override active: Door forced LOCKED.",
			"lock",
		),
	);

	btnUnlock.addEventListener("click", () =>
		sendAdminCommand(
			"/ui/unlock",
			"Admin override active: Door forced UNLOCKED.",
			"unlock",
		),
	);

	btnInfo.addEventListener("click", () => fetchHealth(true));

	btnCloseInfo.addEventListener("click", () => {
		healthPanel.classList.add("hidden");
	});

	btnCamera.addEventListener("click", () => {
		window.location.assign("/cctv1/");
	});

	if (btnDataset) {
		btnDataset.addEventListener("click", () => loadDataset(true));
		btnCloseDataset.addEventListener("click", () =>
			datasetPanel.classList.add("hidden"),
		);
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
				openTriageAt(Number(card.dataset.dsIdx));
			}
		});

		document
			.getElementById("btn-close-triage")
			.addEventListener("click", () => {
				triageModal.classList.add("hidden");
				datasetState.activeIndex = -1;
			});
		document
			.getElementById("btn-triage-prev")
			.addEventListener("click", () =>
				openTriageAt(Math.max(0, datasetState.activeIndex - 1)),
			);
		document
			.getElementById("btn-triage-next")
			.addEventListener("click", () =>
				openTriageAt(
					Math.min(datasetState.items.length - 1, datasetState.activeIndex + 1),
				),
			);
		document
			.getElementById("btn-label-cat")
			.addEventListener("click", () => relabelActiveItem("cat"));
		document
			.getElementById("btn-label-prey")
			.addEventListener("click", () => relabelActiveItem("prey"));
		document
			.getElementById("btn-label-clear")
			.addEventListener("click", () => relabelActiveItem("clear"));
		document
			.getElementById("btn-triage-delete")
			.addEventListener("click", deleteActiveItem);

		// Mobile horizontal swipe navigation in triage modal
		let touchStartX = 0;
		triageStage.addEventListener(
			"touchstart",
			(ev) => {
				touchStartX = ev.changedTouches[0].screenX;
			},
			{ passive: true },
		);
		triageStage.addEventListener(
			"touchend",
			(ev) => {
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

		// Desktop keyboard shortcuts while modal is open
		document.addEventListener("keydown", (ev) => {
			if (triageModal.classList.contains("hidden")) {
				return;
			}
			if (ev.key === "ArrowLeft") {
				openTriageAt(Math.max(0, datasetState.activeIndex - 1));
			}
			if (ev.key === "ArrowRight") {
				openTriageAt(
					Math.min(datasetState.items.length - 1, datasetState.activeIndex + 1),
				);
			}
			if (ev.key === "1") {
				relabelActiveItem("cat");
			}
			if (ev.key === "2") {
				relabelActiveItem("prey");
			}
			if (ev.key === "0") {
				relabelActiveItem("clear");
			}
			if (ev.key === "Escape") {
				triageModal.classList.add("hidden");
				datasetState.activeIndex = -1;
			}
		});

		loadDataset(false);
	}

	// Initial status & config fetch
	loadUiConfig();
	fetchHealth(false);
});
