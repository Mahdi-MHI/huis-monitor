// Huis monitor website. Reads the data files made by
// `python -m huis_monitor export` and asks PDOK where a town or address is.

const PDOK_SEARCH = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free";
const STORAGE_KEY = "huis-monitor-v3";
const ORIGIN_METRICS = ["origin_nl_pct", "origin_europe_pct"];
const ORIGIN_LABEL = "Residents with origin the Netherlands or the rest of Europe";

const STATUS = {
  good: { label: "Meets every limit", fill: "#0ca30c", opacity: 0.6 },
  warning: { label: "Data missing", fill: "#fab219", opacity: 0.65 },
  rejected: { label: "Rejected", fill: "#8f8f8a", opacity: 0.22 },
};

// Limits a first-time visitor starts with: at least half of the residents with
// origin the Netherlands or the rest of Europe, and for every type of crime the
// national average.
const DEFAULT_ORIGIN = { originMin: "50", originMax: "100" };

function defaultCrimeLimits(index) {
  const limits = {};
  for (const crime of index.crimes) {
    const average = index.average[crime.metric];
    if (average !== undefined && average !== null) limits[crime.metric] = String(average);
  }
  return limits;
}

const view = document.getElementById("view");
const store = { index: null, gemeenten: new Map(), search: null, searchKey: null, map: null };
const saved = readSaved();

// ---------- Small helpers ----------

function esc(text) {
  return String(text).replace(
    /[&<>"']/g,
    (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
}

function number(value, digits = 1) {
  if (value === undefined || value === null) return "n/a";
  return Number(value).toLocaleString("en-GB", { maximumFractionDigits: digits });
}

function percent(value) {
  return value === undefined || value === null ? "n/a" : `${number(value)}%`;
}

function euro(value) {
  return value === undefined || value === null ? "n/a" : `€ ${number(value, 0)}`;
}

// Share of residents with origin the Netherlands or another European country.
// The two published shares are rounded, so their sum can pass 100 by a fraction.
function originShare(figures) {
  const parts = ORIGIN_METRICS.map((metric) => figures?.[metric]);
  if (parts.some((part) => part === undefined || part === null)) return null;
  const sum = parts.reduce((total, part) => total + part, 0);
  return Math.min(100, Math.round(sum * 10) / 10);
}

function distanceKm(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(a));
}

function readSaved() {
  const defaults = {
    mode: "search",
    town: "Delft",
    radius: 15,
    lookup: "",
    ...DEFAULT_ORIGIN,
    crimes: null, // filled with the national averages once the data is loaded
  };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") };
  } catch {
    return defaults;
  }
}

function writeSaved() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
  } catch {
    // Private windows may refuse storage; the page works without it.
  }
}

// ---------- Data ----------

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} answered ${response.status}`);
  return response.json();
}

async function loadIndex() {
  if (!store.index) store.index = await getJson("data/index.json");
  return store.index;
}

function loadGemeente(code) {
  if (!store.gemeenten.has(code)) {
    const request = getJson(`data/gm/${code}.json`);
    request.catch(() => store.gemeenten.delete(code));
    store.gemeenten.set(code, request);
  }
  return store.gemeenten.get(code);
}

async function askPdok(query, type) {
  const data = await getJson(`${PDOK_SEARCH}?q=${encodeURIComponent(query)}&fq=type:${type}&rows=1`);
  return data.response.docs[0] ?? null;
}

function pointOf(doc) {
  const match = /POINT\(([-\d.]+) ([-\d.]+)\)/.exec(doc.centroide_ll ?? "");
  return match ? { lon: Number(match[1]), lat: Number(match[2]) } : null;
}

async function findTown(name, index) {
  try {
    const doc = await askPdok(name, "woonplaats");
    const point = doc && pointOf(doc);
    if (point) return { name: doc.weergavenaam, ...point };
  } catch {
    // PDOK could not be reached; try the names of the gemeenten we have.
  }
  const wanted = name.trim().toLowerCase();
  const gemeente =
    index.gemeenten.find((entry) => entry.name.toLowerCase() === wanted) ??
    index.gemeenten.find((entry) => entry.name.toLowerCase().startsWith(wanted));
  if (!gemeente) return null;
  const [west, south, east, north] = gemeente.bounds;
  return { name: gemeente.name, lon: (west + east) / 2, lat: (south + north) / 2 };
}

// ---------- Links to a search ----------
// A search is written into the address as #/search?town=Delft&radius=15&...,
// so the page can be bookmarked or sent to someone else.

function searchHash() {
  const params = new URLSearchParams();
  params.set("town", saved.town);
  params.set("radius", saved.radius);
  if (saved.originMin !== "") params.set("origin_min", saved.originMin);
  if (saved.originMax !== "") params.set("origin_max", saved.originMax);
  for (const [metric, value] of Object.entries(saved.crimes ?? {})) {
    if (value !== "") params.set(metric.replace(/_per_1000$/, ""), value);
  }
  return `#/search?${params}`;
}

