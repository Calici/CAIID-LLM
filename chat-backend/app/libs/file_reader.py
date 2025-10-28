from __future__ import annotations
from typing import Protocol, final
from app.libs.expected import Expected
from docx import Document
import asyncio
import pathlib
import subprocess
import csv


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
                return _FileReader.create_expected(f"headers: {', '.join(headers)}")
        except IOError:
            return _FileReader.create_expected(FileReaderError("file read error"))


file_reader: FileReader = (
    ExtReader(PlainTextReader())
    .add_reader(".doc", DocxReader())
    .add_reader(".docx", DocxReader())
    .add_reader(".pdf", PDFReader())
)
