# API guide

Base URL `http://127.0.0.1:8000`; interactive docs at `/docs`, schema at `/openapi.json`.

**Authentication.** Every *state-changing* (POST) endpoint requires `X-API-Key: <API_KEY>` when `API_KEY` is configured; if it is not configured only loopback clients are accepted (403 otherwise). GET endpoints are read-only and open. With Docker Compose the nginx proxy adds the header, so the browser never holds the key.

**Errors** are JSON `{"error": "<kind>", "detail": "<message>"}`: `invalid_image` 422, `not_found` 404, `model_not_ready` 503, `plc_not_connected` 409, `plc_unavailable` 503, `plc_protocol_error` 502, `invalid_request` 422, `conflict` 409, plus FastAPI's standard 422 body for schema violations.

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /ready` | database reachable **and** model ready (503 otherwise, with reason) |
| `POST /api/v1/inspection/upload` | multipart `files` (≤20, ≤`MAX_UPLOAD_MB` each); returns per-file `{ok, upload_id, ...}` or `{ok:false, error}` |
| `POST /api/v1/inspection/analyze` | `{"upload_ids":[...], "confidence":0.3, "iou":0.45}` → inspection records |
| `GET /api/v1/inspection/{id}` | one record with defects |
| `GET /api/v1/inspection/{id}/image/{original\|annotated}` | image bytes |
| `GET /api/v1/inspections` | filters: `decision, class_name, q, mode, source, date_from, date_to, include_demo, limit, offset` |
| `GET /api/v1/dashboard/stats` | totals, defect distribution, 14-day trend, recent, demo-record count |
| `GET /api/v1/model/status` | mode, readiness, reason, thresholds, rules, metrics (real mode only), training status |
| `POST /api/v1/model/config` | `{confidence_threshold, iou_threshold, mode, decision_rules, reload}` |
| `GET /api/v1/plc/status` | connection and live snapshot (always labelled simulator) |
| `POST /api/v1/plc/connect` / `disconnect` | optional body `{host, port}` (validated against the loopback rule) |
| `GET /api/v1/plc/registers` | register map + live values |
| `GET /api/v1/plc/events` | communication/cycle event log |
| `POST /api/v1/plc/simulate-cycle` | `{"scenario":"normal"\|"defective"\|"upload","upload_id":...}` |
| `POST /api/v1/plc/emergency-stop` | `{"active": true\|false}` |
| `POST /api/v1/demo/seed` | `{"count": 24}` creates records labelled `demo_seed` |
| `GET /api/v1/system/events` | system event log |

## Examples
```bash
# upload + analyse (from localhost)
curl -F "files=@part.png" http://127.0.0.1:8000/api/v1/inspection/upload
curl -H 'Content-Type: application/json' -d '{"upload_ids":["UPL-..."]}' http://127.0.0.1:8000/api/v1/inspection/analyze

# remote call with a key
curl -H "X-API-Key: $API_KEY" -X POST http://host:8000/api/v1/plc/connect
curl -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' -d '{"scenario":"defective"}' \
     http://host:8000/api/v1/plc/simulate-cycle
```

Decision rules (`decision_rules` in `/model/config`): `min_confidence` (0-1), `class_min_confidence` (class→0-1), `ignore_classes`, `min_area_ratio` (box area / image area), `max_defects_allowed`. A part is REJECT when more than `max_defects_allowed` detections pass all filters.

Every record carries `model_mode` (`real`/`demo`), `is_demo`, model name/version (weights hash), thresholds and duration, so demonstration output can always be told apart from real inference.
