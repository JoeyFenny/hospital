## Healthcare Cost Navigator (MVP)

Minimal FastAPI + Postgres service to search hospitals by MS-DRG near a ZIP radius, view estimated prices and mock quality ratings, and ask questions via a small AI assistant.

### Stack
- Python 3.11, FastAPI, async SQLAlchemy (asyncpg)
- PostgreSQL 16 (Docker)
- OpenAI API for NL parsing (optional; falls back to regex)
- pgeocode for offline ZIP geocoding

### Setup (Docker Compose)
1. Copy env and start services
   ```bash
   cp .env.example .env
   docker compose up -d db
   docker compose build api
   ```

2. Run DB migrations (Alembic), then ETL to seed the DB from `sample_prices_ny.csv`
   ```bash
   docker compose run --rm api alembic upgrade head
   docker compose run --rm api python etl.py
   ```

3. Start the API
   ```bash
   docker compose up -d api
   # API at http://localhost:8000
   # UI at http://localhost:8000/ui
   ```

### Web UI

- Open `http://localhost:8000/ui` for a minimal, unstyled HTML page that:
  - Calls `/providers`
  - Calls `/ask`

### REST API

#### GET /providers
Query hospitals offering DRG (ILIKE fuzzy) within radius of a ZIP.

Example:
```bash
curl -s "http://localhost:8000/providers?drg=470&zip=10001&radius_km=40" | jq
```

Response example:
```json
[
  {
    "provider_id": "330123",
    "name": "Hospital A",
    "city": "New York",
    "state": "NY",
    "zip_code": "10001",
    "ms_drg_definition": "470 – Major Joint Replacement w/o MCC",
    "average_covered_charges": 84621.0,
    "rating": 8,
    "distance_km": 2.3
  }
]
```

#### POST /ask
Ask in natural language. Uses OpenAI to extract structured parameters (intent, DRG, ZIP, radius), then executes a safe SQL/ORM query.

```bash
curl -s -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Who is cheapest for DRG 470 within 25 miles of 10001?"}' | jq
```

Out-of-scope:
```bash
curl -s -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"What\'s the weather today?"}' | jq
```

### AI Sample Prompts
1. Cheapest hospital for knee replacement near 10001?
2. Best rated hospitals for heart surgery in NY near 10032?
3. Average cost for DRG 291 within 50km of 10032?
4. Hospitals offering MS-DRG 470 with ratings over 8 near me (10001)?
5. Compare costs for major joint replacement at top 3 hospitals near 10001.

### Data Model
- `providers`: `id` (PK), `provider_id` (unique), `name`, `city`, `state`, `zip_code`, `latitude`, `longitude`
- `procedures`: `id` (PK), `provider_id` (FK to `providers.provider_id`), `ms_drg_definition`, `total_discharges`, `average_*`
- `ratings`: `id` (PK), `provider_id` (FK to `providers.provider_id`), `rating` 1-10

Indexes:
- B-tree on `providers.zip_code`
- Trigram GIN on `procedures.ms_drg_definition` for ILIKE
- Spatial GiST on `providers (ll_to_earth(latitude, longitude))` via `earthdistance` for radius filtering

### Architecture Notes
- Offline ZIP geocoding via `pgeocode` (no external service).
- Haversine distance computed in SQL expression for radius filtering.
- AI layer only extracts parameters; ORM performs the query. This avoids executing arbitrary SQL while meeting the NL-to-SQL intent.

#### Trade-offs
- Using OpenAI for natural language parsing provides better accuracy but adds external dependency and potential costs; fallback to regex ensures basic functionality.
- Haversine formula is efficient for distance calculations but provides straight-line distances, not accounting for actual travel routes.
- Sample dataset limits scope to NY; scaling to full US data would require more robust ETL and storage.
- Async operations enable concurrency but increase code complexity compared to synchronous alternatives.

### Development
Run locally without Docker (requires Postgres running). You can run Alembic locally too:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/hospital
alembic upgrade head
python etl.py
uvicorn app.main:app --reload
```

### Migrations (Alembic)
- Create a new migration after model changes:
  ```bash
  alembic revision -m "your message" --autogenerate
  ```
- Apply migrations:
  ```bash
  alembic upgrade head
  ```
- If your DB was created previously using the raw SQL migration, the ETL flow or `alembic stamp head` can align the Alembic version with the current schema without recreating tables.

### Unfinished tasks
- Bonus: Integrate real Medicare star ratings instead of mock values
  - Check availability of a stable ratings dataset and licensing
  - Update ETL to ingest ratings and adjust `/ask` logic if needed
- Add the referenced demo GIF asset (`demo.gif`) showing `/providers` and `/ask` in action

### Demo
- Use the cURL commands above for `/providers` and `/ask`.
- Add Loom recordings per deliverables when presenting.
![Demo GIF showing /providers and /ask endpoints](demo.gif)

