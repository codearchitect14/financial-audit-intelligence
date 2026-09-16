"""Ingestion tests.

The parser tests build a synthetic DERA archive in a temp directory, so they
run without network access and without a 200MB download. The fixture reproduces
the conventions that make real DERA data hard to parse: restated comparatives,
mixed ``qtrs`` spans, competing revenue tags, and non-USD units.
"""

from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fai.db.models.enums import FilingType, FiscalPeriod, StatementSection
from fai.ingestion.aaer import AaerLabelIndex, load_aaer_mapping
from fai.ingestion.pipeline import Quarter
from fai.ingestion.sec_dera import parse_facts, parse_submissions
from fai.ingestion.tags import WANTED_TAGS, concept_for_tag, tag_preference

SUB_HEADER = "adsh\tcik\tname\tsic\tcountryba\tform\tfy\tfp\tperiod\tfiled"
NUM_HEADER = "adsh\ttag\tddate\tqtrs\tuom\tvalue"


def _write_archive(tmp_path: Path, sub_rows: list[str], num_rows: list[str]) -> Path:
    archive = tmp_path / "2023q1.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("sub.txt", "\n".join([SUB_HEADER, *sub_rows]) + "\n")
        zf.writestr("num.txt", "\n".join([NUM_HEADER, *num_rows]) + "\n")
    return archive


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    sub_rows = [
        # A normal annual filing.
        "0000320193-23-000006\t320193\tAPPLE INC\t3571\tUS\t10-K\t2022\tFY\t20220924\t20221028",
        # A quarterly filing from another registrant.
        "0000789019-23-000010\t789019\tMSFT CORP\t7372\tUS\t10-Q\t2023\tQ2\t20221231\t20230124",
        # An 8-K: carries no financial statements and must be skipped.
        "0000111111-23-000001\t111111\tNOT A STMT CO\t1000\tUS\t8-K\t2023\tFY\t20221231\t20230105",
        # A filing with no fiscal period: cannot be placed on a timeline.
        "0000222222-23-000002\t222222\tNO PERIOD CO\t1000\tUS\t10-K\t\t\t20221231\t20230105",
    ]
    num_rows = [
        # --- Apple, annual, period end 2022-09-24 -------------------------
        # Balance sheet facts are instantaneous: qtrs = 0.
        "0000320193-23-000006\tAssets\t20220924\t0\tUSD\t352755000000",
        "0000320193-23-000006\tLiabilities\t20220924\t0\tUSD\t302083000000",
        "0000320193-23-000006\tStockholdersEquity\t20220924\t0\tUSD\t50672000000",
        "0000320193-23-000006\tAssetsCurrent\t20220924\t0\tUSD\t135405000000",
        "0000320193-23-000006\tLiabilitiesCurrent\t20220924\t0\tUSD\t153982000000",
        # Income statement facts span the year: qtrs = 4.
        "0000320193-23-000006\tRevenueFromContractWithCustomerExcludingAssessedTax\t20220924\t4\tUSD\t394328000000",
        # The same concept under a legacy tag. The catalogue prefers the
        # ASC 606 tag above, so this value must lose.
        "0000320193-23-000006\tRevenues\t20220924\t4\tUSD\t111111111111",
        "0000320193-23-000006\tNetIncomeLoss\t20220924\t4\tUSD\t99803000000",
        # A restated prior-year comparative. Same tag, earlier ddate. Must be
        # excluded, or the filing would carry the wrong year's figures.
        "0000320193-23-000006\tAssets\t20210925\t0\tUSD\t351002000000",
        # A quarterly slice inside an annual filing: wrong span, must be dropped.
        "0000320193-23-000006\tNetIncomeLoss\t20220924\t1\tUSD\t20721000000",
        # A share count, not money. Not comparable and must be dropped.
        "0000320193-23-000006\tAssets\t20220924\t0\tshares\t15943425000",
        # A tag outside the catalogue.
        "0000320193-23-000006\tSomeVendorSpecificTag\t20220924\t0\tUSD\t42",
        # --- Microsoft, quarterly, period end 2022-12-31 ------------------
        "0000789019-23-000010\tAssets\t20221231\t0\tUSD\t364840000000",
        # Quarterly filing: duration facts span one quarter, qtrs = 1.
        "0000789019-23-000010\tNetIncomeLoss\t20221231\t1\tUSD\t16425000000",
        # An annual span inside a quarterly filing: must be dropped.
        "0000789019-23-000010\tNetIncomeLoss\t20221231\t4\tUSD\t72738000000",
    ]
    return _write_archive(tmp_path, sub_rows, num_rows)


