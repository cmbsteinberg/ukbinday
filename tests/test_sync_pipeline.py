"""Regression tests for council matching in the scraper sync pipeline."""

import json
from pathlib import Path

import pytest

from pipeline import sync_all
from pipeline.shared import normalise_council_name

pytestmark = pytest.mark.ci


def test_lad_list_adds_councils_missing_from_ukbcd():
    input_data = {
        "CamdenCouncil": {"url": "https://www.camden.gov.uk/bin-collections"}
    }
    lad_data = json.loads(sync_all.LAD_BASE_PATH.read_text())

    input_ids = sync_all.build_needed_identifiers(input_data)
    lad_ids = sync_all.build_lad_identifiers(lad_data)

    assert "westminster" not in input_ids
    assert "westminster" in lad_ids
    assert "towerhamlets" in lad_ids
    assert "northyorks" in lad_ids


def test_filter_keeps_lad_scraper_and_removes_unknown_council(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "hacs_westminster_gov_uk.py").write_text(
        'TITLE = "Westminster City Council"\nURL = "https://westminster.gov.uk"\n'
    )
    unknown = tmp_path / "hacs_unknown_gov_uk.py"
    unknown.write_text(
        'TITLE = "Unknown Council"\nURL = "https://unknown.gov.uk"\n'
    )
    lad_data = json.loads(sync_all.LAD_BASE_PATH.read_text())
    monkeypatch.setattr(sync_all, "SCRAPERS_DIR", tmp_path)

    removed = sync_all.filter_hacs_scrapers(
        sync_all.build_lad_identifiers(lad_data)
    )

    assert (tmp_path / "hacs_westminster_gov_uk.py").exists()
    assert removed == ["hacs_unknown_gov_uk"]
    assert not unknown.exists()


def test_retained_hacs_scraper_takes_priority_over_ukbcd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    (scrapers_dir / "hacs_westminster_gov_uk.py").write_text(
        'TITLE = "Westminster City Council"\nURL = "https://westminster.gov.uk"\n'
    )
    lad_base_path = tmp_path / "lad_base.json"
    lad_base_path.write_text(
        json.dumps(
            {
                "E09000033": {
                    "name": "Westminster",
                    "govuk_url": "http://cleanstreets.westminster.gov.uk/",
                }
            }
        )
    )
    scraper_map_path = tmp_path / "scraper_lad_map.json"
    scraper_map_path.write_text(
        json.dumps(
            {
                "E09000033": {
                    "scraper_id": "ukbcd_google_public_calendar_council",
                    "url": "https://calendar.google.com/example.ics",
                }
            }
        )
    )
    monkeypatch.setattr(sync_all, "SCRAPERS_DIR", scrapers_dir)
    monkeypatch.setattr(sync_all, "LAD_BASE_PATH", lad_base_path)
    monkeypatch.setattr(sync_all, "SCRAPER_LAD_MAP_PATH", scraper_map_path)

    sync_all._wire_lad_hacs_scrapers()

    assert json.loads(scraper_map_path.read_text())["E09000033"] == {
        "scraper_id": "hacs_westminster_gov_uk",
        "url": "https://westminster.gov.uk",
    }


def test_council_normalisation_never_discards_entire_name():
    assert normalise_council_name("City of London") == "cityoflondon"
