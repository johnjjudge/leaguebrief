from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

_MULTI_SPACE_PATTERN = re.compile(r"\s+")

_POSITION_BY_ID = {
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    5: "K",
    16: "DST",
}

_NFL_TEAM_BY_ID = {
    1: "ATL",
    2: "BUF",
    3: "CHI",
    4: "CIN",
    5: "CLE",
    6: "DAL",
    7: "DEN",
    8: "DET",
    9: "GB",
    10: "TEN",
    11: "IND",
    12: "KC",
    13: "LV",
    14: "LAR",
    15: "MIA",
    16: "MIN",
    17: "NE",
    18: "NO",
    19: "NYG",
    20: "NYJ",
    21: "PHI",
    22: "ARI",
    23: "PIT",
    24: "LAC",
    25: "SF",
    26: "SEA",
    27: "TB",
    28: "WAS",
    29: "CAR",
    30: "JAX",
    33: "BAL",
    34: "HOU",
}


class EspnNormalizationError(ValueError):
    """Raised when required ESPN raw snapshot data cannot be normalized."""


@dataclass(frozen=True)
class CoverageFlags:
    has_draft_data: bool
    has_matchup_data: bool
    has_roster_data: bool
    has_reference_rankings: bool = False


@dataclass(frozen=True)
class ManagerRecord:
    external_manager_id: str
    display_name: str
    normalized_name: str
    first_seen_season: int
    last_seen_season: int


@dataclass(frozen=True)
class TeamRecord:
    external_team_id: str
    external_manager_id: str
    team_name: str
    abbrev: str | None
    wins: int | None
    losses: int | None
    ties: int | None
    points_for: Decimal | None
    points_against: Decimal | None
    final_standing: int | None
    made_playoffs: bool | None
    is_champion: bool | None


@dataclass(frozen=True)
class MatchupRecord:
    source_key: str
    week_number: int
    matchup_type: str
    home_external_team_id: str
    away_external_team_id: str
    home_score: Decimal | None
    away_score: Decimal | None
    winner_external_team_id: str | None
    is_complete: bool


@dataclass(frozen=True)
class WeeklyTeamScore:
    external_team_id: str
    week_number: int
    actual_points: Decimal | None


@dataclass(frozen=True)
class DraftPick:
    team_external_id: str
    overall_pick: int
    round_number: int | None
    round_pick: int | None
    player_name: str
    player_external_id: str | None
    position: str | None
    nfl_team: str | None


@dataclass(frozen=True)
class DraftRecord:
    draft_date: datetime | None
    draft_type: str | None
    pick_count: int
    picks: tuple[DraftPick, ...]


@dataclass(frozen=True)
class NormalizedSeason:
    season_year: int
    settings_json: str | None
    team_count: int | None
    regular_season_weeks: int | None
    playoff_weeks: int | None
    champion_external_team_id: str | None
    runner_up_external_team_id: str | None
    managers: tuple[ManagerRecord, ...]
    teams: tuple[TeamRecord, ...]
    matchups: tuple[MatchupRecord, ...]
    weekly_team_scores: tuple[WeeklyTeamScore, ...]
    draft: DraftRecord | None
    coverage: CoverageFlags
    skipped_matchup_count: int = 0

    @property
    def import_status(self) -> str:
        if (
            self.coverage.has_matchup_data
            and self.coverage.has_draft_data
            and self.coverage.has_roster_data
        ):
            return "complete"
        return "partial"


