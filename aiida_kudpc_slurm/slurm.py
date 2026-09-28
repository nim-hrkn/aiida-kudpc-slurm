# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Hiori Kino
"""京都大学 学術情報メディアセンター（ACCMS / KUDPC）の SLURM（aiida-kudpc-slurm v1.2.0）。

**なぜ ``core.slurm`` が使えないか。**

KUDPC（camphor / laurel / cinnamon）の ``sbatch`` は資源の要求を
``--rsc p=P:t=T:c=C:m=M`` 1 本に一本化しており、素の SLURM の資源指定を
**受け付けずに落ちる**。2026-08-25 に laurel（``gr10653b``）で実測した。

    $ sbatch <aiida-core 2.9.0 の core.slurm が書く形>
    sbatch: error: forbidden option, nodes
    sbatch: error: forbidden option, ntasks-per-node
    sbatch: fatal: forbidden options are given.

``--nodes`` と ``--ntasks-per-node`` は
``SlurmScheduler._get_submit_script_header`` が**必ず**書く。したがって
``core.slurm`` のままでは **job が 1 本も入らない**。
``custom_scheduler_commands`` で ``--rsc`` を足しても、禁止の 2 行は消せない
ので同じく落ちる（実際に投げて確かめた）。

たちが悪いのは、**``verdi computer test`` は 6/6 通る**ことである
（ssh も squeue も生きているので）。「設定は全部通ったのに job だけ落ちる」
という、原因から 2 段離れた症状になる。

**禁止の一覧は公式マニュアルにある**（「ジョブ実行のヒント → ジョブ投入時に
使用できないオプション」）。:data:`FORBIDDEN_OPTIONS` はその表を写したもので
ある。**実測で見つけた 5 つだけを消す作りにしない。** 表には
``--qos`` や ``--get-user-env`` のように aiida-core が条件次第で書くものが
含まれており、実測だけでは取りこぼす。

    実測（sbatch --test-only、2026-08-25、laurel）:
        撥ねられた : nodes / ntasks / ntasks-per-node / cpus-per-task / mem
        通った     : no-requeue / job-name / output / error / partition / time
                     account / nice / rsc / get-user-env(!)

``--get-user-env`` は **``--test-only`` では通ったが、マニュアルは
「使用できない」と書いている。** どちらに従うかは迷わない —— **マニュアルに
従って落とす。** 落として困らないことも分かっている。KUDPC は
「ジョブ投入時に設定されている環境変数は、ジョブ実行時に継承されます」と
明記しており、``--get-user-env`` が無くても環境は渡る。

**``m`` とコア数の関係（マニュアル「計算資源の割り当て」）**

システム B は **1 コアあたり 4571 M** でメモリを紐付けて管理している。

    確保されるコア数 = max( c , ceil(m ÷ 4571M) )

``m`` を書かなければ **4571M × c** が自動で入る。したがって

    --rsc p=1:t=1:c=1          → 1 コア / 4571M      （素直）
    --rsc p=1:t=1:c=1:m=8G     → **2 コア**          （m が c を上回る）
    --rsc p=1:t=8:c=8:m=32768M → 8 コア（32768÷4571 = 7.2 → 8）

**メモリを多く書くとコア数が勝手に増える。**

**``m`` は必ず書く（v1.1.0）。** 省略しても KUDPC が ``4571M × c`` を黙って
入れるので動きはするが、**投入スクリプトを読んでも要求量が分からない**。
この class の既定値は KUDPC が入れるのと同じ ``4571M × c`` なので、
**書くこと自体では確保されるコア数もメモリ量も変わらない**。暗黙を明示に
変えるだけである。

``t`` は ``c`` または ``c × 2``（ハイパースレッディング）のどちらかにする、
というのがマニュアルの指示である。この class は ``t = c`` を既定にする。

**設計。** 親（``SlurmScheduler``）が書いた header から禁止行だけを取り除き、
``--rsc`` を 1 行足す。親の実装を丸ごと書き直さないのは、aiida-core の更新
（メールの旗、``--qos`` の扱いなど）に自動で追随するため。

**その代わり、aiida-core が新しい資源の旗を足したときに気づけない。** だから
``tests/test_kudpc_scheduler.py`` が「親が書く旗の集合」を固定している（``VERIFIED_ALLOWED``）。
aiida-core を上げて集合が変われば試験が落ちる。**落ちたら、その旗が KUDPC で
禁止かどうかを実機で確かめてから固定し直すこと。**
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from aiida.schedulers.plugins.slurm import SlurmScheduler

__all__ = ["KudpcSlurmScheduler", "FORBIDDEN_OPTIONS", "rsc_spec"]

#: KUDPC で ``sbatch`` / ``#SBATCH`` に書けないオプション。
#:
#: **出典は公式マニュアル**「プログラムの実行 → ジョブ実行のヒント →
#: ジョブ投入時に使用できないオプション」の表（2026-08-25 時点）。
#: 短い形（``-N`` など）も表に併記されているものを入れてある。
#:
#: **実測で見つけたものだけにしない。** 撥ねられるのを 1 つ見つけるたびに
#: 足していく作りだと、``--qos`` のように「条件が揃ったときだけ aiida-core が
#: 書く」旗を取りこぼす。そのときの症状は「ある日とつぜん全部の job が
#: 入らなくなる」である。
FORBIDDEN_OPTIONS = (
    "batch",
    "clusters", "M",
    "constraint", "C",
    "contiguous",
    "core-spec", "S",
    "cores-per-socket",
    "cpus-per-gpu",
    "cpus-per-task", "c",
    "distribution", "m",
    "exclude", "x",
    "exclusive",
    "get-user-env",
    "gid",
    "gpu-bind",
    "gpus", "G",
    "gpus-per-node",
    "gpus-per-socket",
    "gres",
    "gres-flags",
    "mem",
    "mem-bind",
    "mem-per-cpu",
    "mem-per-gpu",
    "mincpus",
    "nodefile", "F",
    "nodelist", "w",
    "nodes", "N",
    "ntasks", "n",
    "ntasks-per-core",
    "ntasks-per-gpu",
    "ntasks-per-node",
    "ntasks-per-socket",
    "overcommit", "O",
    "oversubscribe", "s",
    "priority",
    "qos", "q",
    "reboot",
    "sockets-per-node",
    "spread-job",
    "switches",
    "thread-spec",
    "threads-per-core",
    "uid",
    "use-min-nodes",
)

_SBATCH_LINE = re.compile(r"^\s*#SBATCH\s+(?P<flag>--[A-Za-z0-9-]+|-[A-Za-z])")


def _option_name(line: str) -> Optional[str]:
    """``#SBATCH --ntasks-per-node=1`` → ``"ntasks-per-node"``。旗でなければ ``None``。"""
    match = _SBATCH_LINE.match(line)
    if not match:
        return None
    return match.group("flag").lstrip("-")


