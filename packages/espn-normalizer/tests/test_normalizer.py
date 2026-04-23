from decimal import Decimal

import pytest
from leaguebrief_espn_normalizer import (
    EspnNormalizationError,
    normalize_espn_season,
    select_season_payload,
)


def test_select_season_payload_handles_legacy_history_array():
    payload = [{"seasonId": 2021, "settings": {}}, {"status": {"seasonId": 2022}, "teams": []}]

    assert select_season_payload(payload, 2022) == {"status": {"seasonId": 2022}, "teams": []}


def test_select_season_payload_raises_when_legacy_season_is_missing():
    with pytest.raises(EspnNormalizationError):
        select_season_payload([{"seasonId": 2021}], 2022)


def test_normalize_espn_season_extracts_core_tables_from_modern_payloads():
    normalized = normalize_espn_season(
        season=2024,
        league_meta=_league_meta(),
        matchups=_matchups(),
        draft=_draft(),
        rosters=_rosters(),
    )

    assert normalized.season_year == 2024
    assert normalized.team_count == 2
    assert normalized.regular_season_weeks == 14
    assert normalized.playoff_weeks == 3
    assert normalized.import_status == "complete"
    assert normalized.champion_external_team_id == "1"
    assert normalized.runner_up_external_team_id == "2"
    assert [manager.external_manager_id for manager in normalized.managers] == [
        "owner-1",
        "owner-2",
    ]
    assert normalized.teams[0].team_name == "Alpha Dogs"
    assert normalized.teams[0].points_for == Decimal("1200.5")
    assert normalized.matchups[0].source_key == "espn:matchup-1"
    assert normalized.matchups[0].winner_external_team_id == "1"
    assert normalized.weekly_team_scores[0].actual_points == Decimal("111.2")
    assert normalized.draft is not None
    assert normalized.draft.pick_count == 2
    assert normalized.draft.picks[0].player_name == "Christian McCaffrey"
    assert normalized.draft.picks[0].position == "RB"


def test_normalize_espn_season_skips_malformed_matchups():
    payload = _matchups()
    payload["schedule"].append({"id": "bad", "home": {"teamId": 1}})

    normalized = normalize_espn_season(
        season=2024,
        league_meta=_league_meta(),
        matchups=payload,
    )

    assert len(normalized.matchups) == 1
    assert normalized.skipped_matchup_count == 1
    assert normalized.coverage.has_draft_data is False
    assert normalized.coverage.has_roster_data is False
    assert normalized.import_status == "partial"


def test_normalize_espn_season_resolves_id_only_draft_picks_from_rosters():
    normalized = normalize_espn_season(
        season=2024,
        league_meta=_league_meta(),
        matchups=_matchups(),
        draft={
            "draftDetail": {
                "picks": [
                    {
                        "overallPickNumber": 1,
                        "roundId": 1,
                        "roundPickNumber": 1,
                        "teamId": 1,
                        "playerId": 4429795,
                    }
                ]
            }
        },
        rosters={
            "leagueId": "123",
            "season": 2024,
            "snapshotType": "rosters",
            "scoringPeriods": [
                {
                    "scoringPeriodId": 1,
                    "payload": {
                        "teams": [
                            {
                                "id": 1,
                                "roster": {
                                    "entries": [
                                        {
                                            "playerId": 4429795,
                                            "playerPoolEntry": {
                                                "player": {
                                                    "id": 4429795,
                                                    "fullName": "Jahmyr Gibbs",
                                                    "defaultPositionId": 2,
                                                    "proTeamId": 8,
                                                }
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            ],
        },
    )

    assert normalized.draft is not None
    assert normalized.coverage.has_draft_data is True
    assert normalized.draft.picks[0].player_name == "Jahmyr Gibbs"
    assert normalized.draft.picks[0].position == "RB"
    assert normalized.draft.picks[0].nfl_team == "DET"


def test_normalize_espn_season_preserves_id_only_draft_picks_without_player_index():
    normalized = normalize_espn_season(
        season=2024,
        league_meta=_league_meta(),
        matchups=_matchups(),
        draft={
            "draftDetail": {
                "picks": [
                    {
                        "overallPickNumber": 1,
                        "roundId": 1,
                        "roundPickNumber": 1,
                        "teamId": 1,
                        "playerId": 999999,
                    }
                ]
            }
        },
    )

    assert normalized.draft is not None
    assert normalized.draft.picks[0].player_name == "ESPN Player 999999"
    assert normalized.draft.picks[0].player_external_id == "999999"


def test_normalize_espn_season_requires_matchups():
    with pytest.raises(EspnNormalizationError):
        normalize_espn_season(
            season=2024,
            league_meta=_league_meta(),
            matchups={"schedule": []},
        )


def _league_meta():
    return {
        "seasonId": 2024,
        "settings": {
            "size": 2,
            "scheduleSettings": {"matchupPeriodCount": 14},
        },
        "status": {"finalScoringPeriod": 17},
        "members": [
            {"id": "owner-1", "displayName": "Alice Example"},
            {"id": "owner-2", "firstName": "Bob", "lastName": "Example"},
        ],
        "teams": [
            {
                "id": 1,
                "owners": ["owner-1"],
                "location": "Alpha",
                "nickname": "Dogs",
                "abbrev": "ALP",
                "record": {
                    "overall": {
                        "wins": 10,
                        "losses": 4,
                        "ties": 0,
                        "pointsFor": 1200.5,
                        "pointsAgainst": 1110.25,
                    }
                },
                "rankCalculatedFinal": 1,
                "playoffSeed": 1,
            },
            {
                "id": 2,
                "owners": ["owner-2"],
                "location": "Beta",
                "nickname": "Cats",
                "record": {"overall": {"wins": 7, "losses": 7, "ties": 0}},
                "rankCalculatedFinal": 2,
                "playoffSeed": 2,
            },
        ],
    }


def _matchups():
    return {
        "schedule": [
            {
                "id": "matchup-1",
                "matchupPeriodId": 1,
                "home": {"teamId": 1, "totalPoints": 111.2},
                "away": {"teamId": 2, "totalPoints": 100.0},
                "winner": "HOME",
            }
        ]
    }


def _draft():
    return {
        "settings": {"draftSettings": {"type": "SNAKE", "date": 1725058800000}},
        "draftDetail": {
            "picks": [
                {
                    "overallPickNumber": 1,
                    "roundId": 1,
                    "roundPickNumber": 1,
                    "teamId": 1,
                    "playerId": 123,
                    "playerPoolEntry": {
                        "player": {
                            "id": 123,
                            "fullName": "Christian McCaffrey",
                            "defaultPositionId": 2,
                            "proTeamId": 25,
                        }
                    },
                },
                {
                    "overallPickNumber": 2,
                    "teamId": 2,
                    "playerPoolEntry": {
                        "player": {
                            "fullName": "CeeDee Lamb",
                            "defaultPositionId": 3,
                            "proTeamId": 6,
                        }
                    },
                },
            ]
        },
    }


def _rosters():
    return {
        "leagueId": "123",
        "season": 2024,
        "snapshotType": "rosters",
        "scoringPeriods": [{"scoringPeriodId": 1, "payload": {"teams": []}}],
    }
