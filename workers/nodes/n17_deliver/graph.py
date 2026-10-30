"""FFmpeg filter graphs for a reframe and for the render-layer burn.

On-screen words are PNG overlays. The graph never uses drawtext.
"""

from __future__ import annotations

from workers.nodes.n17_deliver.reframe import ShotGeometry

_FPS = 30


def reframe_graph(geometries: list[ShotGeometry], background_inputs: dict[str, int]) -> str:
    count = len(geometries)
    if count == 0:
        raise ValueError("reframe needs at least one shot")
    lines: list[str] = []
    if count == 1:
        sources = ["0:v"]
    else:
        lines.append(f"[0:v]split={count}" + "".join(f"[s{index}]" for index in range(count)))
        sources = [f"s{index}" for index in range(count)]
    labels: list[str] = []
    for index, geo in enumerate(geometries):
        out = "vout" if count == 1 else f"v{index}"
        lines.extend(
            _shot_lines(sources[index], index, geo, background_inputs.get(geo.shot_id), out)
        )
        labels.append(f"[{out}]")
    if count > 1:
        lines.append(f"{''.join(labels)}concat=n={count}:v=1:a=0[vout]")
    return ";".join(lines)


def reframe_command(
    source: str,
    geometries: list[ShotGeometry],
    backgrounds: list[tuple[str, str]],
    dest: str,
) -> list[str]:
    """``backgrounds`` is ``(shot_id, png)`` in input order, starting at input 1."""

    mapping = {shot_id: index + 1 for index, (shot_id, _path) in enumerate(backgrounds)}
    args = ["ffmpeg", "-y", "-loglevel", "error", "-threads", "1", "-i", source]
    span = sum(item.duration_s for item in geometries)
    for _shot_id, path in backgrounds:
        args += ["-loop", "1", "-framerate", str(_FPS), "-t", f"{span:.3f}", "-i", path]
    args += [
        "-filter_complex",
        reframe_graph(geometries, mapping),
        "-map",
        "[vout]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-x264-params",
        "threads=1:sliced-threads=0:bframes=0",
        "-r",
        str(_FPS),
        "-fflags",
        "+bitexact",
        "-flags",
        "+bitexact",
        dest,
    ]
    return args


def burn_command(
    video: str,
    audios: list[tuple[str, float]],
    overlays: list[tuple[str, float, float, int, int]],
    dest: str,
    duration_s: float,
) -> tuple[list[str], str]:
    """Audios are ``(path, delay_s)``. Overlays are ``(path, start, end, x, y)``."""

    delayed: list[tuple[str, float]] = []
    for path, delay_s in audios:
        delayed.append((path, delay_s))
    graph = _burn_with_delays(delayed, overlays, duration_s)
    args = ["ffmpeg", "-y", "-loglevel", "error", "-threads", "1", "-i", video]
    for path, _delay in delayed:
        args += ["-i", path]
    args += [
        "-f",
        "lavfi",
        "-t",
        f"{duration_s:.3f}",
        "-i",
        "anullsrc=r=48000:cl=stereo",
    ]
    for path, _start, _end, _x, _y in overlays:
        args += ["-loop", "1", "-framerate", str(_FPS), "-t", f"{duration_s:.3f}", "-i", path]
    args += [
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-x264-params",
        "threads=1:sliced-threads=0:bframes=0",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-t",
        f"{duration_s:.3f}",
        "-fflags",
        "+bitexact",
        "-flags",
        "+bitexact",
        dest,
    ]
    return args, graph


