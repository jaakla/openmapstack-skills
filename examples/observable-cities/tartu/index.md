<div class="eyebrow">Tartu · Observable delivery sample</div>

# Development parcels & walking access

Explore the recorded parcel screening results near Tartu's main roads and municipal education facilities. Area and road distances were calculated in EPSG:3301; this view draws the exported EPSG:4326 geometry.

<p class="notice">The recorded analysis includes a hypothetical connector road and a kindergarten treated as closed. The tiers reflect the accepted 25-minute walking catchments and these scenarios. Filtering a tier does not recalculate walking access.</p>

```js
import {FileAttachment} from "observablehq:stdlib";
import * as Plot from "npm:@observablehq/plot@0.6.17";
import {controls, filterFeatures, status, table, provenance, forPlot} from "./view.js";
const features = forPlot(await FileAttachment("features.geojson").json());
const context = await FileAttachment("context.geojson").json();
const points = await FileAttachment("points.geojson").json();
const info = await FileAttachment("provenance.json").json();
const form = controls("tartu", features.features);
const filters = Generators.input(form);
display(form);
```

```js
const visible = filterFeatures("tartu", features.features, filters);
display(status(features.features.length, visible.length, filters));
```

```js
display(resize(width => Plot.plot({
  width, height: Math.min(560, width * 0.72), className: "map",
  projection: {type: "mercator", domain: features},
  color: {legend: true, domain: info.categories, range: ["#168b85", "#b5a06a", "#aebfbd"]},
  marks: [
    Plot.geo(context, {stroke: "#bacdca", strokeWidth: 0.6}),
    Plot.geo(visible, {fill: d => d.properties.suitability_tier, stroke: "white", strokeWidth: 0.4,
      tip: true, title: d => `${d.properties.cadastral_id}\n${d.properties.address}\n${(d.properties.area_m2 / 10000).toFixed(2)} ha\n${d.properties.suitability_tier}`}),
    Plot.dot(points.features, {x: d => d.geometry.coordinates[0], y: d => d.geometry.coordinates[1],
      r: 2, fill: "#334d69", tip: true, title: d => `${d.properties.name} · ${d.properties.map_class}`})
  ]
})));
```

Thematic overview: road lines and education points provide context; no street basemap is loaded. Hover a parcel or facility for details. The full original analysis has additional catchment and scenario controls.

## Parcel snapshot

```js
display(table("tartu", visible));
```

Download the full recorded snapshot: <a href="features.geojson" download>parcel GeoJSON</a>, <a href="metrics.csv" download>metrics CSV</a>, <a href="context.geojson" download>roads</a>, <a href="points.geojson" download>education points</a>.

```js
display(provenance(info));
```
