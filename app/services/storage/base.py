from abc import ABC, abstractmethod

class FileStorage(ABC):

    @abstractmethod
    async def save(self, path: str, content: bytes) -> str:
        """Save file and return public or retrievable URL/path"""
        pass

    @abstractmethod
    async def read(self, path: str) -> bytes:
        pass

    @abstractmethod
    async def delete(self, path: str) -> None:
        pass