function cleanNumber(text) {
  if (text === null || text.trim() === "") return "";
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 ? String(value) : "";
}

// Take over the search described by a link. Returns false if it names no town.
function applySearchHash(hash, index) {
  const params = new URLSearchParams(hash.slice(hash.indexOf("?") + 1));
  const town = (params.get("town") ?? "").trim();
  if (!town) return false;

  const radius = Number(params.get("radius"));
  saved.mode = "search";
  saved.town = town;
  saved.radius = radius >= 1 && radius <= 50 ? String(radius) : "15";
  saved.originMin = cleanNumber(params.get("origin_min"));
  saved.originMax = cleanNumber(params.get("origin_max"));
  saved.crimes = {};
  for (const crime of index.crimes) {
    const value = cleanNumber(params.get(crime.count));
    if (value !== "") saved.crimes[crime.metric] = value;
  }
  writeSaved();
  return true;
}

// ---------- Judging neighbourhoods ----------

function limitsFromSaved(index) {
  const limits = [];
  for (const crime of index.crimes) {
    const value = saved.crimes[crime.metric];
    if (value !== undefined && value !== "") {
      limits.push({
        label: crime.label,
        kind: "max",
        value: Number(value),
        read: (figures) => figures?.[crime.metric],
        show: number,
      });
    }
  }
  const origin = { label: ORIGIN_LABEL, read: originShare, show: percent };
  if (saved.originMin !== "") limits.push({ ...origin, kind: "min", value: Number(saved.originMin) });
  if (saved.originMax !== "") limits.push({ ...origin, kind: "max", value: Number(saved.originMax) });
  return limits;
}

function judge(buurt, limits) {
  const breaks = [];
  const gaps = [];
  for (const limit of limits) {
    const actual = limit.read(buurt.figures);
    if (actual === undefined || actual === null) {
      if (!gaps.includes(limit.label)) gaps.push(limit.label);
    } else if (limit.kind === "max" ? actual > limit.value : actual < limit.value) {
      breaks.push({ limit, actual });
    }
  }
  const status = breaks.length ? "rejected" : gaps.length ? "warning" : "good";
  return { status, breaks, gaps };
}

async function search() {
  const index = await loadIndex();
  const centre = await findTown(saved.town, index);
  if (!centre) {
    return { error: `No town called “${saved.town}” was found. Check the spelling.` };
  }

  const radius = Number(saved.radius);
  const reachLat = radius / 111.32;
  const reachLon = radius / (111.32 * Math.cos((centre.lat * Math.PI) / 180));
  const nearby = index.gemeenten.filter(({ bounds: [west, south, east, north] }) => {
    return (
      west <= centre.lon + reachLon &&
      east >= centre.lon - reachLon &&
      south <= centre.lat + reachLat &&
      north >= centre.lat - reachLat
    );
  });
  const files = await Promise.all(nearby.map((entry) => loadGemeente(entry.code)));

  const limits = limitsFromSaved(index);
  const rows = [];
  for (const file of files) {
    for (const buurt of file.buurten) {
      const km = distanceKm(centre.lat, centre.lon, buurt.lat, buurt.lon);
      if (km <= radius) {
        rows.push({ buurt, gemeente: file.name, km, verdict: judge(buurt, limits) });
      }
    }
  }
  if (!rows.length) {
    return { error: `There are no figures for the area around ${centre.name} in this copy of the data.` };
  }
  rows.sort((a, b) => a.km - b.km);
  return { centre, radius, limits, rows };
}

