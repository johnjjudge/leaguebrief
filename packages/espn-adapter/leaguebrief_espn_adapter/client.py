from __future__ import annotations

import json
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MODERN_ENDPOINT_START_SEASON = 2018
DEFAULT_BASE_URL = "https://lm-api-reads.fantasy.espn.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_USER_AGENT = "LeagueBrief ESPN Adapter/0.1"

SNAPSHOT_VIEWS: Mapping[str, tuple[str, ...]] = {
    "league_meta": ("mSettings", "mStatus", "mTeam"),
    "draft": ("mDraftDetail",),
    "matchups": ("mMatchup", "mMatchupScore", "mSchedule", "mScoreboard"),
    "transactions": ("mTransactions2",),
    "rosters": ("mRoster",),
}


class EspnAdapterError(RuntimeError):
    """Base error for safe ESPN adapter failures."""


class EspnAuthenticationError(EspnAdapterError):
    """Raised when ESPN rejects credentials or requires authentication."""


class EspnNotFoundError(EspnAdapterError):
    """Raised when ESPN reports a league or snapshot was not found."""


class EspnDataError(EspnAdapterError):
    """Raised when ESPN returns an unexpected data shape."""


class EspnJsonError(EspnAdapterError):
    """Raised when ESPN does not return valid JSON."""


class EspnHttpError(EspnAdapterError):
    def __init__(self, status_code: int, message: str = "ESPN request failed.") -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class EspnCredentials:
    espn_s2: str
    swid: str | None = None


@dataclass(frozen=True)
class EspnSnapshotRequest:
    league_id: str
    season: int
    snapshot_type: str
    scoring_period_id: int | None = None


@dataclass(frozen=True)
class EspnSnapshotResponse:
    request: EspnSnapshotRequest
    payload: Mapping[str, Any] | Sequence[Any]
    url: str


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    url: str


