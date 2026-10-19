# NEXis AI Inspection Agent - Implementation Notes

This module was prepared from the source files of the deployed NEXis Lightsail project, not from a fabricated sample implementation.

## Architecture

- **Existing deterministic fault diagnosis:** `app/ai_model.py` RandomForest classifier. No LLM inference is used to produce the four-class predictions.
- **Read-only LLM integration:** `app/inspection_agent.py`, with a chat completions HTTP client via the Nebius Token Factory endpoint. Default model: `nvidia/Nemotron-3-Ultra-550b-a55b`.
- **Authenticated HTTP API:** `/api/agent/status`, `/api/agent/events`, `POST /api/agent/ask`, and `POST /api/agent/events/{event_id}/analyze` in `app/main.py`.
- **UI:** Agent page in `app/web/index.html`, with rendering and interaction in `app/web/assets/inspection_agent.js` and `.css`.
- **Database:** PostgreSQL inspection event table created by `InspectionAgent.init_db()` during app startup.

## Available read-only evidence tools

| Tool | Information |
| --- | --- |
| `get_inspection_snapshot` | Latest sensor values and classifier snapshot scoped to the active workspace |
| `get_recent_predictions` | Recent RandomForest class predictions and scores |
| `get_sensor_statistics` | Stored RPM, vibration and current summary statistics |
| `get_recent_inspection_events` | Physical inspection event records |
| `get_vision_status` | Physical Station edge vision status, no image transmission to the LLM |
| `get_trial_recordings` | Metadata for recorded CSV acquisition sessions |

The tools are read-only; the agent has no motor-control endpoint. For Recorded Demo the tools use replay-source records; Physical Station uses physical-source records. The model's output is advisory and can be wrong.

## Server-only configuration

Create a private `.env` using `.env.example`, and set the following values securely (never commit `.env`):

- `ADMIN_USER`, `ADMIN_PASSWORD` - browser authentication. The real password must be strong and unique.
- `NEBIUS_API_KEY` - Nebius Token Factory API key, retained on the server.
- `NEBIUS_MODEL` - e.g. `nvidia/Nemotron-3-Ultra-550b-a55b`.
- `NEBIUS_BASE_URL` - optional HTTPS endpoint override.
- `NEXIS_AGENT_ACCESS_KEY` and `NEXIS_AGENT_OWNER_PASSWORD` - legacy server-only configuration checks required by the current agent implementation. Use independent random strings at least 24 characters long. The UI does not ask the user to enter these.
- `NEXIS_AGENT_AUTO` - automatic analysis on inspection events, normally `false`.
- `NEXIS_AGENT_ALLOW_GUEST` - must remain `false` for the public judging environment.

**Important:** Existing deployed Lightsail Docker Compose and this public GitHub Compose file are intentionally different. The public Compose file uses private `.env` variables, not passwords copied from the server. The files in this package are intended for GitHub synchronization only; uploading or pushing them does **not** deploy changes to Lightsail.

## Known boundaries

- Conversation history is in process memory and is not persistent across restarts.
- Replay timestamps must not be interpreted as live machine timestamps.
- Evidence tools return limited stored samples and summary data; output is not a mechanical failure root-cause confirmation.
- Model API access and the current replay state require actual configuration and data to be demonstrated end-to-end.
- This prototype is not a certified safety system.
