from __future__ import annotations

from htpy import (
    body,
    button,
    fieldset,
    form,
    h1,
    head,
    html,
    input,
    label,
    link,
    main,
    meta,
    option,
    p,
    script,
    section,
    select,
    style,
    title,
)
from markupsafe import Markup

_CSS = """\
.collection { display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 0; }
.collection-icon { font-size: 1.5rem; }
.collection-date { color: var(--pico-muted-color); font-size: 0.9rem; }
#error { color: var(--pico-del-color); }
.hidden { display: none; }
#results article { margin-top: 1rem; }
"""

_JS = Markup("""\
const API = '/api/v1';
let currentData = null;

const $ = (sel) => document.querySelector(sel);

function show(id) { $(`#${id}`).classList.remove('hidden'); }
function hide(id) { $(`#${id}`).classList.add('hidden'); }
function showError(msg) { $('#error').textContent = msg; show('error'); }
function clearError() { hide('error'); }

$('#postcode-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    hide('results');
    const postcode = $('#postcode').value.trim();
    if (!postcode) return;

    const btn = e.target.querySelector('button');
    btn.setAttribute('aria-busy', 'true');

    try {
        const resp = await fetch(`${API}/addresses/${encodeURIComponent(postcode)}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `Lookup failed (${resp.status})`);
        }
        currentData = await resp.json();

        if (currentData.addresses.length === 0) {
            showError('No addresses found for that postcode.');
            return;
        }

        const select = $('#address-select');
        select.innerHTML = '<option value="">-- Choose address --</option>';
        currentData.addresses.forEach((addr, i) => {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = addr.full_address;
            select.appendChild(opt);
        });

        hide('step-postcode');
        show('step-address');
    } catch (err) {
        showError(err.message);
    } finally {
        btn.removeAttribute('aria-busy');
    }
});

$('#address-select').addEventListener('change', (e) => {
    $('#address-btn').disabled = !e.target.value;
});

$('#back-btn').addEventListener('click', () => {
    hide('step-address');
    hide('results');
    show('step-postcode');
});

$('#address-btn').addEventListener('click', async () => {
    clearError();
    hide('results');
    const idx = $('#address-select').value;
    if (!idx || !currentData) return;

    const addr = currentData.addresses[idx];
    const councilId = currentData.council_id;

    if (!councilId) {
        showError('Could not determine council for this postcode. Council may not be supported yet.');
        return;
    }

    const btn = $('#address-btn');
    btn.setAttribute('aria-busy', 'true');

    try {
        const params = new URLSearchParams({ council: councilId, postcode: addr.postcode });
        const resp = await fetch(`${API}/lookup/${encodeURIComponent(addr.uprn)}?${params}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `Lookup failed (${resp.status})`);
        }
        const data = await resp.json();
        renderResults(addr, data);
    } catch (err) {
        showError(err.message);
    } finally {
        btn.removeAttribute('aria-busy');
    }
});

function renderResults(addr, data) {
    const section = $('#results');
    const council = currentData.council_name || data.council;
    const councilId = currentData.council_id;

    if (data.collections.length === 0) {
        section.innerHTML = `
            <article>
                <header><strong>${addr.full_address}</strong></header>
                <p>No upcoming collections found.</p>
            </article>`;
        show('results');
        return;
    }

    const rows = data.collections.map(c => {
        const d = new Date(c.date);
        const dateStr = d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
        const icon = c.icon || '';
        return `<div class="collection">
            <span class="collection-icon">${icon}</span>
            <div>
                <strong>${c.type}</strong>
                <div class="collection-date">${dateStr}</div>
            </div>
        </div>`;
    }).join('');

    const calParams = new URLSearchParams({ council: councilId, postcode: addr.postcode });
    const calUrl = `${API}/calendar/${encodeURIComponent(addr.uprn)}?${calParams}`;

    section.innerHTML = `
        <article>
            <header>
                <strong>${addr.full_address}</strong>
                <div class="collection-date">${council}</div>
            </header>
            ${rows}
            <footer>
                <a href="${calUrl}" role="button" class="outline">Subscribe to calendar (.ics)</a>
            </footer>
        </article>`;
    show('results');
}
""")


def index_page() -> str:
    return str(
        html(lang="en", data_theme="light")[
            head[
                meta(charset="utf-8"),
                meta(name="viewport", content="width=device-width, initial-scale=1"),
                title["UK Bin Collections"],
                link(
                    rel="stylesheet",
                    href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css",
                ),
                style[_CSS],
            ],
            body[
                main(".container")[
                    h1["UK Bin Collections"],
                    p["Find your next bin collection dates."],
                    section("#step-postcode")[
                        form("#postcode-form")[
                            label(for_="postcode")["Enter your postcode"],
                            fieldset(role="group")[
                                input(
                                    "#postcode",
                                    type="text",
                                    name="postcode",
                                    placeholder="e.g. BR8 7RE",
                                    required=True,
                                    autofocus=True,
                                ),
                                button(type="submit")["Search"],
                            ],
                        ]
                    ],
                    section("#step-address.hidden")[
                        label(for_="address-select")["Select your address"],
                        select("#address-select")[
                            option(value="")["-- Choose address --"]
                        ],
                        button("#address-btn", disabled=True)["Get bin dates"],
                        button("#back-btn.outline.secondary")["Back"],
                    ],
                    section("#results.hidden"),
                    p("#error.hidden"),
                ],
                script[_JS],
            ],
        ]
    )
