"""Read a .xlsx without openpyxl.

An xlsx is a zip of XML: the workbook names its sheets, a relationship file says
which part each one lives in, strings are pooled in ``sharedStrings.xml`` and
numbers are stored as text. That is the whole format as far as reading a table
of values goes, so the integration can read regulator spreadsheets without
taking on a spreadsheet library.

Values come back as the strings the file holds. Callers know which of their own
columns are numbers, and the files mix both in one column.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class XlsxError(Exception):
    """Raised when a workbook is not one we can read."""


def _column(ref: str) -> int:
    """Turn a cell reference such as "AE17" into a zero-based column index."""
    number = 0
    for char in ref:
        if not char.isalpha():
            break
        number = number * 26 + (ord(char.upper()) - 64)
    return number - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iter(f"{_MAIN}t"))
        for item in root.iter(f"{_MAIN}si")
    ]


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        node = cell.find(f"{_MAIN}is")
        if node is None:
            return ""
        return "".join(text.text or "" for text in node.iter(f"{_MAIN}t"))
    value = cell.find(f"{_MAIN}v")
    if value is None or value.text is None:
        return ""
    if cell.get("t") == "s":
        index = int(value.text)
        return shared[index] if index < len(shared) else ""
    return value.text


def _rows(data: bytes, shared: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in ET.fromstring(data).iter(f"{_MAIN}row"):
        cells: dict[int, str] = {}
        for cell in row.iter(f"{_MAIN}c"):
            text = _cell_text(cell, shared)
            if text != "":
                cells[_column(cell.get("r") or "")] = text
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return rows


def read_xlsx(data: bytes) -> dict[str, list[list[str]]]:
    """Return ``{sheet name: rows}`` in the order the workbook lists its sheets."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        shared = _shared_strings(archive)
        targets = {
            rel.get("Id"): (rel.get("Target") or "").lstrip("/")
            for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        sheets: dict[str, list[list[str]]] = {}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).iter(f"{_MAIN}sheet"):
            target = targets[sheet.get(f"{_REL}id")]
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            sheets[sheet.get("name") or ""] = _rows(archive.read(target), shared)
        return sheets
    except (KeyError, OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as err:
        raise XlsxError(f"Not a readable xlsx: {err}") from err