class HttpTransport(Protocol):
    def get(
        self,
        url: str,
        query: Sequence[tuple[str, str]],
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        ...


class UrlLibHttpTransport:
    def __init__(self) -> None:
        self._ssl_context = _default_ssl_context()

    def get(
        self,
        url: str,
        query: Sequence[tuple[str, str]],
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        full_url = _with_query(url, query)
        request = Request(full_url, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=timeout, context=self._ssl_context) as response:
                response_headers = {key: value for key, value in response.headers.items()}
                return HttpResponse(
                    status_code=response.status,
                    headers=response_headers,
                    body=response.read(),
                    url=full_url,
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                headers={key: value for key, value in exc.headers.items()},
                body=exc.read(),
                url=full_url,
            )
        except URLError as exc:
            raise EspnHttpError(0, "ESPN request failed before receiving a response.") from exc


class EspnFantasyClient:
    def __init__(
        self,
        transport: HttpTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = transport or UrlLibHttpTransport()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def fetch_league_meta(
        self,
        league_id: str,
        season: int,
        credentials: EspnCredentials | None = None,
    ) -> EspnSnapshotResponse:
        return self.fetch_snapshot(
            EspnSnapshotRequest(
                league_id=league_id,
                season=season,
                snapshot_type="league_meta",
            ),
            credentials,
        )

    def fetch_draft(
        self,
        league_id: str,
        season: int,
        credentials: EspnCredentials | None = None,
    ) -> EspnSnapshotResponse:
        return self.fetch_snapshot(
            EspnSnapshotRequest(league_id=league_id, season=season, snapshot_type="draft"),
            credentials,
        )

    def fetch_matchups(
        self,
        league_id: str,
        season: int,
        credentials: EspnCredentials | None = None,
    ) -> EspnSnapshotResponse:
        return self.fetch_snapshot(
            EspnSnapshotRequest(
                league_id=league_id,
                season=season,
                snapshot_type="matchups",
            ),
            credentials,
        )

    def fetch_transactions(
        self,
        league_id: str,
        season: int,
        credentials: EspnCredentials | None = None,
    ) -> EspnSnapshotResponse:
        return self.fetch_snapshot(
            EspnSnapshotRequest(
                league_id=league_id,
                season=season,
                snapshot_type="transactions",
            ),
            credentials,
        )

    def fetch_rosters(
        self,
        league_id: str,
        season: int,
        scoring_period_ids: Sequence[int],
        credentials: EspnCredentials | None = None,
    ) -> EspnSnapshotResponse:
        scoring_periods: list[dict[str, object]] = []
        last_url = ""
        for scoring_period_id in scoring_period_ids:
            request = EspnSnapshotRequest(
                league_id=league_id,
                season=season,
                snapshot_type="rosters",
                scoring_period_id=scoring_period_id,
            )
            response = self.fetch_snapshot(request, credentials)
            scoring_periods.append(
                {
                    "scoringPeriodId": scoring_period_id,
                    "payload": response.payload,
                }
            )
            last_url = response.url

        return EspnSnapshotResponse(
            request=EspnSnapshotRequest(
                league_id=league_id,
                season=season,
                snapshot_type="rosters",
            ),
            payload={
                "leagueId": league_id,
                "season": season,
                "snapshotType": "rosters",
                "scoringPeriods": scoring_periods,
            },
            url=last_url,
        )

    def fetch_snapshot(
        self,
        request: EspnSnapshotRequest,
        credentials: EspnCredentials | None = None,
    ) -> EspnSnapshotResponse:
        views = SNAPSHOT_VIEWS.get(request.snapshot_type)
        if not views:
            raise EspnDataError("Unsupported ESPN snapshot type.")

        response = self._get(
            league_id=request.league_id,
            season=request.season,
            views=views,
            credentials=credentials,
            scoring_period_id=request.scoring_period_id,
        )
        return EspnSnapshotResponse(
            request=request,
            payload=response.payload,
            url=response.url,
        )

    def discover_seasons(
        self,
        league_id: str,
        credentials: EspnCredentials | None = None,
    ) -> tuple[int, ...]:
        response = self._get(
            league_id=league_id,
            season=None,
            views=("mSettings",),
            credentials=credentials,
            use_history_endpoint=True,
        )
        seasons = sorted(_extract_season_ids(response.payload))
        if not seasons:
            raise EspnDataError("ESPN history discovery did not return seasons.")
        return tuple(seasons)

    def _get(
        self,
        league_id: str,
        season: int | None,
        views: Sequence[str],
        credentials: EspnCredentials | None,
        scoring_period_id: int | None = None,
        use_history_endpoint: bool = False,
    ) -> _JsonResponse:
        query: list[tuple[str, str]] = [("view", view) for view in views]
        if scoring_period_id is not None:
            query.append(("scoringPeriodId", str(scoring_period_id)))

        if use_history_endpoint:
            url = f"{self._base_url}/apis/v3/games/ffl/leagueHistory/{league_id}"
        elif season is None:
            raise EspnDataError("Season is required for ESPN snapshot fetches.")
        elif season >= MODERN_ENDPOINT_START_SEASON:
            url = (
                f"{self._base_url}/apis/v3/games/ffl/seasons/{season}"
                f"/segments/0/leagues/{league_id}"
            )
        else:
            url = f"{self._base_url}/apis/v3/games/ffl/leagueHistory/{league_id}"
            query.append(("seasonId", str(season)))

        headers = _headers(credentials)
        response = self._transport.get(url, query, headers, self._timeout_seconds)
        _raise_for_status(response)
        payload = _decode_json(response.body)
        return _JsonResponse(payload=payload, url=response.url)


@dataclass(frozen=True)
class _JsonResponse:
    payload: Mapping[str, Any] | Sequence[Any]
    url: str


def _headers(credentials: EspnCredentials | None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if credentials is not None:
        cookie_parts = [f"espn_s2={credentials.espn_s2}"]
        if credentials.swid:
            cookie_parts.append(f"SWID={credentials.swid}")
        headers["Cookie"] = "; ".join(cookie_parts)
    return headers


def _default_ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _raise_for_status(response: HttpResponse) -> None:
    if response.status_code < 400:
        return
    if response.status_code in (401, 403):
        raise EspnAuthenticationError("ESPN rejected league credentials.")
    if response.status_code == 404:
        raise EspnNotFoundError("ESPN league or snapshot was not found.")
    raise EspnHttpError(response.status_code)


def _decode_json(body: bytes) -> Mapping[str, Any] | Sequence[Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EspnJsonError("ESPN response was not valid JSON.") from exc

    if not isinstance(payload, (dict, list)):
        raise EspnJsonError("ESPN response JSON must be an object or array.")
    return payload


def _extract_season_ids(payload: Mapping[str, Any] | Sequence[Any]) -> set[int]:
    seasons: set[int] = set()
    if isinstance(payload, Mapping):
        _collect_season_id(payload, seasons)
        return seasons

    for item in payload:
        if isinstance(item, Mapping):
            _collect_season_id(item, seasons)
    return seasons


def _collect_season_id(payload: Mapping[str, Any], seasons: set[int]) -> None:
    season_id = payload.get("seasonId")
    if isinstance(season_id, int) and not isinstance(season_id, bool):
        seasons.add(season_id)

    status = payload.get("status")
    if isinstance(status, Mapping):
        status_season_id = status.get("seasonId")
        if isinstance(status_season_id, int) and not isinstance(status_season_id, bool):
            seasons.add(status_season_id)


def _with_query(url: str, query: Sequence[tuple[str, str]]) -> str:
    if not query:
        return url
    return f"{url}?{urlencode(query)}"