async function lookUp(text) {
  let doc;
  try {
    doc = await askPdok(text, "adres");
  } catch {
    return { error: "The address service (PDOK) could not be reached. Try again in a moment." };
  }
  if (!doc) return { error: `No address was found for “${text}”. Try a postcode such as 2611 GS.` };

  let file;
  try {
    file = await loadGemeente(`GM${doc.gemeentecode}`);
  } catch {
    return { error: `There are no figures for ${doc.gemeentenaam} in this copy of the data.` };
  }
  let buurt = file.buurten.find((entry) => entry.code === doc.buurtcode);
  const point = pointOf(doc);
  if (!buurt && point) {
    // Neighbourhood codes can change between years; fall back to the nearest one.
    const byDistance = (entry) => distanceKm(point.lat, point.lon, entry.lat, entry.lon);
    buurt = [...file.buurten].sort((a, b) => byDistance(a) - byDistance(b))[0];
  }
  if (!buurt) return { error: `No neighbourhood was found for ${doc.weergavenaam}.` };
  return { code: buurt.code, address: doc.weergavenaam };
}

// ---------- Maps ----------

function startMap(element) {
  if (store.map) store.map.remove();
  const map = L.map(element, { scrollWheelZoom: false });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  store.map = map;
  return map;
}

function shapeOf(buurt, status) {
  const rings = buurt.outline.map((ring) => ring.map(([lon, lat]) => [lat, lon]));
  return L.polygon(rings, {
    color: "#3d4f54",
    weight: 1,
    fillColor: STATUS[status].fill,
    fillOpacity: STATUS[status].opacity,
  });
}

// What the map says about a neighbourhood under the mouse: its name, its status
// and, when it is rejected, every limit it breaks.
function tooltipOf(buurt, gemeente, verdict) {
  const lines = [`<b>${esc(buurt.name)}</b>`, esc(gemeente)];
  if (verdict.status === "rejected") {
    lines.push("Rejected, because:");
    for (const { limit, actual } of verdict.breaks) {
      const bound = `${limit.kind === "max" ? "at most" : "at least"} ${limit.show(limit.value)}`;
      lines.push(`${esc(limit.label)}: <b>${limit.show(actual)}</b> (${bound})`);
    }
  } else if (verdict.status === "warning") {
    lines.push(`Data missing: ${esc(verdict.gaps.join("; "))}`);
  } else {
    lines.push(STATUS.good.label);
  }
  return lines.join("<br>");
}

function drawSearchMap(element, result) {
  const map = startMap(element);
  const centre = L.latLng(result.centre.lat, result.centre.lon);
  map.fitBounds(centre.toBounds(result.radius * 2000));
  const order = { rejected: 0, warning: 1, good: 2 };
  const rows = [...result.rows].sort((a, b) => order[a.verdict.status] - order[b.verdict.status]);
  for (const { buurt, gemeente, verdict } of rows) {
    shapeOf(buurt, verdict.status)
      .bindTooltip(tooltipOf(buurt, gemeente, verdict), { sticky: true, className: "verdict" })
      .on("click", () => {
        location.hash = `#/buurt/${buurt.code}`;
      })
      .addTo(map);
  }
  L.circle(centre, {
    radius: result.radius * 1000,
    color: "#13282e",
    weight: 1.5,
    dashArray: "6 6",
    fill: false,
    interactive: false,
  }).addTo(map);
}

// ---------- Home ----------

// The averages describe the whole country only when every gemeente was exported.
function referenceName(index) {
  return index.complete ? "Netherlands" : "Average";
}

function crimeLimitRows(index) {
  return index.crimes
    .map(
      (crime) => `
        <tr>
          <td>${esc(crime.label)}</td>
          <td class="number">${number(index.average[crime.metric])}</td>
          <td><input type="number" min="0" step="0.1" inputmode="decimal"
            name="crime:${esc(crime.metric)}" value="${esc(saved.crimes[crime.metric] ?? "")}"
            aria-label="Highest accepted number per 1,000 residents: ${esc(crime.label)}"></td>
        </tr>`,
    )
    .join("");
}

