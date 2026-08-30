"""thread worker全枯渇を再現する専用consumer入口（Issue #8）。

`blocking_probe`はproductionのscraper registry（`worker.service._adapters`）
へは公開しない診断専用taskで、指定秒数の間そのworker threadを占有し続け
る。現在のHuey `-k thread`構成には、これを外側から強制終了する仕組みが
ないことを実証するために使う。`kuma800.worker.cli`（production入口）は
変更しない。
"""

from __future__ import annotations

import sys
import time

from huey.bin.huey_consumer import consumer_main  # type: ignore[import-untyped]

from kuma800.runtime import RuntimePaths
from kuma800.worker.huey_app import huey

_HUEY_IMPORT_PATH = "kuma800.worker.huey_app.huey"


@huey.task()  # type: ignore[untyped-decorator]
def blocking_probe(seconds: float, marker_name: str) -> None:
    """実行開始をmarker fileで知らせてから、指定秒数worker threadを占有する。"""
    RuntimePaths.resolve().data_dir.joinpath(marker_name).touch()
    time.sleep(seconds)


def main() -> None:
    """`enqueue <seconds> <marker_name>`でtaskを積むか、引数なしでconsumerを起動する。"""
    if len(sys.argv) > 1 and sys.argv[1] == "enqueue":
        blocking_probe(float(sys.argv[2]), sys.argv[3])
        return
    sys.argv = [sys.argv[0], "-w", "2", "-k", "thread", "-n", _HUEY_IMPORT_PATH]
    consumer_main()


if __name__ == "__main__":
    main()
