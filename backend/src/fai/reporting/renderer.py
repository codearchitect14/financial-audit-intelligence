"""Report rendering.

Two formats, deliberately layered:

**HTML** is always available. It needs no native libraries, works everywhere the
API runs, and is what the browser displays.

**PDF** is produced by WeasyPrint from that same HTML, and is optional.
WeasyPrint needs native Pango and Cairo libraries which are present in the Linux
image but awkward on Windows, so it lives in the ``reports`` extra and its
absence degrades to "PDF unavailable" rather than breaking the import of this
module or any endpoint that touches reports.

Every value is escaped through Jinja's autoescaping. A report renders text
drawn from filings and from model output, neither of which is trusted markup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape

from fai.core.logging import get_logger

log = get_logger(__name__)


def pdf_available() -> bool:
    """True when WeasyPrint and its native dependencies are importable."""
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        # OSError as well as ImportError: WeasyPrint imports but raises OSError
        # when the Pango shared library is missing, which is the common case on
        # a developer machine.
        return False
    return True


# autoescape is on for every format. Report content includes filing text and
# model output; treating either as trusted markup would be an injection route
# straight into a document people email around.
_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))

REPORT_TEMPLATE = _env.from_string(
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<style>
  @page { size: A4; margin: 20mm; }
  body { font-family: "Inter", "Helvetica Neue", Arial, sans-serif;
         color: #1a1d23; line-height: 1.5; font-size: 11pt; }
  h1 { font-size: 20pt; margin: 0 0 4pt; }
  h2 { font-size: 13pt; margin: 18pt 0 6pt; border-bottom: 1px solid #d8dce3;
       padding-bottom: 3pt; }
  .meta { color: #5a6472; font-size: 9.5pt; margin-bottom: 14pt; }
  .band { display: inline-block; padding: 2pt 8pt; border-radius: 3pt;
          font-weight: 600; font-size: 9.5pt; }
  .band-high { background: #fde8e8; color: #9b1c1c; }
  .band-elevated { background: #fdf6b2; color: #8e4b10; }
  .band-low { background: #def7ec; color: #03543f; }
  .band-none { background: #eef1f5; color: #4b5563; }
  table { width: 100%; border-collapse: collapse; margin: 8pt 0; font-size: 10pt; }
  th, td { text-align: left; padding: 5pt 6pt; border-bottom: 1px solid #e5e8ec; }
  th { background: #f6f8fa; font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .sev { font-weight: 600; }
  .sev-critical, .sev-high { color: #9b1c1c; }
  .sev-medium { color: #8e4b10; }
  .sev-low, .sev-info { color: #4b5563; }
  .caveat { background: #f6f8fa; border-left: 3px solid #9aa5b1;
            padding: 8pt 10pt; margin: 12pt 0; font-size: 9.5pt; color: #3f4854; }
  .explanation { color: #3f4854; font-size: 9.5pt; margin-top: 3pt; }
  footer { margin-top: 22pt; padding-top: 8pt; border-top: 1px solid #d8dce3;
           color: #6b7280; font-size: 8.5pt; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
<div class="meta">
  {{ facts.company.name }}
  {%- if facts.company.cik %} &middot; CIK {{ facts.company.cik }}{% endif %}
  {%- if facts.company.sector %} &middot; {{ facts.company.sector }}{% endif %}
  <br>
  {{ facts.period.filing_type }} &middot; fiscal {{ facts.period.fiscal_year }}
  {{ facts.period.fiscal_period }}
  {%- if facts.period.period_end_date %} &middot; period ended
  {{ facts.period.period_end_date }}{% endif %}
  <br>Generated {{ generated_at }}
</div>

<h2>Risk</h2>
<p>
  <span class="band band-{{ band_class }}">
    {% if facts.risk.score is not none %}{{ "%.1f"|format(facts.risk.score) }} / 100
    {%- else %}Not assessed{% endif %}
    &middot; {{ facts.risk.band }}
  </span>
</p>
<div class="caveat">{{ facts.risk.basis }}</div>

{% if narrative %}
  {% for section in narrative %}
<h2>{{ section.heading }}</h2>
<p>{{ section.body }}</p>
  {% endfor %}
{% else %}
<div class="caveat">
  Narrative sections were not generated for this report. All figures and
  findings below are complete and unaffected.
</div>
{% endif %}

<h2>Findings ({{ facts.counts.total_findings }})</h2>
{% if facts.findings %}
<table>
  <thead>
    <tr><th>Finding</th><th>Severity</th><th>Status</th><th>Method</th></tr>
  </thead>
  <tbody>
  {% for finding in facts.findings %}
    <tr>
      <td>
        {{ finding.description }}
        {% if finding.explanation %}
        <div class="explanation">{{ finding.explanation }}</div>
        {% endif %}
      </td>
      <td class="sev sev-{{ finding.severity }}">{{ finding.severity }}</td>
      <td>{{ finding.status }}</td>
      <td>{{ finding.detection_method }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No findings were raised for this statement.</p>
{% endif %}

<h2>Ratios</h2>
{% if computed_ratios %}
<table>
  <thead><tr><th>Ratio</th><th>Value</th></tr></thead>
  <tbody>
  {% for name, value in computed_ratios %}
    <tr><td>{{ name }}</td><td class="num">{{ "%.4f"|format(value) }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No ratios could be computed from the available line items.</p>
{% endif %}

<h2>Reported line items</h2>
{% if facts.line_items %}
<table>
  <thead><tr><th>Tag</th><th>Value (USD)</th></tr></thead>
  <tbody>
  {% for tag, value in facts.line_items.items() %}
    <tr><td>{{ tag }}</td><td class="num">{{ value }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No line items are recorded for this statement.</p>
{% endif %}

<footer>
  Findings are produced by deterministic statistical checks. Narrative text,
  where present, is generated from those findings and describes them; it does
  not constitute an audit opinion or a determination that any misstatement
  occurred.
</footer>
</body>
</html>"""
)

_BAND_CLASS = {
    "high": "high",
    "elevated": "elevated",
    "low": "low",
    "no findings": "none",
    "not assessed": "none",
}


def render_html(report_content: dict[str, Any], title: str) -> str:
    """Render a report's stored JSON into HTML."""
    facts = report_content.get("facts", {})
    ratios = facts.get("ratios", {}) or {}

    return REPORT_TEMPLATE.render(
        title=title,
        facts=facts,
        narrative=report_content.get("narrative") or [],
        generated_at=report_content.get("generated_at", ""),
        band_class=_BAND_CLASS.get(facts.get("risk", {}).get("band", ""), "none"),
        # Only computable ratios are tabulated. Printing "None" rows would
        # invite a reader to see a gap in the data as a value of zero.
        computed_ratios=[
            (name.replace("_", " "), value)
            for name, value in sorted(ratios.items())
            if value is not None
        ],
    )


def render_pdf(report_content: dict[str, Any], title: str, destination: Path) -> Path:
    """Render a report to PDF.

    Raises ``RuntimeError`` when WeasyPrint is unavailable, rather than writing
    a zero-byte file that looks like a successful export.
    """
    if not pdf_available():
        raise RuntimeError(
            "PDF export is unavailable: WeasyPrint is not installed, or its native "
            "Pango and Cairo libraries are missing. Install the 'reports' extra, or "
            "export the report as HTML instead."
        )

    from weasyprint import HTML

    destination.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=render_html(report_content, title)).write_pdf(str(destination))
    log.info("report_pdf_written", path=str(destination))
    return destination
