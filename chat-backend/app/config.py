"""Application configuration and provider factories."""

from functools import cached_property
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai import Agent, Tool
from pydantic_settings import BaseSettings
from app.db import (
    db_provider_manager,
    SqliteProvider,
    FilesSchema,
    ConfigsSchema,
    WorkspaceSchema,
    TempFilesSchema,
)
from app.libs._chat import ChatState, AgenticKeywordMaker, ChatFile
from app.libs.expected import Expected
import pathlib
import os


class ConfigError(RuntimeError):
    """Raised when persisted configuration is invalid or incomplete."""

    pass


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment."""

    db_path: pathlib.Path
    root_path: pathlib.Path
    assets_path: pathlib.Path

    def data_path(self) -> pathlib.Path:
        directory = self.root_path / "root"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def tmp_path(self) -> pathlib.Path:
        directory = self.root_path / "tmp"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def prompt_dir(self) -> pathlib.Path:
        return self.assets_path / "system_prompt"

    def chat_dir(self) -> pathlib.Path:
        directory = self.root_path / "chat"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def get_db_conn(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_provider_manager(SqliteProvider(self.db_path))

    @cached_property
    def config(self):
        return ConfigsSchema("configs")

    def get_model(self) -> Expected[OpenAIChatModel, ConfigError]:
        """Return an OpenAIChatModel configured from persisted server settings."""
        with self.get_db_conn() as conn:
            model_name = self.config.get_value("MODEL_NAME", conn)
            api_url = self.config.get_value("API_URL", conn)
            api_key = self.config.get_value("API_KEY", conn)

        if model_name is None:
            return Expected(
                OpenAIChatModel, ConfigError, ConfigError("model_name is missing")
            )
        if api_url is None:
            return Expected(
                OpenAIChatModel, ConfigError, ConfigError("api_url is missing")
            )
        if api_key is None:
            return Expected(
                OpenAIChatModel, ConfigError, ConfigError("api_key is missing")
            )

        provider = OpenAIProvider(base_url=api_url, api_key=api_key)
        return Expected(
            OpenAIChatModel,
            ConfigError,
            OpenAIChatModel(model_name=model_name, provider=provider),
        )

    def get_username(self):
        with self.get_db_conn() as conn:
            username = self.config.get_value("USER_NAME", conn)
            if username is None:
                return "Anoymous User"
            else:
                return username

    def get_topic_agent(self):
        model = self.get_model()
        with open(self.prompt_dir() / "topic.md", "r") as f:
            return model.transform(
                Agent, lambda model: Agent(model=model, system_prompt=f.read())
            )

    def get_summary_agent(self):
        model = self.get_model()
        with open(self.prompt_dir() / "summary.md", "r") as f:
            return model.transform(
                Agent, lambda model: Agent(model=model, system_prompt=f.read())
            )

    def get_keyword_agent(self):
        model = self.get_model()
        with open(self.prompt_dir() / "publication.md", "r") as f:
            return model.transform(
                Agent,
                lambda model: Agent(
                    model=model, system_prompt=f.read().format(keyword_count=3)
                ),
            )

    def get_continuator_agent(self):
        model = self.get_model()
        with open(self.prompt_dir() / "continuation.md", "r") as f:
            return model.transform(
                Agent, lambda model: Agent(model=model, system_prompt=f.read())
            )

    def get_chat_system_prompt(self):
        with open(self.prompt_dir() / "chat.md", "r") as f:
            return f.read()

    def get_chat_agent(self, state: ChatState):
        model = self.get_model()
        with open(self.prompt_dir() / "chat.md", "r") as f:
            return model.transform(
                Agent,
                lambda model: Agent(
                    model=model,
                    tools=[
                        Tool(
                            state.list_file,
                            name="ls",
                            description="List all files in the user filesystem",
                            strict=True,
                            max_retries=1,
                        ),
                        Tool(
                            state.read_file,
                            name="read_file",
                            description="Read a file in the current filesystem",
                            strict=True,
                            max_retries=1,
                        ),
                        Tool(
                            state.query_publications_length,
                            name="query_publications_length",
                            description="Get the length of the current obtained publications",
                            strict=True,
                            max_retries=1,
                        ),
                        Tool(
                            state.query_publications,
                            name="query_publications",
                            description="Queries publications, call get_publication to read the contents of queried publications.",
                            strict=True,
                            max_retries=1,
                        ),
                        Tool(
                            state.get_publications,
                            name="get_publications",
                            description=(
                                "Retrieve cached publication entries by index."
                            ),
                            strict=True,
                            max_retries=1,
                        ),
                    ],
                    system_prompt=f.read().format(username=self.get_username()),
                ),
            )

    def get_keyword_maker(self):
        return self.get_keyword_agent().transform(
            AgenticKeywordMaker, lambda a: AgenticKeywordMaker(a)
        )

    def initialise_database(self):
        with self.get_db_conn() as conn:
            _ = conn.run_query(ConfigsSchema.create_table_sql("configs"))
            _ = conn.run_query(FilesSchema.create_table_sql("files"))
            _ = conn.run_query(WorkspaceSchema.create_table_sql("workspaces"))
            _ = conn.run_query(TempFilesSchema.create_table_sql("temp_files"))

    def set_up(self):
        self.initialise_database()
        _ = self.data_path()
        _ = self.tmp_path()
        _ = self.chat_dir()

    def get_files(self) -> list[ChatFile]:
        with self.get_db_conn() as conn:
            return list(
                map(
                    lambda x: ChatFile(name=x.name, summary=x.summary, path=x.name),
                    FilesSchema.all(conn),
                )
            )


settings = Settings(
    db_path=pathlib.Path(os.environ.get("APP_DB_PATH", "data/local.db")),
    root_path=pathlib.Path(os.environ.get("APP_DATA_PATH", "data")),
    assets_path=pathlib.Path(os.environ.get("APP_ASSETS_PATH", "assets")),
)
settings.set_up()