class TestParseSubmissions:
    def test_keeps_only_statement_bearing_forms(self, archive: Path) -> None:
        submissions = parse_submissions(archive)
        assert {s.accession for s in submissions} == {
            "0000320193-23-000006",
            "0000789019-23-000010",
        }

    def test_cik_is_zero_padded_to_ten_digits(self, archive: Path) -> None:
        """EDGAR and every other SEC source use the padded form; DERA does not.

        Normalising here is what lets the AAER label merge join on CIK later.
        """
        submissions = {s.accession: s for s in parse_submissions(archive)}
        assert submissions["0000320193-23-000006"].cik == "0000320193"

    def test_parses_form_period_and_dates(self, archive: Path) -> None:
        submissions = {s.accession: s for s in parse_submissions(archive)}
        apple = submissions["0000320193-23-000006"]

        assert apple.filing_type is FilingType.ANNUAL_10K
        assert apple.fiscal_period is FiscalPeriod.FY
        assert apple.fiscal_year == 2022
        assert apple.period_end_date == date(2022, 9, 24)
        assert apple.filed_date == date(2022, 10, 28)

    def test_skips_filings_without_a_fiscal_period(self, archive: Path) -> None:
        accessions = {s.accession for s in parse_submissions(archive)}
        assert "0000222222-23-000002" not in accessions


class TestParseFacts:
    @pytest.fixture
    def facts(self, archive: Path) -> dict[tuple[str, str], object]:
        submissions = {s.accession: s for s in parse_submissions(archive)}
        return {(f.accession, f.concept): f for f in parse_facts(archive, submissions)}

    def test_reads_balance_sheet_values(self, facts: dict) -> None:
        assets = facts[("0000320193-23-000006", "Assets")]
        assert assets.value == Decimal("352755000000")
        assert assets.section is StatementSection.BALANCE_SHEET
        assert assets.unit == "USD"

    def test_prefers_the_asc_606_revenue_tag(self, facts: dict) -> None:
        """A filing may report revenue under several tags. The catalogue's
        preference order must decide, deterministically."""
        revenue = facts[("0000320193-23-000006", "Revenue")]
        assert revenue.value == Decimal("394328000000")

    def test_excludes_restated_comparatives(self, facts: dict) -> None:
        """num.txt carries prior-year figures for the same tag. Only facts
        dated at the submission's own period end describe this filing."""
        assert facts[("0000320193-23-000006", "Assets")].value == Decimal("352755000000")

    def test_annual_filing_takes_the_four_quarter_span(self, facts: dict) -> None:
        net_income = facts[("0000320193-23-000006", "NetIncome")]
        assert net_income.value == Decimal("99803000000")

    def test_quarterly_filing_takes_the_one_quarter_span(self, facts: dict) -> None:
        """The same tag appears with qtrs 1 and 4 in the fixture. A 10-Q must
        take the quarter, not the trailing year."""
        net_income = facts[("0000789019-23-000010", "NetIncome")]
        assert net_income.value == Decimal("16425000000")

    def test_excludes_non_monetary_units(self, facts: dict) -> None:
        assert facts[("0000320193-23-000006", "Assets")].unit == "USD"

    def test_excludes_tags_outside_the_catalogue(self, facts: dict) -> None:
        assert not any(concept == "SomeVendorSpecificTag" for _, concept in facts)

    def test_emits_at_most_one_fact_per_concept(self, archive: Path) -> None:
        submissions = {s.accession: s for s in parse_submissions(archive)}
        seen = [(f.accession, f.concept) for f in parse_facts(archive, submissions)]
        assert len(seen) == len(set(seen))


