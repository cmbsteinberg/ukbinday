
## API Endpoints

All endpoints are mounted at both `/api` and `/api/v1`. The v1 prefix is the stable, documented surface for external consumers.

### Endpoints

| Method | Path | Params | Description |
|--------|------|--------|-------------|
| `GET` | `/addresses/{postcode}` | `postcode` (path) | Returns list of addresses with UPRNs + council info |
| `GET` | `/council/{postcode}` | `postcode` (path) | Returns the council/scraper for a postcode |
| `GET` | `/lookup/{uprn}` | `uprn` (path), `council` (required), `postcode`, `address` (optional) | Returns bin collection schedule |
| `GET` | `/calendar/{uprn}` | `uprn` (path), `council` (required), `postcode`, `address` (optional) | Returns iCal file for calendar subscription |
| `GET` | `/councils` | -- | Lists all loaded scrapers with required params |
| `GET` | `/health` | -- | Per-scraper health status (last success/error, counts) |

### HTML Pages

| Path | Description |
|------|-------------|
| `/` | Landing page with postcode search and coverage map |
| `/coverage` | Full-page coverage map |
| `/api-docs` | API documentation page |

### Auto-generated Docs

| Path | Description |
|------|-------------|
| `/api/v1/docs` | Swagger UI |
| `/api/v1/redoc` | ReDoc |
| `/api/v1/openapi.json` | OpenAPI schema |

### Error Responses

- `404`: Council scraper not found
- `422`: Missing required params for this council's scraper
- `503`: Council site unreachable or scraper error
- `429`: Rate limit exceeded (per-IP daily limit via Redis)

### Rate Limiting

Per-IP sliding window in Redis. Disabled when no `REDIS_URL` is set. No API keys required.

### Design

The public API and the web frontend share the same server and endpoints. There is no separate API service. The only difference is that `/api/v1/` is versioned and stable, while `/api/` routes can change freely.