function searchForm(index) {
  return `
    <form id="search-form">
      <div class="pair">
        <label class="field"><span>Town</span>
          <input type="text" name="town" value="${esc(saved.town)}" required autocomplete="off">
        </label>
        <label class="field"><span>Radius in km</span>
          <input type="number" name="radius" min="1" max="50" step="1" value="${esc(saved.radius)}" required>
        </label>
      </div>

      <div class="field">
        <span class="field-title">${ORIGIN_LABEL}
          <span class="hint">The two shares added up, in percent. ${referenceName(index)}:
          ${percent(originShare(index.average))}. Leave empty for no limit.</span>
        </span>
        <div class="pair">
          <label><span class="hint">At least</span>
            <input type="number" name="originMin" min="0" max="100" step="1" value="${esc(saved.originMin)}">
          </label>
          <label><span class="hint">At most</span>
            <input type="number" name="originMax" min="0" max="100" step="1" value="${esc(saved.originMax)}">
          </label>
        </div>
      </div>

      <div class="field">
        <span class="field-title">Registered crimes per 1,000 residents, ${index.crime_year}
          <span class="hint">Type the highest number you accept. Leave empty for no limit.
          The starting limits are the ${referenceName(index).toLowerCase()} figures.</span>
        </span>
        <div class="table-scroll">
          <table class="limits">
            <thead><tr><th>Crime</th><th class="number">${referenceName(index)}</th>
              <th class="number">At most</th></tr></thead>
            <tbody>${crimeLimitRows(index)}</tbody>
          </table>
        </div>
      </div>

      <button class="primary" type="submit">Find neighbourhoods</button>
      <div class="presets">
        <button type="button" data-preset="default">Use the starting limits</button>
        <button type="button" data-preset="none">Clear all limits</button>
      </div>
      <p id="form-message" class="message" hidden></p>
    </form>`;
}

function lookupForm() {
  return `
    <form id="lookup-form">
      <label class="field"><span>Postcode or address
        <span class="hint">For example 2611 GS, or Markt 87 Delft.</span></span>
        <input type="text" name="lookup" value="${esc(saved.lookup)}" required autocomplete="off">
      </label>
      <button class="primary" type="submit">Show this neighbourhood</button>
      <p id="form-message" class="message" hidden></p>
    </form>`;
}

function resultTable(rows, withGaps) {
  const body = rows
    .map(({ buurt, gemeente, km, verdict }) => {
      const figures = buurt.figures ?? {};
      return `
        <tr data-code="${buurt.code}">
          <td><a href="#/buurt/${buurt.code}">${esc(buurt.name)}</a></td>
          <td>${esc(gemeente)}</td>
          <td class="number">${number(km)}</td>
          <td class="number">${percent(originShare(figures))}</td>
          <td class="number">${number(figures.burglaries_per_1000)}</td>
          <td class="number">${number(figures.violent_crimes_per_1000)}</td>
          <td class="number">${number(figures.crimes_total_per_1000)}</td>
          ${withGaps ? `<td>${esc(verdict.gaps.join("; "))}</td>` : ""}
        </tr>`;
    })
    .join("");
  return `
    <div class="table-scroll">
      <table class="results">
        <thead><tr>
          <th>Neighbourhood</th><th>Gemeente</th><th class="number">Km</th>
          <th class="number">Origin NL + Europe</th><th class="number">Burglary</th>
          <th class="number">Violence</th><th class="number">All crimes</th>
          ${withGaps ? "<th>No figures for</th>" : ""}
        </tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

function renderResults(target) {
  const result = store.search;
  const groups = { good: [], warning: [], rejected: [] };
  for (const row of result.rows) groups[row.verdict.status].push(row);

  target.innerHTML = `
    <h1>Neighbourhoods around ${esc(result.centre.name.split(",")[0])}</h1>
    <p class="lead">${result.rows.length} neighbourhoods lie within ${number(result.radius)} km.
      ${result.limits.length ? "" : "No limits are set, so all of them qualify."}</p>
    <p class="share">
      <button type="button" id="copy-link">Copy a link to this search</button>
      <span id="copy-note" role="status"></span>
      <input id="copy-fallback" type="text" readonly hidden aria-label="Link to this search">
    </p>
    <ul class="tally">
      ${Object.entries(groups)
        .map(
          ([status, rows]) => `
            <li><span class="swatch ${status}"></span><strong>${rows.length}</strong>
            ${STATUS[status].label.toLowerCase()}</li>`,
        )
        .join("")}
    </ul>
    <div id="search-map" class="map" role="img"
      aria-label="Map of the neighbourhoods; the same results are listed in the tables below"></div>
    <section class="result-group">
      <h3>Meets every limit</h3>
      ${
        groups.good.length
          ? `<p class="note">Nearest first. Crime figures are per 1,000 residents. Choose a row for all figures.</p>
             ${resultTable(groups.good, false)}`
          : '<p class="note">No neighbourhood meets every limit. Raise a limit or widen the radius.</p>'
      }
    </section>
    ${
      groups.warning.length
        ? `<details><summary>Data missing: ${groups.warning.length} neighbourhoods break no limit,
            but lack a figure you limit</summary>${resultTable(groups.warning, true)}</details>`
        : ""
    }`;

  target.querySelector("#copy-link").addEventListener("click", async () => {
    const note = target.querySelector("#copy-note");
    try {
      await navigator.clipboard.writeText(location.href);
      note.textContent = "Link copied. Anyone who opens it sees this search.";
    } catch {
      // No clipboard access (for example an old browser): show the link to copy by hand.
      const field = target.querySelector("#copy-fallback");
      field.value = location.href;
      field.hidden = false;
      field.select();
      note.textContent = "Copy the link below.";
    }
  });

  drawSearchMap(target.querySelector("#search-map"), result);
  for (const row of target.querySelectorAll("tr[data-code]")) {
    row.addEventListener("click", () => {
      location.hash = `#/buurt/${row.dataset.code}`;
    });
  }
}