class TestTagCatalogue:
    def test_every_catalogue_tag_resolves_to_a_concept(self) -> None:
        for tag in WANTED_TAGS:
            assert concept_for_tag(tag) is not None

    def test_preference_order_is_strict_within_a_concept(self) -> None:
        assert tag_preference("RevenueFromContractWithCustomerExcludingAssessedTax") < (
            tag_preference("Revenues")
        )

    def test_unknown_tag_has_no_concept(self) -> None:
        assert concept_for_tag("NotARealTag") is None


class TestAaerLabels:
    """The three-valued label is the part of the pipeline most likely to be got
    wrong, and getting it wrong invalidates every model metric downstream."""

    @pytest.fixture
    def index(self, tmp_path: Path) -> AaerLabelIndex:
        path = tmp_path / "map.csv"
        path.write_text(
            "cik,company_name,violation_start,violation_end,aaer_number,match_confidence\n"
            "0000000123,FRAUD CO,2015-01-01,2016-12-31,AAER-1,1.00\n"
            "0000000999,WEAK MATCH CO,2015-01-01,2016-12-31,AAER-2,0.40\n",
            encoding="utf-8",
        )
        return load_aaer_mapping(path)

    def test_filing_inside_the_window_is_positive(self, index: AaerLabelIndex) -> None:
        assert index.label("0000000123", date(2015, 12, 31)) is True

    def test_filing_outside_the_window_is_negative(self, index: AaerLabelIndex) -> None:
        """A company named in an AAER was not fraudulent in every year it filed."""
        assert index.label("0000000123", date(2020, 12, 31)) is False

    def test_unknown_company_is_unlabelled_not_negative(self, index: AaerLabelIndex) -> None:
        """NULL means unknown. The SEC prosecutes a fraction of what occurs, so
        an unprosecuted company is not evidence of innocence."""
        assert index.label("0000000456", date(2015, 12, 31)) is None

    def test_low_confidence_matches_are_ignored(self, index: AaerLabelIndex) -> None:
        """An unreviewed fuzzy match becoming a training label is worse than no
        label at all."""
        assert index.label("0000000999", date(2015, 12, 31)) is None

    def test_missing_period_end_cannot_be_labelled(self, index: AaerLabelIndex) -> None:
        assert index.label("0000000123", None) is None

    def test_absent_mapping_file_yields_an_empty_index(self, tmp_path: Path) -> None:
        index = load_aaer_mapping(tmp_path / "does-not-exist.csv")
        assert len(index) == 0
        assert index.label("0000000123", date(2015, 1, 1)) is None

    def test_rejects_a_reversed_window(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.csv"
        path.write_text(
            "cik,company_name,violation_start,violation_end,aaer_number,match_confidence\n"
            "0000000123,BACKWARDS CO,2016-12-31,2015-01-01,AAER-3,1.00\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="precedes"):
            load_aaer_mapping(path)

    def test_rejects_a_file_missing_required_columns(self, tmp_path: Path) -> None:
        path = tmp_path / "short.csv"
        path.write_text("cik,company_name\n0000000123,X\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required columns"):
            load_aaer_mapping(path)


class TestQuarterParsing:
    @pytest.mark.parametrize("text", ["2023q1", "2023Q1", " 2023q1 "])
    def test_accepts_valid_forms(self, text: str) -> None:
        quarter = Quarter.parse(text)
        assert (quarter.year, quarter.quarter) == (2023, 1)

    @pytest.mark.parametrize("text", ["2023", "2023q5", "q1", "abcd"])
    def test_rejects_invalid_forms(self, text: str) -> None:
        with pytest.raises(ValueError):
            Quarter.parse(text)
