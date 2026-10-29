"""BrandKit (SPEC §5.1) and the built-in advertising-law word list."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from workers.schemas.base import HEX_COLOR_PATTERN, JsonBool, JsonFloat, SchemaModel

# SPEC §5.1 names 最 / 第一 / 顶级 / 国家级, and the sample document also uses
# 最好. The rest are the usual absolute claims covered by 广告法第九条
# 「国家级、最高级、最佳」及同类用语. This is our own list, not a third-party dump.
AD_LAW_EXTREME_WORDS: tuple[str, ...] = (
    "最",
    "第一",
    "顶级",
    "国家级",
    "最好",
    "最高级",
    "最佳",
    "最大",
    "最高",
    "最低",
    "最新",
    "最先进",
    "最便宜",
    "唯一",
    "首个",
    "首选",
    "独家",
    "极致",
    "极品",
    "绝对",
    "万能",
    "无敌",
    "顶尖",
    "世界级",
    "史无前例",
    "绝无仅有",
    "销量第一",
    "全网第一",
    "中国第一",
    "第一品牌",
    "永久",
    "根治",
    "包治",
    "无副作用",
    "零风险",
    "100%",
    "百分之百",
)


def default_banned_words() -> list[str]:
    return list(AD_LAW_EXTREME_WORDS)


def find_banned_words(text: str, banned: list[str]) -> list[str]:
    """Return banned terms that occur in ``text``, in list order."""

    return [word for word in banned if word and word in text]


class Industry(StrEnum):
    """Chapter 7 industries. The SPEC sample uses ``manufacturing``."""

    manufacturing = "manufacturing"
    foreign_trade = "foreign_trade"
    ecommerce = "ecommerce"
    local_life = "local_life"
    education = "education"
    public_sector = "public_sector"


class LogoAsset(SchemaModel):
    primary: str = Field(min_length=1)
    mono_white: str = Field(min_length=1)
    safe_area_ratio: JsonFloat = Field(gt=0, le=1)


class BrandColors(SchemaModel):
    primary: str = Field(pattern=HEX_COLOR_PATTERN)
    secondary: str = Field(pattern=HEX_COLOR_PATTERN)
    accent: str = Field(pattern=HEX_COLOR_PATTERN)


class BrandFonts(SchemaModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)


class Product(SchemaModel):
    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    photos: list[str]
    cutouts: list[str]
    selling_points: list[str]
    forbidden_changes: list[str]


class Person(SchemaModel):
    """A person may be stored only with an explicit consent flag (N2)."""

    person_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    photos: list[str]
    consent: JsonBool
    voice_id: str | None


class BrandVoice(SchemaModel):
    tts_voice: str = Field(min_length=1)
    speed: JsonFloat = Field(gt=0, le=3)


class CallToAction(SchemaModel):
    phone: str
    website: str
    wechat_qr: str


class BrandKit(SchemaModel):
    brand_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    industry: Industry
    logo: LogoAsset
    colors: BrandColors
    fonts: BrandFonts
    products: list[Product]
    people: list[Person]
    voice: BrandVoice
    tone: str = Field(min_length=1)
    banned_words: list[str] = Field(default_factory=default_banned_words)
    cta: CallToAction

    def consented_people(self) -> list[Person]:
        """People N2 is allowed to put on screen (``consent`` is true)."""

        return [person for person in self.people if person.consent]

    def with_extra_banned_words(self, extra: list[str]) -> BrandKit:
        """Return a copy whose banned list appends enterprise-specific terms.

        An explicit ``banned_words`` value is stored as written so the SPEC
        sample round-trips. Call this when the enterprise wants to append.
        """

        merged = list(self.banned_words)
        for word in extra:
            if word and word not in merged:
                merged.append(word)
        return self.model_copy(update={"banned_words": merged})
