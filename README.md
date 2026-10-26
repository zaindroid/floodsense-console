# floodsense-console

The team's FloodSense EU console, deployed. Everything here except `serve/`
is mirrored from
[Hackathon-Monorepo](https://github.com/GenAI-Open-Agent-Hackathon/Hackathon-Monorepo)
`main`; the monorepo is where it is owned and changed.

<https://floodsense-console.zaindroid.me>

## One container, four services

The monorepo runs these as a Compose stack. The platform gives an app one
port, so they run together here instead:

| | where | what |
| --- | --- | --- |
| `ui` | served at `/` | the React console: insurer desk, citizen page, map, replay |
| `api` | mounted at `/api` | the proxy, cache and labelled replay |
| `agents` | `127.0.0.1:8100` | the LangGraph graph |
| `engines` | `127.0.0.1:8300` | H-MEM and the World Model |

Only the first two are reachable from outside, and only through this
origin. The engines carry no authentication at all, which is why they are
on loopback. `VITE_API_URL` is baked to `/api` at image build time, so the
browser never needs a second origin and CORS never comes into it.

## What it answers with

Nothing is pretending here. With no `ZETARIS_REST_URL` the agents read
their own SQLite seed of the same contract views, and every answer is
labelled `replay` with the time it was recorded. Set the two Zetaris
variables and the same screens answer `live`.

Meterless Nightshift is not deployed anywhere, so model calls go to the
deterministic stand-in. The lanes are still named on `/api/config`, and an
answer built that way is never called live.

## Tests are not here

They stay in the monorepo, where the code is owned and where CI runs
them. Several read folders this mirror does not carry, so a copy here
would look broken while proving nothing. What is checked instead is the
container: the four endpoints answer, a run completes through `/api`,
and an approval reaches the memory write.

## Endpoints

`/health`, `/ready`, `/version` and `/openapi.json` describe the container.
`/api/*` is the team's API, `/api/openapi.json` its own spec.

## Keeping up with main

`.github/workflows/sync-from-monorepo.yml` pulls `ui/`, `api/`, `agents/`,
`engines/` and `contracts/` hourly and pushes the difference, which is what
asks for a redeploy. It needs `MONOREPO_TOKEN`; without it the job says so
and stops rather than failing on a schedule.
