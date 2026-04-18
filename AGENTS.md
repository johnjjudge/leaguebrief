# LeagueBrief agent instructions

## Product context
LeagueBrief is an ESPN fantasy football league history and draft prep analytics service.

The MVP allows users to:
- sign in with Google or Microsoft
- connect one or more ESPN leagues
- import historical league data asynchronously
- reuse shared league data across multiple users
- view league overview, manager analysis, and draft analytics
- support the project via a Buy Me a Coffee link

Read these files before making nontrivial changes:
- `docs/leaguebrief-prd.md`
- `docs/leaguebrief-implementation-plan.md` or `docs/IMPLEMENTATION_PLAN.md`
- `docs/API_SPEC.md` if it exists
- `docs/METRICS.md` if it exists

## Existing proof of concept reference
There is an existing proof of concept under:

- `docs/espn-fantasy-league-analyzer/`

This proof of concept uses the ESPN API and calculates some of the target metrics in Python.

### How to use the proof of concept
- Use it as a **reference** for understanding domain logic, ESPN data shapes, and possible metric calculations.
- It may be consulted to help guide implementation decisions, data modeling, normalization logic, and metric definitions.
- It should be treated as supporting material, not production code.

### Strict rule for new source code
- Do **not** directly reference, import, call, or depend on code from `docs/espn-fantasy-league-analyzer/` in the new application source code.
- Do **not** create runtime dependencies on the proof of concept.
- Re-implement required logic cleanly inside the new architecture and packages.
- The new source code should stand on its own and follow the LeagueBrief architecture in the PRD.

## Core architecture
- Frontend: React + TypeScript
- Backend: Python
- API and workers: Azure Functions
- Database: Azure SQL serverless
- Blob and queue: Azure Storage
- Secrets: Azure Key Vault
- Edge: Azure Front Door
- Hosting: Azure Static Web Apps for frontend

## Critical product invariants
These rules must not be broken.

1. Canonical league uniqueness
- A league is globally unique by `(platform, external_league_id)`.
- Do not create duplicate canonical league records for the same ESPN league.

2. Shared league data
- Historical league data is shared across users.
- Do not duplicate normalized league data per user.
- Expensive imports and analytics should be reusable when another user joins the same league.

3. Authorization model
- `user_leagues` is the authorization link between users and leagues.
- All league-scoped read and write operations must verify access through `user_leagues`.

4. Secrets handling
- Never store raw `espn_s2` or `SWID` values in SQL.
- Never log raw ESPN credential values.
- Store secret references in SQL and the actual secret values in Key Vault or a secret abstraction.

5. Analytics design
- Metrics must be persisted.
- Metrics must be versioned through `metric_definitions`.
- Dashboard reads must not trigger full recomputation.

6. Async job model
- Imports and recomputes must be asynchronous.
- Use `import_jobs`, `job_tasks`, and `job_events` consistently.
- Preserve job state transitions and auditability.

## Schema expectations
Keep schema names aligned with the PRD unless explicitly asked to change them.

Expected core tables include:
- `users`
- `auth_provider_accounts`
- `leagues`
- `user_leagues`
- `league_access_credentials`
- `import_jobs`
- `job_tasks`
- `job_events`
- `raw_snapshots`
- `reference_files`
- `seasons`
- `season_data_coverage`
- `managers`
- `teams`
- `matchups`
- `weekly_team_scores`
- `drafts`
- `draft_picks`
- `transactions`
- `player_reference`
- `reference_rankings`
- `reference_ranking_items`
- `metric_definitions`
- `league_metrics`
- `manager_metrics`
- `team_metrics`

## Coding rules
- Prefer small, reviewable changes.
- Keep analytics logic framework-independent.
- Keep ESPN integration isolated behind an adapter layer.
- Keep FantasyPros CSV ingestion isolated behind an adapter layer.
- Favor explicit types and clear naming.
- Add tests for nontrivial logic.
- Preserve idempotency for ingestion and normalization paths.
- Avoid broad refactors unless they are required for the requested task.

## Things not to introduce without explicit approval
- Password auth
- Custom payment processing
- Duplicate league data per user
- Live recomputation on dashboard page load
- Unnecessary additional infrastructure or services
- Large dependency additions without justification

## Frontend guidelines
- Use the LeagueBrief brand consistently.
- Include loading, empty, and error states for async data.
- Keep the UI clean and credible, not gimmicky.
- The Buy Me a Coffee link should be present but not intrusive.

## Backend guidelines
- Separate route handlers, service logic, repositories, adapters, and analytics.
- Prefer idempotent upserts for normalization.
- Validate ownership/access early in request handling.
- Return safe error messages to clients.
- Keep secret-bearing code paths tightly scoped.

## Testing expectations
For nontrivial changes, add or update:
- unit tests for pure logic
- integration tests for DB/service behavior where practical
- authorization tests for league access checks
- ingestion/idempotency tests for normalization flows
- representative metric tests for analytics logic

## Completion checklist
Before marking a task complete:
1. Run tests.
2. Run lint.
3. Run type checks.
4. Summarize changed files.
5. Call out risks, TODOs, or assumptions.

## Preferred workflow
For substantial tasks:
- read the PRD and implementation plan first
- review the proof of concept for domain context if helpful
- write a short plan before editing code
- identify invariants and likely risks
- implement the smallest viable change that satisfies the task
- verify with tests and checks

## Local development assumptions
Unless the repo says otherwise:
- use environment variables for local config
- use injectable abstractions or mocks for cloud services in tests
- do not require live Azure resources for the core unit test suite

## If something is ambiguous
- preserve the current architecture direction from the PRD
- choose the simpler implementation that does not violate invariants
- document assumptions clearly in the final summary
