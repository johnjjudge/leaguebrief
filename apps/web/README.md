# LeagueBrief Web

Minimal React + TypeScript shell for LeagueBrief, built with Vite and deployed to Azure Static Web Apps.

## Routes

- `/`: Home
- `/league`: League overview placeholder
- `/managers`: Manager analysis placeholder
- `/draft`: Draft analytics placeholder
- `*`: Not found

## Environment

No production build-time environment variables are required for this shell.

Optional local value:

- `VITE_API_BASE_URL`: API base URL. Defaults to `/api`.

Use `.env.example` as the local template.

The deployed Static Web App receives additional app settings from Bicep, including `API_BASE_PATH`, `PUBLIC_APP_URL`, `FRONT_DOOR_PUBLIC_HOST`, Key Vault-backed auth settings, and `LEAGUEBRIEF_ENVIRONMENT`. The UI shell does not implement ESPN workflows yet.

## Run locally

```bash
npm ci
npm run dev
```

## Build

```bash
npm run lint
npm run test
npm run typecheck
npm run build
```

The build output is `dist/`, which matches `infra/scripts/deploy-app-web.sh`.
