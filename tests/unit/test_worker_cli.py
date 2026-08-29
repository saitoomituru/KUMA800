"""worker CLIのperiodic owner境界を検証する。"""

from __future__ import annotations

from kuma800.worker.cli import build_consumer_argv


def test_default_argv_disables_periodic_scheduling() -> None:
    """`--periodic-owner`を指定しない既定では、periodic taskをenqueueしない。"""
    argv = build_consumer_argv([])

    assert "-n" in argv
    assert "kuma800.worker.huey_app.huey" == argv[-1]


def test_periodic_owner_flag_enables_periodic_scheduling() -> None:
    """`--periodic-owner`を指定した場合だけperiodic taskをenqueueする。"""
    argv = build_consumer_argv(["--periodic-owner"])

    assert "-n" not in argv
    assert "--periodic-owner" not in argv


def test_explicit_no_periodic_flag_is_preserved() -> None:
    """operatorが明示した`-n`をperiodic owner既定と二重に足さない。"""
    argv = build_consumer_argv(["-n"])

    assert argv.count("-n") == 1


def test_worker_type_and_count_defaults_are_untouched() -> None:
    """periodic owner判定は既存のthread/worker数既定へ影響しない。"""
    argv = build_consumer_argv([])

    assert argv[:4] == ["-k", "thread", "-w", "2"]
