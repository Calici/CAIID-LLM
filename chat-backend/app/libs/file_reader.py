from __future__ import annotations

import asyncio
import csv
import pathlib
import subprocess
import zipfile
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from typing import Protocol, final

from docx import Document

from app.libs.expected import Expected


@final
class FileReaderError(RuntimeError):
    pass


class FileReader(Protocol):
    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]: ...


class _FileReader:
    @staticmethod
    def create_expected(v: str | FileReaderError):
        return Expected(str, FileReaderError, v)


@final
class PDFReader:
    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pdftotext",
                str(p),
                "-",
                stdout=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert proc.stdout is not None  # unreachable
            output = await proc.stdout.read()
            return _FileReader.create_expected(output.decode())
        except subprocess.CalledProcessError:
            return _FileReader.create_expected(
                FileReaderError("pdftotext conversion fail")
            )
        except UnicodeDecodeError:
            return _FileReader.create_expected(
                FileReaderError("pdftotext conversion fail")
            )


@final
class PlainTextReader:
    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]:
        try:
            with open(p, "r") as f:
                return _FileReader.create_expected(f.read())
        except IOError:
            return _FileReader.create_expected(FileReaderError("file read error"))


@final
class DocxReader:
    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]:
        try:
            doc = Document(str(p))
            return _FileReader.create_expected(
                "\n".join([p.text for p in doc.paragraphs])
            )
        except Exception as e:
            return _FileReader.create_expected(FileReaderError(str(e)))


@final
class ExtReader:
    def __init__(self, fallback_reader: FileReader):
        self.readers: dict[str, FileReader] = {"*": fallback_reader}

    def add_reader(self, ext: str, reader: FileReader) -> ExtReader:
        self.readers[ext] = reader
        return self

    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]:
        reader = self.readers.get(p.suffix, self.readers["*"])
        return await reader.read_file(p)


@final
class CSVReader:
    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]:
        try:
            with open(p, "r") as f:
                reader = csv.reader(f)
                headers = next(reader)
                rows = list(reader)
                payload = self.build_table_xml(headers, rows)
                return _FileReader.create_expected(payload)
        except IOError:
            return _FileReader.create_expected(FileReaderError("file read error"))
        except StopIteration:
            return _FileReader.create_expected(FileReaderError("csv header missing"))

    @staticmethod
    def build_table_xml(headers: list[str], rows: list[list[str]]) -> str:
        table_elem = ET.Element("table")
        header_elem = ET.SubElement(table_elem, "header")
        header_elem.text = ", ".join(str(value) for value in headers)
        for row in rows:
            row_elem = ET.SubElement(table_elem, "row")
            row_elem.text = ", ".join(str(cell) for cell in row)
        return ET.tostring(table_elem, encoding="unicode")


@final
class XlsxReader:
    _SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    _REL_NS = (
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    )
    _PACKAGE_REL_NS = (
        "{http://schemas.openxmlformats.org/package/2006/relationships}"
    )

    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]:
        try:
            headers = self._read_headers(p)
            if not headers or all(not h for h in headers):
                raise FileReaderError("xlsx header missing")
            payload = CSVReader.build_table_xml(headers, [])
            return _FileReader.create_expected(payload)
        except FileReaderError as e:
            return _FileReader.create_expected(e)
        except (IOError, zipfile.BadZipFile, ET.ParseError, KeyError, ValueError):
            return _FileReader.create_expected(FileReaderError("xlsx read error"))

    def _read_headers(self, path: pathlib.Path) -> list[str]:
        with zipfile.ZipFile(path) as archive:
            sheet_path = self._resolve_first_sheet_path(archive)
            shared_strings = self._read_shared_strings(archive)
            sheet_xml = archive.read(sheet_path)
            return self._extract_header_row(sheet_xml, shared_strings)

    def _resolve_first_sheet_path(self, archive: zipfile.ZipFile) -> str:
        try:
            workbook_xml = archive.read("xl/workbook.xml")
        except KeyError as exc:
            raise FileReaderError("xlsx workbook missing") from exc
        workbook_root = ET.fromstring(workbook_xml)
        sheets = workbook_root.find(f"{self._SPREADSHEET_NS}sheets")
        if sheets is None:
            raise FileReaderError("xlsx sheets missing")
        sheet = sheets.find(f"{self._SPREADSHEET_NS}sheet")
        if sheet is None:
            raise FileReaderError("xlsx sheets missing")
        rel_id = sheet.attrib.get(f"{self._REL_NS}id")
        if rel_id is None:
            raise FileReaderError("xlsx sheets missing")

        try:
            rels_xml = archive.read("xl/_rels/workbook.xml.rels")
        except KeyError as exc:
            raise FileReaderError("xlsx relationship missing") from exc
        rels_root = ET.fromstring(rels_xml)
        target = None
        for rel in rels_root.findall(f"{self._PACKAGE_REL_NS}Relationship"):
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib.get("Target")
                break
        if not target:
            raise FileReaderError("xlsx worksheet target missing")

        if target.startswith("/"):
            return target.lstrip("/")
        return str(PurePosixPath("xl").joinpath(target))

    def _read_shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        try:
            shared_strings_xml = archive.read("xl/sharedStrings.xml")
        except KeyError:
            return []
        root = ET.fromstring(shared_strings_xml)
        values: list[str] = []
        for si in root.findall(f"{self._SPREADSHEET_NS}si"):
            texts = [
                t.text or ""
                for t in si.findall(f".//{self._SPREADSHEET_NS}t")
            ]
            values.append("".join(texts))
        return values

    def _extract_header_row(
        self, sheet_xml: bytes, shared_strings: list[str]
    ) -> list[str]:
        sheet_root = ET.fromstring(sheet_xml)
        sheet_data = sheet_root.find(f"{self._SPREADSHEET_NS}sheetData")
        if sheet_data is None:
            raise FileReaderError("xlsx sheet data missing")
        header_row = sheet_data.find(f"{self._SPREADSHEET_NS}row")
        if header_row is None:
            raise FileReaderError("xlsx header missing")

        headers: list[str] = []
        for cell in header_row.findall(f"{self._SPREADSHEET_NS}c"):
            headers.append(self._parse_cell(cell, shared_strings))
        return headers

    def _parse_cell(
        self, cell: ET.Element, shared_strings: list[str]
    ) -> str:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            inline = cell.find(f"{self._SPREADSHEET_NS}is")
            if inline is None:
                return ""
            texts = [
                t.text or ""
                for t in inline.findall(f".//{self._SPREADSHEET_NS}t")
            ]
            return "".join(texts)

        value_element = cell.find(f"{self._SPREADSHEET_NS}v")
        if value_element is None or value_element.text is None:
            return ""

        if cell_type == "s":
            try:
                idx = int(value_element.text)
                return shared_strings[idx]
            except (ValueError, IndexError):
                return ""
        if cell_type == "b":
            return "TRUE" if value_element.text == "1" else "FALSE"
        return value_element.text


file_reader: FileReader = (
    ExtReader(PlainTextReader())
    .add_reader(".doc", DocxReader())
    .add_reader(".docx", DocxReader())
    .add_reader(".pdf", PDFReader())
    .add_reader(".xlsx", XlsxReader())
)
