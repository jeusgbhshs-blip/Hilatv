"""Which nodes a change set invalidates.

Narration or duration changes the spoken length, so that shot's video is
regenerated. A logo, price, or phone change only re-renders N14 and N15.
"""

from __future__ import annotations

from workers.nodes.n18_revision.schema import RevisionPlan
from workers.schemas.director import RevisionDirective
from workers.schemas.script import Script

_PICTURE = ("lighting", "visual")
_OVERLAY = ("logo", "price", "phone")


def plan_for(script: Script, directive: RevisionDirective) -> RevisionPlan:
    change = directive.change
    keep = set(directive.keep)
    known = [shot.shot_id for shot in script.shots]
    targets = [shot_id for shot_id in known if shot_id in set(directive.targets)]
    picture = any(key in change for key in _PICTURE) and "visual" not in keep
    spoken = "narration" in change and "narration" not in keep
    duration = "duration" in change and "duration" not in keep
    video = list(targets) if picture or spoken or duration else []
    nodes: list[str] = []
    if spoken or "voice" in change or duration:
        nodes.append("n06_voiceover")
    if picture:
        nodes.extend(["n08_keyframe", "n09_keyframe_qa", "n10_video", "n11_video_qa"])
    elif video:
        nodes.extend(["n10_video", "n11_video_qa"])
    if spoken or duration:
        nodes.append("n13_subtitle")
    if any(key in change for key in _OVERLAY):
        nodes.append("n14_packaging")
    nodes.append("n15_compose")
    reuse = [shot_id for shot_id in known if shot_id not in set(video)]
    return RevisionPlan(nodes=nodes, video_shots=video, reuse_shots=reuse, directive=directive)
