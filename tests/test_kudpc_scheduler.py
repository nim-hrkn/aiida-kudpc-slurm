# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Hiori Kino
"""KudpcSlurmScheduler の header: 禁止の旗を落とし、--rsc を 1 行だけ足す。"""
import math

import pytest

pytest.importorskip("aiida", reason="aiida-core が無い環境では scheduler を組み立てられない")

from aiida.common.extendeddicts import AttributeDict  # noqa: E402
from aiida.schedulers.datastructures import JobTemplate  # noqa: E402
from aiida.schedulers.plugins.slurm import SlurmScheduler  # noqa: E402

from aiida_kudpc_slurm.slurm import (  # noqa: E402
    DEFAULT_MEMORY_MB_PER_CORE, FORBIDDEN_OPTIONS, KudpcSlurmScheduler, _option_name, rsc_spec,
)

#: 実機（laurel、gr10653b、sbatch --test-only、2026-08-25）で通ることを確かめた旗。
#: この plugin が出す header の旗は、すべてここに入っていなければならない。
#: **増えたら**、その旗が KUDPC で禁止でないことを実機で確かめてから足す。表だけ合わせない。
VERIFIED_ALLOWED = {"no-requeue", "job-name", "output", "error", "partition", "time", "account", "nice", "rsc"}


def template(machines=1, procs=1, cores=None, memory_kb=None, custom=None, **extra):
    tmpl = JobTemplate()
    tmpl.job_resource = SlurmScheduler.create_job_resource(
        num_machines=machines, num_mpiprocs_per_machine=procs,
        **({"num_cores_per_mpiproc": cores} if cores else {}))
    tmpl.job_name = "aiida-1"
    tmpl.sched_output_path = "_scheduler-stdout.txt"
    tmpl.sched_error_path = "_scheduler-stderr.txt"
    tmpl.queue_name = extra.get("queue_name", "gr10653b")
    tmpl.max_wallclock_seconds = extra.get("wallclock", 3600)
    tmpl.import_sys_environment = extra.get("import_sys_environment", True)
    if memory_kb:
        tmpl.max_memory_kb = memory_kb
    if custom:
        tmpl.custom_scheduler_commands = custom
    if "account" in extra:
        tmpl.account = extra["account"]
    return tmpl


def flags(header):
    return [f for f in (_option_name(line) for line in header.splitlines()) if f]


def parent_header(tmpl):
    return SlurmScheduler()._get_submit_script_header(tmpl)


def kudpc_header(tmpl):
    return KudpcSlurmScheduler()._get_submit_script_header(tmpl)


# ---------------------------------------------------------------- 引き算に意味があるか

def test_the_parent_really_writes_them():
    """core.slurm が禁止の旗を実際に書くこと（書かないなら、この plugin は要らない）。"""
    written = set(flags(parent_header(template(machines=1, procs=4, cores=2, memory_kb=4 * 1024 * 1024))))
    assert {"nodes", "ntasks-per-node"} <= written
    assert written & set(FORBIDDEN_OPTIONS) >= {"nodes", "ntasks-per-node", "cpus-per-task", "mem", "get-user-env"}


def test_forbidden_flags_are_dropped_and_one_rsc_is_added():
    header = kudpc_header(template(machines=1, procs=4, cores=2, memory_kb=4 * 1024 * 1024))
    written = flags(header)
    assert not set(written) & set(FORBIDDEN_OPTIONS)
    assert written.count("rsc") == 1
    assert "#SBATCH --rsc p=4:t=2:c=2:m=1024M" in header


def test_every_flag_the_header_writes_was_checked_on_the_real_machine():
    """出す旗が、実機で確かめた集合に収まっていること（aiida-core を上げたときの見張り）。"""
    for tmpl in (template(), template(procs=8), template(cores=8, account="gr10653", wallclock=86400),
                 template(import_sys_environment=False)):
        unknown = set(flags(kudpc_header(tmpl))) - VERIFIED_ALLOWED
        assert not unknown, f"実機で確かめていない旗: {sorted(unknown)}"


def test_parent_non_resource_lines_survive():
    header = kudpc_header(template(queue_name="gr10653b", wallclock=5400))
    assert "#SBATCH --partition=gr10653b" in header and "#SBATCH --time=01:30:00" in header
    assert "#SBATCH --job-name=" in header and "#SBATCH --no-requeue" in header


# ---------------------------------------------------------------- --rsc の中身

def test_rsc_spec_defaults():
    assert rsc_spec(1) == f"p=1:t=1:c=1:m={DEFAULT_MEMORY_MB_PER_CORE}M"
    assert rsc_spec(4, 8) == f"p=4:t=8:c=8:m={DEFAULT_MEMORY_MB_PER_CORE * 8}M"
    assert rsc_spec(1, 8, memory_kb_per_process=32768 * 1024) == "p=1:t=8:c=8:m=32768M"
    assert rsc_spec(0, 0) == f"p=1:t=1:c=1:m={DEFAULT_MEMORY_MB_PER_CORE}M"


@pytest.mark.parametrize("cores", [1, 2, 8, 16, 56, 112])
def test_the_default_memory_does_not_inflate_the_core_count(cores):
    """既定の m で max(c, ceil(m / 4571M)) が c を超えないこと（超えると 8 コアのつもりが 9 コアになる）。"""
    m = int(rsc_spec(1, cores).split("m=")[1].rstrip("M"))
    assert max(cores, math.ceil(m / DEFAULT_MEMORY_MB_PER_CORE)) == cores


def test_max_memory_is_per_node_in_aiida_and_per_process_in_kudpc():
    header = kudpc_header(template(machines=2, procs=4, memory_kb=16 * 1024 * 1024))
    assert "--rsc p=8:t=1:c=1:m=2048M" in header


def test_user_rsc_is_respected():
    header = kudpc_header(template(custom="#SBATCH --rsc g=1"))
    assert flags(header).count("rsc") == 1 and "#SBATCH --rsc g=1" in header


def test_memory_per_core_can_be_changed_in_a_subclass():
    class Camphor(KudpcSlurmScheduler):
        memory_mb_per_core = 1071
    assert "m=2142M" in Camphor()._get_submit_script_header(template(cores=2))


# ---------------------------------------------------------------- entry points

def test_entry_points():
    from importlib.metadata import entry_points
    found = [(ep.name, ep.value) for ep in entry_points(group="aiida.schedulers")]
    names = dict(found)
    if "kudpc_slurm.slurm" not in names:
        pytest.skip("pip install していない木では entry point を確かめられない（`pip install -e .` してから走らせる）")
    target = "aiida_kudpc_slurm.slurm:KudpcSlurmScheduler"
    legacy = [value for name, value in found if name == "kudpc.slurm"]
    assert legacy == [target], (f"kudpc.slurm が {len(legacy)} 個ある: {legacy}。"
                                "旧パッケージ aiida-kudpc が入っている。`pip uninstall aiida-kudpc` すること")
    assert names["kudpc_slurm.slurm"] == target
    from aiida.plugins import SchedulerFactory
    assert SchedulerFactory("kudpc_slurm.slurm") is KudpcSlurmScheduler