function showMessage(form, text) {
  const message = form.querySelector("#form-message");
  message.textContent = text;
  message.hidden = !text;
}

const SEARCH_INTRO = `
  <h1>Find a neighbourhood that fits</h1>
  <p class="lead">Name a town and a radius, say how much crime you accept and what share of
  residents with origin the Netherlands or the rest of Europe you look for. You get every neighbourhood in range
  that fits, on a map and in a list.</p>`;

// Run the search in `saved` (or reuse the last one if nothing changed) and show it.
async function showSearch(results, form) {
  const key = searchHash();
  if (!store.search || store.searchKey !== key) {
    const button = form.querySelector("button.primary");
    button.disabled = true;
    results.innerHTML = '<p class="loading">Searching…</p>';
    try {
      const result = await search();
      if (result.error) {
        results.innerHTML = SEARCH_INTRO;
        showMessage(form, result.error);
        return;
      }
      store.search = result;
      store.searchKey = key;
    } catch (error) {
      console.error(error);
      results.innerHTML = SEARCH_INTRO;
      showMessage(form, "The figures could not be loaded. Check your connection and try again.");
      return;
    } finally {
      button.disabled = false;
    }
  }
  renderResults(results);
}

// `searchLink` is the address of a search (#/search?...) or null for the start page.
async function renderHome(searchLink) {
  const index = await loadIndex();
  describeData(index);
  const searching = Boolean(searchLink) && applySearchHash(searchLink, index);
  if (saved.crimes === null) saved.crimes = defaultCrimeLimits(index);

  view.innerHTML = `
    <div class="workspace">
      <section class="panel" aria-label="What to look for">
        <div class="modes">
          <button type="button" data-mode="search" aria-pressed="${saved.mode === "search"}">Search an area</button>
          <button type="button" data-mode="lookup" aria-pressed="${saved.mode === "lookup"}">One neighbourhood</button>
        </div>
        ${saved.mode === "search" ? searchForm(index) : lookupForm()}
      </section>
      <section id="results" aria-live="polite"></section>
    </div>`;

  const results = view.querySelector("#results");
  if (saved.mode === "search") {
    results.innerHTML = SEARCH_INTRO;
  } else {
    results.innerHTML = `
      <h1>Look up one neighbourhood</h1>
      <p class="lead">Type a postcode or an address to see the figures of the neighbourhood it
      lies in: who lives there, what the homes are like and how much crime is registered.</p>`;
  }

  // Leave a search address behind without adding a step to the browser history.
  const showStartPage = () => {
    if (location.hash.startsWith("#/search")) history.replaceState(null, "", "#/");
    renderHome(null);
  };

  for (const button of view.querySelectorAll(".modes button")) {
    button.addEventListener("click", () => {
      saved.mode = button.dataset.mode;
      writeSaved();
      showStartPage();
    });
  }

  for (const button of view.querySelectorAll("[data-preset]")) {
    button.addEventListener("click", () => {
      // Keep the town and radius that are typed in; only the limits change.
      const typed = new FormData(view.querySelector("#search-form"));
      saved.town = typed.get("town").trim();
      saved.radius = typed.get("radius");
      if (button.dataset.preset === "default") {
        Object.assign(saved, DEFAULT_ORIGIN, { crimes: defaultCrimeLimits(index) });
      } else {
        Object.assign(saved, { originMin: "", originMax: "", crimes: {} });
      }
      writeSaved();
      showStartPage();
    });
  }

  view.querySelector("#search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    saved.town = data.get("town").trim();
    saved.radius = data.get("radius");
    saved.originMin = data.get("originMin");
    saved.originMax = data.get("originMax");
    saved.crimes = {};
    for (const [name, value] of data) {
      if (name.startsWith("crime:") && value !== "") saved.crimes[name.slice(6)] = value;
    }
    writeSaved();

    // The address carries the search; changing it makes the page run the search.
    const link = searchHash();
    if (location.hash === link) route();
    else location.hash = link;
  });

  view.querySelector("#lookup-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    saved.lookup = new FormData(form).get("lookup").trim();
    writeSaved();
    const button = form.querySelector("button.primary");
    button.disabled = true;
    showMessage(form, "");
    const found = await lookUp(saved.lookup);
    button.disabled = false;
    if (found.error) showMessage(form, found.error);
    else location.hash = `#/buurt/${found.code}`;
  });

  if (searching) await showSearch(results, view.querySelector("#search-form"));
}