def _burn_with_delays(
    audios: list[tuple[str, float]],
    overlays: list[tuple[str, float, float, int, int]],
    duration_s: float,
) -> str:
    lines: list[str] = ["[0:v]fps=30,setsar=1,format=yuv420p[base]"]
    bed = 1 + len(audios)
    lines.append(
        f"[{bed}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
        f"atrim=0:{duration_s:.3f},asetpts=PTS-STARTPTS[bed]"
    )
    mix = ["[bed]"]
    for index, (_path, delay_s) in enumerate(audios):
        delay_ms = max(0, int(round(delay_s * 1000)))
        lines.append(
            f"[{1 + index}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS,adelay={delay_ms}:all=1[a{index}]"
        )
        mix.append(f"[a{index}]")
    if len(mix) == 1:
        lines.append("[bed]anull[aout]")
    else:
        lines.append(
            f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[aout]"
        )
    current = "base"
    png_at = bed + 1
    for index, (_path, start_s, end_s, x, y) in enumerate(overlays):
        prepared = f"p{index}"
        lines.append(f"[{png_at + index}:v]format=rgba[{prepared}]")
        out = f"o{index}"
        enable = f"enable='between(t,{start_s:.3f},{end_s:.3f})'"
        lines.append(f"[{current}][{prepared}]overlay={x}:{y}:format=rgb:{enable}[{out}]")
        current = out
    lines.append(f"[{current}]format=yuv420p[vout]")
    return ";".join(lines)


def _shot_lines(
    source: str,
    index: int,
    geo: ShotGeometry,
    background: int | None,
    out: str,
) -> list[str]:
    end = geo.start_s + geo.duration_s
    head = f"[{source}]trim=start={geo.start_s:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
    if geo.mode == "crop":
        x_expr = _axis_expr(geo, axis="x")
        y_expr = _axis_expr(geo, axis="y")
        return [
            f"{head},crop={geo.crop_w}:{geo.crop_h}:x='{x_expr}':y='{y_expr}',"
            f"scale={geo.out_w}:{geo.out_h}:flags=bilinear,setsar=1,fps={_FPS},format=yuv420p[{out}]"
        ]
    foreground = (
        f"{head},scale={geo.out_w}:{geo.out_h}:force_original_aspect_ratio=decrease[f{index}]"
    )
    if geo.mode == "regenerate" and background is not None:
        plate = (
            f"[{background}:v]scale={geo.out_w}:{geo.out_h}:force_original_aspect_ratio=increase,"
            f"crop={geo.out_w}:{geo.out_h},setsar=1[b{index}]"
        )
    else:
        plate = (
            f"{head},split[a{index}][c{index}];"
            f"[a{index}]scale={geo.out_w}:{geo.out_h}:force_original_aspect_ratio=increase,"
            f"crop={geo.out_w}:{geo.out_h},hue=s=0,gblur=sigma=12,eq=brightness=-0.15[b{index}];"
            f"[c{index}]scale={geo.out_w}:{geo.out_h}:force_original_aspect_ratio=decrease[f{index}]"
        )
        # The split already consumed ``head``. Don't trim twice.
        return [
            plate,
            (
                f"[b{index}][f{index}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2,"
                f"fps={_FPS},setsar=1,format=yuv420p[{out}]"
            ),
        ]
    return [
        foreground,
        plate,
        (
            f"[b{index}][f{index}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2,"
            f"fps={_FPS},setsar=1,format=yuv420p[{out}]"
        ),
    ]


def _axis_expr(geo: ShotGeometry, *, axis: str) -> str:
    if axis == "x":
        start = geo.subject0.x
        end = geo.subject1.x
        size = geo.subject0.w
        crop = geo.crop_w
        limit = geo.src_w - geo.crop_w
    else:
        start = geo.subject0.y
        end = geo.subject1.y
        size = geo.subject0.h
        crop = geo.crop_h
        limit = geo.src_h - geo.crop_h
    span = max(geo.motion_s, 0.001)
    subject = f"({start:.3f}+({end - start:.3f})*min(t/{span:.6f},1))"
    center = f"({subject}+{size:.3f}/2-{crop}/2)"
    placed = f"max(0,min({limit},{center}))"
    placed = f"if(lt({subject},{placed}),{subject},{placed})"
    placed = f"if(gt({subject}+{size:.3f},{placed}+{crop}),{subject}+{size:.3f}-{crop},{placed})"
    placed = f"max(0,min({limit},{placed}))"
    return f"floor({placed})"