def normalize_espn_season(
    *,
    season: int,
    league_meta: Mapping[str, Any] | Sequence[Any],
    matchups: Mapping[str, Any] | Sequence[Any],
    draft: Mapping[str, Any] | Sequence[Any] | None = None,
    rosters: Mapping[str, Any] | Sequence[Any] | None = None,
) -> NormalizedSeason:
    meta_payload = select_season_payload(league_meta, season)
    matchup_payload = select_season_payload(matchups, season)
    draft_payload = select_season_payload(draft, season) if draft is not None else None

    managers_by_id = _extract_managers(meta_payload, season)
    teams = _extract_teams(meta_payload, managers_by_id, season)
    for team in teams:
        managers_by_id.setdefault(
            team.external_manager_id,
            ManagerRecord(
                external_manager_id=team.external_manager_id,
                display_name=team.team_name,
                normalized_name=_normalize_display_name(team.team_name),
                first_seen_season=season,
                last_seen_season=season,
            ),
        )

    normalized_matchups, weekly_scores, skipped_matchup_count = _extract_matchups(
        matchup_payload,
        teams,
    )
    player_index = _build_player_index(draft_payload, matchup_payload, rosters)
    draft_record = (
        _extract_draft(draft_payload, len(teams), player_index)
        if draft_payload is not None
        else None
    )
    settings = _mapping_value(meta_payload, "settings")
    schedule_settings = _mapping_value(settings, "scheduleSettings")
    final_scoring_period = _int_value(_mapping_value(meta_payload, "status"), "finalScoringPeriod")
    regular_weeks = _first_int(
        _mapping_value(schedule_settings, "matchupPeriodCount"),
        _mapping_value(schedule_settings, "regularSeasonMatchupPeriodCount"),
        _mapping_value(schedule_settings, "regularSeasonWeeks"),
    )
    playoff_weeks = None
    if final_scoring_period is not None and regular_weeks is not None:
        playoff_weeks = max(final_scoring_period - regular_weeks, 0)

    champion_id, runner_up_id = _champion_and_runner_up(teams)
    coverage = CoverageFlags(
        has_draft_data=draft_record is not None and bool(draft_record.picks),
        has_matchup_data=bool(normalized_matchups),
        has_roster_data=_has_roster_data(rosters),
        has_reference_rankings=False,
    )
    if not coverage.has_matchup_data:
        raise EspnNormalizationError("Required ESPN matchups snapshot did not contain matchups.")

    return NormalizedSeason(
        season_year=season,
        settings_json=_canonical_json(settings) if isinstance(settings, Mapping) else None,
        team_count=_first_int(_mapping_value(settings, "size"), len(teams) or None),
        regular_season_weeks=regular_weeks,
        playoff_weeks=playoff_weeks,
        champion_external_team_id=champion_id,
        runner_up_external_team_id=runner_up_id,
        managers=tuple(sorted(managers_by_id.values(), key=lambda item: item.external_manager_id)),
        teams=tuple(teams),
        matchups=normalized_matchups,
        weekly_team_scores=weekly_scores,
        draft=draft_record,
        coverage=coverage,
        skipped_matchup_count=skipped_matchup_count,
    )


def select_season_payload(
    payload: Mapping[str, Any] | Sequence[Any] | None,
    season: int,
) -> Mapping[str, Any]:
    if payload is None:
        raise EspnNormalizationError("ESPN raw snapshot payload is missing.")
    if isinstance(payload, Mapping):
        return payload
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        season_id = _first_int(
            _mapping_value(item, "seasonId"),
            _mapping_value(_mapping_value(item, "status"), "seasonId"),
        )
        if season_id == season:
            return item
    raise EspnNormalizationError(f"ESPN history payload does not include season {season}.")


def _extract_managers(
    payload: Mapping[str, Any],
    season: int,
) -> dict[str, ManagerRecord]:
    managers: dict[str, ManagerRecord] = {}
    members = _mapping_value(payload, "members")
    if isinstance(members, Sequence) and not isinstance(members, (str, bytes, bytearray)):
        for member in members:
            if not isinstance(member, Mapping):
                continue
            manager_id = _text_value(member, "id")
            if manager_id is None:
                continue
            display_name = _first_text(
                _mapping_value(member, "displayName"),
                _join_names(member),
                manager_id,
            )
            managers[manager_id] = ManagerRecord(
                external_manager_id=manager_id,
                display_name=display_name,
                normalized_name=_normalize_display_name(display_name),
                first_seen_season=season,
                last_seen_season=season,
            )
    return managers


def _extract_teams(
    payload: Mapping[str, Any],
    managers_by_id: dict[str, ManagerRecord],
    season: int,
) -> list[TeamRecord]:
    teams_payload = _mapping_value(payload, "teams")
    if not isinstance(teams_payload, Sequence) or isinstance(
        teams_payload,
        (str, bytes, bytearray),
    ):
        raise EspnNormalizationError("Required ESPN league metadata did not contain teams.")

    teams: list[TeamRecord] = []
    for team in teams_payload:
        if not isinstance(team, Mapping):
            continue
        team_id = _text_value(team, "id")
        if team_id is None:
            continue
        manager_id, manager_display_name = _manager_identity(team, managers_by_id, team_id)
        if manager_id not in managers_by_id:
            managers_by_id[manager_id] = ManagerRecord(
                external_manager_id=manager_id,
                display_name=manager_display_name,
                normalized_name=_normalize_display_name(manager_display_name),
                first_seen_season=season,
                last_seen_season=season,
            )

        record = _mapping_value(_mapping_value(team, "record"), "overall")
        wins = _int_value(record, "wins")
        losses = _int_value(record, "losses")
        ties = _int_value(record, "ties")
        final_standing = _first_int(
            _mapping_value(team, "rankCalculatedFinal"),
            _mapping_value(team, "finalStanding"),
            _mapping_value(team, "playoffSeed"),
        )
        teams.append(
            TeamRecord(
                external_team_id=team_id,
                external_manager_id=manager_id,
                team_name=_team_name(team, team_id),
                abbrev=_text_value(team, "abbrev"),
                wins=wins,
                losses=losses,
                ties=ties,
                points_for=_decimal_value(record, "pointsFor"),
                points_against=_decimal_value(record, "pointsAgainst"),
                final_standing=final_standing,
                made_playoffs=_made_playoffs(team),
                is_champion=(final_standing == 1 if final_standing is not None else None),
            )
        )
    if not teams:
        raise EspnNormalizationError("Required ESPN league metadata did not contain teams.")
    return teams


