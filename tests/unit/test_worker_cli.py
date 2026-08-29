"""worker CLIのperiodic owner境界を検証する。"""

from __future__ import annotations

from kuma800.worker.cli import build_consumer_argv


def test_default_argv_disables_periodic_scheduling() -> None:
    """periodic_owner=Falseの既定では、periodic taskをenqueueしない。"""
    argv = build_consumer_argv([], periodic_owner=False)

    assert "-n" in argv
    assert "kuma800.worker.huey_app.huey" == argv[-1]


def test_periodic_owner_true_enables_periodic_scheduling() -> None:
    """lockを取得できた場合（periodic_owner=True）だけperiodic taskをenqueueする。"""
    argv = build_consumer_argv(["--periodic-owner"], periodic_owner=True)

    assert "-n" not in argv
    assert "--periodic-owner" not in argv


def test_requested_but_not_granted_ownership_still_disables_periodic() -> None:
    """`--periodic-owner`を指定してもlockを取れなければ、既定どおりnon-ownerになる。"""
    argv = build_consumer_argv(["--periodic-owner"], periodic_owner=False)

    assert "-n" in argv
    assert "--periodic-owner" not in argv


def test_explicit_no_periodic_flag_is_preserved() -> None:
    """operatorが明示した`-n`をperiodic owner既定と二重に足さない。"""
    argv = build_consumer_argv(["-n"], periodic_owner=False)

    assert argv.count("-n") == 1


def test_worker_type_and_count_defaults_are_untouched() -> None:
    """periodic owner判定は既存のthread/worker数既定へ影響しない。"""
    argv = build_consumer_argv([], periodic_owner=False)

    assert argv[:4] == ["-k", "thread", "-w", "2"]
