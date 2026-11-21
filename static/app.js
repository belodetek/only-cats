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
		repoUrl: "",
	};

	const datasetState = {
		filter: "all",
		items: [],
		activeIndex: -1,
		editMode: false,
		selectedBoxIndex: 0,
		defaultDrawClass: 1,
		drag: null,
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

	function updateTriageSubtitle() {
		const item = datasetState.items[datasetState.activeIndex];
		if (!item) {
			return;
		}
		const selInfo =
			datasetState.editMode && item.boxes.length
				? ` · Selected #${datasetState.selectedBoxIndex + 1} (${item.boxes[datasetState.selectedBoxIndex]?.cls === 1 ? "Prey" : "Cat"})`
				: "";
		triageSubtitle.textContent = `${datasetState.activeIndex + 1} of ${datasetState.items.length} · ${item.boxes.length} box(es)${selInfo}`;
		if (btnRemoveSelectedBox) {
			btnRemoveSelectedBox.disabled = item.boxes.length === 0;
		}
		if (boxEditHint) {
			const clsName = datasetState.defaultDrawClass === 1 ? "Prey" : "Cat";
			boxEditHint.textContent = `Draw mode: ${clsName} · Drag empty area or handles`;
		}
	}

	function renderSvgBoxes(boxes) {
		const list = boxes || [];
		if (datasetState.selectedBoxIndex >= list.length) {
			datasetState.selectedBoxIndex = Math.max(0, list.length - 1);
		}
		triageSvg.innerHTML = list
			.map((box, idx) => {
				const isPrey = box.cls === 1;
				const isSelected =
					datasetState.editMode && idx === datasetState.selectedBoxIndex;
				const stroke = isPrey ? "#f43f5e" : "#34d399";
				const fill = isSelected
					? isPrey
						? "rgba(244, 63, 94, 0.16)"
						: "rgba(52, 211, 153, 0.16)"
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
		const item = datasetState.items[datasetState.activeIndex];
		if (item) {
			renderSvgBoxes(item.boxes);
		}
	}

	function openTriageAt(index) {
		if (index < 0 || index >= datasetState.items.length) {
			triageModal.classList.add("hidden");
			datasetState.activeIndex = -1;
			datasetState.drag = null;
			return;
		}
		datasetState.activeIndex = index;
		datasetState.selectedBoxIndex = 0;
		datasetState.drag = null;
		const item = datasetState.items[index];
		triageTitle.textContent = item.filename;
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
		if (reveal) {
			datasetPanel.classList.remove("hidden");
			datasetGrid.innerHTML =
				'<div class="col-span-full text-center text-xs text-slate-400 py-6">Loading captures...</div>';
			datasetPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
		}
		try {
			const resp = await fetch(
				`/ui/dataset/items?filter=${encodeURIComponent(datasetState.filter)}&limit=60`,
				{ cache: "no-store" },
			);
			if (!resp.ok) {
				throw new Error(`HTTP ${resp.status}`);
			}
			const payload = await resp.json();
			datasetState.items = payload.items || [];
			if (datasetCountBadge && payload.counts) {
				datasetCountBadge.textContent = String(payload.counts.all ?? 0);
			}
			renderDatasetGrid();
		} catch (err) {
			if (reveal) {
				datasetGrid.innerHTML = `<div class="col-span-full text-center text-xs text-rose-400 py-6">Failed to load captures (${err.message}).</div>`;
				showToast(`Failed to load training images: ${err.message}`, "error");
			}
		}
	}

	async function persistBoxes(item, nextBoxes, advanceAfter = false) {
		const resp = await fetch(
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
		item.has_prey = updated.boxes.some((b) => b.cls === 1);
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
		if (mode === "cat") {
			datasetState.defaultDrawClass = 0;
		} else if (mode === "prey") {
			datasetState.defaultDrawClass = 1;
		}

		let nextBoxes = [];
		if (mode === "cat") {
			if (datasetState.editMode && item.boxes.length) {
				nextBoxes = item.boxes.map((b, i) =>
					i === datasetState.selectedBoxIndex ? { ...b, cls: 0 } : b,
				);
			} else {
				nextBoxes = item.boxes.length
					? item.boxes.map((b) => ({ ...b, cls: 0 }))
					: [{ cls: 0, x: 0.5, y: 0.5, w: 0.5, h: 0.5 }];
			}
		} else if (mode === "prey") {
			if (datasetState.editMode && item.boxes.length) {
				nextBoxes = item.boxes.map((b, i) =>
					i === datasetState.selectedBoxIndex ? { ...b, cls: 1 } : b,
				);
			} else {
				nextBoxes = item.boxes.length
					? item.boxes.map((b, i) => ({ ...b, cls: i === 0 ? 1 : b.cls }))
					: [{ cls: 1, x: 0.5, y: 0.5, w: 0.35, h: 0.35 }];
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

		if (btnToggleBoxEdit) {
			btnToggleBoxEdit.addEventListener("click", () =>
				setBoxEditMode(!datasetState.editMode),
			);
		}
		if (btnRemoveSelectedBox) {
			btnRemoveSelectedBox.addEventListener("click", removeSelectedBox);
		}

		// Interactive SVG pointer gestures (draw new box, move box, resize corners)
		triageSvg.addEventListener("pointerdown", (ev) => {
			if (!datasetState.editMode) {
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

		document
			.getElementById("btn-close-triage")
			.addEventListener("click", () => {
				setBoxEditMode(false);
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

		// Mobile horizontal swipe navigation in triage modal (disabled while editing boxes)
		let touchStartX = 0;
		triageStage.addEventListener(
			"touchstart",
			(ev) => {
				if (datasetState.editMode) {
					return;
				}
				touchStartX = ev.changedTouches[0].screenX;
			},
			{ passive: true },
		);
		triageStage.addEventListener(
			"touchend",
			(ev) => {
				if (datasetState.editMode) {
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
			if (ev.key === "e" || ev.key === "E") {
				setBoxEditMode(!datasetState.editMode);
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
				setBoxEditMode(false);
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