def _extract_matchups(
    payload: Mapping[str, Any],
    teams: Sequence[TeamRecord],
) -> tuple[tuple[MatchupRecord, ...], tuple[WeeklyTeamScore, ...], int]:
    team_ids = {team.external_team_id for team in teams}
    schedule = _mapping_value(payload, "schedule")
    if not isinstance(schedule, Sequence) or isinstance(schedule, (str, bytes, bytearray)):
        raise EspnNormalizationError("Required ESPN matchups snapshot did not contain schedule.")

    matchups: list[MatchupRecord] = []
    weekly_scores: dict[tuple[str, int], WeeklyTeamScore] = {}
    skipped = 0
    for entry in schedule:
        if not isinstance(entry, Mapping):
            skipped += 1
            continue
        home = _mapping_value(entry, "home")
        away = _mapping_value(entry, "away")
        home_team_id = _text_value(home, "teamId")
        away_team_id = _text_value(away, "teamId")
        week = _first_int(
            _mapping_value(entry, "matchupPeriodId"),
            _mapping_value(entry, "scoringPeriodId"),
        )
        if (
            home_team_id is None
            or away_team_id is None
            or week is None
            or home_team_id not in team_ids
            or away_team_id not in team_ids
        ):
            skipped += 1
            continue

        home_score = _decimal_value(home, "totalPoints")
        away_score = _decimal_value(away, "totalPoints")
        winner_id = _winner_team_id(entry, home_team_id, away_team_id, home_score, away_score)
        matchup = MatchupRecord(
            source_key=_matchup_source_key(entry, week, home_team_id, away_team_id),
            week_number=week,
            matchup_type=_matchup_type(entry),
            home_external_team_id=home_team_id,
            away_external_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            winner_external_team_id=winner_id,
            is_complete=_bool_from_status(_mapping_value(entry, "winner")) or (
                home_score is not None and away_score is not None
            ),
        )
        matchups.append(matchup)
        weekly_scores[(home_team_id, week)] = WeeklyTeamScore(home_team_id, week, home_score)
        weekly_scores[(away_team_id, week)] = WeeklyTeamScore(away_team_id, week, away_score)

    return tuple(matchups), tuple(weekly_scores.values()), skipped


