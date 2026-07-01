from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SnippetBase(BaseModel):
    shortcut: str = Field(min_length=1, max_length=100)
    expansion: str = Field(min_length=1)


class SnippetCreate(SnippetBase):
    pass


class SnippetUpdate(BaseModel):
    shortcut: str | None = Field(default=None, min_length=1, max_length=100)
    expansion: str | None = Field(default=None, min_length=1)


class SnippetRead(SnippetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archived: bool
    created_at: datetime
    updated_at: datetime
