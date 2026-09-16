"""US-GAAP tag catalogue.

The DERA ``num.txt`` file for a single quarter contains millions of rows across
thousands of distinct XBRL tags. Ingesting all of them would store mostly noise:
company-specific extension tags, immaterial detail, and dimensional breakdowns
that cannot be compared across filers.

This catalogue is the allowlist. It covers the tags needed to compute the
standard ratios in Phase 3 and to test the accounting identities, and it is the
filter that keeps ingestion tractable on free-tier resources.

Tags are listed with synonyms because US-GAAP has revised its vocabulary over
the corpus period: revenue in particular is reported under at least three tags
depending on filing year and the adoption of ASC 606. Resolution order within a
concept is significant, most-preferred first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fai.db.models.enums import StatementSection


@dataclass(frozen=True)
class Concept:
    """A financial concept and the XBRL tags that may report it.

    ``duration`` distinguishes flows from stocks. A balance-sheet figure is
    measured at an instant (``qtrs = 0`` in DERA); an income-statement or
    cash-flow figure is measured over a span (``qtrs = 1`` for a quarter,
    ``qtrs = 4`` for a year). Reading the wrong one silently mixes a point-in-
    time balance with a twelve-month flow.
    """

    name: str
    section: StatementSection
    duration: bool
    tags: tuple[str, ...] = field(default_factory=tuple)


CONCEPTS: tuple[Concept, ...] = (
    # ------------------------------------------------------------------
    # Balance sheet (instantaneous, qtrs = 0)
    # ------------------------------------------------------------------
    Concept("Assets", StatementSection.BALANCE_SHEET, False, ("Assets",)),
    Concept("AssetsCurrent", StatementSection.BALANCE_SHEET, False, ("AssetsCurrent",)),
    Concept("Liabilities", StatementSection.BALANCE_SHEET, False, ("Liabilities",)),
    Concept("LiabilitiesCurrent", StatementSection.BALANCE_SHEET, False, ("LiabilitiesCurrent",)),
    Concept(
        "StockholdersEquity",
        StatementSection.BALANCE_SHEET,
        False,
        (
            "StockholdersEquity",
            # Includes non-controlling interests. Used only when the narrower
            # tag is absent, because the two are not interchangeable.
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
    ),
    Concept(
        "LiabilitiesAndStockholdersEquity",
        StatementSection.BALANCE_SHEET,
        False,
        ("LiabilitiesAndStockholdersEquity",),
    ),
    Concept(
        "Cash",
        StatementSection.BALANCE_SHEET,
        False,
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
    ),
    Concept(
        "AccountsReceivable",
        StatementSection.BALANCE_SHEET,
        False,
        ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"),
    ),
    Concept("Inventory", StatementSection.BALANCE_SHEET, False, ("InventoryNet",)),
    Concept(
        "PropertyPlantAndEquipment",
        StatementSection.BALANCE_SHEET,
        False,
        ("PropertyPlantAndEquipmentNet",),
    ),
    Concept("Goodwill", StatementSection.BALANCE_SHEET, False, ("Goodwill",)),
    Concept(
        "LongTermDebt",
        StatementSection.BALANCE_SHEET,
        False,
        ("LongTermDebtNoncurrent", "LongTermDebt"),
    ),
    Concept(
        "RetainedEarnings",
        StatementSection.BALANCE_SHEET,
        False,
        ("RetainedEarningsAccumulatedDeficit",),
    ),
    # ------------------------------------------------------------------
    # Income statement (duration)
    # ------------------------------------------------------------------
    Concept(
        "Revenue",
        StatementSection.INCOME_STATEMENT,
        True,
        (
            # ASC 606 tag, used by filings from roughly 2018 onward.
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ),
    ),
    Concept(
        "CostOfRevenue",
        StatementSection.INCOME_STATEMENT,
        True,
        ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    ),
    Concept("GrossProfit", StatementSection.INCOME_STATEMENT, True, ("GrossProfit",)),
    Concept("OperatingIncome", StatementSection.INCOME_STATEMENT, True, ("OperatingIncomeLoss",)),
    Concept(
        "NetIncome",
        StatementSection.INCOME_STATEMENT,
        True,
        ("NetIncomeLoss", "ProfitLoss"),
    ),
    Concept("OperatingExpenses", StatementSection.INCOME_STATEMENT, True, ("OperatingExpenses",)),
    Concept(
        "SellingGeneralAndAdministrative",
        StatementSection.INCOME_STATEMENT,
        True,
        ("SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"),
    ),
    Concept(
        "ResearchAndDevelopment",
        StatementSection.INCOME_STATEMENT,
        True,
        ("ResearchAndDevelopmentExpense",),
    ),
    Concept("InterestExpense", StatementSection.INCOME_STATEMENT, True, ("InterestExpense",)),
    Concept(
        "IncomeTaxExpense",
        StatementSection.INCOME_STATEMENT,
        True,
        ("IncomeTaxExpenseBenefit",),
    ),
    # ------------------------------------------------------------------
    # Cash flow (duration)
    # ------------------------------------------------------------------
    Concept(
        "OperatingCashFlow",
        StatementSection.CASH_FLOW,
        True,
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
    ),
    Concept(
        "InvestingCashFlow",
        StatementSection.CASH_FLOW,
        True,
        ("NetCashProvidedByUsedInInvestingActivities",),
    ),
    Concept(
        "FinancingCashFlow",
        StatementSection.CASH_FLOW,
        True,
        ("NetCashProvidedByUsedInFinancingActivities",),
    ),
    Concept(
        "DepreciationAndAmortization",
        StatementSection.CASH_FLOW,
        True,
        ("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet"),
    ),
    Concept(
        "CapitalExpenditures",
        StatementSection.CASH_FLOW,
        True,
        ("PaymentsToAcquirePropertyPlantAndEquipment",),
    ),
)

CONCEPTS_BY_NAME: dict[str, Concept] = {concept.name: concept for concept in CONCEPTS}

# Flat set of every XBRL tag worth reading, used to filter num.txt on load.
WANTED_TAGS: frozenset[str] = frozenset(tag for c in CONCEPTS for tag in c.tags)

# Reverse map from XBRL tag to the concept that claims it, with the preference
# order preserved so that a filing reporting both "Revenues" and the ASC 606 tag
# resolves to the preferred one.
TAG_TO_CONCEPT: dict[str, tuple[Concept, int]] = {
    tag: (concept, rank) for concept in CONCEPTS for rank, tag in enumerate(concept.tags)
}


def concept_for_tag(tag: str) -> Concept | None:
    """Return the concept a tag belongs to, or None when it is not of interest."""
    entry = TAG_TO_CONCEPT.get(tag)
    return entry[0] if entry else None


def tag_preference(tag: str) -> int:
    """Rank of a tag within its concept. Lower is more preferred."""
    entry = TAG_TO_CONCEPT.get(tag)
    return entry[1] if entry else 999