def _extract_draft(
    payload: Mapping[str, Any],
    team_count: int,
    player_index: Mapping[str, Mapping[str, Any]],
) -> DraftRecord | None:
    draft_detail = _mapping_value(payload, "draftDetail")
    if not isinstance(draft_detail, Mapping):
        return None
    picks_payload = _mapping_value(draft_detail, "picks")
    if not isinstance(picks_payload, Sequence) or isinstance(
        picks_payload,
        (str, bytes, bytearray),
    ):
        return None

    picks: list[DraftPick] = []
    for pick in picks_payload:
        if not isinstance(pick, Mapping):
            continue
        overall_pick = _first_int(
            _mapping_value(pick, "overallPickNumber"),
            _mapping_value(pick, "overallPick"),
            _mapping_value(pick, "pickNumber"),
        )
        team_id = _text_value(pick, "teamId")
        player = _player_from_pick(pick, player_index)
        player_id = _first_text(_mapping_value(pick, "playerId"))
        player_name = _player_name_from_pick(pick, player, player_id)
        if overall_pick is None or team_id is None or not player_name:
            continue
        round_number = _first_int(_mapping_value(pick, "roundId"), _mapping_value(pick, "round"))
        round_pick = _first_int(
            _mapping_value(pick, "roundPickNumber"),
            _mapping_value(pick, "roundPick"),
        )
        if round_number is None and team_count:
            round_number = ((overall_pick - 1) // team_count) + 1
        if round_pick is None and team_count:
            round_pick = ((overall_pick - 1) % team_count) + 1
        picks.append(
            DraftPick(
                team_external_id=team_id,
                overall_pick=overall_pick,
                round_number=round_number,
                round_pick=round_pick,
                player_name=player_name,
                player_external_id=_first_text(
                    player_id,
                    _mapping_value(player, "id") if isinstance(player, Mapping) else None,
                ),
                position=_position_from_player(player),
                nfl_team=_nfl_team_from_player(player),
            )
        )

    if not picks:
        return None
    draft_settings = _mapping_value(_mapping_value(payload, "settings"), "draftSettings")
    return DraftRecord(
        draft_date=_timestamp_value(
            _first_int(
                _mapping_value(draft_detail, "draftDate"),
                _mapping_value(draft_settings, "date"),
            )
        ),
        draft_type=_first_text(
            _mapping_value(draft_detail, "draftType"),
            _mapping_value(draft_settings, "type"),
        ),
        pick_count=len(picks),
        picks=tuple(sorted(picks, key=lambda item: item.overall_pick)),
    )


def _manager_identity(
    team: Mapping[str, Any],
    managers_by_id: Mapping[str, ManagerRecord],
    team_id: str,
) -> tuple[str, str]:
    owners = _mapping_value(team, "owners")
    if isinstance(owners, Sequence) and not isinstance(owners, (str, bytes, bytearray)):
        for owner in owners:
            if isinstance(owner, Mapping):
                owner_id = _text_value(owner, "id")
                display_name = _first_text(_mapping_value(owner, "displayName"), owner_id)
            else:
                owner_id = str(owner) if owner is not None and str(owner).strip() else None
                manager = managers_by_id.get(owner_id) if owner_id else None
                display_name = manager.display_name if manager is not None else None
            if owner_id:
                return owner_id, display_name or owner_id
    primary_owner = _first_text(
        _mapping_value(team, "primaryOwner"),
        _mapping_value(team, "owner"),
    )
    if primary_owner:
        manager = managers_by_id.get(primary_owner)
        return primary_owner, manager.display_name if manager is not None else primary_owner
    fallback = f"team:{team_id}"
    return fallback, _team_name(team, team_id)


def _team_name(team: Mapping[str, Any], team_id: str) -> str:
    explicit = _first_text(_mapping_value(team, "name"), _mapping_value(team, "teamName"))
    if explicit:
        return explicit
    location = _first_text(_mapping_value(team, "location"), "")
    nickname = _first_text(_mapping_value(team, "nickname"), "")
    combined = f"{location} {nickname}".strip()
    return combined or f"Team {team_id}"


def _made_playoffs(team: Mapping[str, Any]) -> bool | None:
    value = _mapping_value(team, "madePlayoffs")
    if isinstance(value, bool):
        return value
    playoff_seed = _first_int(_mapping_value(team, "playoffSeed"))
    if playoff_seed is None:
        return None
    return playoff_seed > 0


def _champion_and_runner_up(teams: Sequence[TeamRecord]) -> tuple[str | None, str | None]:
    champion = next((team.external_team_id for team in teams if team.is_champion), None)
    runner_up = next(
        (team.external_team_id for team in teams if team.final_standing == 2),
        None,
    )
    return champion, runner_up


def _matchup_source_key(
    entry: Mapping[str, Any],
    week: int,
    home_team_id: str,
    away_team_id: str,
) -> str:
    matchup_id = _first_text(_mapping_value(entry, "id"), _mapping_value(entry, "matchupId"))
    if matchup_id:
        return f"espn:{matchup_id}"
    return f"week:{week}:home:{home_team_id}:away:{away_team_id}"


def _matchup_type(entry: Mapping[str, Any]) -> str:
    value = _first_text(_mapping_value(entry, "matchupType"), _mapping_value(entry, "playoffTierType"))
    if value and "PLAYOFF" in value.upper():
        return "playoff"
    if _mapping_value(entry, "playoffTierType") not in (None, "NONE"):
        return "playoff"
    return "regular"


def _winner_team_id(
    entry: Mapping[str, Any],
    home_team_id: str,
    away_team_id: str,
    home_score: Decimal | None,
    away_score: Decimal | None,
) -> str | None:
    winner = _first_text(_mapping_value(entry, "winner"), _mapping_value(entry, "winnerTeamId"))
    if winner == "HOME":
        return home_team_id
    if winner == "AWAY":
        return away_team_id
    if winner in {home_team_id, away_team_id}:
        return winner
    if home_score is None or away_score is None or home_score == away_score:
        return None
    return home_team_id if home_score > away_score else away_team_id


def _bool_from_status(value: Any) -> bool:
    return value not in (None, "", "UNDECIDED")


def _build_player_index(
    *payloads: Mapping[str, Any] | Sequence[Any] | None,
) -> dict[str, Mapping[str, Any]]:
    players: dict[str, Mapping[str, Any]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            player_pool_entry = _mapping_value(value, "playerPoolEntry")
            player = _mapping_value(player_pool_entry, "player")
            if isinstance(player, Mapping):
                _add_player_index_entry(players, player)

            direct_player = _mapping_value(value, "player")
            if isinstance(direct_player, Mapping):
                _add_player_index_entry(players, direct_player)

            _add_player_index_entry(players, value)

            for child in value.values():
                visit(child)
            return

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                visit(item)

    for payload in payloads:
        visit(payload)
    return players


def _add_player_index_entry(
    players: dict[str, Mapping[str, Any]],
    player: Mapping[str, Any],
) -> None:
    player_id = _first_text(_mapping_value(player, "id"), _mapping_value(player, "playerId"))
    player_name = _first_text(
        _mapping_value(player, "fullName"),
        _mapping_value(player, "name"),
        _join_names(player),
    )
    if player_id and player_name:
        players.setdefault(player_id, player)


def _player_from_pick(
    pick: Mapping[str, Any],
    player_index: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    player_pool_entry = _mapping_value(pick, "playerPoolEntry")
    player = _mapping_value(player_pool_entry, "player")
    if isinstance(player, Mapping):
        return player
    player_id = _first_text(_mapping_value(pick, "playerId"))
    if player_id:
        indexed_player = player_index.get(player_id)
        if isinstance(indexed_player, Mapping):
            return indexed_player
    return None


def _player_name_from_pick(
    pick: Mapping[str, Any],
    player: Mapping[str, Any] | None,
    player_id: str | None,
) -> str | None:
    explicit_name = _first_text(
        _mapping_value(pick, "playerName"),
        _mapping_value(pick, "playerFullName"),
        _mapping_value(player, "fullName") if isinstance(player, Mapping) else None,
        _mapping_value(player, "name") if isinstance(player, Mapping) else None,
    )
    if explicit_name:
        return explicit_name
    if player_id:
        return f"ESPN Player {player_id}"
    return None


def _position_from_player(player: Mapping[str, Any] | None) -> str | None:
    if not isinstance(player, Mapping):
        return None
    explicit = _first_text(_mapping_value(player, "defaultPosition"), _mapping_value(player, "position"))
    if explicit:
        return explicit.upper()
    position_id = _first_int(_mapping_value(player, "defaultPositionId"))
    return _POSITION_BY_ID.get(position_id, str(position_id) if position_id is not None else None)


def _nfl_team_from_player(player: Mapping[str, Any] | None) -> str | None:
    if not isinstance(player, Mapping):
        return None
    explicit = _first_text(_mapping_value(player, "proTeam"), _mapping_value(player, "team"))
    if explicit:
        return explicit.upper()
    team_id = _first_int(_mapping_value(player, "proTeamId"))
    return _NFL_TEAM_BY_ID.get(team_id, str(team_id) if team_id is not None else None)


def _has_roster_data(rosters: Mapping[str, Any] | Sequence[Any] | None) -> bool:
    if rosters is None:
        return False
    try:
        payload = select_season_payload(rosters, 0) if isinstance(rosters, list) else rosters
    except EspnNormalizationError:
        payload = rosters
    if not isinstance(payload, Mapping):
        return False
    scoring_periods = _mapping_value(payload, "scoringPeriods")
    return isinstance(scoring_periods, Sequence) and len(scoring_periods) > 0


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mapping_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, Mapping) else None


def _text_value(value: Any, key: str) -> str | None:
    return _first_text(_mapping_value(value, key))


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _parse_int(value)
        if parsed is not None:
            return parsed
    return None


def _int_value(value: Any, key: str) -> int | None:
    return _parse_int(_mapping_value(value, key))


def _parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_value(value: Any, key: str) -> Decimal | None:
    raw_value = _mapping_value(value, key)
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        return Decimal(str(raw_value))
    except Exception:
        return None


def _timestamp_value(value: int | None) -> datetime | None:
    if value is None:
        return None
    timestamp = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _join_names(member: Mapping[str, Any]) -> str | None:
    return _first_text(
        " ".join(
            part
            for part in (
                _first_text(_mapping_value(member, "firstName")),
                _first_text(_mapping_value(member, "lastName")),
            )
            if part
        )
    )


def _normalize_display_name(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = _MULTI_SPACE_PATTERN.sub(" ", text)
    return text.strip()
