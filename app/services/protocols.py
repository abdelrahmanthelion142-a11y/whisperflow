from typing import Protocol


class UploadLike(Protocol):
    """A file-like object exposing a filename and an async ``read``."""

    filename: str

    async def read(self, _size: int = -1) -> bytes: ...