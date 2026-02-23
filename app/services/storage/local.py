import os
from pathlib import Path
from .base import FileStorage


class LocalStorage(FileStorage):

    def __init__(self, root="./tmp_case_files"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(self, path: str, content: bytes) -> str:
        full_path = self.root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "wb") as f:
            f.write(content)

        return str(full_path)

    async def read(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    async def delete(self, path: str) -> None:
        full_path = Path(path)

        if full_path.exists():
            full_path.unlink()
            await self._cleanup_empty_parents(full_path.parent)

    async def _cleanup_empty_parents(self, folder: Path):
        """
        Recursively remove empty directories up to storage root.
        """
        while folder != self.root:
            if not any(folder.iterdir()):
                folder.rmdir()
                folder = folder.parent
            else:
                break