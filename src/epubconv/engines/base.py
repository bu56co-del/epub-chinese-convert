from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable


class Engine(ABC):
    name: str = "base"

    @abstractmethod
    def convert(self, text: str) -> str:
        ...

    def convert_batch(self, texts: Iterable[str]) -> list[str]:
        return [self.convert(t) for t in texts]
