"""Trim a V-test workbook to the suppliers a fixture needs.

The published file is 4 MB of every supplier's every month. A fixture only needs
a couple of suppliers, but it must keep the real shared strings, styles and
relationships: shared-string indices are positional, so rebuilding them would
make the fixture prove something the real file does not.

Usage:
    python3 tools/trim_vtest.py <source.xlsx> <dest.xlsx> "Energie.be" "Aspiravi Energy"
"""

from __future__ import annotations

import sys
import zipfile
from xml.etree import ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_KEEP = "xl/worksheets/sheet3.xml"  # Var-dyn (excl. btw) (<year>)
_STUB = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    b"<sheetData/></worksheet>"
)
_DROP = {
    "xl/worksheets/sheet2.xml",
    "xl/worksheets/sheet4.xml",
    "xl/worksheets/sheet5.xml",
}
_SUPPLIER_COLUMN = 5


def _column(ref: str) -> int:
    number = 0
    for char in ref:
        if not char.isalpha():
            break
        number = number * 26 + (ord(char.upper()) - 64)
    return number - 1


def main() -> None:
    source, dest, *suppliers = sys.argv[1:]
    wanted = {" ".join(name.split()) for name in suppliers}
    archive = zipfile.ZipFile(source)
    shared = [
        "".join(text.text or "" for text in item.iter(f"{_MAIN}t"))
        for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).iter(f"{_MAIN}si")
    ]

    kept: list[str] = []
    position = -1
    for _, row in ET.iterparse(archive.open(_KEEP)):
        if not row.tag.endswith("}row"):
            continue
        position += 1
        keep = position == 0  # the header row
        for cell in row.iter(f"{_MAIN}c"):
            if _column(cell.get("r") or "") != _SUPPLIER_COLUMN:
                continue
            value = cell.find(f"{_MAIN}v")
            if cell.get("t") == "s" and value is not None and value.text is not None:
                keep = keep or " ".join(shared[int(value.text)].split()) in wanted
        if keep:
            kept.append(
                ET.tostring(row, encoding="unicode").replace(_MAIN, "").replace("ns0:", "")
            )
        row.clear()

    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(kept) + "</sheetData></worksheet>"
    ).encode()

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
        for item in archive.infolist():
            if item.filename == _KEEP:
                out.writestr(item.filename, sheet)
            elif item.filename in _DROP:
                out.writestr(item.filename, _STUB)
            else:
                out.writestr(item, archive.read(item.filename))

    print(f"kept {len(kept)} rows")


if __name__ == "__main__":
    main()
