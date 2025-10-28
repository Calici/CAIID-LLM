from __future__ import annotations
from typing import Annotated, Protocol, final, TypeVar
from pydantic import BaseModel, ConfigDict, PlainSerializer
from datetime import datetime
import sqlite3
import uuid
import pathlib
from app.libs.chat import ChatFile, ChatMessages, ChatState
from sqlalchemy import literal
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
import contextlib

RawDbCell = int | float | str | bytes | None
RawDbRow = list[RawDbCell]


def sanitise_sql(value: str) -> str:
    assert isinstance(value, str), "value must be str"
    compiled = literal(value).compile(
        dialect=sqlite_dialect(), compile_kwargs={"literal_binds": True}
    )
    return str(compiled)


class DbCursor(Protocol):
    def __iter__(self) -> DbCursor: ...
    def __next__(self) -> RawDbRow: ...


class DBProvider(Protocol):
    def run_query(self, q: str) -> DbCursor: ...
    def close(self): ...


T = TypeVar("T", bound=DBProvider, covariant=True)


@contextlib.contextmanager
def db_provider_manager(v: T):
    try:
        yield v
    finally:
        v.close()


@final
class SqliteCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self.cursor = cursor

    def __iter__(self) -> SqliteCursor:
        return self

    def __next__(self) -> RawDbRow:
        row = self.cursor.fetchone()
        if row is None:
            raise StopIteration
        return row


@final
class SqliteProvider:
    def __init__(self, path: str | pathlib.Path):
        self.conn = sqlite3.connect(path, autocommit=True)
        self.path = path

    def run_query(self, q: str) -> SqliteCursor:
        return SqliteCursor(self.conn.execute(q))

    def close(self):
        self.conn.close()


"""
    Database Schema
"""