#: システム B（laurel）の 1 コアあたりメモリ量（MB）。マニュアル
#: 「計算資源の割り当て」の初期値。``m`` を省いたとき KUDPC が入れるのが
#: **この値 × c** である。
#:
#: 他システムは違う（システム A = 1071M、システム C = 18392M、
#: システム G = 8000M、クラウド = 14222M）。**camphor / cinnamon で使うなら
#: ここを変えるか、``max_memory_kb`` を明示すること。**
DEFAULT_MEMORY_MB_PER_CORE = 4571


def rsc_spec(
    num_processes: int,
    num_cores_per_process: int = 1,
    num_threads_per_process: Optional[int] = None,
    memory_kb_per_process: Optional[int] = None,
    memory_mb_per_core: int = DEFAULT_MEMORY_MB_PER_CORE,
) -> str:
    """``p=P:t=T:c=C:m=M`` を組み立てる。**書式を書くのはここ 1 か所。**

    ``t``（プロセスあたりのスレッド数）の既定は ``c`` に合わせる。KUDPC の
    公式例（``--rsc p=4:t=8:c=8:m=8G``）がその形であり、``t > c`` にすると
    コアより多いスレッドを立てることになるため。

    **``m`` は必ず書く**（v1.1.0）。省いても KUDPC が
    ``1 コアあたりの初期値 × c`` を黙って入れるので動きはするが、
    **投入スクリプトを読んでも要求量が分からない**。暗黙の既定を明示に
    変えるだけで、確保されるコア数もメモリ量も変わらない。

        m を省いたとき KUDPC が入れる値  = 4571M × c   （システム B）
        この関数が書く値（既定）         = 4571M × c   ← 同じ

    ``memory_kb_per_process`` を渡せばその値になる。**ただし ``m`` を増やすと
    コア数も増える**（``max(c, ceil(m ÷ 4571M))``）ので、``c`` より多くの
    コアを呼び込まない範囲に収めること。
    """
    procs = max(1, int(num_processes))
    cores = max(1, int(num_cores_per_process))
    threads = cores if num_threads_per_process is None else max(1, int(num_threads_per_process))
    if memory_kb_per_process:
        megabytes = max(1, int(memory_kb_per_process) // 1024)
    else:
        megabytes = max(1, int(memory_mb_per_core) * cores)
    return f"p={procs}:t={threads}:c={cores}:m={megabytes}M"


class KudpcSlurmScheduler(SlurmScheduler):
    """KUDPC 向けの SLURM。資源の要求を ``--rsc`` 1 本に置き換える。

    entry point は ``kudpc_slurm.slurm``（v1.2.0 から。旧名 ``kudpc.slurm`` も同じ class を指す）。

        verdi computer setup --scheduler kudpc_slurm.slurm ...

    ``JobResource`` は親と同じ（``num_machines`` / ``num_mpiprocs_per_machine``
    / ``num_cores_per_mpiproc``）。対応は

        p = num_machines × num_mpiprocs_per_machine   （プロセスの総数）
        c = num_cores_per_mpiproc                     （既定 1）
        t = c
        m = max_memory_kb ÷ p                         （無ければ 4571M × c）

    **``max_memory_kb`` は AiiDA ではノードあたり、KUDPC の ``m`` はプロセス
    あたり**である。``p`` で割って合わせる。``p=1`` なら同じ値になる。

    **``m`` は必ず書く（v1.1.0）。** 書かないと KUDPC が
    ``1 コアあたりの初期値 × c`` を黙って入れる。動きはするが、投入
    スクリプトを読んでも要求量が分からない。既定値は KUDPC が入れるのと
    同じ値なので、**確保されるコア数もメモリ量も変わらない**。

    ``max_memory_kb`` を指定するときは、``max(c, ceil(m ÷ 4571M))`` が ``c``
    を超えない範囲に収めること。超えるとコア数が勝手に増える。

    ``custom_scheduler_commands`` に自分で ``--rsc`` を書いた場合は、**こちらは
    足さない**。明示した要求を黙って二重にしない。

    **``--rsc g=GPU``（GPU 版の書式）はまだ扱っていない。** 使うときは
    ``custom_scheduler_commands`` に直接書けば、この class はそれを尊重する。
    """

    _logger = SlurmScheduler._logger.getChild("kudpc")

    #: ``m`` を省いたときに使う「1 コアあたりメモリ量（MB）」。
    #: 既定はシステム B（laurel）の 4571M。**camphor（A）や cinnamon（C）で
    #: 使うなら、この属性を差し替えた subclass を作るか
    #: ``max_memory_kb`` を明示すること。**
    memory_mb_per_core = DEFAULT_MEMORY_MB_PER_CORE

    def _get_submit_script_header(self, job_tmpl) -> str:
        header = super()._get_submit_script_header(job_tmpl)

        kept: List[str] = []
        dropped: List[str] = []
        for line in header.splitlines():
            if _option_name(line) in FORBIDDEN_OPTIONS:
                dropped.append(line.strip())
            else:
                kept.append(line)

        if dropped:
            self.logger.debug(
                "KUDPC: 禁止されている旗を落として --rsc に置き換えた: %s", "; ".join(dropped)
            )

        if not any("--rsc" in line for line in kept):
            kept.append(f"#SBATCH --rsc {self._rsc_for(job_tmpl)}")

        return "\n".join(kept)

    # ------------------------------------------------------------------
    def _rsc_for(self, job_tmpl) -> str:
        resource: Any = getattr(job_tmpl, "job_resource", None)
        if resource is None:
            raise ValueError("job resources (num_machines) が必要です（kudpc.slurm）")

        machines = int(getattr(resource, "num_machines", 1) or 1)
        procs_per_machine = int(getattr(resource, "num_mpiprocs_per_machine", 1) or 1)
        procs = max(1, machines * procs_per_machine)
        cores = int(getattr(resource, "num_cores_per_mpiproc", 0) or 0) or 1

        memory_kb = getattr(job_tmpl, "max_memory_kb", None)
        per_process_kb = None
        if memory_kb:
            per_process_kb = int(memory_kb) // procs

        return rsc_spec(
            procs,
            cores,
            memory_kb_per_process=per_process_kb,
            memory_mb_per_core=self.memory_mb_per_core,
        )
