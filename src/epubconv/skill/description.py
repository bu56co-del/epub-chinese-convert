"""Generate a Skill `description` field from EPUB metadata + extracted names.

The Skill description is what Claude reads at discovery time to decide
whether to load the skill, so it must contain the right trigger phrases.
We compose it deterministically from:

* `<dc:title>` and `<dc:creator>`
* the OPF `<dc:description>` blurb when present
* the top-N proper-noun candidates (from ``names.extract_candidates``)

Combined output is capped at ``DESCRIPTION_MAX_CHARS`` so it fits inside
Claude Code's frontmatter budget.
"""
from __future__ import annotations

DESCRIPTION_MAX_CHARS = 1024
TOP_NAMES = 5


def build_description(
    metadata: dict[str, str | list[str]],
    top_names: list[str],
    *,
    override: str | None = None,
    max_chars: int = DESCRIPTION_MAX_CHARS,
) -> str:
    """Return a triggerful description for a SKILL.md frontmatter."""
    if override:
        return override.strip()[:max_chars]

    title = _first(metadata.get("title", "")) or "Untitled"
    creator = _first(metadata.get("creator", ""))
    blurb = _first(metadata.get("description", "")).strip()

    head = f"《{title}》"
    if creator:
        head += f"（{creator}）"
    head += " 嘅原著內容知識庫。"

    names_part = ""
    picked = [n for n in top_names if n][:TOP_NAMES]
    if picked:
        names_part = f"主要角色或專名：{ '、'.join(picked) }。"

    trigger = (
        f"Use when the user asks about plot, characters, terminology, or wants "
        f"to verify details from《{title}》, including specific events, "
        f"chapters, or quotations."
    )

    parts = [head]
    if blurb:
        parts.append(_truncate(blurb, max_chars // 3))
    if names_part:
        parts.append(names_part)
    parts.append(trigger)

    out = " ".join(p.strip() for p in parts if p.strip())
    return _truncate(out, max_chars)


def _first(value: str | list[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"
