const API = "/api/v1";
let currentData = null;

let turnstileToken = null;
window.onTurnstileOk = (t) => {
	turnstileToken = t;
};
window.onTurnstileExpired = () => {
	turnstileToken = null;
	if (window.turnstile) window.turnstile.reset();
};
window.onTurnstileError = () => {
	turnstileToken = null;
};

async function getTurnstileToken() {
	if (!window.turnstile) return null;
	if (turnstileToken) return turnstileToken;
	return await new Promise((resolve) => {
		const start = Date.now();
		const poll = () => {
			if (turnstileToken) return resolve(turnstileToken);
			if (Date.now() - start > 8000) return resolve(null);
			setTimeout(poll, 150);
		};
		try {
			window.turnstile.execute();
		} catch {}
		poll();
	});
}

const $ = (sel) => document.querySelector(sel);

function show(id) {
	$(`#${id}`).classList.remove("hidden");
}
function hide(id) {
	$(`#${id}`).classList.add("hidden");
}
function showError(msg) {
	$("#error").textContent = msg;
	show("error");
}
function clearError() {
	hide("error");
}

$("#postcode-form").addEventListener("submit", async (e) => {
	e.preventDefault();
	clearError();
	hide("results");
	const postcode = $("#postcode").value.trim();
	if (!postcode) return;

	const btn = e.target.querySelector("button");
	btn.setAttribute("aria-busy", "true");

	try {
		const councilResp = await fetch(
			`${API}/council/${encodeURIComponent(postcode)}`,
		);

		let council_id = null;
		let council_name = null;
		if (councilResp.ok) {
			const councilData = await councilResp.json();
			council_id = councilData.council_id;
			council_name = councilData.council_name;
		} else {
			const err = await councilResp.json().catch(() => ({}));
			showError(
				err.detail ||
					`We don't support this council yet (${councilResp.status}).`,
			);
			return;
		}

		if (!council_id) {
			showError(
				council_name
					? `${council_name} council is not supported yet.`
					: "We couldn't determine a supported council for that postcode.",
			);
			return;
		}

		const token = await getTurnstileToken();
		if (window.turnstile && !token) {
			showError(
				"Could not verify your browser. Please reload the page and try again.",
			);
			return;
		}
		const addressResp = await fetch(
			`${API}/addresses/${encodeURIComponent(postcode)}`,
			token ? { headers: { "X-Turnstile-Token": token } } : {},
		);
		turnstileToken = null;
		if (window.turnstile) {
			try {
				window.turnstile.reset();
			} catch {}
		}
		if (!addressResp.ok) {
			const err = await addressResp.json().catch(() => ({}));
			throw new Error(
				err.detail || `Address lookup failed (${addressResp.status})`,
			);
		}
		const { addresses } = await addressResp.json();

		currentData = { addresses, council_id, council_name };

		if (addresses.length === 0) {
			showError("No addresses found for that postcode.");
			return;
		}

		const select = $("#address-select");
		select.innerHTML = '<option value="">-- Choose address --</option>';
		addresses.forEach((addr, i) => {
			const opt = document.createElement("option");
			opt.value = i;
			opt.textContent = addr.full_address;
			select.appendChild(opt);
		});

		hide("step-postcode");
		show("step-address");
		$("#address-select").focus();
	} catch (err) {
		showError(err.message);
	} finally {
		btn.removeAttribute("aria-busy");
	}
});

$("#address-select").addEventListener("change", (e) => {
	$("#address-btn").disabled = !e.target.value;
});

$("#back-btn").addEventListener("click", () => {
	hide("step-address");
	hide("results");
	show("step-postcode");
	$("#postcode").focus();
});

$("#address-btn").addEventListener("click", async () => {
	clearError();
	hide("results");
	const idx = $("#address-select").value;
	if (!idx || !currentData) return;

	const addr = currentData.addresses[idx];
	const councilId = currentData.council_id;

	if (!councilId) {
		showError(
			"Could not determine council for this postcode. Council may not be supported yet.",
		);
		return;
	}

	const btn = $("#address-btn");
	btn.setAttribute("aria-busy", "true");

	try {
		const params = new URLSearchParams({
			council: councilId,
			postcode: addr.postcode,
			address: addr.full_address,
		});
		if (addr.house_number_or_name)
			params.set("house_number", addr.house_number_or_name);
		if (addr.street) params.set("street", addr.street);
		const resp = await fetch(
			`${API}/lookup/${encodeURIComponent(addr.uprn)}?${params}`,
		);
		if (!resp.ok) {
			const err = await resp.json().catch(() => ({}));
			throw new Error(err.detail || `Lookup failed (${resp.status})`);
		}
		const data = await resp.json();
		renderResults(addr, data);
	} catch (err) {
		showError(err.message);
	} finally {
		btn.removeAttribute("aria-busy");
	}
});

const tpl = (id) => document.getElementById(id).content.cloneNode(true);

function formatDate(dateStr) {
	const d = new Date(dateStr + "T00:00:00");
	return d.toLocaleDateString("en-GB", {
		weekday: "long",
		day: "numeric",
		month: "long",
		year: "numeric",
	});
}

function relativeDay(dateStr) {
	const today = new Date();
	today.setHours(0, 0, 0, 0);
	const d = new Date(dateStr + "T00:00:00");
	const diff = Math.round((d - today) / 86400000);
	if (diff < 0)
		return { text: `${-diff} day${diff === -1 ? "" : "s"} ago`, past: true };
	if (diff === 0) return { text: "Today", past: false };
	if (diff === 1) return { text: "Tomorrow", past: false };
	return { text: `In ${diff} days`, past: false };
}

