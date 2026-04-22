import json
from urllib.parse import parse_qs, urlparse

import pytest
from leaguebrief_espn_adapter import (
    EspnAuthenticationError,
    EspnCredentials,
    EspnFantasyClient,
    EspnJsonError,
    HttpResponse,
)


class _FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, query, headers, timeout):
        self.requests.append(
            {
                "url": url,
                "query": tuple(query),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if response.url == "":
            full_url = url + ("?" + "&".join(f"{k}={v}" for k, v in query) if query else "")
            return HttpResponse(response.status_code, response.headers, response.body, full_url)
        return response


def test_modern_snapshot_uses_season_endpoint_repeated_view_params_and_cookies():
    transport = _FakeTransport([_json_response({"draftDetail": {}})])
    client = EspnFantasyClient(transport=transport, base_url="https://example.test")

    client.fetch_draft(
        "12345",
        2020,
        EspnCredentials(espn_s2="secret-s2", swid="{secret-swid}"),
    )

    request = transport.requests[0]
    assert request["url"] == (
        "https://example.test/apis/v3/games/ffl/seasons/2020/segments/0/leagues/12345"
    )
    assert request["query"] == (("view", "mDraftDetail"),)
    assert request["headers"]["Cookie"] == "espn_s2=secret-s2; SWID={secret-swid}"


def test_legacy_snapshot_uses_league_history_endpoint_with_season_id():
    transport = _FakeTransport([_json_response([{"settings": {}}])])
    client = EspnFantasyClient(transport=transport, base_url="https://example.test")

    client.fetch_league_meta("12345", 2017)

    request = transport.requests[0]
    assert request["url"] == "https://example.test/apis/v3/games/ffl/leagueHistory/12345"
    assert request["query"] == (
        ("view", "mSettings"),
        ("view", "mStatus"),
        ("view", "mTeam"),
        ("seasonId", "2017"),
    )


def test_fetch_rosters_wraps_weekly_payloads_in_one_envelope():
    transport = _FakeTransport(
        [
            _json_response({"teams": [{"id": 1}]}),
            _json_response({"teams": [{"id": 2}]}),
        ]
    )
    client = EspnFantasyClient(transport=transport, base_url="https://example.test")

    response = client.fetch_rosters("12345", 2024, (1, 2))

    assert response.payload == {
        "leagueId": "12345",
        "season": 2024,
        "snapshotType": "rosters",
        "scoringPeriods": [
            {"scoringPeriodId": 1, "payload": {"teams": [{"id": 1}]}},
            {"scoringPeriodId": 2, "payload": {"teams": [{"id": 2}]}},
        ],
    }
    assert [request["query"][-1] for request in transport.requests] == [
        ("scoringPeriodId", "1"),
        ("scoringPeriodId", "2"),
    ]


def test_discover_seasons_reads_history_endpoint():
    transport = _FakeTransport(
        [_json_response([{"seasonId": 2016}, {"seasonId": 2020}, {"status": {"seasonId": 2017}}])]
    )
    client = EspnFantasyClient(transport=transport, base_url="https://example.test")

    assert client.discover_seasons("12345") == (2016, 2017, 2020)
    assert transport.requests[0]["url"] == (
        "https://example.test/apis/v3/games/ffl/leagueHistory/12345"
    )


def test_authentication_errors_do_not_include_cookie_values():
    transport = _FakeTransport([HttpResponse(401, {}, b'{"message":"no"}', "")])
    client = EspnFantasyClient(transport=transport, base_url="https://example.test")

    with pytest.raises(EspnAuthenticationError) as exc_info:
        client.fetch_matchups("12345", 2024, EspnCredentials("secret-s2", "{secret-swid}"))

    assert "secret" not in str(exc_info.value)


def test_invalid_json_raises_safe_json_error():
    transport = _FakeTransport([HttpResponse(200, {}, b"not json", "")])
    client = EspnFantasyClient(transport=transport, base_url="https://example.test")

    with pytest.raises(EspnJsonError):
        client.fetch_matchups("12345", 2024)


def test_response_url_contains_repeated_view_query_params():
    transport = _FakeTransport([_json_response({"settings": {}})])
    client = EspnFantasyClient(transport=transport, base_url="https://example.test")

    response = client.fetch_league_meta("12345", 2024)

    parsed = urlparse(response.url)
    assert parse_qs(parsed.query)["view"] == ["mSettings", "mStatus", "mTeam"]


def _json_response(payload):
    return HttpResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
        url="",
    )
