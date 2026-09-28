# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Hiori Kino
"""aiida-kudpc-slurm: 京都大学 学術情報メディアセンター（ACCMS）の計算機を
AiiDA から使うための scheduler plugin（v1.2.0）。

対象は KUDPC のスーパーコンピュータ（camphor / laurel / cinnamon）。
提供するのは scheduler ただ 1 つである。

    entry point : kudpc_slurm.slurm   （旧名 kudpc.slurm も同じ class を指す）
    実体        : aiida_kudpc_slurm.slurm.KudpcSlurmScheduler

**ここでは重い import をしない。** ``aiida`` を読むのは ``slurm`` module に
入ったときだけにする（entry point 経由でしか使われないので、それで足りる）。
"""

from __future__ import annotations

__version__ = "1.2.0"

__all__ = ["KudpcSlurmScheduler", "__version__"]


def __getattr__(name):  # pragma: no cover - 遅延 import の受け口
    if name == "KudpcSlurmScheduler":
        from .slurm import KudpcSlurmScheduler as _cls

        return _cls
    raise AttributeError(name)
