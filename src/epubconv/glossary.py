from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Private Use Area markers; OpenCC and Fanhuaji leave PUA untouched.
_OPEN = ""
_CLOSE = ""


@dataclass(frozen=True)
class Glossary:
    """User-defined rules applied around the engine.

    - ``protect``: tokens passed through unchanged (engine sees a placeholder).
    - ``pre``: ordered (search, replace) pairs applied to the source text
      before protection / engine conversion. Useful for typo fixes or to
      normalise the source side.
    - ``post``: ordered (search, replace) pairs applied after the engine and
      placeholder restoration. Useful for overriding engine output (e.g.
      forcing HK terminology even when engine produces a TW term).
    """

    protect: tuple[str, ...] = ()
    pre: tuple[tuple[str, str], ...] = ()
    post: tuple[tuple[str, str], ...] = ()

    @classmethod
    def empty(cls) -> "Glossary":
        return cls()

    @classmethod
    def from_yaml(cls, path: Path) -> "Glossary":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: glossary YAML must be a mapping")
        return cls(
            protect=tuple(_as_str_list(data.get("protect", []), "protect")),
            pre=tuple(_as_pair_list(data.get("pre", {}), "pre")),
            post=tuple(_as_pair_list(data.get("post", {}), "post")),
        )

    def is_empty(self) -> bool:
        return not (self.protect or self.pre or self.post)

    def merge(self, other: "Glossary") -> "Glossary":
        """Concatenate ``other`` after ``self``.

        ``self``'s rules apply first; ``other``'s rules run after and can
        therefore override (e.g. a series glossary defines a default term,
        and a per-book glossary overrides it).
        """
        return Glossary(
            protect=self.protect + other.protect,
            pre=self.pre + other.pre,
            post=self.post + other.post,
        )

    def apply_pre(self, text: str) -> tuple[str, dict[str, str]]:
        """Apply pre rules and replace protected tokens with placeholders.

        Returns ``(transformed_text, restore_map)`` where ``restore_map`` maps
        each placeholder back to its original token.
        """
        for search, replace in self.pre:
            if search:
                text = text.replace(search, replace)

        restore: dict[str, str] = {}
        # Sort by length desc so longer overlapping tokens win.
        for idx, token in enumerate(sorted(set(self.protect), key=len, reverse=True)):
            if not token or token not in text:
                continue
            placeholder = f"{_OPEN}{idx}{_CLOSE}"
            text = text.replace(token, placeholder)
            restore[placeholder] = token
        return text, restore

    def apply_post(self, text: str, restore: dict[str, str]) -> str:
        for placeholder, token in restore.items():
            text = text.replace(placeholder, token)
        for search, replace in self.post:
            if search:
                text = text.replace(search, replace)
        return text


def _as_str_list(value: object, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"glossary.{key} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"glossary.{key} entries must be strings, got {type(item).__name__}")
        out.append(item)
    return out


def _as_pair_list(value: object, key: str) -> list[tuple[str, str]]:
    if value is None:
        return []
    # Accept either a mapping or a list of single-key mappings (preserves order in either case;
    # PyYAML 5.1+ preserves dict order).
    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, list):
        items = []
        for entry in value:
            if not isinstance(entry, dict) or len(entry) != 1:
                raise ValueError(
                    f"glossary.{key} list entries must be single-pair mappings"
                )
            items.append(next(iter(entry.items())))
    else:
        raise ValueError(f"glossary.{key} must be a mapping or list of single-pair mappings")

    pairs: list[tuple[str, str]] = []
    for k, v in items:
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(f"glossary.{key} keys and values must be strings")
        pairs.append((k, v))
    return pairs
