from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

FANTASYPROS_MIN_SEASON = 2015
FANTASYPROS_SOURCE = "fantasypros"
FANTASYPROS_FILE_TYPE = "adp"
FANTASYPROS_RANKING_TYPE = "adp"
FANTASYPROS_RANKING_FORMAT = "overall"

_FILENAME_PATTERN = re.compile(
    r"^FantasyPros_(?P<season>\d{4})_Overall_ADP_Rankings-(?P<suffix>STD|HALF|PPR)\.csv$"
)
_SCORING_BY_SUFFIX = {
    "STD": "standard",
    "HALF": "half_ppr",
    "PPR": "ppr",
}
_SCORING_ORDER = {
    "standard": 0,
    "half_ppr": 1,
    "ppr": 2,
}
_SUFFIX_PATTERN = re.compile(r"\b(jr|sr|ii|iii|iv)\b", flags=re.IGNORECASE)
_NON_ALNUM_SPACE_PATTERN = re.compile(r"[^a-z0-9\s]", flags=re.IGNORECASE)
_MULTI_SPACE_PATTERN = re.compile(r"\s+")
_POSITION_PATTERN = re.compile(r"^(?P<position>[A-Za-z/]+)\s*(?P<rank>\d+)?$")


class FantasyProsCsvError(ValueError):
    """Raised when a FantasyPros CSV file cannot be parsed safely."""


@dataclass(frozen=True)
class FantasyProsReferenceFile:
    path: Path
    season: int
    scoring: str
    scoring_suffix: str

    @property
    def package_relative_path(self) -> str:
        return f"adpreferences/{self.path.name}"


@dataclass(frozen=True)
class FantasyProsRankingItem:
    rank_value: Decimal | None
    adp_value: Decimal | None
    adp_source: str | None
    position_rank: int | None
    raw_player_name: str
    normalized_player_name: str
    raw_team: str | None
    raw_position: str | None
    base_position: str | None


@dataclass(frozen=True)
class ParsedFantasyProsAdp:
    reference: FantasyProsReferenceFile
    source_hash: str
    version_label: str
    published_label: str
    items: tuple[FantasyProsRankingItem, ...]
    source: str = FANTASYPROS_SOURCE
    file_type: str = FANTASYPROS_FILE_TYPE
    ranking_type: str = FANTASYPROS_RANKING_TYPE
    ranking_format: str = FANTASYPROS_RANKING_FORMAT


def discover_adp_files(root: str | Path) -> tuple[FantasyProsReferenceFile, ...]:
    """Return all supported FantasyPros ADP CSVs in deterministic import order."""

    root_path = Path(root)
    if not root_path.exists():
        raise FantasyProsCsvError(f"FantasyPros CSV directory does not exist: {root_path}")
    references: list[FantasyProsReferenceFile] = []
    for path in root_path.glob("FantasyPros_*_Overall_ADP_Rankings-*.csv"):
        try:
            reference = parse_reference_filename(path)
        except FantasyProsCsvError:
            continue
        if reference.season >= FANTASYPROS_MIN_SEASON:
            references.append(reference)
    return tuple(
        sorted(
            references,
            key=lambda reference: (
                reference.season,
                _SCORING_ORDER[reference.scoring],
                reference.path.name,
            ),
        )
    )


def parse_reference_filename(path: str | Path) -> FantasyProsReferenceFile:
    file_path = Path(path)
    match = _FILENAME_PATTERN.match(file_path.name)
    if match is None:
        raise FantasyProsCsvError(f"Unsupported FantasyPros ADP filename: {file_path.name}")

    season = int(match.group("season"))
    scoring_suffix = match.group("suffix")
    if season < FANTASYPROS_MIN_SEASON:
        raise FantasyProsCsvError("FantasyPros ADP seasons before 2015 are unsupported.")

    return FantasyProsReferenceFile(
        path=file_path,
        season=season,
        scoring=_SCORING_BY_SUFFIX[scoring_suffix],
        scoring_suffix=scoring_suffix,
    )


