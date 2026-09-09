# Agent guide — parcels

## Count rule, read this before you query

`record_status` is `current` or `superseded`. A `superseded` row is a
historical version of a parcel that a later record replaced; the parcel it
describes still appears in the collection under its current record. **Filter
`record_status = 'current'` in every count, area, and selection.** Including
superseded rows double-counts parcels that were revised, and there is no
warning when you do — the geometry and the land-use value both look valid.

```sql
SELECT count(*) FROM read_parquet('.../parcels.parquet')
WHERE land_use = 'ARIMAA' AND record_status = 'current';
```

## Keys and CRS

- `cadastral_id` is the join key. It is not unique across the file: it is
  unique only among `current` rows.
- Geometry is EPSG:3301, a projected CRS in metres. Areas and distances are
  computed directly in it. Do not reproject to EPSG:4326 to measure.

## Assets

The GeoParquet is the `data` asset. The GeoJSON carries the `source` role — it
is the upstream extract before conversion, keeps the publisher's original
column names, and is not the file to query. Select on `roles`, not on the
asset key.

## License

CC-BY-4.0, produced by Maa- ja Ruumiamet. Attribution is required in anything
derived from it.
