"""Build the N15 filter_complex from a timeline. Hard cuts are concat, not xfade."""

from __future__ import annotations

from workers.nodes.n15_compose.schema import OverlayItem, Timeline

_DISSOLVE = {"dissolve", "xfade", "fade", "crossfade"}


def filter_complex(timeline: Timeline, variant: str) -> str:
    overlays = _overlays_for(timeline, variant)
    audios = [] if variant == "novo" else list(timeline.audio)
    use_audio = variant != "novo"
    lines: list[str] = []
    labels: list[str] = []
    lut = _quote(timeline.lut_path)
    for index, clip in enumerate(timeline.clips):
        label = f"v{index}"
        lines.append(
            f"[{index}:v]scale={timeline.width}:{timeline.height}:force_original_aspect_ratio=decrease,"
            f"pad={timeline.width}:{timeline.height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={timeline.fps},setsar=1,format=rgb24,"
            f"lut3d=file='{lut}',"
            f"colorchannelmixer=rr={clip.grade_rr:.4f}:gg={clip.grade_gg:.4f}:bb={clip.grade_bb:.4f},"
            f"eq=brightness=0.02:saturation=1.05,format=yuv420p[{label}]"
        )
        labels.append(label)
    joined, current = _join(labels, timeline)
    if joined:
        lines.append(joined)
    n_video = len(timeline.clips)
    n_audio = len(audios)
    if use_audio:
        bed = n_video + n_audio
        lines.append(
            f"[{bed}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"atrim=0:{timeline.duration_s:.3f},asetpts=PTS-STARTPTS[bed]"
        )
        mix_inputs = ["[bed]"]
        for index, audio in enumerate(audios):
            src = n_video + index
            delay = max(0, int(round(audio.start_s * 1000)))
            lines.append(
                f"[{src}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                f"atrim=0:{audio.duration_s:.3f},asetpts=PTS-STARTPTS,"
                f"adelay={delay}:all=1[a{index}]"
            )
            mix_inputs.append(f"[a{index}]")
        if len(mix_inputs) == 1:
            lines.append("[bed]anull[aout]")
        else:
            lines.append(
                f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:"
                f"duration=first:dropout_transition=0:normalize=0[aout]"
            )
    if not overlays:
        lines.append(f"[{current}]format=yuv420p[vout]")
        return ";".join(lines)
    ov_base = n_video + n_audio + (1 if use_audio else 0)
    for index, overlay in enumerate(overlays):
        src = ov_base + index
        prepared = f"p{index}"
        lines.append(_prepare(src, overlay, prepared))
        out = f"o{index}"
        x, y = _position(overlay)
        enable = f"enable='between(t,{overlay.start_s:.3f},{overlay.end_s:.3f})'"
        lines.append(f"[{current}][{prepared}]overlay={x}:{y}:format=rgb:{enable}[{out}]")
        current = out
    lines.append(f"[{current}]format=yuv420p[vout]")
    return ";".join(lines)


def command(timeline: Timeline, dest: str, variant: str) -> list[str]:
    overlays = _overlays_for(timeline, variant)
    audios = [] if variant == "novo" else list(timeline.audio)
    use_audio = variant != "novo"
    args = ["ffmpeg", "-y", "-loglevel", "error", "-threads", "1"]
    for clip in timeline.clips:
        args += ["-i", clip.path]
    for audio in audios:
        args += ["-i", audio.path]
    if use_audio:
        args += [
            "-f",
            "lavfi",
            "-t",
            f"{timeline.duration_s:.3f}",
            "-i",
            "anullsrc=r=48000:cl=stereo",
        ]
    for overlay in overlays:
        args += [
            "-loop",
            "1",
            "-framerate",
            str(timeline.fps),
            "-t",
            f"{timeline.duration_s:.3f}",
            "-i",
            overlay.path,
        ]
    args += [
        "-filter_complex",
        filter_complex(timeline, variant),
        "-map",
        "[vout]",
    ]
    if use_audio:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
    else:
        args += ["-an"]
    args += [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-x264-params",
        "threads=1:sliced-threads=0:bframes=0",
        "-r",
        str(timeline.fps),
        "-t",
        f"{timeline.duration_s:.3f}",
        "-fflags",
        "+bitexact",
        "-flags",
        "+bitexact",
        "-map_metadata",
        "-1",
        dest,
    ]
    return args


def _overlays_for(timeline: Timeline, variant: str) -> list[OverlayItem]:
    if variant == "nosub":
        return [item for item in timeline.overlays if item.kind != "subtitle"]
    return list(timeline.overlays)


def _join(labels: list[str], timeline: Timeline) -> tuple[str, str]:
    if len(labels) == 1:
        return "", labels[0]
    dissolves = [
        index
        for index, clip in enumerate(timeline.clips[:-1])
        if clip.transition_out.lower() in _DISSOLVE
    ]
    if not dissolves:
        inside = "".join(f"[{label}]" for label in labels)
        return f"{inside}concat=n={len(labels)}:v=1:a=0[vcat]", "vcat"
    current = labels[0]
    elapsed = timeline.clips[0].duration_s
    parts: list[str] = []
    for index in range(1, len(labels)):
        out = f"j{index}"
        previous = timeline.clips[index - 1]
        if previous.transition_out.lower() in _DISSOLVE:
            overlap = min(0.3, previous.duration_s / 2, timeline.clips[index].duration_s / 2)
            offset = max(0.0, elapsed - overlap)
            parts.append(
                f"[{current}][{labels[index]}]xfade=transition=fade:"
                f"duration={overlap:.3f}:offset={offset:.3f}[{out}]"
            )
            elapsed = elapsed + timeline.clips[index].duration_s - overlap
        else:
            parts.append(f"[{current}][{labels[index]}]concat=n=2:v=1:a=0[{out}]")
            elapsed += timeline.clips[index].duration_s
        current = out
    return ";".join(parts), current


def _prepare(src: int, overlay: OverlayItem, label: str) -> str:
    if overlay.animate == "fade":
        return f"[{src}:v]format=rgba,fade=t=in:st=0:d=0.4:alpha=1[{label}]"
    if overlay.animate == "scale":
        return (
            f"[{src}:v]format=rgba,scale=w='iw*(0.72+0.28*min(t/0.5\\,1))':"
            f"h='ih*(0.72+0.28*min(t/0.5\\,1))':eval=frame[{label}]"
        )
    return f"[{src}:v]format=rgba[{label}]"


def _position(overlay: OverlayItem) -> tuple[str, str]:
    if overlay.anchor == "center":
        x = "(W-w)/2"
        if overlay.animate == "rise":
            y = f"'(H*{overlay.y_ratio:.4f}-h/2)+(1-min(t/0.5\\,1))*48'"
        else:
            y = f"(H*{overlay.y_ratio:.4f}-h/2)"
        return x, y
    return str(overlay.x), str(overlay.y)


def _quote(path: str) -> str:
    return path.replace("'", r"'\''")
