from __future__ import annotations

import asyncio
import csv
import pathlib
import subprocess
import zipfile
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
class XLSXReader:
    MAIN_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    REL_NAMESPACE = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    async def read_file(self, p: pathlib.Path) -> Expected[str, FileReaderError]:
        try:
            xml_payload = await asyncio.to_thread(self._convert_workbook_to_xml, p)
            return _FileReader.create_expected(xml_payload)
        except FileReaderError as err:
            return _FileReader.create_expected(err)
        except Exception:
            return _FileReader.create_expected(FileReaderError("xlsx read error"))

    def _convert_workbook_to_xml(self, path: pathlib.Path) -> str:
        try:
            with zipfile.ZipFile(path) as zf:
                sheet_map = self._load_sheet_map(zf)
                if not sheet_map:
                    raise FileReaderError("xlsx missing worksheet")
                shared_strings = self._load_shared_strings(zf)
                sheet_fragments: list[str] = []
                for sheet_name, sheet_path in sheet_map:
                    table_xml = self._sheet_to_table(zf, sheet_path, shared_strings)
                    sheet_elem = ET.Element("sheet", {"name": str(sheet_name)})
                    sheet_elem.append(ET.fromstring(table_xml))
                    sheet_fragments.append(ET.tostring(sheet_elem, encoding="unicode"))
                return "".join(sheet_fragments)
        except zipfile.BadZipFile as exc:
            raise FileReaderError("xlsx read error") from exc
        except ET.ParseError as exc:
            raise FileReaderError("xlsx read error") from exc

    def _load_sheet_map(self, zf: zipfile.ZipFile) -> list[tuple[str, str]]:
        try:
            workbook_data = zf.read("xl/workbook.xml")
        except KeyError as exc:
            raise FileReaderError("xlsx missing workbook") from exc
        workbook_root = ET.fromstring(workbook_data)
        rels = self._load_relationships(zf)
        sheets: list[tuple[str, str]] = []
        sheets_parent = workbook_root.find(f"{self.MAIN_NAMESPACE}sheets")
        if sheets_parent is None:
            return sheets
        for sheet in sheets_parent.findall(f"{self.MAIN_NAMESPACE}sheet"):
            name = sheet.get("name", "")
            rel_id = sheet.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
            if not rel_id:
                continue
            target = rels.get(rel_id)
            if target is None:
                continue
            if target.startswith("/"):
                sheet_path = target.lstrip("/")
            elif target.startswith("xl/"):
                sheet_path = target
            else:
                sheet_path = f"xl/{target}"
            sheets.append((name, sheet_path))
        return sheets

    def _load_relationships(self, zf: zipfile.ZipFile) -> dict[str, str]:
        try:
            rels_data = zf.read("xl/_rels/workbook.xml.rels")
        except KeyError:
            return {}
        rels_root = ET.fromstring(rels_data)
        relationships: dict[str, str] = {}
        for rel in rels_root.findall(f"{self.REL_NAMESPACE}Relationship"):
            rel_id = rel.get("Id")
            target = rel.get("Target")
            if rel_id and target:
                relationships[rel_id] = target
        return relationships

    def _sheet_to_table(
        self, zf: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]
    ) -> str:
        try:
            sheet_data = zf.read(sheet_path)
        except KeyError as exc:
            raise FileReaderError("xlsx missing worksheet") from exc
        sheet_root = ET.fromstring(sheet_data)
        sheet_data_node = sheet_root.find(f"{self.MAIN_NAMESPACE}sheetData")
        if sheet_data_node is None:
            raise FileReaderError("xlsx missing sheet data")
        rows = sheet_data_node.findall(f"{self.MAIN_NAMESPACE}row")
        if not rows:
            raise FileReaderError("xlsx missing header row")
        header_row = rows[0]
        headers_map: dict[int, str] = {}
        max_index = -1
        for cell in header_row.findall(f"{self.MAIN_NAMESPACE}c"):
            index = self._column_index(cell.get("r", ""))
            if index is None:
                continue
            value = self._cell_text(cell, shared_strings).strip()
            headers_map[index] = value
            if index > max_index:
                max_index = index
        if max_index < 0:
            raise FileReaderError("xlsx missing header row")
        header_values = [headers_map.get(i, "") for i in range(max_index + 1)]
        if not any(value.strip() for value in header_values):
            raise FileReaderError("xlsx missing header row")
        return CSVReader.build_table_xml(header_values, [])

    def _column_index(self, cell_ref: str) -> int | None:
        if not cell_ref:
            return None
        letters = []
        for char in cell_ref:
            if char.isalpha():
                letters.append(char.upper())
            else:
                break
        if not letters:
            return None
        index = 0
        for char in letters:
            index = index * 26 + (ord(char) - ord("A") + 1)
        return index - 1

    def _load_shared_strings(self, zf: zipfile.ZipFile) -> list[str]:
        try:
            data = zf.read("xl/sharedStrings.xml")
        except KeyError:
            return []
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise FileReaderError("xlsx read error") from exc
        strings: list[str] = []
        for si in root.findall(f"{self.MAIN_NAMESPACE}si"):
            pieces = [
                node.text or ""
                for node in si.findall(f".//{self.MAIN_NAMESPACE}t")
            ]
            strings.append("".join(pieces))
        return strings

    def _cell_text(self, cell: ET.Element, shared_strings: list[str]) -> str:
        cell_type = cell.get("t")
        if cell_type == "s":
            value_node = cell.find(f"{self.MAIN_NAMESPACE}v")
            if value_node is None or value_node.text is None:
                return ""
            try:
                index = int(value_node.text)
            except ValueError:
                return ""
            if 0 <= index < len(shared_strings):
                return shared_strings[index]
            return ""
        if cell_type == "inlineStr":
            inline = cell.find(f"{self.MAIN_NAMESPACE}is")
            if inline is None:
                return ""
            parts = [
                node.text or ""
                for node in inline.findall(f".//{self.MAIN_NAMESPACE}t")
            ]
            return "".join(parts)
        value_node = cell.find(f"{self.MAIN_NAMESPACE}v")
        if value_node is None or value_node.text is None:
            return ""
        if cell_type == "b":
            return "TRUE" if value_node.text == "1" else "FALSE"
        return value_node.text


file_reader: FileReader = (
    ExtReader(PlainTextReader())
    .add_reader(".doc", DocxReader())
    .add_reader(".docx", DocxReader())
    .add_reader(".xlsx", XLSXReader())
    .add_reader(".pdf", PDFReader())
)
