# aiida-kudpc-slurm

**Unofficial** AiiDA scheduler plugin for the Kyoto University ACCMS supercomputers
(KUDPC: camphor / laurel / cinnamon). Not provided or supported by ACCMS.

KUDPC's `sbatch` accepts resources only as `--rsc p=P:t=T:c=C:m=M` and rejects the standard Slurm
resource options that aiida-core's `core.slurm` always writes (`--nodes`, `--ntasks-per-node`, ...):
`sbatch: fatal: forbidden options are given`. `verdi computer test` still passes, so the failure only
shows up when a CalcJob is submitted. This plugin subclasses `core.slurm`, drops every option listed as
forbidden in the KUDPC manual and adds one `--rsc` line built from the AiiDA job resources.

| AiiDA | `--rsc` |
|---|---|
| `num_machines × num_mpiprocs_per_machine` | `p` |
| `num_cores_per_mpiproc` (default 1) | `c`, and `t = c` |
| `max_memory_kb ÷ p` | `m` (default 4571 MB × `c`, the system B default) |

```bash
pip install git+https://github.com/nim-hrkn/aiida-kudpc-slurm.git   # on the host that runs the AiiDA daemon
verdi computer setup --label laurel-async --hostname laurel --transport core.ssh_async \
    --scheduler kudpc_slurm.slurm --work-dir /home/<x>/<user>/aiida_work/ \
    --mpirun-command "srun -n {tot_num_mpiprocs}" --mpiprocs-per-machine 1
```

Entry point `kudpc_slurm.slurm`; the former name `kudpc.slurm` points to the same class. Tested with
aiida-core 2.9. License: Apache-2.0. The detailed notes below are in Japanese.

## 日本語

### aiida-kudpc-slurm v1.2.0

京都大学 学術情報メディアセンター（ACCMS）のスーパーコンピュータ
**camphor / laurel / cinnamon**（KUDPC）を AiiDA から使うための plugin。

提供するのは **scheduler 1 つだけ**である。

```
entry point : kudpc_slurm.slurm   （旧名 kudpc.slurm も同じ class を指す）
実体        : aiida_kudpc_slurm.slurm.KudpcSlurmScheduler
```

デーモンが動く側（手元の PC / WSL）にだけ入れる。**計算ノードには要らない。**

---

### なぜ要るのか —— `core.slurm` では job が 1 本も入らない

KUDPC の `sbatch` は資源の要求を `--rsc p=P:t=T:c=C:m=M` 1 本に一本化して
おり、素の SLURM の資源指定を**受け付けずに落ちる**。

```
$ sbatch <aiida-core 2.9.0 の core.slurm が書く形>
sbatch: error: forbidden option, nodes
sbatch: error: forbidden option, ntasks-per-node
sbatch: fatal: forbidden options are given.
```

`--nodes` と `--ntasks-per-node` は `SlurmScheduler._get_submit_script_header`
が**必ず**書く。`custom_scheduler_commands` で `--rsc` を足しても、禁止の
2 行は消せないので同じく落ちる（実際に投げて確かめた）。

**たちが悪いのは症状の出方である。**

```
verdi computer test laurel-async   →  Success: all 6 tests succeeded
（CalcJob を投入）                  →  submit で excepted
```

ssh も squeue も生きているので、**設定の側は全部「通った」と言う。**
原因（scheduler が書く 2 行）から症状（CalcJob の例外）まで 2 段離れている。

---

### 使い方

```bash
pip install git+https://github.com/nim-hrkn/aiida-kudpc-slurm.git   # デーモンが動く環境に

verdi computer setup \
  --non-interactive \
  --label laurel-async \
  --hostname laurel \
  --transport core.ssh_async \
  --scheduler kudpc_slurm.slurm \
  --work-dir /home/<x>/<user>/aiida_work/ \
  --mpirun-command "srun -n {tot_num_mpiprocs}" \
  --mpiprocs-per-machine 1 \
  --append-text ""
```

`--mpiprocs-per-machine` は **1 にする**。`--rsc` の `p` は
`num_machines × num_mpiprocs_per_machine` から作るので、ここを 64 などに
すると `p=64` の要求になりうる。

### 資源の対応

AiiDA の `JobResource` は親（`core.slurm`）と同じものを使う。

| AiiDA | `--rsc` |
|---|---|
| `num_machines × num_mpiprocs_per_machine` | `p`（プロセスの総数） |
| `num_cores_per_mpiproc` | `c`（既定 1）。`t` も同じ値にする |
| `max_memory_kb ÷ p` | `m`（無ければ **4571M × c**。必ず書く） |

