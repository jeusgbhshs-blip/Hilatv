"""Medical, food, and finance copy is flagged for a person to review.

推断: chapter 7 industries do not include these sectors, so the flag is a
keyword scan of the brief and the script. It does not block the file. A launch
review should replace the lists.
"""

from __future__ import annotations

from workers.schemas.brand import BrandKit, Industry

SECTORS: dict[str, tuple[str, ...]] = {
    "medical": ("医疗", "医药", "药品", "医院", "诊所", "处方", "保健品"),
    "food": ("食品", "保健食品", "预制菜", "餐饮"),
    "finance": ("金融", "理财", "保险", "贷款", "基金", "证券", "银行"),
}


def manual_sectors(text: str, brand: BrandKit | None = None) -> list[str]:
    found: list[str] = []
    for name, words in SECTORS.items():
        if any(word and word in text for word in words):
            found.append(name)
    if brand is not None and brand.industry == Industry.public_sector:
        found.append("public_sector")
    return found
