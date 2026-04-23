from decimal import Decimal

import pytest
from leaguebrief_fantasypros_adapter import (
    FantasyProsCsvError,
    FantasyProsReferenceFile,
    discover_adp_files,
    normalize_player_name,
    parse_adp_csv,
    parse_reference_filename,
    select_reference_for_scoring,
)


def test_parse_reference_filename_maps_scoring():
    reference = parse_reference_filename("FantasyPros_2024_Overall_ADP_Rankings-HALF.csv")

    assert reference.season == 2024
    assert reference.scoring == "half_ppr"
    assert reference.package_relative_path == (
        "adpreferences/FantasyPros_2024_Overall_ADP_Rankings-HALF.csv"
    )


def test_parse_reference_filename_rejects_pre_2015():
    with pytest.raises(FantasyProsCsvError):
        parse_reference_filename("FantasyPros_2014_Overall_ADP_Rankings-PPR.csv")


def test_parse_adp_csv_prefers_espn_adp_over_avg(tmp_path):
    path = tmp_path / "FantasyPros_2024_Overall_ADP_Rankings-PPR.csv"
    path.write_text(
        "\n".join(
            [
                '"Rank","Player","Team","Bye","POS","ESPN","AVG"',
                '"1","Christian McCaffrey","SF","9","RB1","2.0","1.3"',
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_adp_csv(path)

    assert parsed.reference.scoring == "ppr"
    assert parsed.file_type == "adp"
    assert parsed.ranking_type == "adp"
    assert parsed.ranking_format == "overall"
    assert parsed.items[0].adp_value == Decimal("2.0")
    assert parsed.items[0].adp_source == "ESPN"
    assert parsed.items[0].base_position == "RB"
    assert parsed.items[0].position_rank == 1


def test_parse_adp_csv_uses_avg_when_espn_is_missing_or_blank(tmp_path):
    path = tmp_path / "FantasyPros_2024_Overall_ADP_Rankings-STD.csv"
    path.write_text(
        "\n".join(
            [
                '"Rank","Player","Team","Bye","POS","Sleeper","AVG"',
                '"7","Ja\'Marr Chase","CIN","10","WR4","","8.4"',
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_adp_csv(path)

    assert parsed.reference.scoring == "standard"
    assert parsed.items[0].adp_value == Decimal("8.4")
    assert parsed.items[0].adp_source == "AVG"


def test_parse_adp_csv_repairs_apostrophe_split_rows_and_skips_blank_footers(tmp_path):
    path = tmp_path / "FantasyPros_2015_Overall_ADP_Rankings-PPR.csv"
    path.write_text(
        "\n".join(
            [
                '"Rank","Player","Team","Bye","POS","Sleeper","RTSports","AVG"',
                '"2","Le","","\'Veon Bell","","","RB2","","","3.0"',
                '""',
                "",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_adp_csv(path)

    assert len(parsed.items) == 1
    assert parsed.items[0].raw_player_name == "Le'Veon Bell"
    assert parsed.items[0].normalized_player_name == "leveon bell"
    assert parsed.items[0].base_position == "RB"
    assert parsed.items[0].position_rank == 2
    assert parsed.items[0].adp_value == Decimal("3.0")


def test_normalize_player_name_handles_suffixes_and_special_characters():
    assert normalize_player_name("Patrick Mahomes II") == "patrick mahomes"
    assert normalize_player_name("Michael Pittman Jr.") == "michael pittman"
    assert normalize_player_name("Kenneth Walker III") == "kenneth walker"
    assert normalize_player_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_player_name("Amon-Ra St. Brown") == "amonra st brown"
    assert normalize_player_name("D.J. Moore") == "dj moore"
    assert normalize_player_name("José Núñez IV") == "jose nunez"


def test_discover_and_select_reference_for_scoring(tmp_path):
    for filename in [
        "FantasyPros_2017_Overall_ADP_Rankings-PPR.csv",
        "FantasyPros_2017_Overall_ADP_Rankings-STD.csv",
        "FantasyPros_2018_Overall_ADP_Rankings-HALF.csv",
        "FantasyPros_2018_Overall_ADP_Rankings-PPR.csv",
    ]:
        (tmp_path / filename).write_text('"Rank","Player","POS","AVG"\n', encoding="utf-8")

    references = discover_adp_files(tmp_path)

    assert [reference.scoring for reference in references] == [
        "standard",
        "ppr",
        "half_ppr",
        "ppr",
    ]
    assert select_reference_for_scoring(references, 2017, "half_ppr").scoring == "ppr"
    assert select_reference_for_scoring(references, 2018, "half_ppr").scoring == "half_ppr"
    assert select_reference_for_scoring(references, 2018, "standard") is None


def test_select_reference_rejects_unknown_scoring():
    references = [
        FantasyProsReferenceFile(
            path=parse_reference_filename("FantasyPros_2024_Overall_ADP_Rankings-PPR.csv").path,
            season=2024,
            scoring="ppr",
            scoring_suffix="PPR",
        )
    ]

    with pytest.raises(FantasyProsCsvError):
        select_reference_for_scoring(references, 2024, "superflex")