function binColour(type) {
	const t = type.toLowerCase();
	const colourMatch = t.match(
		/\b(black|blue|green|brown|red|purple|grey|gray|orange|pink|white)\b/,
	);
	if (colourMatch) {
		const c = colourMatch[1] === "gray" ? "grey" : colourMatch[1];
		if (c === "brown") return "brown";
		if (c === "green" || c === "blue") return "green";
		return "grey";
	}
	if (/food|organic|compost|garden/.test(t)) return "brown";
	if (/recycl|paper|card|plastic|glass|can|mixed dry/.test(t)) return "green";
	if (/general|residual|refuse|rubbish|domestic|non.?recycl/.test(t))
		return "grey";
	return "grey";
}

function toTitleCase(str) {
	return str.replace(
		/\b\w+/g,
		(w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase(),
	);
}

function isToday(dateStr) {
	const today = new Date();
	today.setHours(0, 0, 0, 0);
	const d = new Date(dateStr + "T00:00:00");
	return d >= today;
}

function renderHeader(address, council) {
	const frag = tpl("tpl-results-header");
	frag.querySelector('[data-slot="address"]').textContent = address;
	frag.querySelector('[data-slot="council"]').textContent = council;
	return frag;
}

function renderCard(type, next) {
	const displayType = toTitleCase(type);
	const frag = tpl("tpl-bin-card");
	const group = frag.querySelector(".bin-group");
	group.dataset.binColour = binColour(type);
	group.setAttribute("aria-label", `${displayType} collection`);
	frag.querySelector('[data-slot="type"]').textContent = displayType;
	frag.querySelector('[data-slot="date"]').textContent = formatDate(next.date);
	frag.querySelector('[data-slot="relative"]').textContent = relativeDay(
		next.date,
	).text;
	return frag;
}

function renderAccordion(items) {
	const frag = tpl("tpl-accordion");
	frag.querySelector('[data-slot="count"]').textContent = items.length;
	const ul = frag.querySelector(".all-dates-list");
	for (const c of items) {
		const li = tpl("tpl-accordion-item");
		li.querySelector('[data-slot="type"]').textContent = toTitleCase(c.type);
		li.querySelector('[data-slot="date"]').textContent = formatDate(c.date);
		ul.appendChild(li);
	}
	return frag;
}

function renderActions(icsUrl) {
	const frag = tpl("tpl-actions");
	const webcalUrl = icsUrl.replace(/^https:/, "webcal:");
	const googleUrl = `https://calendar.google.com/calendar/render?cid=${webcalUrl}`;
	const outlookUrl = `https://outlook.live.com/calendar/0/addcalendar?url=${encodeURIComponent(icsUrl)}&name=${encodeURIComponent("Bin collections")}`;
	frag.querySelector('[data-slot="apple"]').href = webcalUrl;
	frag.querySelector('[data-slot="google"]').href = googleUrl;
	frag.querySelector('[data-slot="outlook"]').href = outlookUrl;
	return frag;
}

function attachCopyHandler(icsUrl) {
	const btn = document.getElementById("copy-btn");
	const label = document.getElementById("copy-btn-label");
	if (!btn || !label) return;
	btn.addEventListener("click", async () => {
		try {
			await navigator.clipboard.writeText(icsUrl);
			label.textContent = "Copied!";
		} catch {
			const ta = document.createElement("textarea");
			ta.value = icsUrl;
			ta.style.position = "fixed";
			ta.style.opacity = "0";
			document.body.appendChild(ta);
			ta.select();
			try {
				document.execCommand("copy");
				label.textContent = "Copied!";
			} catch {
				label.textContent = "Copy failed";
			}
			ta.remove();
		}
		setTimeout(() => {
			label.textContent = "ICS";
		}, 2000);
	});
}

const PASSTHROUGH_ICS = {
	ukbcd_google_public_calendar_council:
		"https://calendar.google.com/calendar/ical/0d775884b4db6a7bae5204f06dae113c1a36e505b25991ebc27c6bd42edf5b5e%40group.calendar.google.com/public/basic.ics",
};

function icsUrlFor(councilId, addr) {
	if (PASSTHROUGH_ICS[councilId]) return PASSTHROUGH_ICS[councilId];
	const params = new URLSearchParams({
		council: councilId,
		postcode: addr.postcode,
		address: addr.full_address,
	});
	if (addr.house_number_or_name)
		params.set("house_number", addr.house_number_or_name);
	if (addr.street) params.set("street", addr.street);
	return `${window.location.origin}${API}/calendar/${encodeURIComponent(addr.uprn)}?${params}`;
}

function renderResults(addr, data) {
	const section = $("#results");
	const council = currentData.council_name || data.council;
	const councilId = currentData.council_id;
	const icsUrl = icsUrlFor(councilId, addr);

	section.replaceChildren();
	section.appendChild(renderHeader(addr.full_address, council));

	const futureCollections = data.collections.filter((c) => isToday(c.date));
	const groups = new Map();
	for (const c of futureCollections) {
		if (!groups.has(c.type)) groups.set(c.type, []);
		groups.get(c.type).push(c);
	}

	if (groups.size === 0) {
		section.appendChild(tpl("tpl-empty-state"));
	} else {
		for (const [type, items] of groups) {
			section.appendChild(renderCard(type, items[0]));
		}

		const allFuture = [];
		for (const [type, items] of groups) {
			for (const c of items.slice(1)) allFuture.push({ type, date: c.date });
		}
		allFuture.sort((a, b) => a.date.localeCompare(b.date));
		if (allFuture.length > 0) section.appendChild(renderAccordion(allFuture));
	}

	section.appendChild(renderActions(icsUrl));
	show("results");
	section.tabIndex = -1;
	section.focus();

	attachCopyHandler(icsUrl);
}