class FilesSchema(BaseModel):
    name: str
    summary: str
    create_date: datetime
    last_modified: datetime
    uuid: uuid.UUID

    def insert_sql(self, table_name: str = "files") -> str:
        return f"""
            INSERT INTO {table_name} VALUES (
                '{self.name}',
                '{self.summary}',
                '{self.create_date.isoformat()}',
                '{self.last_modified.isoformat()}',
                '{self.uuid}'
            )
        """

    def update_sql(self, table_name: str = "files") -> str:
        self.last_modified = datetime.now()
        return f"""
            UPDATE {table_name}
            SET
                name='{self.name}',
                summary='{self.summary}',
                create_date='{self.create_date.isoformat()}',
                last_modified='{self.last_modified.isoformat()}'
            WHERE uuid='{self.uuid}'
        """

    def delete_sql(self, table_name: str = "files") -> str:
        return f"""
            DELETE FROM {table_name}
            WHERE uuid='{self.uuid}'
        """

    @staticmethod
    def create_table_sql(table_name: str = "files") -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                name TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL,
                create_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                uuid TEXT NOT NULL UNIQUE PRIMARY KEY
            ) STRICT
        """

    @staticmethod
    def create(name: str, summary: str) -> FilesSchema:
        return FilesSchema(
            name=name,
            summary=summary,
            create_date=datetime.now(),
            last_modified=datetime.now(),
            uuid=uuid.uuid4(),
        )

    @staticmethod
    def from_cursor(row: RawDbRow) -> FilesSchema:
        if len(row) != 5:
            raise ValueError

        name, summary, _raw_create_date, _raw_last_modified, _raw_uuid = row

        assert isinstance(name, str), "name must be str"
        assert isinstance(summary, str), "summary must be str"
        assert isinstance(_raw_create_date, str), "create_date must be str"
        assert isinstance(_raw_last_modified, str), "last_modified must be str"
        assert isinstance(_raw_uuid, str), "uuid must be str"

        create_date = datetime.fromisoformat(_raw_create_date)
        last_modified = datetime.fromisoformat(_raw_last_modified)
        file_uuid = uuid.UUID(_raw_uuid)

        return FilesSchema(
            name=name,
            summary=summary,
            create_date=create_date,
            last_modified=last_modified,
            uuid=file_uuid,
        )

    @staticmethod
    def get_by_uuid(
        provider: DBProvider,
        record_uuid: str,
        table_name: str = "files",
    ) -> FilesSchema | None:
        rows = list(
            provider.run_query(
                f"""
                SELECT
                    name,
                    summary,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                WHERE uuid='{record_uuid}'
                """
            )
        )
        if not rows:
            return None
        return FilesSchema.from_cursor(rows[0])

    @staticmethod
    def get_by_name(
        provider: DBProvider,
        name: str,
        table_name: str = "files",
    ) -> FilesSchema | None:
        safe_name = sanitise_sql(name)
        rows = list(
            provider.run_query(
                f"""
                SELECT
                    name,
                    summary,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                WHERE name={safe_name}
                """
            )
        )
        if not rows:
            return None
        return FilesSchema.from_cursor(rows[0])

    @staticmethod
    def all(
        provider: DBProvider,
        table_name: str = "files",
    ) -> list[FilesSchema]:
        return [
            FilesSchema.from_cursor(row)
            for row in provider.run_query(
                f"""
                SELECT
                    name,
                    summary,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                """
            )
        ]


class TempFilesSchema(BaseModel):
    name: str
    extension: str
    create_date: datetime
    last_modified: datetime
    uuid: uuid.UUID

    def insert_sql(self, table_name: str = "temp_files") -> str:
        return f"""
            INSERT INTO {table_name} VALUES (
                '{self.name}',
                '{self.extension}',
                '{self.create_date.isoformat()}',
                '{self.last_modified.isoformat()}',
                '{self.uuid}'
            )
        """

    def update_sql(self, table_name: str = "temp_files") -> str:
        self.last_modified = datetime.now()
        return f"""
            UPDATE {table_name}
            SET
                name='{self.name}',
                extension='{self.extension}',
                create_date='{self.create_date.isoformat()}',
                last_modified='{self.last_modified.isoformat()}'
            WHERE uuid='{self.uuid}'
        """

    def delete_sql(self, table_name: str = "temp_files") -> str:
        return f"""
            DELETE FROM {table_name}
            WHERE uuid='{self.uuid}'
        """

    @staticmethod
    def create_table_sql(table_name: str = "temp_files") -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                name TEXT NOT NULL,
                extension TEXT NOT NULL,
                create_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                uuid TEXT NOT NULL UNIQUE PRIMARY KEY
            ) STRICT
        """

    @staticmethod
    def create(name: str, extension: str) -> TempFilesSchema:
        now = datetime.now()
        return TempFilesSchema(
            name=name,
            extension=extension,
            create_date=now,
            last_modified=now,
            uuid=uuid.uuid4(),
        )

    @staticmethod
    def from_cursor(row: RawDbRow) -> TempFilesSchema:
        if len(row) != 5:
            raise ValueError

        name, extension, _raw_create_date, _raw_last_modified, _raw_uuid = row

        assert isinstance(name, str), "name must be str"
        assert isinstance(extension, str), "extension must be str"
        assert isinstance(_raw_create_date, str), "create_date must be str"
        assert isinstance(_raw_last_modified, str), "last_modified must be str"
        assert isinstance(_raw_uuid, str), "uuid must be str"

        return TempFilesSchema(
            name=name,
            extension=extension,
            create_date=datetime.fromisoformat(_raw_create_date),
            last_modified=datetime.fromisoformat(_raw_last_modified),
            uuid=uuid.UUID(_raw_uuid),
        )

    @staticmethod
    def get_by_uuid(
        provider: DBProvider,
        record_uuid: str,
        table_name: str = "temp_files",
    ) -> TempFilesSchema | None:
        rows = list(
            provider.run_query(
                f"""
                SELECT
                    name,
                    extension,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                WHERE uuid='{record_uuid}'
                """
            )
        )
        if not rows:
            return None
        return TempFilesSchema.from_cursor(rows[0])

    @staticmethod
    def get_by_name(
        provider: DBProvider,
        name: str,
        table_name: str = "temp_files",
    ) -> TempFilesSchema | None:
        safe_name = sanitise_sql(name)
        rows = list(
            provider.run_query(
                f"""
                SELECT
                    name,
                    extension,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                WHERE name={safe_name}
                """
            )
        )
        if not rows:
            return None
        return TempFilesSchema.from_cursor(rows[0])

    @staticmethod
    def all(
        provider: DBProvider,
        table_name: str = "temp_files",
    ) -> list[TempFilesSchema]:
        return [
            TempFilesSchema.from_cursor(row)
            for row in provider.run_query(
                f"""
                SELECT
                    name,
                    extension,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                """
            )
        ]


