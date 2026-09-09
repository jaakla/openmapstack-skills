# parcels

Cadastral parcels with legal land-use designation, for a few blocks of Tartu.

| Column | Meaning |
|---|---|
| `cadastral_id` | Stable cadastral identifier, unique among current records |
| `land_use` | Legal designation: `ARIMAA` (commercial), `ELAMUMAA` (residential), `MAATULUNDUSMAA` (agricultural), `TOOTMISMAA` (industrial) |
| `municipality` | Municipality name |
| `record_status` | `current` or `superseded` — see AGENTS.md |
| `geometry` | Polygon, EPSG:3301 |

Converted from the publisher's extract; the pre-conversion file is published
beside it with the `source` role.