// ---------- One neighbourhood ----------

// One ring of a pie chart: the shares of `figures` drawn between two radii.
function ring(group, figures, inner, outer, who) {
  const present = group.figures
    .map((figure, position) => ({ ...figure, position, value: figures?.[figure.metric] }))
    .filter((figure) => figure.value !== undefined && figure.value !== null && figure.value > 0);
  const total = present.reduce((sum, figure) => sum + figure.value, 0);
  if (!total) return "";

  const point = (radius, angle) =>
    `${(110 + radius * Math.sin(angle)).toFixed(2)} ${(110 - radius * Math.cos(angle)).toFixed(2)}`;
  let from = 0;
  return present
    .map((figure) => {
      // Stop just short of a full turn, or a single 100% slice would vanish.
      const to = from + Math.min(figure.value / total, 0.9999) * 2 * Math.PI;
      const large = to - from > Math.PI ? 1 : 0;
      const path =
        `M ${point(outer, from)} A ${outer} ${outer} 0 ${large} 1 ${point(outer, to)} ` +
        `L ${point(inner, to)} A ${inner} ${inner} 0 ${large} 0 ${point(inner, from)} Z`;
      from = to;
      return `<path class="s${figure.position + 1}" d="${path}">
        <title>${esc(who)}: ${esc(figure.label)} ${percent(figure.value)}</title></path>`;
    })
    .join("");
}