class WorkspaceSchema(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    create_date: datetime
    last_modified: datetime
    uuid: uuid.UUID

    def insert_sql(self, table_name: str = "workspaces") -> str:
        return f"""
            INSERT INTO {table_name} VALUES (
                '{self.name}',
                '{self.create_date.isoformat()}',
                '{self.last_modified.isoformat()}',
                '{self.uuid}'
            )
        """

    def update_sql(self, table_name: str = "workspaces") -> str:
        self.last_modified = datetime.now()
        return f"""
            UPDATE {table_name}
            SET
                name='{self.name}',
                create_date='{self.create_date.isoformat()}',
                last_modified='{self.last_modified.isoformat()}'
            WHERE uuid='{self.uuid}'
        """

    def delete_sql(self, chat_dir: pathlib.Path, table_name: str = "workspaces") -> str:
        chat_path = chat_dir / f"{self.uuid}.json"
        chat_path.unlink(missing_ok=True)
        return f"""
            DELETE FROM {table_name}
            WHERE uuid='{self.uuid}'
        """

    def create_state(
        self, prompt: str, data_path: pathlib.Path, files: list[ChatFile]
    ) -> ChatState:
        return ChatState(ChatMessages(prompt), data_path, files, [])

    def load_state(
        self, chat_dir: pathlib.Path, data_path: pathlib.Path, files: list[ChatFile]
    ) -> ChatState:
        fpath = chat_dir / f"{self.uuid}.json"
        return ChatState.from_file(fpath, data_path, files)

    def save_state(self, state: ChatState, chat_dir: pathlib.Path):
        fpath = chat_dir / f"{self.uuid}.json"
        with open(fpath, "w") as f:
            _ = f.write(state.to_json())

    @staticmethod
    def create_table_sql(table_name: str = "workspaces") -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                name TEXT NOT NULL,
                create_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                uuid TEXT NOT NULL UNIQUE PRIMARY KEY
            ) STRICT
        """

    @staticmethod
    def create(name: str) -> WorkspaceSchema:
        now = datetime.now()
        cur_uuid = uuid.uuid4()
        return WorkspaceSchema(
            name=name,
            create_date=now,
            last_modified=now,
            uuid=cur_uuid,
        )

    @staticmethod
    def from_cursor(row: RawDbRow) -> WorkspaceSchema:
        if len(row) != 4:
            raise ValueError

        name, _raw_create_date, _raw_last_modified, _raw_uuid = row

        assert isinstance(name, str), "name must be str"
        assert isinstance(_raw_create_date, str), "create_date must be str"
        assert isinstance(_raw_last_modified, str), "last_modified must be str"
        assert isinstance(_raw_uuid, str), "uuid must be str"
        return WorkspaceSchema(
            name=name,
            create_date=datetime.fromisoformat(_raw_create_date),
            last_modified=datetime.fromisoformat(_raw_last_modified),
            uuid=uuid.UUID(_raw_uuid),
        )

    @staticmethod
    def get_by_uuid(
        provider: DBProvider,
        record_uuid: str,
        table_name: str = "workspaces",
    ) -> WorkspaceSchema | None:
        rows = list(
            provider.run_query(
                f"""
                SELECT
                    name,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                WHERE uuid='{record_uuid}'
                """
            )
        )
        if not rows:
            return None
        return WorkspaceSchema.from_cursor(rows[0])

    @staticmethod
    def all(
        provider: DBProvider,
        table_name: str = "workspaces",
    ) -> list[WorkspaceSchema]:
        return [
            WorkspaceSchema.from_cursor(row)
            for row in provider.run_query(
                f"""
                SELECT
                    name,
                    create_date,
                    last_modified,
                    uuid
                FROM {table_name}
                """
            )
        ]


@final
class ConfigsSchema:
    def __init__(self, table_name: str = "configs"):
        self.table_name = table_name

    def get_value(self, name: str, provider: DBProvider) -> str | None:
        safe_name = sanitise_sql(name)
        rows = list(
            provider.run_query(
                f"""
                    SELECT value
                    FROM {self.table_name}
                    WHERE name={safe_name}
                    LIMIT 1
                """
            )
        )
        if not rows:
            return None

        row = rows[0]
        assert len(row) == 1, "configs row must contain single column"
        value = row[0]
        assert isinstance(value, str), "value must be str"
        return value

    def set_value(self, name: str, value: str, provider: DBProvider) -> None:
        assert isinstance(value, str), "value must be str"
        safe_name = sanitise_sql(name)
        safe_value = sanitise_sql(value)
        _ = provider.run_query(
            f"""
                DELETE FROM {self.table_name}
                WHERE name={safe_name}
            """
        )
        _ = provider.run_query(
            f"""
                INSERT INTO {self.table_name} (name, value)
                VALUES ({safe_name}, {safe_value})
            """
        )

    @staticmethod
    def create_table_sql(table_name: str = "configs") -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                name TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL
            ) STRICT
        """
