<div class="eyebrow">NYC · Observable delivery sample</div>

# Mobility hub opportunities

Explore the recorded H3 cell metrics for tenant alpha. Borough and eligibility filters narrow the same precomputed rows; the demand, coverage, market and saturation scores stay fixed.

<p class="notice">Business records are synthetic demo data. Some synthetic vehicle locations reuse historical 2016 NYC TLC pickup coordinates. These points are not live tracking, and the scores are not real-world siting recommendations.</p>

```js
import {FileAttachment} from "observablehq:stdlib";
import * as Plot from "npm:@observablehq/plot@0.6.17";
import {controls, filterFeatures, status, table, provenance, forPlot} from "./view.js";
const features = forPlot(await FileAttachment("features.geojson").json());
const context = await FileAttachment("context.geojson").json();
const points = await FileAttachment("points.geojson").json();
const info = await FileAttachment("provenance.json").json();
const form = controls("nyc", features.features);
const filters = Generators.input(form);
display(form);
```

```js
const visible = filterFeatures("nyc", features.features, filters);
display(status(features.features.length, visible.length, filters));
```

```js
display(resize(width => Plot.plot({
  width, height: Math.min(560, width * 0.72), className: "map",
  projection: {type: "mercator", domain: features},
  color: {type: "linear", domain: [0, 100], scheme: "YlGnBu", legend: true, label: "Fixed suitability score"},
  marks: [
    Plot.geo(features, {fill: "#dce5e5", stroke: "white", strokeWidth: 1}),
    Plot.geo(visible, {fill: d => d.properties.final_score ?? "#dce5e5", stroke: "white", strokeWidth: 1,
      tip: true, title: d => `${d.properties.h3_cell}\n${d.properties.borough}\nScore: ${d.properties.final_score ?? "Unscored"}\n${d.properties.eligible ? "Eligible" : "Ineligible"}`}),
    Plot.dot(points.features, {x: d => d.geometry.coordinates[0], y: d => d.geometry.coordinates[1], r: 1.5, fill: "#70829a", opacity: 0.5}),
    Plot.dot(context.features, {x: d => d.geometry.coordinates[0], y: d => d.geometry.coordinates[1],
      r: 5, fill: "#a56124", stroke: "white", tip: true, title: d => `${d.properties.name} · capacity ${d.properties.capacity}`})
  ]
})));
```

Thematic overview: grey cells show the study grid, small dots show synthetic fleet positions, and orange markers show existing hubs. No street basemap is loaded. Hover a cell or hub for details.

## Cell snapshot

```js
display(table("nyc", visible));
```

Download the full recorded snapshot: <a href="features.geojson" download>cell GeoJSON</a>, <a href="metrics.csv" download>metrics CSV</a>, <a href="context.geojson" download>existing hubs</a>, <a href="points.geojson" download>synthetic fleet points</a>.

<section data-openmapstack-provenance>
__CREDITS__
<div id="provenance-notes"></div>
</section>

```js
document.getElementById("provenance-notes").replaceChildren(provenance(info));
```
