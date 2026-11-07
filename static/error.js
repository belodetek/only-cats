(() => {
	const copy = {
		502: ["Bad Gateway", "The backend service is temporarily unreachable."],
		503: ["Service Unavailable", "The controller is restarting or overloaded."],
		504: ["Gateway Timeout", "The backend took too long to respond."],
	};
	const params = new URLSearchParams(window.location.search);
	const nav = performance.getEntriesByType("navigation")[0];
	const code =
		params.get("code") ||
		(nav && nav.responseStatus >= 400 ? String(nav.responseStatus) : "502");
	const [title, message] = copy[code] || [
		"Service Error",
		"The cat flap controller could not be reached.",
	];
	const codeEl = document.getElementById("err-code");
	const titleEl = document.getElementById("err-title");
	const msgEl = document.getElementById("err-msg");
	if (codeEl) codeEl.textContent = code;
	if (titleEl) titleEl.textContent = title;
	if (msgEl) msgEl.textContent = message;
})();