function groupPanel(group, buurt, file, index) {
  // Rings from the outside in: this neighbourhood, its gemeente, the country.
  const rings = [
    ["This neighbourhood", buurt.figures, 76, 106],
    [file.name, file.average, 54, 72],
  ];
  if (index.complete) rings.push(["Netherlands", index.average, 32, 50]);

  const drawn = rings.map(([who, figures, inner, outer]) => ring(group, figures, inner, outer, who));
  const chart = drawn[0]
    ? `<svg class="pie" viewBox="0 0 220 220" role="img"
         aria-label="${esc(group.title)}; the figures are in the table next to this chart">${drawn.join("")}</svg>`
    : '<p class="pie empty">No figures published for this neighbourhood</p>';

  const rows = group.figures
    .map(
      (figure, position) => `
        <tr>
          <td><span class="swatch s${position + 1}"></span>${esc(figure.label)}</td>
          ${rings
            .map(
              ([, figures], column) =>
                `<td class="number${column ? "" : " self"}">${percent(figures?.[figure.metric])}</td>`,
            )
            .join("")}
        </tr>`,
    )
    .join("");

  return `
    <section class="panel group">
      <h3>${esc(group.title)}</h3>
      <div class="pie-row">
        ${chart}
        <table class="shares">
          <thead><tr><th></th>
            ${rings.map(([who], column) => `<th class="number">${column ? esc(who) : "Here"}</th>`).join("")}
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}

function crimeTable(buurt, file, index) {
  const rows = index.crimes
    .map(
      (crime) => `
        <tr>
          <td>${esc(crime.label)}</td>
          <td class="number">${number(buurt.counts?.[crime.count], 0)}</td>
          <td class="number">${number(buurt.figures?.[crime.metric])}</td>
          <td class="number">${number(file.average[crime.metric])}</td>
          ${index.complete ? `<td class="number">${number(index.average[crime.metric])}</td>` : ""}
        </tr>`,
    )
    .join("");
  return `
    <div class="panel table-scroll">
      <table>
        <thead><tr>
          <th>Crime</th><th class="number">Number</th><th class="number">Per 1,000 residents</th>
          <th class="number">${esc(file.name)}, per 1,000</th>
          ${index.complete ? '<th class="number">Netherlands, per 1,000</th>' : ""}
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// Funda searches by four-digit postcode area, which is usually a bit larger
// than one neighbourhood.
function fundaLink(buurt) {
  if (!buurt.postcode) return "";
  const area = encodeURIComponent(JSON.stringify([buurt.postcode]));
  return `
    <p class="funda">
      <a class="button" href="https://www.funda.nl/zoeken/koop?selected_area=${area}"
        target="_blank" rel="noopener">See homes for sale on Funda</a>
      <span>Funda shows postcode area ${esc(buurt.postcode)}, which can reach past this
      neighbourhood. Look up a home's full postcode under One neighbourhood to be sure.</span>
    </p>`;
}

async function renderBuurt(code) {
  const index = await loadIndex();
  describeData(index);

  let file;
  try {
    file = await loadGemeente(`GM${code.slice(2, 6)}`);
  } catch {
    file = null;
  }
  const buurt = file?.buurten.find((entry) => entry.code === code);
  const back = store.search
    ? `<a class="back" href="${esc(store.searchKey)}">Back to the results</a>`
    : '<a class="back" href="#/">Search an area</a>';
  if (!buurt) {
    view.innerHTML = `${back}<h1>Neighbourhood not found</h1>
      <p class="lead">There are no figures for ${esc(code)} in this copy of the data.</p>`;
    return;
  }

  const figures = buurt.figures ?? {};
  view.innerHTML = `
    ${back}
    <div class="buurt-head">
      <div>
        <h1>${esc(buurt.name)}</h1>
        <p class="lead">Neighbourhood in ${esc(file.name)}, CBS code ${esc(buurt.code)}</p>
        ${fundaLink(buurt)}
        <dl class="facts">
          <div><dt>Residents</dt><dd>${number(figures.residents, 0)}</dd></div>
          <div><dt>Residents per km²</dt><dd>${number(figures.density_per_km2, 0)}</dd></div>
          <div><dt>Average WOZ value</dt><dd>${euro(figures.avg_woz_eur)}</dd></div>
          <div><dt>Income per resident</dt><dd>${euro(figures.avg_income_eur)}</dd></div>
        </dl>
      </div>
      <div id="buurt-map" class="map small" role="img" aria-label="Map showing where ${esc(buurt.name)} lies"></div>
    </div>

    <h2 class="section-title">Residents and homes</h2>
    <p class="note">In each chart the outer ring is this neighbourhood, the next ring is
      ${esc(file.name)}${index.complete ? " and the inner ring is the Netherlands" : ""}.
      Hover over a slice for its share.</p>
    <div class="groups">
      ${index.groups.map((group) => groupPanel(group, buurt, file, index)).join("")}
    </div>

    <h2 class="section-title">Safety</h2>
    <p class="note">Registered crimes in ${index.crime_year}. Sexual offences are not published
      per neighbourhood, so they are not counted.</p>
    ${crimeTable(buurt, file, index)}`;

  const map = startMap(view.querySelector("#buurt-map"));
  const shape = shapeOf(buurt, "good");
  map.fitBounds(shape.getBounds(), { padding: [30, 30], maxZoom: 15 });
  shape.addTo(map);
}

// ---------- Page frame ----------

function describeData(index) {
  const note = document.getElementById("data-note");
  note.textContent =
    `Data made on ${index.generated}, crime figures for ${index.crime_year}. ` +
    (index.complete
      ? `All ${index.gemeenten.length} gemeenten are included.`
      : `This copy holds ${index.gemeenten.length} gemeenten, not the whole country.`);
}

async function route() {
  const match = /^#\/buurt\/(BU\d{8})$/.exec(location.hash);
  try {
    if (match) await renderBuurt(match[1]);
    else await renderHome(location.hash.startsWith("#/search?") ? location.hash : null);
  } catch (error) {
    console.error(error);
    view.innerHTML = `<h1>The figures could not be loaded</h1>
      <p class="lead">Check your connection and reload the page. If you run the site yourself,
      make the data files first with <code>python -m huis_monitor export</code>.</p>`;
  }
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
