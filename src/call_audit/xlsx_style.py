"""Excel cosmetics.

The report is read by team leads in Excel, not by a notebook, so the sheets get
a header band, wrapped text, frozen panes and column widths that fit the
content. Wide free-text columns are widened explicitly; everything else is
sized from the data with a sane cap.
"""
from __future__ import annotations

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BODY_FONT = Font(name="Calibri", size=11)
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="4472C4")
WRAP = Alignment(wrap_text=True, vertical="top")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

#: Columns that hold sentences rather than values.
WIDE_COLUMNS = {
    "content", "theme_detail", "resolution_summary", "strengths", "weaknesses",
    "uncertainty", "missed_opportunities", "product_issues", "knowledge_gaps",
    "script_gaps", "training_recommendations", "top_strengths",
    "top_weaknesses", "coaching", "product_issue", "knowledge_gap", "issues",
}
MAX_WIDTH = 60
MIN_WIDTH = 12


def style_sheet(worksheet) -> None:
    if worksheet.max_row == 0:
        return
    for row in worksheet.iter_rows(min_row=1, max_row=worksheet.max_row,
                                   min_col=1, max_col=worksheet.max_column):
        for cell in row:
            cell.font = BODY_FONT
            if cell.row > 1:
                cell.alignment = WRAP

    for cell in worksheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
    worksheet.row_dimensions[1].height = 30

    for index in range(1, worksheet.max_column + 1):
        header = worksheet.cell(row=1, column=index).value
        letter = get_column_letter(index)
        if header in WIDE_COLUMNS:
            worksheet.column_dimensions[letter].width = 55
        elif isinstance(header, str) and len(header) > 18:
            worksheet.column_dimensions[letter].width = 22
        else:
            longest = max(
                (len(str(cell.value)) for cell in worksheet[letter]
                 if cell.value is not None),
                default=MIN_WIDTH,
            )
            worksheet.column_dimensions[letter].width = min(
                max(MIN_WIDTH, longest + 2), MAX_WIDTH)

    worksheet.freeze_panes = "A2"
