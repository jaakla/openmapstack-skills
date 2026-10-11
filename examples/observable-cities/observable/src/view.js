// Plot's spherical projection expects clockwise exterior rings. Upstream
// GeoJSON uses RFC 7946 winding; adapt local-city render copies only.
export function forPlot(collection) {
  function rings(polygon) {
    return polygon.map((ring, index) => {
      const area = ring.slice(1).reduce((sum, b, i) => sum + ring[i][0] * b[1] - b[0] * ring[i][1], 0);
      return (index === 0 ? area > 0 : area < 0) ? [...ring].reverse() : ring;
    });
  }
  return {...collection, features: collection.features.map(feature => {
    const g = feature.geometry;
    const coordinates = g.type === "Polygon" ? rings(g.coordinates) :
      g.type === "MultiPolygon" ? g.coordinates.map(rings) : g.coordinates;
    return {...feature, geometry: {...g, coordinates}};
  })};
}

export function controls(city, features) {
  const form = document.createElement("form");
  form.className = "controls";
  const selects = {};
  function select(name, label, values) {
    const wrapper = document.createElement("label");
    wrapper.textContent = label;
    const input = document.createElement("select");
    input.name = name;
    for (const [value, text] of values) input.add(new Option(text, value));
    wrapper.append(input); form.append(wrapper); selects[name] = input;
  }
  if (city === "tartu") {
    const tiers = [...new Set(features.map(d => d.properties.suitability_tier))].sort();
    select("category", "Suitability tier", [["all", "All recorded tiers"], ...tiers.map(t => [t, t])]);
  } else {
    const boroughs = [...new Set(features.map(d => d.properties.borough))].sort();
    select("category", "Borough", [["all", "All boroughs"], ...boroughs.map(b => [b, b])]);
    select("eligibility", "Eligibility", [["all", "All cells"], ["eligible", "Eligible only"], ["ineligible", "Ineligible only"]]);
  }
  const reset = document.createElement("button");
  reset.type = "button"; reset.textContent = "Reset to snapshot";
  reset.onclick = () => { form.reset(); form.dispatchEvent(new Event("input", {bubbles: true})); };
  form.append(reset);
  function update() { form.value = Object.fromEntries(Object.entries(selects).map(([key, input]) => [key, input.value])); }
  form.addEventListener("input", update);
  form.onsubmit = event => event.preventDefault();
  update();
  return form;
}

export function filterFeatures(city, features, filters) {
  return features.filter(({properties: p}) =>
    (filters.category === "all" || filters.category === (city === "tartu" ? p.suitability_tier : p.borough)) &&
    (!filters.eligibility || filters.eligibility === "all" || p.eligible === (filters.eligibility === "eligible")));
}

export function status(total, count, filters) {
  const p = document.createElement("p");
  p.id = "snapshot-status";
  const filtered = Object.values(filters).some(value => value !== "all");
  p.textContent = `${filtered ? "Exploratory subset — accepted snapshot unchanged" : "Accepted snapshot"} · ${count} of ${total} rows`;
  return p;
}

export function table(city, features) {
  const wrapper = document.createElement("div"); wrapper.className = "table-scroll";
  wrapper.tabIndex = 0; wrapper.setAttribute("role", "region"); wrapper.setAttribute("aria-label", "Snapshot data table");
  const table = document.createElement("table"); table.id = "snapshot-table";
  const columns = city === "tartu" ? [["cadastral_id", "Parcel"], ["address", "Address"], ["area_m2", "Area (m²)"],
    ["dist_main_road_m", "Road distance (m)"], ["suitability_tier", "Recorded tier"]] :
    [["h3_cell", "H3 cell"], ["borough", "Borough"], ["eligible", "Eligible"], ["final_score", "Fixed score"], ["trips_total", "Trips"]];
  const head = table.createTHead().insertRow();
  for (const [, title] of columns) { const th = document.createElement("th"); th.scope = "col"; th.textContent = title; head.append(th); }
  const body = table.createTBody();
  const rows = [...features].sort((a, b) => city === "nyc" ? (b.properties.final_score ?? -1) - (a.properties.final_score ?? -1) :
    a.properties.suitability_tier.localeCompare(b.properties.suitability_tier) || b.properties.area_m2 - a.properties.area_m2);
  for (const {properties} of rows) {
    const row = body.insertRow();
    for (const [key] of columns) {
      const value = properties[key];
      row.insertCell().textContent = value == null ? "Unscored" : typeof value === "number" ? value.toLocaleString("en-US") : String(value);
    }
  }
  if (!rows.length) { const cell = body.insertRow().insertCell(); cell.colSpan = columns.length; cell.textContent = "No snapshot rows match these filters."; }
  wrapper.append(table);
  return wrapper;
}

export function provenance(info) {
  const section = document.createElement("section"); section.setAttribute("data-openmapstack-provenance", "");
  const title = document.createElement("h2"); title.textContent = "Provenance & limitations"; section.append(title);
  for (const text of info.notes) { const p = document.createElement("p"); p.textContent = text; section.append(p); }
  return section;
}
