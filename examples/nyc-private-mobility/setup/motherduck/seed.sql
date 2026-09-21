-- Northstar Mobility MotherDuck fixture: deterministic seed
--
-- Every value derives from md5_number('northstar|20260917|' || label), so the
-- fixture is byte-reproducible: no random(), no wall-clock values. Re-running
-- is idempotent (tables are emptied first).
--
--   python provision.py motherduck      (runs after schema.sql)
--
-- Volumes: zone_market_scores 60 (one per zone), relevant_pois 240,
-- analyst_annotations 24. Zones are 101..160, matching the PostGIS fixture.

DELETE FROM market.analyst_annotations;
DELETE FROM market.relevant_pois;
DELETE FROM market.zone_market_scores;

-- -- 60 zone market scores ---------------------------------------------------
INSERT INTO market.zone_market_scores
    (taxi_zone_id, market_score, competitor_hubs, parking_index, transit_index, source_vintage)
SELECT
    101 + g,
    round(abs(md5_number('northstar|20260917|mkt-score-' || g) % 1000) / 1000.0, 3),
    abs(md5_number('northstar|20260917|mkt-comp-' || g) % 4)::INTEGER,
    round(abs(md5_number('northstar|20260917|mkt-park-' || g) % 1000) / 1000.0, 3),
    round(abs(md5_number('northstar|20260917|mkt-transit-' || g) % 1000) / 1000.0, 3),
    DATE '2026-06-30'
FROM generate_series(0, 59) AS t(g);

-- -- 240 POIs spread over the zone grid --------------------------------------
INSERT INTO market.relevant_pois (poi_id, taxi_zone_id, category, name, source, geom)
SELECT
    'POI-' || lpad(g::VARCHAR, 4, '0'),
    zone_id,
    category,
    upper(category[1]) || category[2:] || ' ' || lpad(g::VARCHAR, 4, '0'),
    CASE WHEN category = 'competitor' THEN 'northstar-private' ELSE 'shared-open-places' END,
    ST_Point(
        -74.030 + ((zone_id - 101) % 12) * 0.010
            + (0.1 + 0.8 * (abs(md5_number('northstar|20260917|poi-x-' || g) % 10000) / 10000.0)) * 0.010,
        40.700 + ((zone_id - 101) / 12)::INTEGER * 0.015
            + (0.1 + 0.8 * (abs(md5_number('northstar|20260917|poi-y-' || g) % 10000) / 10000.0)) * 0.015
    )
FROM (
    SELECT
        g,
        101 + abs(md5_number('northstar|20260917|poi-zone-' || g) % 60)::INTEGER AS zone_id,
        (ARRAY['charging', 'parking', 'transit', 'competitor', 'retail'])[
            1 + abs(md5_number('northstar|20260917|poi-cat-' || g) % 5)::INTEGER] AS category
    FROM generate_series(1, 240) AS t(g)
);

-- -- 24 private analyst annotations -------------------------------------------
INSERT INTO market.analyst_annotations (annotation_id, taxi_zone_id, analyst, note, confidence)
SELECT
    'AN-' || lpad(g::VARCHAR, 3, '0'),
    101 + abs(md5_number('northstar|20260917|ann-zone-' || g) % 60)::INTEGER,
    'analyst-' || (1 + abs(md5_number('northstar|20260917|ann-who-' || g) % 4)::INTEGER),
    'Private assessment note ' || lpad(g::VARCHAR, 3, '0'),
    round(0.5 + abs(md5_number('northstar|20260917|ann-conf-' || g) % 500) / 1000.0, 3)
FROM generate_series(1, 24) AS t(g);
