"""Financial ratio computation.

Pure functions over a concept-to-value mapping. No database, no LLM, no
randomness: the same inputs always produce the same ratios, which is what makes
every downstream flag reproducible and defensible.

Two rules run through all of it:

* **Decimal in, float out.** The inputs are exact decimals and the arithmetic is
  done in ``Decimal`` so that large magnitudes do not lose precision mid-
  calculation. Only the final ratio, a small dimensionless number, is converted
  to ``float`` for storage and display.
* **A missing ratio is ``None``, never zero.** Zero is a real and meaningful
  value for most of these; conflating "we could not compute this" with "this is
  zero" would produce false flags on incomplete filings, which are common.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation

# Concept names as produced by fai.ingestion.tags.
Values = dict[str, Decimal]


def _divide(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    """Safe division returning None rather than raising or returning zero.

    A zero denominator is not an error in this domain: a company can genuinely
    report zero equity or zero revenue. It simply means the ratio is undefined.
    """
    if numerator is None or denominator is None:
        return None
    try:
        if denominator == 0:
            return None
        return float(numerator / denominator)
    except (DivisionByZero, InvalidOperation, ArithmeticError):
        return None


@dataclass(frozen=True)
class Ratios:
    """Computed ratios for one statement."""

    current_ratio: float | None = None
    quick_ratio: float | None = None
    debt_to_equity: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    operating_margin: float | None = None
    return_on_assets: float | None = None
    asset_turnover: float | None = None
    accruals_ratio: float | None = None

    def as_dict(self) -> dict[str, float | None]:
        return asdict(self)

    def available(self) -> dict[str, float]:
        """Only the ratios that could actually be computed."""
        return {k: v for k, v in self.as_dict().items() if v is not None}


def compute_ratios(values: Values) -> Ratios:
    """Compute every ratio the available line items support."""
    assets = values.get("Assets")
    assets_current = values.get("AssetsCurrent")
    liabilities = values.get("Liabilities")
    liabilities_current = values.get("LiabilitiesCurrent")
    equity = values.get("StockholdersEquity")
    inventory = values.get("Inventory")
    revenue = values.get("Revenue")
    cost_of_revenue = values.get("CostOfRevenue")
    gross_profit = values.get("GrossProfit")
    operating_income = values.get("OperatingIncome")
    net_income = values.get("NetIncome")
    operating_cash_flow = values.get("OperatingCashFlow")

    # Gross profit is frequently not tagged even when its components are.
    # Deriving it keeps margin available for many more filings.
    if gross_profit is None and revenue is not None and cost_of_revenue is not None:
        gross_profit = revenue - cost_of_revenue

    quick_assets = None
    if assets_current is not None:
        # Inventory is the least liquid current asset, so the quick ratio
        # excludes it. A filing that omits the inventory tag is treated as
        # having none rather than being skipped: for a services company that is
        # usually correct, and the ratio is a screen, not a conclusion.
        quick_assets = assets_current - (inventory or Decimal(0))

    return Ratios(
        current_ratio=_divide(assets_current, liabilities_current),
        quick_ratio=_divide(quick_assets, liabilities_current),
        debt_to_equity=_divide(liabilities, equity),
        gross_margin=_divide(gross_profit, revenue),
        net_margin=_divide(net_income, revenue),
        operating_margin=_divide(operating_income, revenue),
        return_on_assets=_divide(net_income, assets),
        asset_turnover=_divide(revenue, assets),
        # Accruals: the gap between reported earnings and the cash actually
        # generated, scaled by assets. A persistently large positive gap is one
        # of the most durable empirical markers of earnings manipulation, which
        # is why it is computed here rather than left to the model.
        accruals_ratio=(
            _divide(net_income - operating_cash_flow, assets)
            if net_income is not None and operating_cash_flow is not None
            else None
        ),
    )


def accounting_identity_error(values: Values) -> Decimal | None:
    """Relative error in ``assets = liabilities + equity``.

    Returns the absolute difference scaled by total assets, or ``None`` when any
    component is missing. A filing that fails this identity by more than a
    rounding margin either has a tagging error or something worse, and either
    way a human should look at it.
    """
    assets = values.get("Assets")
    liabilities = values.get("Liabilities")
    equity = values.get("StockholdersEquity")

    if assets is None or liabilities is None or equity is None or assets == 0:
        return None

    difference = abs(assets - (liabilities + equity))
    try:
        return difference / abs(assets)
    except (DivisionByZero, InvalidOperation):
        return None
