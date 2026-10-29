"""Which aspect ratios are valid on each delivery platform.

The table is ours. Vertical feeds prefer 9:16. YouTube, LinkedIn, and a
company site prefer 16:9 and also accept a vertical cut.
"""

from __future__ import annotations

COMMON_ASPECTS = ("16:9", "9:16", "1:1", "3:4", "4:5")

# preferred is what we add when the user named the platform but not the frame.
# allowed is what quality check treats as a match.
_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "抖音": {"preferred": ("9:16",), "allowed": ("9:16", "1:1")},
    "TikTok": {"preferred": ("9:16",), "allowed": ("9:16", "1:1")},
    "快手": {"preferred": ("9:16",), "allowed": ("9:16", "1:1")},
    "视频号": {"preferred": ("9:16",), "allowed": ("9:16", "16:9", "1:1")},
    "小红书": {"preferred": ("3:4",), "allowed": ("3:4", "9:16", "1:1")},
    "YouTube": {"preferred": ("16:9",), "allowed": ("16:9", "9:16", "1:1")},
    "LinkedIn": {"preferred": ("16:9",), "allowed": ("16:9", "9:16", "1:1")},
    "B站": {"preferred": ("16:9",), "allowed": ("16:9", "9:16")},
    "官网": {"preferred": ("16:9",), "allowed": ("16:9", "1:1")},
    "Instagram": {"preferred": ("9:16",), "allowed": ("9:16", "1:1", "4:5")},
    "微信朋友圈": {"preferred": ("1:1",), "allowed": ("1:1", "16:9", "9:16")},
}

# Longer aliases first inside a row. Rows are scanned by earliest match in the text.
PLATFORM_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("微信朋友圈", ("微信朋友圈", "朋友圈")),
    ("视频号", ("微信视频号", "视频号")),
    ("小红书", ("小红书", "rednote")),
    ("抖音", ("抖音", "douyin")),
    ("TikTok", ("tiktok",)),
    ("快手", ("快手", "kuaishou")),
    ("YouTube", ("youtube", "油管")),
    ("LinkedIn", ("linkedin", "领英")),
    ("Instagram", ("instagram",)),
    ("B站", ("哔哩哔哩", "bilibili", "b站")),
    ("官网", ("官方网站", "官网")),
)

ASPECT_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("16:9", ("16:9", "16比9", "16：9", "横屏")),
    ("9:16", ("9:16", "9比16", "9：16", "竖屏")),
    ("1:1", ("1:1", "1比1", "方屏", "正方形")),
    ("3:4", ("3:4", "3比4")),
    ("4:5", ("4:5", "4比5")),
)


def known_platforms() -> tuple[str, ...]:
    return tuple(_PROFILES)


def allowed_aspects(platform: str) -> set[str]:
    profile = _PROFILES.get(platform)
    if profile is None:
        return set(COMMON_ASPECTS)
    return set(profile["allowed"])


def preferred_aspect(platform: str) -> str:
    profile = _PROFILES.get(platform)
    if profile is None:
        return "16:9"
    return profile["preferred"][0]


def aspects_match(platforms: list[str], aspects: list[str]) -> bool:
    """Every platform must accept at least one chosen ratio."""

    if not platforms or not aspects:
        return False
    chosen = set(aspects)
    return all(chosen & allowed_aspects(platform) for platform in platforms)


def aspects_for_platforms(platforms: list[str]) -> list[str]:
    ordered: list[str] = []
    for platform in platforms:
        ratio = preferred_aspect(platform)
        if ratio not in ordered:
            ordered.append(ratio)
    return ordered or ["16:9"]


def repair_aspects(platforms: list[str], aspects: list[str]) -> list[str]:
    """Keep the caller's ratios and append a preferred one when a platform has none."""

    kept = _dedupe(aspects)
    for platform in platforms:
        if not set(kept) & allowed_aspects(platform):
            kept.append(preferred_aspect(platform))
    return _dedupe(kept) or ["16:9"]


def canonical_platform(value: str) -> str | None:
    text = value.strip().lower()
    if not text or text in {"mock", "string", "none", "null"}:
        return None
    for canonical, aliases in PLATFORM_ALIASES:
        names = (canonical.lower(), *(alias.lower() for alias in aliases))
        if text in names:
            return canonical
    return None


def find_platforms(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[tuple[int, str]] = []
    for canonical, aliases in PLATFORM_ALIASES:
        positions = [lowered.find(alias.lower()) for alias in aliases]
        positions = [pos for pos in positions if pos >= 0]
        if positions:
            hits.append((min(positions), canonical))
    hits.sort()
    return _dedupe(name for _, name in hits)


def find_aspects(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[tuple[int, str]] = []
    for canonical, aliases in ASPECT_ALIASES:
        positions = [lowered.find(alias.lower()) for alias in aliases]
        positions = [pos for pos in positions if pos >= 0]
        if positions:
            hits.append((min(positions), canonical))
    hits.sort()
    return _dedupe(name for _, name in hits)


def _dedupe(items: object) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:  # type: ignore[union-attr]
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
