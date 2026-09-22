-- Northstar Mobility MotherDuck fixture: access boundary
--
-- What actually enforces the boundary here is *not* SQL, and this file says
-- so rather than implying otherwise. For MotherDuck the canonical fixture
-- profile is:
--
--   1. a private database (`northstar_market`) that is not shared publicly;
--   2. a dedicated **read-scoped access token** for the analysis identity,
--      created in MotherDuck (UI or API) and referenced by the project only
--      as `env:MOTHERDUCK_TOKEN` -- never the provisioning token;
--   3. the connector's own read-only session: the database is attached
--      READ_ONLY where the installed DuckDB supports it, and analysis SQL is
--      restricted to a single SELECT.
--
-- Fine-grained per-table security is an optional later profile
-- (docs/maintainers/nyc-private-mobility.md). Do not read the views below as
-- an enforced column boundary: they are the *intended* analysis surface, and
-- `provision.py verify` reports what the token can actually reach.
--
--   python provision.py motherduck      (runs after seed.sql)
--
-- Ordinary DuckDB SQL, so it runs against MotherDuck and locally alike.

-- The analysis surface: public-origin geometry plus the derived scores the
-- project is allowed to publish. market.analyst_annotations is deliberately
-- absent -- the private notes inform the scores and are never republished.
CREATE OR REPLACE VIEW market.analysis_zone_scores AS
SELECT
    taxi_zone_id,
    market_score,
    competitor_hubs,
    parking_index,
    transit_index,
    source_vintage
FROM market.zone_market_scores;

CREATE OR REPLACE VIEW market.analysis_pois AS
SELECT
    poi_id,
    taxi_zone_id,
    category,
    name,
    source,
    geom
FROM market.relevant_pois;

-- Per-zone POI context in the shape the pipeline consumes, so the approved
-- snapshot query stays small and its digest stays stable.
CREATE OR REPLACE VIEW market.analysis_zone_poi_counts AS
SELECT
    taxi_zone_id,
    count(*) FILTER (WHERE category = 'charging')   AS charging_pois,
    count(*) FILTER (WHERE category = 'parking')    AS parking_pois,
    count(*) FILTER (WHERE category = 'transit')    AS transit_pois,
    count(*) FILTER (WHERE category = 'competitor') AS competitor_pois,
    count(*)                                        AS total_pois
FROM market.relevant_pois
GROUP BY taxi_zone_id;
