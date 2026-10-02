const API = "/api/v2";
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
		const token = await getTurnstileToken();
		if (window.turnstile && !token) {
			showError(
				"Could not verify your browser. Please reload the page and try again.",
			);
			return;
		}
		const resp = await fetch(
			`${API}/find?${new URLSearchParams({ postcode })}`,
			token ? { headers: { "X-Turnstile-Token": token } } : {},
		);
		turnstileToken = null;
		if (window.turnstile) {
			try {
				window.turnstile.reset();
			} catch {}
		}
		if (!resp.ok) {
			const err = await resp.json().catch(() => ({}));
			showError(err.detail || `Postcode lookup failed (${resp.status}).`);
			return;
		}
		const { council, council_name, deeplink, addresses } = await resp.json();

		if (!council) {
			if (deeplink) {
				renderDeeplink(deeplink);
				return;
			}
			showError(
				council_name
					? `${council_name} council is not supported yet.`
					: "We couldn't determine a supported council for that postcode.",
			);
			return;
		}

		if (addresses === null) {
			showError(
				"Could not verify your browser. Please reload the page and try again.",
			);
			return;
		}

		currentData = { addresses, council, council_name };

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
	const council = currentData.council;

	if (!council) {
		showError(
			"Could not determine council for this postcode. Council may not be supported yet.",
		);
		return;
	}

	const btn = $("#address-btn");
	btn.setAttribute("aria-busy", "true");

	try {
		const params = new URLSearchParams({
			postcode: addr.postcode,
			address: addr.full_address,
		});
		if (addr.house_number_or_name)
			params.set("house_number", addr.house_number_or_name);
		if (addr.street) params.set("street", addr.street);
		const resp = await fetch(
			`${API}/${encodeURIComponent(council)}/view/${encodeURIComponent(addr.uprn)}?${params}`,
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

// Stream themes by the API's icon (api/councils/_base/collection.py Icon),
// for labels that name no bin colour: garden/food/compost brown, recycling
// streams green, anything else grey.
const STREAM_COLOURS = {
	"mdi:flower": "brown",
	"mdi:food-apple": "brown",
	"mdi:leaf": "brown",
	"mdi:recycle": "green",
	"mdi:recycle-variant": "green",
	"mdi:package-variant": "green",
	"mdi:bottle-soda": "green",
	"mdi:nail": "green",
};

// The colour the API read off the council's label, else the stream's theme.
function binColour(type) {
	if (type.colour) return type.colour.toLowerCase();
	return STREAM_COLOURS[type.icon] || "grey";
}

function dateWithHoliday(c) {
	const d = formatDate(c.date);
	return c.holiday ? `${d} (${c.holiday})` : d;
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

function renderCard(label, next) {
	const displayType = toTitleCase(label);
	const frag = tpl("tpl-bin-card");
	const group = frag.querySelector(".bin-group");
	group.dataset.binColour = binColour(next.type);
	group.setAttribute("aria-label", `${displayType} collection`);
	frag.querySelector('[data-slot="type"]').textContent = displayType;
	frag.querySelector('[data-slot="date"]').textContent = dateWithHoliday(next);
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
		li.querySelector("li").dataset.binColour = binColour(c.type);
		li.querySelector('[data-slot="type"]').textContent = toTitleCase(
			c.type.label,
		);
		li.querySelector('[data-slot="date"]').textContent = dateWithHoliday(c);
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

// council is the LAD code /find returned (e.g. E06000001).
function icsUrlFor(council, addr) {
	const params = new URLSearchParams({
		postcode: addr.postcode,
		address: addr.full_address,
	});
	if (addr.house_number_or_name)
		params.set("house_number", addr.house_number_or_name);
	if (addr.street) params.set("street", addr.street);
	return `${window.location.origin}${API}/${encodeURIComponent(council)}/subscribe/${encodeURIComponent(addr.uprn)}?${params}`;
}

function renderDeeplink(deeplink) {
	const section = $("#results");
	section.replaceChildren();
	const frag = tpl("tpl-deeplink");
	frag.querySelector('[data-slot="council"]').textContent =
		deeplink.council_name;
	frag.querySelector('[data-slot="blocker"]').textContent =
		deeplink.blocker_label;
	frag.querySelector('[data-slot="reason"]').textContent = deeplink.reason;
	frag.querySelector('[data-slot="link"]').href = deeplink.url;
	section.appendChild(frag);
	show("results");
}

function renderResults(addr, data) {
	const section = $("#results");
	if (data.deeplink) {
		renderDeeplink(data.deeplink);
		return;
	}
	const council = currentData.council_name || data.council;
	const icsUrl = icsUrlFor(currentData.council, addr);

	section.replaceChildren();
	section.appendChild(renderHeader(addr.full_address, council));

	const futureCollections = data.dates.filter((c) => isToday(c.date));
	const groups = new Map();
	for (const c of futureCollections) {
		if (!groups.has(c.type.label)) groups.set(c.type.label, []);
		groups.get(c.type.label).push(c);
	}

	if (groups.size === 0) {
		section.appendChild(tpl("tpl-empty-state"));
	} else {
		for (const [label, items] of groups) {
			section.appendChild(renderCard(label, items[0]));
		}

		const allFuture = [];
		for (const items of groups.values()) allFuture.push(...items.slice(1));
		allFuture.sort((a, b) => a.date.localeCompare(b.date));
		if (allFuture.length > 0) section.appendChild(renderAccordion(allFuture));
	}

	section.appendChild(renderActions(icsUrl));
	show("results");
	section.tabIndex = -1;
	section.focus();

	attachCopyHandler(icsUrl);
}
