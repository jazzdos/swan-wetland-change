"""The newest public-release licence note agrees with data/SOURCES.md.

The note is docs/research/<date>-public-release-licences.md (st-1a9c, ADR 0011
step 2). These tests check its structure and that every data/SOURCES.md row it
covers has the same licence and redistribute_public value. A note with a later
date supersedes an earlier one. Writer citations are pinned to the commit the
note names; a renamed writer file needs the citation updated or a newer note.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
RESEARCH: Final = REPO / "docs" / "research"
SOURCES: Final = REPO / "data" / "SOURCES.md"
NOTE_NAME: Final = re.compile(r"\d{4}-\d{2}-\d{2}-public-release-licences\.md")
DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
DBCA: Final = "DBCA-010 Ramsar Sites"

# data/SOURCES.md rows whose data reaches an object in the output store.
REQUIRED_SOURCES: Final = (
    "Earth Search sentinel-2-c1-l2a",
    DBCA,
    "DEA Waterbodies v3 (Swan subset)",
    "DEA Sentinel-2 ARD NBART (ga_s2am_ard_3, ga_s2bm_ard_3, ga_s2cm_ard_3)",
    "DEA Waterbodies v3 per-lake CSV time series",
    "DEA Sentinel-2 Water Observations (ga_s2_wo_provisional_3)",
    "Planetary Computer sentinel-2-l2a (pixel identity reference)",
    "Copernicus Data Space STAC sentinel-2-l2a (discovery and freshness counts)",
)
PUBLISHED_KINDS: Final = (
    "observation Parquet",
    "change rows",
    "STAC catalog",
    "STAC collection",
    "STAC items",
    "run manifests",
    "ledger",
    "verification JSON",
)
JUDGED_COLUMNS: Final = (
    "CC BY-SA 4.0 attribution",
    "CC BY-SA 4.0 ShareAlike",
    "CC BY 4.0 attribution",
    "Copernicus notice",
)
JUDGEMENT: Final = re.compile(r"met|n/a|unmet \(T\d+(?:, T\d+)*\)")
TERM_ID: Final = re.compile(r"T\d+")
STORY_ID: Final = re.compile(r"st-[0-9a-f]{4}")
DEFERRED: Final = "deferred: question to Jarrod"
PROMOTED: Final = re.compile(r"^Promoted: (yes|no) \(([0-3]) of 3\)$", re.MULTILINE)
CITATION: Final = re.compile(r"(src/wetland_change/[\w/]+\.py):(\d+)")


def latest_note() -> Path:
    notes = sorted(p for p in RESEARCH.iterdir() if NOTE_NAME.fullmatch(p.name))
    assert notes, "no docs/research/<date>-public-release-licences.md"
    return notes[-1]


def note_text() -> str:
    return latest_note().read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    marker = f"\n## {heading}\n"
    assert marker in text, f"missing section '## {heading}'"
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def table(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.startswith("|")]
    assert len(lines) >= 2, "no table"
    header = [cell.strip() for cell in lines[0].strip().strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == len(header), line
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def dataset_rows() -> list[dict[str, str]]:
    return table(section(note_text(), "Datasets in published files"))


def published_rows() -> list[dict[str, str]]:
    return table(section(note_text(), "Published files"))


def unmet_rows() -> list[dict[str, str]]:
    return table(section(note_text(), "Unmet terms"))


def promotion() -> tuple[bool, int]:
    match = PROMOTED.search(section(note_text(), "DBCA-010 licence claim"))
    assert match, "no 'Promoted: yes|no (N of 3)' line"
    return match.group(1) == "yes", int(match.group(2))


def test_note_is_dated_and_has_no_em_dash() -> None:
    assert NOTE_NAME.fullmatch(latest_note().name)
    assert "\u2014" not in note_text()


def test_note_covers_every_dataset_that_reaches_a_published_file() -> None:
    names = [row["SOURCES.md source"] for row in dataset_rows()]
    assert len(names) == len(set(names))
    assert [name for name in REQUIRED_SOURCES if name not in names] == []


def test_dataset_rows_name_licence_primary_source_and_fetch_date() -> None:
    for row in dataset_rows():
        name = row["SOURCES.md source"]
        assert row["licence"], name
        assert row["redistribute_public"], name
        assert "https://" in row["primary source"], name
        assert DATE.fullmatch(row["fetched"]), name


def test_note_licence_and_redistribute_public_match_sources() -> None:
    sources = {row["source"]: row for row in table(SOURCES.read_text(encoding="utf-8"))}
    for row in dataset_rows():
        name = row["SOURCES.md source"]
        assert name in sources, name
        assert row["licence"] == sources[name]["licence"], name
        assert row["redistribute_public"] == sources[name]["redistribute_public"], name


def test_rows_not_true_are_named_blocking() -> None:
    blocking = section(note_text(), "Blocking")
    for row in dataset_rows():
        if row["redistribute_public"] != "true":
            assert row["SOURCES.md source"] in blocking


def test_three_claim_verdicts_with_source_urls_and_promotion_count() -> None:
    rows = table(section(note_text(), "DBCA-010 licence claim"))
    assert [row["verifier"] for row in rows] == ["1", "2", "3"]
    for row in rows:
        assert row["verdict"] in {"confirmed", "not confirmed"}
        assert "https://" in row["source URL"]
        assert DATE.fullmatch(row["fetched"])
    promoted, confirmed = promotion()
    assert confirmed == sum(row["verdict"] == "confirmed" for row in rows)
    assert promoted == (confirmed >= 2)


def test_promotion_outcome_is_reflected_in_sources_and_stories() -> None:
    promoted, _ = promotion()
    stories = [row["story"] for row in unmet_rows()]
    if promoted:
        assert DEFERRED not in stories
        return
    dbca = next(row for row in dataset_rows() if row["SOURCES.md source"] == DBCA)
    assert dbca["redistribute_public"] != "true"
    assert DBCA in section(note_text(), "Blocking")
    assert section(note_text(), "Question for Jarrod").strip() not in {"", "None."}


def test_every_published_file_kind_is_judged_with_a_writer_citation() -> None:
    rows = published_rows()
    kinds = [row["file kind"] for row in rows]
    assert [kind for kind in PUBLISHED_KINDS if kind not in kinds] == []
    for row in rows:
        citations = CITATION.findall(row["writer"])
        assert citations, row["file kind"]
        for path, _line in citations:
            assert (REPO / path).is_file(), path
        for column in JUDGED_COLUMNS:
            assert JUDGEMENT.fullmatch(row[column]), (row["file kind"], column)


def test_every_unmet_term_is_referenced_and_has_a_story_or_a_deferral() -> None:
    rows = unmet_rows()
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    referenced = {
        term
        for row in published_rows()
        for column in JUDGED_COLUMNS
        for term in TERM_ID.findall(row[column])
    }
    assert referenced == set(ids)
    for row in rows:
        story = row["story"]
        assert STORY_ID.fullmatch(story) or story == DEFERRED, row["id"]
