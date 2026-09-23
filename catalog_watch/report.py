"""The three things a run leaves behind: a CSV, an XLSX, and a change summary
a person can read without opening either.

The text summary is the one that gets emailed or piped into Slack by the cron
job, so it is written to be legible in a fixed-width font at a glance: what
changed, on which product, from what to what.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from .models import (
    DELISTED,
    FIRST_READ,
    NEW,
    UNREADABLE,
    Change,
    Product,
    Snapshot,
)

COLUMNS = [
    "sku",
    "name",
    "price",
    "currency",
    "availability",
    "url",
    "status",
    "change",
    "change_detail",
    "needs_review",
    "issues",
]

# Short, unambiguous labels. "price cut" and "price up" read faster in a column
# than a signed number does.
LABELS = {
    NEW: "new",
    DELISTED: "delisted",
    "availability": "stock",
    "name": "renamed",
    UNREADABLE: "unreadable",
    FIRST_READ: "readable",
}


def label(change: Change) -> str:
    if change.kind == "price":
        return "price up" if change.note.startswith("+") else "price cut"
    return LABELS.get(change.kind, change.kind)


def _changes_by_sku(changes: list[Change]) -> dict[str, list[Change]]:
    grouped: dict[str, list[Change]] = {}
    for change in changes:
        grouped.setdefault(change.sku, []).append(change)
    return grouped


def _row(product: Product, status: str, changes: list[Change]) -> dict:
    detail = "; ".join(
        _movement(c) + (f" ({c.note})" if c.note else "") for c in changes
    )
    return {
        "sku": product.sku,
        "name": product.name or "",
        "price": "" if product.price is None else f"{product.price:.2f}",
        "currency": product.currency or "",
        "availability": product.availability or "",
        "url": product.url or "",
        "status": status,
        "change": ", ".join(label(c) for c in changes),
        "change_detail": detail,
        "needs_review": "yes" if product.needs_review else "no",
        "issues": "; ".join(product.issues),
    }


def build_rows(
    snapshot: Snapshot, previous: Snapshot | None, changes: list[Change]
) -> list[dict]:
    """One row per product currently listed, plus one per product that
    disappeared — so nothing drops out of the file without a trace."""
    grouped = _changes_by_sku(changes)
    rows = [_row(p, "listed", grouped.get(p.sku, [])) for p in snapshot.products]

    if previous is not None:
        current = snapshot.by_sku()
        for product in previous.products:
            if product.sku not in current:
                rows.append(_row(product, "delisted", grouped.get(product.sku, [])))
    return rows


def write_csv(path: str | Path, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _as_money(cell) -> None:
    """Turn a cell holding "41.50" into the number 41.50, formatted.

    An empty cell is a price we could not read, and it stays empty — writing a
    0 there would be the guess this whole tool exists not to make.
    """
    value = cell.value
    if value in (None, ""):
        return
    try:
        cell.value = float(value)
    except (TypeError, ValueError):
        return
    cell.number_format = "0.00"


def write_xlsx(
    path: str | Path, rows: list[dict], changes: list[Change], summary: str
) -> Path:
    """Two sheets: what changed, then the whole catalogue.

    Changes first because that is the question the file is opened to answer.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header_font = Font(bold=True)
    review_fill = PatternFill("solid", fgColor="FFF2CC")
    up_fill = PatternFill("solid", fgColor="FCE4E4")
    down_fill = PatternFill("solid", fgColor="E2F0D9")

    workbook = Workbook()

    sheet = workbook.active
    sheet.title = "Changes"
    change_columns = ["kind", "sku", "name", "before", "after", "detail"]
    sheet.append(change_columns)
    for change in changes:
        sheet.append(
            [
                label(change),
                change.sku,
                change.name or "",
                change.before or "",
                change.after or "",
                change.note,
            ]
        )
    for index, change in enumerate(changes, start=2):
        if change.kind == "price":
            fill = up_fill if change.note.startswith("+") else down_fill
            sheet.cell(row=index, column=1).fill = fill
            # Numbers, not text that looks like numbers: a before/after column
            # you cannot subtract is not much use in a spreadsheet.
            for column in (4, 5):
                _as_money(sheet.cell(row=index, column=column))
        elif change.kind == UNREADABLE:
            sheet.cell(row=index, column=1).fill = review_fill
    if not changes:
        sheet.append(["no changes since the previous run"])

    catalogue = workbook.create_sheet("Catalogue")
    catalogue.append(COLUMNS)
    price_column = COLUMNS.index("price") + 1
    for row in rows:
        catalogue.append([row[column] for column in COLUMNS])
    for index, row in enumerate(rows, start=2):
        _as_money(catalogue.cell(row=index, column=price_column))
        if row["needs_review"] == "yes":
            catalogue.cell(row=index, column=1).fill = review_fill

    notes = workbook.create_sheet("Run")
    for line in summary.splitlines():
        notes.append([line])

    for worksheet in (sheet, catalogue):
        for cell in worksheet[1]:
            cell.font = header_font
            cell.alignment = Alignment(vertical="center")
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
    for worksheet in workbook.worksheets:
        for column_index in range(1, worksheet.max_column + 1):
            longest = max(
                (
                    len(str(worksheet.cell(row=r, column=column_index).value or ""))
                    for r in range(1, min(worksheet.max_row, 200) + 1)
                ),
                default=10,
            )
            worksheet.column_dimensions[get_column_letter(column_index)].width = min(
                max(longest + 2, 9), 52
            )

    buffer = io.BytesIO()
    workbook.save(buffer)
    path.write_bytes(_repack(buffer.getvalue()))
    return path


