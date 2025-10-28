from typing import final

from pydantic import BaseModel


class ClinicalTrialsReport(BaseModel):
    title: str
    nct_id: str
    organisation: str
    collaborators: list[str]


class ClinicalTrialsGov:
    pass
