const API = "/api/v1";
let currentData = null;

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

		const addressResp = await fetch(
			`${API}/addresses/${encodeURIComponent(postcode)}`,
		);
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
		});
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

const BIN_SVG = `<svg viewBox="0 0 64 80" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">
  <rect x="12" y="18" width="40" height="54" rx="3" fill="#546E7A" stroke="#37474F" stroke-width="2"/>
  <rect x="16" y="24" width="4" height="40" rx="1" fill="#455A64"/>
  <rect x="24" y="24" width="4" height="40" rx="1" fill="#455A64"/>
  <rect x="36" y="24" width="4" height="40" rx="1" fill="#455A64"/>
  <rect x="44" y="24" width="4" height="40" rx="1" fill="#455A64"/>
  <rect x="8" y="12" width="48" height="8" rx="2" fill="#607D8B" stroke="#37474F" stroke-width="2"/>
  <rect x="24" y="6" width="16" height="8" rx="2" fill="#78909C" stroke="#37474F" stroke-width="2"/>
  <rect x="14" y="72" width="10" height="4" rx="2" fill="#37474F"/>
  <rect x="40" y="72" width="10" height="4" rx="2" fill="#37474F"/>
</svg>`;

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
	// Priority 1: explicit colour word in the bin name
	const colourMatch = t.match(
		/\b(black|blue|green|brown|red|purple|grey|gray|orange|pink|white)\b/,
	);
	if (colourMatch) {
		const c = colourMatch[1] === "gray" ? "grey" : colourMatch[1];
		// Map explicit colours to our three categories
		if (c === "brown") return "brown";
		if (c === "green" || c === "blue") return "green";
		// black, grey, red, purple, orange, pink, white → default grey
		return "grey";
	}
	// Priority 2: infer from waste category
	if (/food|organic|compost|garden/.test(t)) return "brown";
	if (/recycl|paper|card|plastic|glass|can|mixed dry/.test(t)) return "green";
	if (/general|residual|refuse|rubbish|domestic|non.?recycl/.test(t))
		return "grey";
	// Default
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

function renderResults(addr, data) {
	const section = $("#results");
	const council = currentData.council_name || data.council;
	const councilId = currentData.council_id;

	const calParams = new URLSearchParams({
		council: councilId,
		postcode: addr.postcode,
	});
	const calPath = `${API}/calendar/${encodeURIComponent(addr.uprn)}?${calParams}`;
	const calUrl = `webcal://${window.location.host}${calPath}`;

	const PASSTHROUGH_ICS = {
		ukbcd_google_public_calendar_council:
			"https://calendar.google.com/calendar/ical/0d775884b4db6a7bae5204f06dae113c1a36e505b25991ebc27c6bd42edf5b5e%40group.calendar.google.com/public/basic.ics",
	};
	const subscribeUrl = PASSTHROUGH_ICS[councilId]
		? PASSTHROUGH_ICS[councilId].replace(/^https:/, "webcal:")
		: calUrl;

	if (data.collections.length === 0) {
		section.innerHTML = `
			<div>
				<strong>${addr.full_address}</strong>
				<div>
			<strong>${addr.full_address}</strong>
			<div class="collection-date">${council}</div>
		</div>
			</div>
			<p>No upcoming collections found.</p>
			<div class="results-actions">
				<a href="${subscribeUrl}" class="action-btn">Add to Calendar</a>
				<button class="action-btn outline" id="report-btn" type="button">Report wrong answer</button>
				<span id="report-status" role="status" aria-live="polite"></span>
			</div>`;
		show("results");
		section.tabIndex = -1;
		section.focus();
		return;
	}

	// Filter out past dates for display
	const futureCollections = data.collections.filter((c) => isToday(c.date));

	// Group by type, preserving date order — show next upcoming per type
	const groups = new Map();
	for (const c of futureCollections) {
		if (!groups.has(c.type)) groups.set(c.type, []);
		groups.get(c.type).push(c);
	}

	// Cards: one per type showing next date
	let cards = "";
	for (const [type, items] of groups) {
		const next = items[0];
		const rel = relativeDay(next.date);
		const colour = binColour(type);
		const displayType = toTitleCase(type);
		cards += `
			<div class="bin-group" data-bin-colour="${colour}" role="group" aria-label="${displayType} collection">
				<div class="bin-next">
					<div class="bin-icon">${BIN_SVG}</div>
					<div class="bin-info">
						<span class="bin-type">${displayType}</span>
						<span class="bin-date">${formatDate(next.date)}</span>
						<span class="bin-relative">${rel.text}</span>
					</div>
				</div>
			</div>`;
	}

	// Single accordion with all future dates across all types
	const allFuture = [];
	for (const [type, items] of groups) {
		for (const c of items.slice(1)) {
			allFuture.push({ type, date: c.date });
		}
	}
	allFuture.sort((a, b) => a.date.localeCompare(b.date));

	let accordionHtml = "";
	if (allFuture.length > 0) {
		const lis = allFuture
			.map(
				(c) =>
					`<li><span class="all-dates-type">${toTitleCase(c.type)}</span><span>${formatDate(c.date)}</span></li>`,
			)
			.join("");
		accordionHtml = `
			<details class="all-dates">
				<summary>All upcoming dates (${allFuture.length})</summary>
				<ul class="all-dates-list">${lis}</ul>
			</details>`;
	}

	section.innerHTML = `
		<div>
			<strong>${addr.full_address}</strong>
			<div class="collection-date">${council}</div>
		</div>
		${cards}
		${accordionHtml}
		<div class="results-actions">
			<a href="${subscribeUrl}" class="action-btn">Add to Calendar</a>
			<button class="action-btn outline" id="report-btn" type="button">Report wrong answer</button>
			<span id="report-status" role="status" aria-live="polite"></span>
		</div>`;
	show("results");
	section.tabIndex = -1;
	section.focus();

	const reportBtn = $("#report-btn");
	if (reportBtn) {
		reportBtn.addEventListener("click", async () => {
			reportBtn.disabled = true;
			reportBtn.textContent = "Sending...";
			try {
				const resp = await fetch(`${API}/report`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						postcode: addr.postcode,
						address: addr.full_address,
						uprn: addr.uprn,
						council: councilId,
						collections: data.collections,
					}),
				});
				const status = $("#report-status");
				if (resp.ok) {
					status.textContent = "Thanks, report sent.";
					status.className = "report-sent";
				} else {
					status.textContent = "Failed to send report.";
					status.style.color = "#e53935";
					reportBtn.disabled = false;
					reportBtn.textContent = "Report wrong answer";
				}
			} catch {
				reportBtn.disabled = false;
				reportBtn.textContent = "Report wrong answer";
			}
		});
	}
}
