"""Application configuration and agent setup."""

from functools import lru_cache

from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment."""

    model_config = SettingsConfigDict(env_file=('.env',), extra="ignore")

    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_api_provider: str = Field(alias="OPENAI_API_PROVIDER")
    openai_default_model: str = Field(alias="OPENAI_API_MODEL")

    def initial_check(self) -> None:
        """Ensure required environment variables are populated."""

        assert self.openai_api_key is not None, "OPENAI_API_KEY must be set"
        assert self.openai_api_provider is not None, "OPENAI_API_PROVIDER must be set"
        assert self.openai_default_model is not None, "OPENAI_API_MODEL must be set"

    def get_agent(self) -> Agent:
        """Create an agent instance configured for the current environment."""

        resolved_model = self.openai_default_model
        api_key = self.openai_api_key or None
        provider = OpenAIProvider(base_url=self.openai_api_provider, api_key=api_key)
        chat_model = OpenAIChatModel(model_name=resolved_model, provider=provider)
        return Agent(model=chat_model)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.initial_check()
    return settings
