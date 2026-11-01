"""Cut detection retains low-contrast joins beside a brighter ending card."""

from workers.nodes.n12_music.picture import _cut_times, _steps


def test_bright_outro_does_not_hide_eight_low_contrast_joins() -> None:
    steps = [0.2] * 360
    for frame in range(30, 270, 30):
        steps[frame - 1] = 10.4
    steps[299] = 34.1
    assert _cut_times(steps, 30) == [float(second) for second in range(1, 9)] + [10.0]


def test_small_overlay_pops_are_not_cuts_in_high_contrast_footage() -> None:
    steps = [0.2] * 240
    steps[29], steps[89], steps[149] = 100, 110, 105
    steps[59], steps[119] = 10, 12
    assert _cut_times(steps, 30) == [1, 3, 5]


def test_camera_noise_does_not_invent_cuts() -> None:
    assert _cut_times([2, 2.5, 1.5, 3] * 60, 30) == []


def test_continuous_motion_and_single_scene_change_have_separate_clocks() -> None:
    steps = [9, 10, 11, 10] * 60
    assert _cut_times(steps, 30) == []
    steps[119] = 80
    assert _cut_times(steps, 30) == [4]


def test_local_subtitle_pop_does_not_become_a_scene_change() -> None:
    blank = bytes([40] * (96 * 54 * 3))
    overlay = bytearray(blank)
    # A full-width, high-contrast subtitle panel covers the bottom third.
    overlay[96 * 36 * 3 :] = bytes([250] * (96 * 18 * 3))
    frames = [blank, bytes(overlay), blank]
    assert _cut_times(_steps(frames), 30) == []


def test_single_decoded_frame_change_remains_detectable() -> None:
    left = bytes([40] * (96 * 54 * 3))
    right = bytes([70] * (96 * 54 * 3))
    assert _cut_times(_steps([left, left, right, right]), 30) == [2 / 30]
