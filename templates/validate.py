"""Schema and acceptance checks for chapter 7 templates. No live model calls."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from gateway.adapters.mock_adapter import MockAdapter
from gateway.cache import MemoryCache
from gateway.pricing import Pricing
from gateway.router import RouteTable
from gateway.service import Gateway
from gateway.store import SqlStore
from workers.nodes.n01_brief.industries import (
    INDUSTRY_ORDER,
    IndustryTemplate,
    audit_template,
    detect_industry,
    load_industries,
    reset_industries,
)
from workers.nodes.n01_brief.node import run
from workers.nodes.n01_brief.platforms import aspects_match
from workers.nodes.n05_storyboard.presets import (
    ShotPreset,
    load_presets,
    presets_dir,
    reset_presets,
)
from workers.schemas.brief import Brief

ROOT = Path(__file__).resolve().parents[1]
INDUSTRY_DIR = ROOT / "templates" / "industries"

# Chapter 7 table, normalized. Parentheticals and a few wording aliases collapse.
SPEC_NARRATIVE: dict[str, list[str]] = {
    "manufacturing": ["痛点", "产品特写", "参数", "工厂/检测", "认证", "CTA"],
    "foreign_trade": ["应用场景", "产品", "优势", "工厂", "联系方式"],
    "ecommerce": ["3秒钩子", "使用场景", "卖点", "促销", "下单"],
    "local_life": ["环境", "招牌产品", "氛围", "优惠", "地址"],
    "education": ["问题", "解法", "课程亮点", "讲师", "报名"],
    "public_sector": ["背景", "举措", "成效", "愿景"],
}

KEY_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "manufacturing": ("产品零失真", "工业质感", "参数准确"),
    "foreign_trade": ("本地化文案", "多语种配音", "海外审美"),
    "ecommerce": ("9:16", "节奏快", "批量"),
    "local_life": ("真实感", "食物质感", "地址信息"),
    "education": ("数字人讲解可选", "信息清晰"),
    "public_sector": ("庄重", "数据准确", "合规审核更严"),
}

REQUIRED_KEYS = (
    "narrative",
    "shot_sequence",
    "duration_s",
    "aspect_ratios",
    "style_keywords",
    "music_mood",
    "must_include",
    "forbidden",
)

SAMPLES: tuple[tuple[str, str, str], ...] = (
    ("manufacturing", "给数控机床做一条产品宣传片", "product_showcase"),
    ("foreign_trade", "给外贸采购商做一条出海产品视频", "product_showcase"),
    ("ecommerce", "给电商店铺做一条带货短视频", "live_commerce"),
    ("local_life", "给餐厅做一条探店视频", "store_visit"),
    ("education", "给培训机构做一条课程招生片", "course_promo"),
    ("public_sector", "给高新区政府做一条招商宣传片", "corporate_film"),
)

SHOT_SIZES = {"wide", "medium", "close_up"}
SHOT_PURPOSES = {"hook", "selling_point", "spec", "proof", "cta", "person"}
SHOT_MODELS = {"seedance", "kling", "wan"}
_PAREN = re.compile(r"（[^）]*）|\([^)]*\)")
_ALIASES = {
    "工厂与检测": "工厂/检测",
    "行动号召": "CTA",
    "三秒钩子": "3秒钩子",
}


@dataclass
class Report:
    industries: int = 6
    schema: int = 0
    narratives: int = 0
    required: int = 0
    public_review: bool = False
    others_clear: int = 0
    preset_files: int = 0
    trial: int = 0
    formal: int = 0
    selected: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            not self.errors
            and self.schema == self.industries
            and self.narratives == self.industries
            and self.required == self.industries
            and self.public_review
            and self.others_clear == self.industries - 1
            and self.preset_files > 0
            and self.trial == self.preset_files
            and self.formal == 0
            and self.selected == self.industries
        )


def norm_beat(beat: str) -> str:
    text = "".join(str(beat).split())
    text = _PAREN.sub("", text)
    return _ALIASES.get(text, text)


def run_checks() -> Report:
    """Validate the repo templates. Template dir overrides are ignored for this run."""

    saved = {
        key: os.environ.pop(key, None)
        for key in ("HILATV_INDUSTRY_TEMPLATES", "HILATV_SHOT_TEMPLATES")
    }
    reset_industries()
    reset_presets()
    try:
        return _run_checks()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_industries()
        reset_presets()


def main() -> int:
    report = run_checks()
    print(format_report(report))
    return 0 if report.ok else 1


def format_report(report: Report) -> str:
    lines = [
        f"T25 industries schema: {report.schema}/{report.industries}",
        f"T25 narratives: {report.narratives}/{report.industries}",
        f"T25 required elements: {report.required}/{report.industries}",
        (
            "T25 manual_review: "
            f"public_sector={str(report.public_review).lower()} "
            f"others_clear={report.others_clear}/{report.industries - 1}"
        ),
        (f"T25 shot presets: {report.trial}/{report.preset_files} trial, formal {report.formal}"),
        f"T25 n1 select: {report.selected}/{report.industries} mock",
    ]
    lines.extend(f"T25 error: {item}" for item in report.errors)
    lines.append("T25 accept: PASS" if report.ok else "T25 accept: FAIL")
    return "\n".join(lines)


def _run_checks() -> Report:
    report = Report()
    templates: dict[str, IndustryTemplate] = {}
    for industry in INDUSTRY_ORDER:
        template = _check_industry(industry, report)
        if template is not None:
            templates[industry] = template
    if len(templates) == len(INDUSTRY_ORDER):
        try:
            loaded = load_industries()
        except Exception as exc:
            report.errors.append(f"loader: {exc}")
        else:
            if tuple(loaded) != INDUSTRY_ORDER:
                report.errors.append("loader industry order drifted")
    by_id = _check_shots(report)
    _check_references(templates, by_id, report)
    if len(templates) == len(INDUSTRY_ORDER) and not _shot_errors(report):
        _check_selection(templates, report)
    return report


def _shot_errors(report: Report) -> bool:
    return any(item.startswith("shot ") or item.startswith("preset ") for item in report.errors)


def _check_industry(industry: str, report: Report) -> IndustryTemplate | None:
    path = INDUSTRY_DIR / f"{industry}.yaml"
    if not path.is_file():
        report.errors.append(f"{industry}: missing {path.name}")
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        report.errors.append(f"{industry}: template is not a mapping")
        return None
    if "manual_review" not in raw:
        report.errors.append(f"{industry}: manual_review field is missing")
    try:
        template = IndustryTemplate.model_validate(raw)
        if template.industry != industry:
            raise ValueError(f"declares {template.industry}")
        template.video(template.default_video_type)
        if len(template.video_types) > 1 and not template.clarify_question.strip():
            raise ValueError("needs a clarify question")
        if not aspects_match(template.platforms, template.aspect_ratios):
            raise ValueError("platforms and aspects do not match")
        audit_template(industry, template)
    except Exception as exc:
        report.errors.append(f"{industry}: schema {exc}")
        return None
    report.schema += 1
    if industry == "public_sector":
        report.public_review = template.manual_review
    elif not template.manual_review:
        report.others_clear += 1
    got = [norm_beat(item) for item in template.narrative]
    if got == SPEC_NARRATIVE[industry]:
        report.narratives += 1
    else:
        report.errors.append(f"{industry}: narrative {got} != {SPEC_NARRATIVE[industry]}")
    missing = _missing_required(raw, template)
    if missing:
        report.errors.append(f"{industry}: missing {', '.join(missing)}")
    else:
        report.required += 1
    blob = " ".join([*template.requirements, *template.style_keywords])
    for phrase in KEY_REQUIREMENTS[industry]:
        if phrase not in blob:
            report.errors.append(f"{industry}: chapter 7 requirement missing {phrase}")
    if not any("文字" in item for item in template.forbidden):
        report.errors.append(f"{industry}: forbidden list does not block drawn text")
    return template


def _missing_required(raw: dict[str, object], template: IndustryTemplate) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in raw:
            missing.append(key)
            continue
        value = getattr(template, key)
        if value is None or value == "" or value == []:
            missing.append(key)
    if not template.shot_plan:
        missing.append("shot_plan")
    return missing


def _check_shots(report: Report) -> dict[str, ShotPreset]:
    root = presets_dir()
    paths = sorted(root.glob("*.yaml"))
    report.preset_files = len(paths)
    found: dict[str, ShotPreset] = {}
    if not paths:
        report.errors.append("shot library is empty")
        return found
    for path in paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            report.errors.append(f"shot {path.name}: not a mapping")
            continue
        for key in ("status", "formal", "tested_runs"):
            if key not in raw:
                report.errors.append(f"shot {path.name}: missing {key}")
        if raw.get("formal") is True:
            report.formal += 1
        try:
            preset = ShotPreset.model_validate(raw)
        except Exception as exc:
            report.errors.append(f"shot {path.name}: schema {exc}")
            continue
        if preset.id != path.stem:
            report.errors.append(f"shot {path.name}: id is {preset.id}")
            continue
        problems = _preset_problems(preset)
        if problems:
            report.errors.append(f"shot {preset.id}: {'; '.join(problems)}")
            continue
        if preset.id in found:
            report.errors.append(f"shot {preset.id}: duplicate id")
            continue
        found[preset.id] = preset
        report.trial += 1
    try:
        loaded = load_presets()
    except Exception as exc:
        report.errors.append(f"preset loader: {exc}")
    else:
        if len(loaded) != report.trial:
            report.errors.append("preset loader count does not match the trial files")
    return found


def _preset_problems(preset: ShotPreset) -> list[str]:
    problems: list[str] = []
    if preset.status != "试用" or preset.formal or preset.tested_runs != 0:
        problems.append("not an unvalidated trial preset")
    if any(ch.isdigit() for ch in preset.prompt_fragment):
        problems.append("prompt contains a digit")
    if not set(preset.shot_sizes) <= SHOT_SIZES:
        problems.append("unknown shot size")
    if not set(preset.purposes) <= SHOT_PURPOSES:
        problems.append("unknown purpose")
    if preset.recommended_model not in SHOT_MODELS:
        problems.append("unknown recommended model")
    negative = preset.negative_fragment
    lowered = negative.lower()
    if "text" not in lowered and "文字" not in negative:
        problems.append("missing no-text constraint")
    if "logo" not in lowered and "Logo" not in negative:
        problems.append("missing no-logo constraint")
    if "price" not in lowered and "价格" not in negative:
        problems.append("missing no-price constraint")
    if "phone" not in lowered and "电话" not in negative:
        problems.append("missing no-phone constraint")
    return problems


def _check_references(
    templates: dict[str, IndustryTemplate],
    presets: dict[str, ShotPreset],
    report: Report,
) -> None:
    for industry, template in templates.items():
        for row in template.shot_plan:
            preset = presets.get(row.preset)
            if preset is None:
                report.errors.append(f"{industry}: unknown preset {row.preset}")
                continue
            if preset.status != "试用" or preset.formal:
                report.errors.append(f"{industry}: {row.preset} is not trial-only")


def _check_selection(templates: dict[str, IndustryTemplate], report: Report) -> None:
    with tempfile.TemporaryDirectory(prefix="hilatv-t25-") as tmp:
        gateway = _mock_gateway(Path(tmp))
        for industry, sentence, video_type in SAMPLES:
            template = templates[industry]
            if detect_industry(sentence) != industry:
                report.errors.append(f"n1 {industry}: keyword select missed")
                continue
            try:
                result = run(
                    {"project_id": f"accept-t25-{industry}", "payload": {"raw_input": sentence}},
                    gateway=gateway,
                )
                brief = Brief.model_validate(result.payload["brief"])
            except Exception as exc:
                report.errors.append(f"n1 {industry}: {exc}")
                continue
            mismatches = _brief_mismatches(brief, template, video_type)
            if mismatches:
                report.errors.append(f"n1 {industry}: {'; '.join(mismatches)}")
                continue
            logs = gateway.store.list_logs(project_id=f"accept-t25-{industry}")
            if not logs or any(row["provider"] != "mock" or row["live"] for row in logs):
                report.errors.append(f"n1 {industry}: call was not mock")
                continue
            if any(Decimal(str(row["cost_cny"])) != 0 for row in logs):
                report.errors.append(f"n1 {industry}: mock call recorded a cost")
                continue
            report.selected += 1


def _brief_mismatches(brief: Brief, template: IndustryTemplate, video_type: str) -> list[str]:
    found: list[str] = []
    if brief.video_type != video_type:
        found.append(f"video_type={brief.video_type}")
    if brief.duration_s != template.duration_s:
        found.append(f"duration={brief.duration_s}")
    if brief.platform != template.platforms:
        found.append(f"platforms={brief.platform}")
    if brief.languages != template.languages:
        found.append(f"languages={brief.languages}")
    if brief.style != template.style_default:
        found.append(f"style={brief.style}")
    if not any(template.label in item and "模板" in item for item in brief.assumptions):
        found.append("assumptions do not name the template")
    return found


def _mock_gateway(tmp: Path) -> Gateway:
    routes = tmp / "routes.yaml"
    routes.write_text(
        "\n".join(
            (
                "version: 1",
                "defaults:",
                "  timeout_s: 5",
                "routes:",
                "  - id: llm",
                "    task: llm",
                "    shot_type: '*'",
                "    language: '*'",
                "    primary: {provider: mock, model: mock-llm}",
                "    fallbacks: []",
                "",
            )
        ),
        encoding="utf-8",
    )
    progress = tmp / "progress.md"
    progress.write_text(
        "## 告警（预算超限等，由网关自动追加）\n\n<!-- hilatv:alerts -->\n\n## 每日日志\n",
        encoding="utf-8",
    )
    return Gateway(
        routes=RouteTable(routes),
        store=SqlStore.sqlite(tmp / "gateway.sqlite"),
        cache=MemoryCache(),
        pricing=Pricing.load(),
        registry={"mock": MockAdapter()},
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=progress,
        model_overrides_fn=lambda: {},
    )


if __name__ == "__main__":
    raise SystemExit(main())