**`max_memory_kb` は AiiDA ではノードあたり、KUDPC の `m` はプロセスあたり**
である。`p` で割って合わせる。

```python
builder.metadata.options = {
    "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1,
                  "num_cores_per_mpiproc": 8},
    "max_wallclock_seconds": 3600,
    "withmpi": False,
}
# → #SBATCH --rsc p=1:t=8:c=8:m=36568M
```

**`max_memory_kb` は普通は書かなくてよい。** 書かなければこの plugin が
「1 コアあたりの初期値 × c」を入れる（システム B なら 4571M × 8 = 36568M）。
これは KUDPC が `m` 省略時に入れる値と同じなので、**確保されるコア数も
メモリ量も変わらない**。中途半端な値を書くと、それに比例してコア数が増える
（次節）。

明示したいときは `max_memory_kb` を渡す。

```python
"max_memory_kb": 8 * 1024 * 1024,   # → --rsc p=1:t=8:c=8:m=8192M
```

`custom_scheduler_commands` に自分で `--rsc` を書いた場合は、**こちらは
足さない**。GPU 版の書式（`--rsc g=1`）はまだ扱っていないので、そのときは
直接書く。

---

### 禁止の一覧は、実測ではなくマニュアルから写す

`FORBIDDEN_OPTIONS` の出典は公式マニュアル
「プログラムの実行 → ジョブ実行のヒント → **ジョブ投入時に使用できない
オプション**」の表である。

**実測で撥ねられたものだけを消す作りにしなかった理由。** 手元で
`sbatch --test-only` に旗を 1 つずつ足して確かめられるのは、その日その設定で
aiida-core が実際に書いた旗だけである。`--qos` は `metadata.options.qos` を
指定したときにしか書かれないし、`--gres` は GPU を要求したときにしか出ない。
**実測を頼りにすると、条件が揃った日にとつぜん全部の job が入らなくなる。**

実測とマニュアルが食い違ったところが 1 つある。

```
--get-user-env    sbatch --test-only では**通った**
                  マニュアルは「使用できない」と書いている
```

**マニュアルに従って落とす。** `import_sys_environment` は aiida-core の
**既定が True** なので、放っておくと必ず書かれる旗である。落として困らない
ことも分かっている —— KUDPC は「ジョブ投入時に設定されている環境変数は、
ジョブ実行時に継承されます」と明記している。

### `m` とコア数（マニュアル「計算資源の割り当て」）

システム B は **1 コアあたり 4571 M** でメモリを紐付けて管理している。

```
確保されるコア数 = max( c , ceil(m ÷ 4571M) )
m を書かなければ  m = 4571M × c  が自動で入る
```

```
--rsc p=1:t=1:c=1:m=4571M   →  1 コア / 4571M   （この plugin の既定）
--rsc p=1:t=1:c=1:m=8G      →  **2 コア**（m のほうが多くのコアを要求する）
--rsc p=1:t=8:c=8:m=32768M  →  8 コア（32768 ÷ 4571 = 7.2 → 8）
```

**`m` は必ず書く（v1.1.0）。** 省略しても KUDPC が `4571M × c` を黙って
入れるので動きはするが、**投入スクリプトを読んでも要求量が分からない**。
既定値は KUDPC が入れるのと同じ値なので、書くこと自体で挙動は変わらない。
**暗黙を明示に変えるだけ**である。

`max_memory_kb` を指定するときは、`max(c, ceil(m ÷ 4571M))` が `c` を
超えない範囲に収めること。超えるとコア数が勝手に増える。

システムごとに 1 コアあたりの初期値が違う（A = 1071M、B = 4571M、
C = 18392M、G = 8000M）。既定は**システム B**。camphor や cinnamon で使うなら
`KudpcSlurmScheduler.memory_mb_per_core` を差し替えた subclass を作るか、
`max_memory_kb` を明示する。

`t` は `c` か `c × 2`（ハイパースレッディング）のどちらかにする、という
のがマニュアルの指示である。この class は `t = c` を既定にする。

### 実走で確認

この plugin が出す header をそのまま `sbatch` に投げて、走ることを確認した。

```
job 23546538   --rsc p=1:t=8:c=8:m=32768M   → 16 processors（8 コア × HT 2）
job 23546871   --rsc p=1:t=8:c=8            → 同上（m は 4571M×8 が自動で入る）
job 23547782   AiiDA 経由の RelaxBatchCalculation（gr10653b、COMPLETED）
job 23547988   AiiDA 経由の GenerateCalculation（gr10653b、COMPLETED）
```

### スレッド数を決めるなら `SLURM_DPC_CPUS`

```
$SLURM_DPC_CPUS       タスクごとの**物理**コア数   → c=8 なら 8
$SLURM_CPUS_PER_TASK  タスクごとの**論理**コア数   → c=8 なら 16（HT 込み）
```

