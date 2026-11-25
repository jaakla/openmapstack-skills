Prepare a reviewable tiling plan; do not execute tools or download anything.
Write `tiling-plan.json` with the key `accelerated`, containing one argv array
(executable followed by individual arguments). This task needs no full project
scaffold. Use a bare executable name, explicit long option names and no shell
wrappers. Include only the input, output, zooms, layer and the existing dropping
option. Do not add version checks, comparison builds or inspection commands to
the array; those belong to later execution QA.

Our tuned Tippecanoe build of `buildings.geojsonl` now takes too long on every
data refresh:

    tippecanoe --output buildings.pmtiles --minimum-zoom 10 --maximum-zoom 14 \
      --layer buildings --drop-densest-as-needed buildings.geojsonl

- `accelerated`: the same build on a faster engine that accepts these Tippecanoe
  options unchanged and is meant to produce the same tiles. Keep the input,
  output, zooms, layer and dropping behaviour exactly as they are. Do not change
  the cartography to gain speed.