#: The two places an .xlsx records a wall clock. Measured on openpyxl 3.1.5:
#: `created` honours `workbook.properties` and `modified` is refreshed to the
#: save time whatever the properties said — so pinning it has to happen here,
#: after the save.
_TIMESTAMP = re.compile(
    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
)
_EPOCH_XML = b"1980-01-01T00:00:00Z"


def _repack(data: bytes) -> bytes:
    """Rewrite an xlsx with every clock in it flattened.

    Two of them. An .xlsx is a zip, and `ZipFile.writestr` stamps each member
    with the current local time; it is also an Office document, and
    `docProps/core.xml` carries a modification timestamp that openpyxl
    refreshes on save. Either one makes this morning's run and tomorrow's
    produce different bytes for an unchanged catalogue, which would put "the
    file is the same, so nothing moved" out of reach of `cmp` — the one check
    a client might actually perform on a watcher that runs every day. Order
    and contents are left exactly as openpyxl wrote them; only the clocks go.
    """
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            body = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                body = _TIMESTAMP.sub(rb"\g<1>" + _EPOCH_XML + rb"\g<2>", body)
            info = zipfile.ZipInfo(item.filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = item.compress_type
            info.external_attr = item.external_attr
            info.create_system = 0
            target.writestr(info, body)
    return out.getvalue()


def _movement(change: Change) -> str:
    """The "from -> to" column, with the dashes that mean "there was nothing
    here" spelled out rather than printed as a stray hyphen."""
    before = (change.before or "").replace("_", " ")
    after = (change.after or "").replace("_", " ")
    if change.kind == NEW:
        return f"-> {after}"
    if change.kind == DELISTED:
        return f"{before} ->"
    if change.kind == UNREADABLE:
        return f"{before} -> ?"
    if change.kind == FIRST_READ:
        return f"? -> {after}"
    return f"{before} -> {after}"


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def summarise(
    snapshot: Snapshot,
    previous: Snapshot | None,
    changes: list[Change],
    site_name: str,
) -> str:
    """The plain-text change report. This is the artefact the schedule emails."""
    lines: list[str] = []
    lines.append(f"catalog-watch — {site_name}")
    lines.append(f"  run at   {snapshot.scraped_at}")
    lines.append(f"  target   {snapshot.url}")

    page_word = "page" if snapshot.pages == 1 else "pages"
    lines.append("")
    lines.append(
        f"{len(snapshot.products)} products on {snapshot.pages} {page_word}"
        f" · {snapshot.clean_count} read clean"
        f" · {snapshot.review_count} needing review"
    )

    if previous is None:
        lines.append("")
        lines.append(
            "First run: this is the baseline. The next run reports what moved."
        )
    else:
        lines.append(f"compared against the run at {previous.scraped_at}")
        lines.append("")
        if not changes:
            lines.append("No changes since the previous run.")
        else:
            word = "change" if len(changes) == 1 else "changes"
            lines.append(f"{len(changes)} {word} since the previous run")
            lines.append("")
            for change in changes:
                movement = _movement(change)
                lines.append(
                    f"  {_truncate(label(change), 10)}  "
                    f"{_truncate(change.sku, 9)}  "
                    f"{_truncate(change.name or '', 34)}  "
                    f"{movement:<26}{change.note}".rstrip()
                )

    flagged = [p for p in snapshot.products if p.needs_review]
    if flagged:
        lines.append("")
        word = "product" if len(flagged) == 1 else "products"
        lines.append(f"{len(flagged)} {word} needing review (read, not guessed):")
        for product in flagged:
            lines.append(
                f"  review      {_truncate(product.sku, 9)}  "
                f"{_truncate(product.name or '', 34)}  {'; '.join(product.issues)}"
            )

    return "\n".join(lines) + "\n"


def write_text(path: str | Path, summary: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary, encoding="utf-8")
    return path