`SLURM_CPUS_PER_TASK` からスレッド数を決めると、**8 コアに 16 スレッドを
立てる**。numba や OpenMP の本数を計算ノード側で決めているなら
`SLURM_DPC_CPUS` を使うこと。

```bash
export NUMBA_NUM_THREADS=${SLURM_DPC_CPUS:-1}
```

### `srun` を使うこと

マニュアルは「逐次プログラム、MPI プログラムに関わらず、**必ず `srun`
コマンドを使用する必要があります**」と書いている。AiiDA で `withmpi=True` に
すれば Computer の `mpirun-command`（`srun -n {tot_num_mpiprocs}`）が使われる。

`withmpi=False` で直接叩いても走ることは確認した（job 23546538 / 23546871）。
**走るが、マニュアルの指示からは外れている。** 逐次の python を 1 本動かす
だけなら実害は見つかっていない。

---

### 設計 —— 親から引き算する

```python
header = super()._get_submit_script_header(job_tmpl)
kept   = [l for l in header.splitlines() if _option_name(l) not in FORBIDDEN_OPTIONS]
if not any("--rsc" in l for l in kept):
    kept.append(f"#SBATCH --rsc {self._rsc_for(job_tmpl)}")
```

親の実装を丸写しにすると、aiida-core がメールの旗や `--qos` の扱いを直した
ときに置いていかれる。**引き算なら追随する。**

**その代わり、aiida-core が新しい資源の旗を足したら黙って通してしまう。**
だから `tests/test_kudpc_scheduler.py` が両方向を見る。

```
test_the_parent_really_writes_them            親が本当に禁止の旗を書くか
                                              （引き算に意味があるか）
test_every_flag_..._was_checked_on_the_real_machine
                                              出す旗が**実機で確かめた集合**に
                                              収まっているか
```

後者が落ちたら、その旗が KUDPC で禁止かを `sbatch --test-only` で確かめて
から `VERIFIED_ALLOWED` を更新する。**表だけ合わせて済ませない。**

---

### 試験

```bash
pip install -e ".[dev]"
pytest
```

`aiida` が入っていない環境では飛ばす。entry point の試験は
`pip install` していない木では確かめようがないので飛ばすが、**飛ばした理由を
言う**（黙って通さない）。

---

### 参考

* バッチ処理 — <https://web.kudpc.kyoto-u.ac.jp/manual/ja/run/batch>
* 計算資源の割り当て（`--rsc` の意味、Rmin / Rstd / Rmax、`m` とコア数の関係）
  — <https://web.kudpc.kyoto-u.ac.jp/manual/ja/run/resource>
* ジョブ実行のヒント（**使用できないオプションの表**、ジョブ実行時の環境変数）
  — <https://web.kudpc.kyoto-u.ac.jp/manual/ja/run/hint>

### 履歴

#### v1.2.0（2026-09-29）

パッケージ名を **aiida-kudpc → aiida-kudpc-slurm**、import 名を **aiida_kudpc → aiida_kudpc_slurm** に変えた。
AiiDA の慣例に合わせて entry point を **`kudpc_slurm.slurm`** にし、**旧名 `kudpc.slurm` も同じ class を指すように残した**
（旧名で登録した computer はそのまま動く）。**旧パッケージ aiida-kudpc と同時に入れないこと**
（`kudpc.slurm` が 2 つになり AiiDA が entry point を決められない）。`pip uninstall aiida-kudpc` してから入れる。
挙動（出す header）は v1.1.0 と同じ。試験を公開用に書き直した。

### v1.1.0（2026-08-25）

`--rsc` に **`m` を必ず書く**ようにした。省略時は `4571M × c`（システム B の
初期値 × コア数）で、**KUDPC が黙って入れるのと同じ値**。したがって確保される
資源は変わらない。変わるのは「投入スクリプトを読めば要求量が分かる」こと
だけである。

1 コアあたりの初期値を `KudpcSlurmScheduler.memory_mb_per_core` に出したので、
システム A / C / G で使うときはここを差し替えられる。

`test_the_default_memory_does_not_inflate_the_core_count` を足した。既定の
`m` が `max(c, ceil(m ÷ 4571M))` で `c` を超えないことを見張る。**ここがずれる
と、8 コアのつもりが 9 コア確保になる。**

### v1.0.0（2026-08-25）

最初の版。`aiida-shotgun-csp` v4.6.0 の中に書いたものを切り出した。
**scheduler は特定の応用に依存しない**ので、独立した配布にしたほうが
他の plugin からも使えるし、版も別々に動かせる。
