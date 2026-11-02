"""把结构化分镜字段编译成 Seedance 可用的提示词与参数。

分镜表是可编辑的：用户改的是字段，不是一段黑盒提示词。
编译器负责把字段按固定规则拼成提示词，并保留每一段的来源（parts），
这样界面能解释「这句话是哪来的」，也能只改其中一段再重编译。
"""

from __future__ import annotations

from typing import Any

# 全片固定的质感词（剧本可覆盖 style_bible）
STYLE_WORDS = {
    "写实电影感": "照片级真实感，真实光影与材质，浅景深，电影级打光，cinematic photoreal；"
    "不要动画、不要卡通、不要插画。",
    "2D绘本": "2D柔和绘本动画风格，干净线条，温暖平涂，绘本质感；不要3D渲染、不要写实照片。",
    "广告质感": "高端商业广告质感，干净构图，产品细节清晰，柔和棚拍光；不要杂乱背景。",
}

DEFAULT_NEGATIVE = (
    "画面中不要出现任何文字、数字、字母、字幕、水印、标志、价格、电话；"
    "屏幕只显示纯发光画面，不显示可读内容；不要变形的手、不要畸变人脸。"
)


def compile_shot(
    shot: dict[str, Any],
    *,
    order: int,
    total: int,
    meta: dict[str, Any] | None = None,
    ext: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns the prompt, negative prompt, per-shot generation params and parts."""

    meta = meta or {}
    ext = ext or {}
    size = str(shot.get("shot_size") or "medium")
    camera = str(shot.get("camera") or "locked_off")
    duration = float(shot.get("duration_s") or 5)
    model = str((ext.get("generation") or {}).get("model") or "seedance-2.0")
    # Seedance 2.x 只接受 5 或 10 秒。
    gen_duration = 5 if duration <= 7 else 10
    ratio = str(meta.get("aspect_ratio") or "9:16")
    resolution = str((ext.get("generation") or {}).get("resolution") or "720p")
    style = str(meta.get("style_bible") or "写实电影感")
    style_words = STYLE_WORDS.get(style, style)

    parts: list[dict[str, str]] = []

    def add(kind: str, text: str) -> None:
        if text.strip():
            parts.append({"kind": kind, "text": text.strip()})

    genre = meta.get("genre") or "商业短片"
    add("任务", f"这是{genre}的第 {order}/{total} 镜，时长 {gen_duration} 秒，{ratio} 竖屏。")
    subject = str(shot.get("visual") or "")
    add("主体与画面", subject)
    purpose = str(shot.get("purpose") or "")
    add("这一镜的任务", purpose)
    add("景别与机位", f"景别：{size}；机位：{camera}。")
    lighting = str(ext.get("lighting") or "")
    mood = str(ext.get("mood") or "")
    if lighting or mood:
        add("光线与氛围", "；".join(item for item in (lighting, mood) if item))
    characters = ext.get("characters") or []
    character_text = "；".join(
        f"{item.get('name')}（{item.get('desc')}）"
        for item in characters
        if isinstance(item, dict) and (item.get("name") or item.get("desc"))
    )
    if character_text:
        add("角色与造型", character_text)
    action = str(ext.get("action") or "")
    emotion = str(ext.get("emotion") or "")
    if action or emotion:
        add("动作与情绪", "；".join(item for item in (action, emotion) if item))
    angle = str(ext.get("camera_angle") or "")
    if angle:
        add("机位角度", angle)
    visual_effect = str(ext.get("visual_effect") or "")
    color = str(ext.get("color") or "")
    if color or visual_effect:
        add("色彩与视觉效果", "；".join(item for item in (color, visual_effect) if item))
    sfx = ext.get("sfx") or []
    bgm = str(ext.get("bgm") or "")
    if sfx or bgm:
        add("声音", "；".join([*(str(item) for item in sfx), f"BGM：{bgm}" if bgm else ""]))
    continuity = str(ext.get("continuity_notes") or "")
    if continuity:
        add("连续性", continuity)
    if previous:
        add(
            "衔接",
            f"与上一镜（{previous.get('shot_id')}）保持同一场景、同一人物造型与光线方向，"
            "上一镜结尾动作接这一镜开头。",
        )
    transition = str(shot.get("transition_out") or "cut")
    if transition and transition != "cut":
        add("转场", f"本镜结尾使用{transition}转场。")
    add("质感", style_words)

    prompt = "\n".join(part["text"] for part in parts)
    negative = str((ext.get("generation") or {}).get("negative") or DEFAULT_NEGATIVE)
    return {
        "prompt": prompt,
        "negative_prompt": negative,
        "parts": parts,
        "params": {
            "model": model,
            "ratio": ratio,
            "resolution": resolution,
            "duration_s": gen_duration,
            "source_duration_s": duration,
        },
    }


def compile_script(
    shots: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
    exts: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    exts = exts or {}
    total = len(shots)
    compiled: list[dict[str, Any]] = []
    for index, shot in enumerate(shots, 1):
        previous = shots[index - 2] if index >= 2 else None
        compiled.append(
            compile_shot(
                shot,
                order=index,
                total=total,
                meta=meta,
                ext=exts.get(str(shot.get("shot_id")), {}),
                previous=previous,
            )
        )
    return compiled
