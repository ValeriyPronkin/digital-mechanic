"""make video: ускоряется только ожидание ответа модели, куски записи — по порядку, без вырезания."""

from __future__ import annotations

import itertools

import pytest

pytest.importorskip("playwright")
from video import LIMIT_S, SPEED_MAX, SPEED_MIN, plan, remap


def test_only_waits_are_sped_up_and_nothing_is_cut() -> None:
    speed, pieces = plan(100.0, [(10.0, 30.0), (50.0, 60.0)])
    assert speed == SPEED_MIN
    assert pieces == [(0.0, 10.0, 1.0), (10.0, 30.0, SPEED_MIN), (30.0, 50.0, 1.0), (50.0, 60.0, SPEED_MIN),
                      (60.0, 100.0, 1.0)]  # fmt: skip
    assert pieces[0][0] == 0.0 and pieces[-1][1] == 100.0  # вся запись, без дыр
    assert all(a == b for (_, a, _), (b, _, _) in itertools.pairwise(pieces))


def test_speed_grows_to_fit_limit_but_not_past_max() -> None:
    speed, _ = plan(162.0 + 120.0, [(0.0, 120.0)])  # 162 с без ожидания + 120 с ожидания
    assert SPEED_MIN < speed <= SPEED_MAX and 162 + 120 / speed <= LIMIT_S + 0.5
    speed, _ = plan(400.0, [(0.0, 100.0)])  # не влезает и на ×8 — ×8, длину честно покажет отчёт
    assert speed == SPEED_MAX


def test_timecodes_follow_the_sped_up_video() -> None:
    _, pieces = plan(100.0, [(10.0, 30.0)])
    assert remap(5.0, pieces) == 5.0
    assert remap(30.0, pieces) == pytest.approx(10.0 + 20.0 / SPEED_MIN)
    assert remap(40.0, pieces) == pytest.approx(10.0 + 20.0 / SPEED_MIN + 10.0)


def test_video_starts_when_fleet_is_on_screen() -> None:
    """Загрузка страницы до парка (пустой кадр) в видео не входит; внутри — без вырезов."""
    _, pieces = plan(100.0, [(30.0, 40.0)], start=12.0)
    assert pieces[0][0] == 12.0 and pieces[-1][1] == 100.0
    assert remap(12.0, pieces) == 0.0


def test_caption_hides_stress_marks() -> None:
    """Ударения SpeechKit («строк+ах») — только для синтеза; в подписи их нет."""
    from video import NARRATION, caption

    assert caption("в двух строк+ах") == "в двух строках"
    assert all("+" not in caption(t) for t in NARRATION.values())
    assert "строк+ах" in NARRATION["drive"]
