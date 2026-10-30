"""「本片使用的素材与授权说明」. The path is chosen here, not by the client."""

from __future__ import annotations

from pathlib import Path

from workers.schemas.label_lock import LABEL_TEXT
from workers.schemas.licensing import LicensingSummary

NOTE_NAME = "materials-and-licences.txt"


def note_path(root: Path) -> Path:
    path = (root / "compliance" / NOTE_NAME).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("materials note must stay inside the project directory")
    return path


def render_note(
    summary: LicensingSummary,
    *,
    manual_review: bool,
    sectors: list[str],
    variants: int,
) -> str:
    lines = [
        "本片使用的素材与授权说明",
        f"项目: {summary.project_id}",
        f"导出版本: {variants}",
        "",
        "显式标识: 画面角标「" + LABEL_TEXT + "」，由渲染层叠加，不能通过改稿去掉。",
        "隐式标识: MP4 文件元数据字段 AIGC（Label=1，服务提供者 HiLatv，内容编号见 ProduceID）。",
        "标识依据: 《人工智能生成合成内容标识办法》第四条、第五条"
        "（国信办通字〔2025〕2号，2025-03-14 公布，2025-09-01 施行）。",
        "推断: 角标字号、白字深底和 ffmpeg format tag 对照 GB 45438-2025，上线前由法务核对。",
        "",
        "类型\t来源\t许可\t证明\t到期\t使用范围",
    ]
    for record in summary.records:
        expiry = record.expires_on.isoformat() if record.expires_on else "未设到期"
        lines.append(
            "\t".join(
                [
                    record.kind,
                    record.source or "（缺失）",
                    record.license or "（缺失）",
                    record.evidence_ref or "（无证明引用）",
                    expiry,
                    record.usage_scope or record.note or "本片",
                ]
            )
        )
    lines.append("")
    if manual_review:
        names = "、".join(sectors) or "未命名"
        lines.append(
            f"人工审核: 需要。命中特殊行业 {names}（医疗 / 食品 / 金融）。"
            "成片已生成，未视为审核通过。"
        )
    else:
        lines.append("人工审核: 未命中医疗、食品、金融关键词。")
    if summary.blocked:
        lines.append(f"交付: 已阻断。{summary.block_reason}")
    else:
        lines.append("交付: 授权记录齐全且未过期。")
    lines.append("")
    return "\n".join(lines)


def write_note(root: Path, text: str) -> Path:
    path = note_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