def parse_adp_csv(path: str | Path) -> ParsedFantasyProsAdp:
    reference = parse_reference_filename(path)
    payload = reference.path.read_bytes()
    source_hash = hashlib.sha256(payload).hexdigest()
    rows = csv.reader(payload.decode("utf-8-sig").splitlines())

    try:
        header = next(rows)
    except StopIteration as exc:
        raise FantasyProsCsvError(f"FantasyPros ADP CSV is empty: {reference.path.name}") from exc

    header_index = {name.strip(): index for index, name in enumerate(header)}
    if "Player" not in header_index or "Rank" not in header_index or "POS" not in header_index:
        raise FantasyProsCsvError(
            f"FantasyPros ADP CSV is missing required columns: {reference.path.name}"
        )
    if "AVG" not in header_index and "ESPN" not in header_index:
        raise FantasyProsCsvError(
            f"FantasyPros ADP CSV must include ESPN or AVG ADP: {reference.path.name}"
        )

    items: list[FantasyProsRankingItem] = []
    for row_number, row in enumerate(rows, start=2):
        repaired = _repair_row(row, len(header), reference.path.name, row_number)
        if repaired is None:
            continue
        raw_player_name = _clean_text(_cell(repaired, header_index["Player"]))
        if not raw_player_name:
            continue

        raw_position = _clean_text(_cell(repaired, header_index["POS"]))
        base_position, position_rank = _parse_position(raw_position)
        adp_value, adp_source = _select_adp_value(repaired, header_index)
        item = FantasyProsRankingItem(
            rank_value=_parse_decimal(_cell(repaired, header_index["Rank"])),
            adp_value=adp_value,
            adp_source=adp_source,
            position_rank=position_rank,
            raw_player_name=raw_player_name,
            normalized_player_name=normalize_player_name(raw_player_name),
            raw_team=_clean_optional_text(_cell(repaired, header_index.get("Team"))),
            raw_position=raw_position or None,
            base_position=base_position,
        )
        items.append(item)

    hash_prefix = source_hash[:12]
    return ParsedFantasyProsAdp(
        reference=reference,
        source_hash=source_hash,
        version_label=f"{reference.scoring}:{hash_prefix}",
        published_label=f"{reference.path.stem}@{hash_prefix}",
        items=tuple(items),
    )


def select_reference_for_scoring(
    references: Iterable[FantasyProsReferenceFile],
    season: int,
    scoring: str | None,
) -> FantasyProsReferenceFile | None:
    requested_scoring = _normalize_scoring(scoring)
    candidates = {
        reference.scoring: reference for reference in references if reference.season == season
    }
    scoring_order = (
        ("half_ppr", "ppr") if requested_scoring == "half_ppr" else (requested_scoring,)
    )
    for candidate_scoring in scoring_order:
        candidate = candidates.get(candidate_scoring)
        if candidate is not None:
            return candidate
    return None


def normalize_player_name(name: str | None) -> str:
    """Normalize player names for robust joins across ESPN and FantasyPros data."""

    if name is None:
        return ""
    text = unicodedata.normalize("NFKD", str(name).strip())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = _NON_ALNUM_SPACE_PATTERN.sub("", text)
    text = _SUFFIX_PATTERN.sub("", text)
    text = _MULTI_SPACE_PATTERN.sub(" ", text)
    return text.strip()


def _repair_row(
    row: Sequence[str],
    expected_width: int,
    filename: str,
    row_number: int,
) -> list[str] | None:
    if not row or not any(cell.strip() for cell in row):
        return None
    if len(row) == expected_width:
        return list(row)

    if (
        len(row) == expected_width + 2
        and len(row) >= 7
        and row[2] == ""
        and row[3].lstrip().startswith("'")
    ):
        repaired = [row[0], f"{row[1]}{row[3]}", row[4], row[5], *row[6:]]
        if len(repaired) == expected_width:
            return repaired

    raise FantasyProsCsvError(
        f"Unexpected CSV shape in {filename} at row {row_number}: "
        f"expected {expected_width} columns, found {len(row)}."
    )


def _select_adp_value(
    row: Sequence[str],
    header_index: dict[str, int],
) -> tuple[Decimal | None, str | None]:
    espn_value = _parse_decimal(_cell(row, header_index.get("ESPN")))
    if espn_value is not None:
        return espn_value, "ESPN"
    avg_value = _parse_decimal(_cell(row, header_index.get("AVG")))
    if avg_value is not None:
        return avg_value, "AVG"
    return None, None


def _parse_position(raw_position: str | None) -> tuple[str | None, int | None]:
    if not raw_position:
        return None, None
    match = _POSITION_PATTERN.match(raw_position.strip())
    if match is None:
        return raw_position.strip().upper(), None

    base_position = match.group("position").upper()
    if base_position in {"D/ST", "DEF"}:
        base_position = "DST"
    rank_text = match.group("rank")
    return base_position, int(rank_text) if rank_text else None


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text or text.upper() in {"NA", "N/A", "-", "--"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _normalize_scoring(scoring: str | None) -> str:
    if scoring is None:
        return "standard"
    value = scoring.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "std": "standard",
        "standard": "standard",
        "non_ppr": "standard",
        "half": "half_ppr",
        "half_ppr": "half_ppr",
        "0.5_ppr": "half_ppr",
        "ppr": "ppr",
        "full_ppr": "ppr",
    }
    if value not in aliases:
        raise FantasyProsCsvError(f"Unsupported scoring type: {scoring}")
    return aliases[value]


def _cell(row: Sequence[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    return row[index]


def _clean_text(value: str | None) -> str:
    return "" if value is None else value.strip()


def _clean_optional_text(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    return cleaned or None
