# CPU 서버 ↔ GPU 서버 연동

EC2 CPU 서버의 `/srv/processed/v1` 을 GPU 서버로 가져오는 계층의 구현 문서.

* **책임 분리 / 스키마 / 작업 현황: [`README_HANDOFF_CONTRACT.md`](README_HANDOFF_CONTRACT.md)**
* 검증 게이트 (무엇이 왜 FAIL 하는가): [`README_GPU_VALIDATION.md`](README_GPU_VALIDATION.md)
* 학습 파이프라인 전체: [`README_GPU_WORKFLOW.md`](README_GPU_WORKFLOW.md)
* 실데이터 통합 실행 결과: [`REPORT_STAGE_A_INTEGRATION.md`](REPORT_STAGE_A_INTEGRATION.md)

---

## 1. 한 장 요약

```
Galaxy S10
    │  multipart/form-data
    ▼
EC2 FastAPI  ──►  /srv/tiger/sessions/<session_id>      (raw ingestion, CPU 담당)
    │
    │  CPU preprocessing
    ▼
/srv/processed/v1/<session>/                            (CPU 담당)
    │   └─ READY                ← 검증 전부 통과한 뒤 '마지막에' 생성
    │
    │  ★ 이번에 GPU에 구현한 부분: rsync over SSH, GPU가 pull
    ▼
<mirror>/.incoming/<session>.partial                    (staging)
    │  READY 있음? frames.csv 1개 이상?
    ▼
<mirror>/<session>/  + GPU_SYNCED                       (atomic mv)
    │
    ▼
UMI Zarr  →  UmiDataset  →  Training
```

* **GPU가 pull 한다.** CPU는 push 하지 않고, GPU 서버의 존재를 알 필요가 없다.
* **GPU는 Android용 `POST /sessions` 에 접속하지 않는다.** Android→CPU 와
  CPU→GPU 는 다른 계층이다.
* **GPU는 raw session 을 받지 않는다.** preprocessing 이 끝난
  `/srv/processed/v1` 만 가져온다.
* 새 API, S3, 큐, NFS 는 만들지 않았다. `rsync over SSH` 뿐이다.

---

## 2. 역할 분리

| | 책임 |
|---|---|
| CPU | 완성된 processed dataset 을 publish 하고, 마지막에 `READY` 를 쓴다 |
| GPU | `READY` 인 session 을 원하는 시점에 가져간다 |

**tracking 정제는 전부 CPU 책임이다.**

```
CPU:  pose validity → start/end trim → short gap interpolation
      → long gap split → invalid/short segment reject → quality metadata → READY
GPU:  strict sanity check  (복구하지 않음. 통과 아니면 FAIL)
```

GPU converter 에서 long gap interpolation / episode splitting / tracking recovery 를
**다시 구현하지 않는다.** 중복 구현이고, 두 곳에서 서로 다르게 고치면 dataset 이
조용히 갈라진다.

CPU preprocessing 코드는 GPU 서버의 상태를 전혀 알 필요가 없다.
GPU 는 CPU 에 아무것도 쓰지 않는다 (읽기 전용 pull).

### GPU 에서 다시 하지 않는 것

CPU 에서 이미 끝난 것은 GPU 가 재구현하지 않는다.

```
raw session integrity      frame extraction
timestamp alignment        ARCore pose alignment
episode slicing            tracking / quality 정보 생성
```

즉 GPU 는 `main_rgb.mp4` 를 다시 디코드해서 timestamp 를 맞추거나,
`arcore_poses.csv` 를 nearest join 하거나, IMU 를 재동기화하지 않는다.
GPU 는 `processed_v1 → 학습 contract 변환 → UMI Zarr` 에만 집중한다.

---

## 3. 구현물

```
scripts/
├─ sync_processed_from_cpu.sh        CPU → GPU pull (READY gate + staging + atomic publish)
└─ inspect_synced_processed.py       mirror 검증 + DATASET STATUS

config/
└─ cpu_sync.env.example              설정 템플릿 (실제 파일은 .gitignore)

omx/
├─ config.py                         PROCESSED_ROOT 를 cpu_sync.env 에서 해석
└─ data/processed_v1.py              READY gate + dot-dir skip (discover_processed_v1)

scripts/convert_processed_to_umi_zarr.py
                                     --require-ready (기본 on), skip 개수 metadata 기록
```

`.gitignore` 에 추가: `config/cpu_sync.env`, `cpu_sync.env`, `*.pem`
— 실제 host/key 는 절대 커밋되지 않는다.

---

## 4. READY marker contract

**가장 중요한 규칙.** session directory 가 존재한다는 이유만으로 가져오면 안 된다.
CPU preprocessing 이 돌고 있는 도중에도 directory 자체는 존재할 수 있다.

```
정상 조건 =  session directory 존재  AND  <session>/READY 존재
```

GPU 쪽은 두 군데에서 이걸 강제한다.

1. `sync_processed_from_cpu.sh` — CPU 에서 `READY` 가 있는 session 만 찾는다.

   ```bash
   find /srv/processed/v1 -mindepth 2 -maxdepth 2 -type f -name READY -printf '%h\n'
   ```

2. `omx/data/processed_v1.py: discover_processed_v1()` — 로컬 mirror 에서도
   `READY` 가 없는 session 의 episode 는 converter 가 건너뛴다.
   (`--no-require-ready` 는 손으로 만든 테스트 트리 전용)

### CPU 담당자가 확인해야 할 것

설계 contract 에는 `READY` 가 정의돼 있지만, 최신 CPU 실행 기록에서 실제 생성까지는
확인되지 않았다. 최초 연동 전에 **딱 한 번** 확인한다.

```bash
find /srv/processed/v1 -maxdepth 2 -name READY -print
```

session 은 있는데 아무것도 안 나오면, CPU preprocessing 의 **맨 마지막**,
validation 이 성공한 뒤에만 다음을 추가하면 된다.

```python
(session_output_dir / "READY").touch()
```

> 순서가 중요하다. trajectory 생성 → metadata 생성 → quality validation →
> **전부 성공** → `READY`. 중간에 쓰면 GPU 가 미완성 session 을 가져간다.

---

## 5. Staging → atomic publish

다운로드 중인 directory 를 converter 가 읽어버리는 사고를 막기 위해,
최종 경로에 직접 rsync 하지 않는다.

```
<mirror>/.incoming/<session>.partial     ← rsync 목적지
        │
        │  전송 완료 후 검증:
        │    · READY 파일이 전송됐는가
        │    · frames.csv 가 1개 이상 있는가  (depth 2)
        ▼
<mirror>/<session>/                      ← mv (같은 파일시스템이므로 atomic rename)
<mirror>/<session>/GPU_SYNCED            ← 동기화 시각 기록
```

CPU ingestion 도 `incoming → 검증 → rename → sessions` 형태의 atomic publish 를
쓰고 있으므로, GPU 도 같은 철학을 따른다.

converter 는 `.incoming/` 을 **절대** 읽지 않는다
(`discover_processed_v1` 이 dot-directory 를 아예 순회하지 않는다).

### CPU 가 같은 session 을 다시 정제했을 때

**이게 지금 실제로 걸리는 문제다.** GPU 에 이미 받아둔 7 session 은 수정 전 CPU
preprocessing 의 결과물이다. CPU 를 고쳐서 **같은 session UUID** 로 다시 publish
하면, 단순히 "local 에 있으면 skip" 하는 구조는 옛 사본을 그대로 쓴다.

```
CPU old bad session  →  GPU sync 완료  →  GPU/<same id>/READY 존재
CPU preprocessing 수정  →  같은 id 로 재정제  →  GPU sync
                                                 → "already synced, skipping"   ← 문제
```

#### 감지 방법

`rsync -a` 는 mtime 을 보존한다. 따라서 **로컬 `READY` 파일의 mtime 은 CPU 가
그것을 쓴 시각**이다. 이걸 원격 `READY` 의 mtime 과 비교한다.

```
remote READY mtime == local READY mtime   →  최신. skip
remote READY mtime != local READY mtime   →  STALE. 크게 보고하고 절대 조용히 넘기지 않음
```

두 값 모두 **CPU 의 시계**에서 나오므로 두 서버 간 시계 오차가 오판을 만들지 않는다.
이미 받아둔 7 session 에도 그대로 적용된다 — 별도 마이그레이션이 필요 없다.

```
=== session 15769f88-... ===
STALE: the CPU re-published this session after we mirrored it
       local  READY 2026-09-21T10:51:42+09:00
       remote READY 2026-09-23T14:20:07+09:00
       not replaced. Re-run with --resync to pull the new copy.
...
  1 session(s) were re-published by the CPU after we mirrored them:
    15769f88-...
  The local copies are OUT OF DATE. Replace them with:
      ./scripts/sync_processed_from_cpu.sh --resync
```

#### 교체 방법

```bash
# CPU 수정이 끝난 뒤
./scripts/sync_processed_from_cpu.sh -n --resync   # 무엇이 교체될지 먼저 확인
./scripts/sync_processed_from_cpu.sh --resync      # 실행
```

| 옵션 | 동작 |
|---|---|
| `--resync` | STALE 로 감지된 session 만 교체 |
| `--force-resync` | READY mtime 이 안 바뀌었어도 **모든** session 교체 |
| `--prune-orphans` | CPU 가 더 이상 publish 하지 않는 로컬 session 을 치움 |
| `-s <uuid>` | 위를 특정 session 하나로 한정 |
| `-n` | 무엇이 바뀔지만 출력 |

`--force-resync` 는 CPU 가 재정제하면서 `READY` 의 timestamp 를 유지해버린 경우를
위한 안전망이다. 확신이 안 서면 이걸 쓰면 된다.

#### CPU 가 reject 한 session (고아)

CPU 수정 후 어떤 session 은 아예 reject 되어 `READY` 가 사라진다. 그러면 그
session 은 **로컬에만 남는다.** stale 이 아니라 원격에 존재하지 않는 상태다.

이걸 방치하면 **converter 가 계속 읽는다.** 그래서 sync 가 항상 보고한다.

```
  1 local session(s) are NOT published by the CPU any more:
    e096668c-...
  Most likely the fixed CPU preprocessing now rejects them.
  They are STILL ON DISK and the converter will still read them. Move
  them aside with:
      ./scripts/sync_processed_from_cpu.sh --prune-orphans
  (moved to .superseded/, not deleted)
```

```bash
./scripts/sync_processed_from_cpu.sh --prune-orphans
```

이것도 삭제가 아니라 `.superseded/<session>.orphan.<stamp>/` 로 이동이다.

#### 옛 사본은 지우지 않는다

교체는 **삭제가 아니라 이동**이다.

```
<mirror>/<session>/  →  <mirror>/.superseded/<session>.<timestamp>/
```

converter 와 inspector 는 `.superseded/` 를 읽지 않는다 (dot directory).
새 데이터가 검사를 통과한 걸 확인한 뒤 직접 지운다.

```bash
python scripts/inspect_synced_processed.py       # Training Status 확인
rm -rf ~/omx_data/processed/v1/.superseded       # 확인됐으면 정리
```

새 `GPU_SYNCED` 에는 무엇을 교체했는지도 남는다.

```
synced_at=2026-09-23T14:31:02+09:00
cpu_host=<EC2_HOST>
cpu_path=/srv/processed/v1/15769f88-...
remote_ready_mtime=1790140807
episodes=1
replaced_previous=/home/.../.superseded/15769f88-....20260923_143102
```

### 그 밖의 안전장치

| | |
|---|---|
| **멱등성** | 내용이 그대로면 `already synced, skipping`. 몇 번을 돌려도 재복제하지 않는다 |
| **stale 감지** | CPU 가 같은 session 을 다시 publish 하면 감지해서 보고한다. **조용히 건너뛰지 않는다** (아래 참고) |
| **재개** | `rsync --partial` 로 staging 이 남으므로 끊긴 전송은 다음 실행에서 이어받는다 |
| **비파괴** | 스크립트는 아무것도 지우지 않는다. 교체할 때도 옛 사본을 `.superseded/` 로 옮긴다 |
| **직렬화** | `<mirror>/.sync.lock` 에 `flock`. 두 번째 실행은 즉시 빠져나간다 |
| **로그** | 매 실행마다 `<mirror>/.logs/sync_<YYYYmmdd_HHMMSS>.log` |

---

## 6. 설정

모든 설정은 `cpu_sync.env` 한 곳. Python 코드에 IP/key 를 하드코딩하지 않는다.

```bash
# 기본 위치 (CPU_SYNC_ENV 환경변수로 변경 가능)
~/umi-gpu/config/cpu_sync.env
```

```bash
CPU_USER=ubuntu
CPU_HOST=<EC2_HOST>                       # ← 채워야 함
CPU_PROCESSED_ROOT=/srv/processed/v1

GPU_PROCESSED_ROOT=$HOME/omx_data/processed/v1

SSH_KEY=$HOME/.ssh/tiger_cpu_sync
SSH_PORT=22

# RSYNC_EXTRA_FLAGS=--bwlimit=50M         # 공유 회선일 때 유용
```

### mirror 위치가 `/data/dataset/v1` 이 아닌 이유

**이 서버는 sudo 가 없고 `/data` 마운트가 없다.**

```
sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
/data: No such file or directory
/home: 12T total, 11T available
```

그래서 **root 만** 옮겼다. namespace 는 그대로 둔다.

```
/data/dataset/v1              원 사양
~/omx_data/processed/v1       현재
^^^^^^^^^^^^               이 부분만 다름
```

`processed/v1` 을 유지하는 이유:

* 경로만 봐도 무엇의 mirror 인지 드러난다 —
  `<cpu>:/srv/processed/v1` → `<gpu>:~/omx_data/processed/v1`
* GPU 가 **생성한** 것(`data/omx/zarr` 등)과 CPU 에서 **받아온** 것이 이름으로 구분된다

`/data` 를 쓸 수 있게 되면 `GPU_PROCESSED_ROOT` 한 줄만 바꾸면 된다.

**sync 스크립트와 converter 가 같은 값을 본다.** `omx/config.py` 가 동일한
`cpu_sync.env` 를 읽으므로 둘이 다른 경로를 가리킬 수 없다.

```
PROCESSED_ROOT 해석 순서
  1. OMX_PROCESSED_ROOT            (환경변수)
  2. GPU_PROCESSED_ROOT            (cpu_sync.env)
  3. ~/omx_data/processed/v1       (기본값)
```

`~/.bashrc` 에도 `OMX_PROCESSED_ROOT` 를 export 해 두었다.

---

## 7. 최초 1회 셋업

```bash
# 1) SSH key 생성
ssh-keygen -t ed25519 -f ~/.ssh/tiger_cpu_sync
cat ~/.ssh/tiger_cpu_sync.pub          # → EC2 계정의 authorized_keys 에 등록

# 2) 설정 파일 (이미 템플릿이 복사돼 있음)
$EDITOR ~/umi-gpu/config/cpu_sync.env  # CPU_HOST 채우기

# 3) 연결 확인
ssh -i ~/.ssh/tiger_cpu_sync ubuntu@<EC2_HOST> 'echo CPU_CONNECTION_OK'
#   기대 출력: CPU_CONNECTION_OK

# 4) CPU 쪽 상태 확인
ssh -i ~/.ssh/tiger_cpu_sync ubuntu@<EC2_HOST> 'ls -al /srv/processed/v1'
ssh -i ~/.ssh/tiger_cpu_sync ubuntu@<EC2_HOST> \
    'find /srv/processed/v1 -maxdepth 2 -name READY -print'
```

비밀번호는 스크립트 안에 적지 않는다. 자동 sync 까지 고려하면 passphrase 유무는
운영 방식에 따라 결정한다 (cron 으로 돌릴 거면 passphrase 없이 + 키 권한 600).

스크립트는 시작할 때 다음을 먼저 막는다.

* 설정 파일 없음 → 어디에 무엇을 복사하면 되는지 출력하고 종료
* 필수 변수 누락 → 어떤 변수인지 출력하고 종료
* `CPU_HOST` 가 아직 `<EC2_HOST>` placeholder → 종료
* SSH key 파일 없음 → `ssh-keygen` 명령을 그대로 출력하고 종료

---

## 8. 실행

```bash
./scripts/sync_processed_from_cpu.sh            # READY 인 것 전부
./scripts/sync_processed_from_cpu.sh -n         # dry run (목록만, 전송 없음)
./scripts/sync_processed_from_cpu.sh -s <uuid>  # 특정 session 하나만
./scripts/sync_processed_from_cpu.sh -e <path>  # 다른 설정 파일
```

출력 예:

```
[1/4] looking for READY sessions on the CPU server...

=== session 5f82c2d9-... ===
[2/4] rsync -> <mirror>/.incoming/5f82c2d9-....partial
[3/4] validating the local copy
episodes = 5
[4/4] atomic publish
SYNC COMPLETE: 5f82c2d9-...

=== session b8e8cd4e-... ===
already synced, skipping

==============================================================================
READY on CPU: 2   synced: 1   already present: 1   failed: 0
```

**session 하나가 실패해도 나머지는 계속 진행하고, 마지막에 exit code 1 로 끝난다.**
(원 사양 스케치는 첫 실패에서 `exit 1` 이었는데, 그러면 깨진 session 하나가
다른 전부를 막는다.)

### 권장 command flow

```bash
# 1. 연결 확인
ssh -i ~/.ssh/tiger_cpu_sync ubuntu@<EC2_HOST> 'echo OK'

# 2. READY 확인
ssh -i ~/.ssh/tiger_cpu_sync ubuntu@<EC2_HOST> \
    'find /srv/processed/v1 -maxdepth 2 -name READY -print'

# 3. pull
./scripts/sync_processed_from_cpu.sh

# 4. 로컬 검증
python scripts/inspect_synced_processed.py -v

# 5. UMI 변환
python -m omx.cli build omx_pick_raw_center_v1

# 6. 학습용 dataset 검사
python -m omx.cli inspect omx_pick_raw_center_v1
```

---

## 9. 검사 — `inspect_synced_processed.py`

```bash
python scripts/inspect_synced_processed.py              # OMX_PROCESSED_ROOT 사용
python scripts/inspect_synced_processed.py --root <dir> -v
```

### session 단위

* `READY` 존재 여부 (없으면 "converter 가 건너뛴다" 고 경고)
* `GPU_SYNCED` 존재 여부
* `.incoming/` 에 남아있는 미완 전송 개수

### episode 단위

| 검사 | 실패 시 | `--no-strict` |
|---|---|---|
| pose column 존재 | error | error |
| **pose 값 전부 parse 가능** (blank/`""` 없음) | error | **error** |
| position / quaternion finite | error | error |
| quaternion norm ≈ 1 | error | error |
| timestamp parse 가능 / 단조 증가 | error | error |
| `rgb_frames/` 이미지 개수 == `frames.csv` row 개수 | error | error |
| `rgb_path` 전부 실제 파일로 resolve (전체 row) | error | error |
| `frame_idx` 연속성 | error | error |
| `pose_valid=false` 잔존 | error | 경고 |
| `tracking_state` 비정상 잔존 | error | 경고 |
| episode 길이 < action_horizon 충족치 | error | 경고 |
| 측정 fps vs `timing.source_fps` | 1 Hz 넘게 벌어지면 경고 | 경고 |
| frame interval jitter | max/min > 3 이면 경고 | 경고 |
| `quality.json` 존재 / gripper 컬럼 | 집계 + 경고 | 집계 + 경고 |

전체 규칙과 실패 출력 예시는 [`README_GPU_VALIDATION.md`](README_GPU_VALIDATION.md) 참고.

`--no-strict` 는 **triage 전용**이다. `pose_valid=false` / 비정상 tracking / 짧은
episode 세 가지만 경고로 낮춘다. **blank pose cell 은 어느 모드에서도 error 다** —
정책 선택의 문제가 아니라 복구 불가능한 결손이기 때문이다. 그리고 `--no-strict` 는
이 리포트만 바꾼다. converter 는 여전히 build 를 거부한다.

### blank pose cell 을 0 으로 채우지 않는 이유

`camera_tx=""` 를 `0.0` 으로 읽으면 end effector 가 world origin 으로 순간이동한
것처럼 보이는 궤적이 만들어지고, 그게 학습 데이터에 그대로 들어간다.
reader 는 blank 를 **NaN** 으로만 만들고, NaN 은 validity mask 를 타고 내려가
`invalid_policy=error` 에서 build 를 멈춘다. 숫자 기본값을 넣는 경로는 코드에 없다.

### 마지막 출력

```
DATASET STATUS
--------------
Transfer         : OK
RGB/Pose Align   : OK
T_camera_EE      : PLACEHOLDER
Gripper Width    : MISSING
Training Status  : INTEGRATION ONLY
```

`Training Status` 는 세 단계다.

| | 의미 |
|---|---|
| `BLOCKED` | 정합 자체가 깨짐. 변환하면 안 됨 |
| `INTEGRATION ONLY` | 파이프라인은 돌지만 calibration/gripper 가 placeholder. 결과로 보고하면 안 됨 |
| `READY` | `T_camera_EE` 가 실제 calibration 이고 gripper 가 marker 기반 meter 값 |

placeholder 나 gripper 누락은 **hard failure 가 아니다.** 상태만 낮춘다.
지금 단계(Stage A)에서는 `INTEGRATION ONLY` 가 정상이다.

---

## 10. Converter 와의 연결

sync 후 converter 는 mirror 아래에서 **`READY` 가 있고 dot-directory 가 아닌**
session 만 읽는다.

```python
# omx/data/processed_v1.py: discover_processed_v1()
#   · os.walk 중 이름이 '.' 로 시작하는 디렉토리는 아예 순회하지 않음  (.incoming, .logs)
#   · episode 의 조상 중 READY 를 가진 디렉토리가 없으면 skip
#   · 건너뛴 episode 는 skipped 리스트로 반환 → converter 가 경고 출력
```

### converter 도 같은 gate 다

`configs/collector/default.yaml` 의 `validity.invalid_policy` 기본값은 `error` 다.

```
error   유효하지 않은 frame 이 하나라도 있으면 build 거부  ← contract
trim    가장 긴 유효 구간만 남김        \  알려진 불량 export 를 들여다볼 때만.
split   내부 불량 구간에서 잘라 나눔    /  학습 dataset 생성에 쓰면 안 됨
keep    그대로 통과 (값은 NaN 으로 남고, 0 이 되지 않음)
```

에러 메시지는 어느 episode 의 어느 컬럼 몇 번째 row 인지까지 찍고,
**모든 episode 를 다 검사한 뒤 한 번에** 보고한다 (CPU 왕복을 줄이기 위해).

```
==============================================================================
CPU processed_v1 CONTRACT VIOLATION in 1 of 5 episode(s)
==============================================================================
[<session>__<episode>] 15/210 frames fail validation and validity.invalid_policy='error'.
  causes: non_finite_pose=15
          blank/unparseable cells in camera_tx (15/210 rows, at index 40, 41, ...), ...
          quaternion_norm=15
          pose_valid_false=15
  This is a CPU processed_v1 contract violation: the CPU side is responsible for
  trimming, interpolating short gaps, splitting long gaps and rejecting unusable
  segments before writing READY.
  The GPU side is the final gate, not a repair step ...
```

### READY gate 출력 예 (실제 테스트):

```
! skipped 5 episode(s) whose session has no READY marker
  (CPU preprocessing may still be running): ['00000000-notready-...__3b51de2c-...', ...]
found 10 episode(s)
```

이 개수는 zarr metadata 에도 남는다.

```json
"dataset": { "require_ready": true, "episodes_skipped_not_ready": 5 }
```

### 검증한 케이스

READY 2개 session(10 episode) + READY 없는 session 1개(5 episode) +
`.incoming` 미완 전송 1개를 섞어서 실제로 확인했다.

```
inspect_synced_processed.py
  → notready session 을 "NO READY marker" 로 보고
  → .incoming 1건을 "never read by the converter" 로 보고
  → 10 episodes / 2100 frames / 측정 fps 30.00
converter (dry-run)
  → skipped 5 episode(s) ... / found 10 episode(s)
```

---

## 11. mirror 는 읽기 전용

GPU local copy 는 **학습 입력의 mirror** 일 뿐이다. 다음은 하지 않는다.

```
frames.csv 수정          RGB 원본 overwrite
trajectory.npz 수정      quality.json 수정
READY 수정
```

GPU 에서 만든 것은 전부 다른 위치에 둔다.

```
<mirror>/                       CPU processed mirror  (읽기 전용)
data/omx/zarr/                  GPU 가 만든 UMI dataset
data/omx/{inspect,train,infer}/ 검사 결과 / 체크포인트 / 추론 결과
```

---

## 12. 원 사양 대비 변경점

| 항목 | 사양 | 구현 | 이유 |
|---|---|---|---|
| mirror **root** | `/data` | `$HOME/omx_data` (설정 가능) | 이 서버에 root 권한과 `/data` 마운트가 없음. `/home` 에 11 TB 여유. `processed/v1` namespace 는 CPU 쪽과 대응되도록 그대로 유지 |
| 세션 실패 처리 | 첫 실패에서 `exit 1` | 기록 후 계속, 마지막에 exit 1 | session 하나가 나머지 전부를 막지 않도록 |
| `invalid_policy` 기본값 | — | `split` → `error` | tracking 정제는 CPU 책임. GPU 는 복구자가 아니라 마지막 gate |
| blank pose cell | — | NaN, 그리고 FAIL | `float("")` crash 를 고치되 0 으로 채우지 않기 위해 |
| 동시 실행 | 없음 | `flock` 직렬화 | 두 번 돌렸을 때 staging 충돌 방지 |
| 재-publish 처리 | 없음 (local 에 있으면 무조건 skip) | READY mtime 비교로 STALE 감지 + `--resync` | CPU 가 같은 UUID 로 재정제하면 옛 사본을 계속 쓰게 됨 |
| 교체 시 옛 사본 | — | `.superseded/` 로 이동 | 새 export 가 더 나쁠 수 있으므로 되돌릴 수 있게 |
| 로그 | 없음 | `.logs/sync_<stamp>.log` | 전송 실패 사후 추적 |
| dry run | 없음 | `-n` | 전송 전에 대상 확인 |

그 외(READY gate, staging → atomic publish, 멱등성, 비파괴, env 파일 분리,
`cpu_sync.env.example` 에 실제 IP/key 미포함)는 사양 그대로다.

---

## 13. CPU 담당자 action item

1. **`READY` 생성 확인** — `find /srv/processed/v1 -maxdepth 2 -name READY -print`
   가 비어 있으면 preprocessing 마지막(validation 성공 후)에
   `(session_output_dir / "READY").touch()` 추가.

2. **SSH public key 등록** — GPU 쪽에서 `~/.ssh/tiger_cpu_sync.pub` 를 전달하면
   EC2 계정의 `authorized_keys` 에 추가.

3. **`gripper_width_m` 컬럼** — ArUco marker 기반 gripper width 추출은 CPU
   deterministic preprocessing 에 두는 것이 맞다. 학습 모델이 계산할 값이 아니라
   dataset 생성용 측정값이기 때문.

   ```
   RGB frame → ArUco detection → pivot/gripper geometry calibration
            → physical fingertip opening width [m]
            → frames.csv 의 frame timestamp 에 align
   ```

   `frames.csv` 에 meter 단위로 들어오면 GPU 는 그대로
   `robot0_gripper_width` 로 export 한다 (변환 없음).
   컬럼명이 다르면 `configs/collector/default.yaml` 의 `field_map` 에 한 줄 추가하면 된다.

4. **`T_camera_EE` calibration** — 확보되면 GPU 에서 동일 converter 를 재실행해
   dataset 을 재-export 한다. **raw 데이터 재수집은 필요 없다.**
   raw ARCore camera pose 가 그대로 보존돼 있으므로
   `raw pose + new T_camera_EE → 새 EE trajectory` 가 성립한다.

---

## 14. 실데이터 전환 절차 (CPU 수정 완료 후)

현재 mirror 의 7 session 은 **전부 수정 전 데이터**다. reject 된 것만 문제가
아니라, 살아남은 것도 trim 후 내용이 바뀐다. 따라서 7개 전부 갈아야 한다.

두 가지 방법이 있다. 어느 쪽이든 결과는 같다.

### 방법 A — 스크립트에 맡긴다 (권장)

```bash
cd ~/universal_manipulation_interface

./scripts/sync_processed_from_cpu.sh -n --force-resync      # 1. 무엇이 바뀔지 확인
./scripts/sync_processed_from_cpu.sh    --force-resync      # 2. 전부 교체
./scripts/sync_processed_from_cpu.sh    --prune-orphans     # 3. reject 된 것 치우기
```

`--force-resync` 를 쓰는 이유는, CPU 가 재정제하면서 `READY` 의 timestamp 를
유지해버리면 stale 감지가 안 되기 때문이다. 확실하게 가려면 이걸 쓴다.
옛 사본은 전부 `.superseded/` 에 남는다.

### 방법 B — mirror 를 통째로 보존하고 새로 받는다

```bash
mv ~/omx_data/processed/v1 ~/omx_data/processed/v1_pre_posefix_20260921
mkdir -p ~/omx_data/processed/v1/.incoming ~/omx_data/processed/v1/.logs

cd ~/universal_manipulation_interface
./scripts/sync_processed_from_cpu.sh
```

빈 mirror 에서 시작하므로 고아가 생길 수 없다. 대신 전부 다시 받는다.

> **주의**: CPU 재정제가 끝나기 전에 B 를 하면 안 된다. 빈 mirror 에 옛 데이터를
> 다시 받게 된다.

### 그다음 (GPU-6 ~ GPU-10)

```bash
conda activate umi
cd ~/universal_manipulation_interface

# 6. strict inspection
python scripts/inspect_synced_processed.py -v
#    기대: Transfer OK / RGB/Pose Align OK
#          T_camera_EE PLACEHOLDER, Gripper MISSING -> INTEGRATION ONLY 는 정상
#          blank pose / pose_valid=false / 보간 안 된 비정상 tracking /
#          짧은 segment 가 하나라도 남으면 BLOCKED

# 7. dry-run
python -m omx.cli build omx_pick_raw_center_v1 --dry-run
#    확인: READY session 수, episode/segment 수, contract violation 0

# 8. 실제 build
python -m omx.cli build omx_pick_raw_center_v1 --overwrite

# 9. zarr 검사
python -m omx.cli inspect omx_pick_raw_center_v1
#    확인: UmiDataset load, action.shape == [16,10], short episode silent drop 없음

# 10. smoke training
python -m omx.cli train omx_pick_raw_center_v1 --profile smoke
#    성능을 보는 게 아니라 실데이터가 stack 을 통과하는지만 본다
```

### 실패하면 (GPU-11)

**GPU 에서 고치지 않는다.** inspector 가 `BLOCKED` 을 내면 마지막에
`CPU ACTION ITEMS` 블록이 출력된다. session / episode / 컬럼 / row 까지 들어
있으므로 그대로 CPU 에 넘기면 된다.

```
CPU ACTION ITEMS
==============================================================================
root   : /home/.../omx_data/processed/v1
config : configs/collector/default.yaml  (source_fps=30, policy_hz=10,
         min 16 stored / 46 source frames)

session = 5f82c2d9-...
episode = 3b51de2c-...
  rows=180 images=180 duration=6.0s fps=30.00 interpolated=0
  - blank/unparseable cells -- CPU processed contract violation:
    camera_tx (5/180 rows, at index 40, 41, 42, 43, 44)
    ...
  - 5/180 rows have pose_valid=false. CPU preprocessing should have trimmed,
    interpolated or split these out before writing READY
  - 5/180 rows have a non-tracking tracking_state and are NOT marked
    pose_interpolated
```

---

## 15. 현재 상태 / 완료 조건

### 완료 조건

```
CPU 에 READY session 존재
      ↓
GPU script 1회 실행
      ↓
session 자동 발견 → .incoming 으로 rsync → 전송 검증 → atomic publish
      ↓
<mirror>/<session>
      ↓
inspect 통과
      ↓
converter 가 바로 읽음
      ↓
같은 명령을 다시 실행하면 "already synced, skipping" 으로 끝남
```

### 현재

| 항목 | 상태 |
|---|---|
| sync 스크립트 | 구현 완료, 문법/인자/에러 경로 검증 완료 |
| mirror 검증 스크립트 | 구현 완료, READY/notready/.incoming 혼합 케이스 검증 완료 |
| converter READY gate | 구현 완료, 실제로 5 episode skip 확인 |
| 경로 설정 일원화 | 완료 (`cpu_sync.env` 하나를 sync 와 converter 가 공유) |
| 재-publish 감지 / 교체 | 구현 완료, 7개 시나리오 검증 완료 |
| **실제 EC2 연결** | **완료** — 7 session / 9 episode / 72 MB 동기화됨 |
| **CPU 측 재정제** | **대기** — 수정 후 `--resync` 로 교체 |

현재 mirror 에는 **수정 전 CPU preprocessing 의 결과물 7 session** 이 들어 있다.
CPU 수정이 끝나면 다음 한 줄로 교체된다.

```bash
./scripts/sync_processed_from_cpu.sh --resync
```

READY mtime 이 바뀌지 않았다면 `--force-resync` 를 쓴다.
옛 사본은 `.superseded/` 에 남으므로 손으로 지울 필요가 없다.

---

## 16. 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `ERROR: config not found` | `cp config/cpu_sync.env.example ~/umi-gpu/config/cpu_sync.env` |
| `ERROR: CPU_HOST is still the placeholder` | `cpu_sync.env` 의 `CPU_HOST` 를 실제 주소로 |
| `ERROR: SSH key not found` | `ssh-keygen -t ed25519 -f ~/.ssh/tiger_cpu_sync` 후 `.pub` 등록 |
| `ERROR: cannot reach ... over SSH` | key 등록 여부 / `SSH_PORT` / 보안그룹 확인. `BatchMode=yes` 라 비밀번호 프롬프트는 뜨지 않고 바로 실패한다 |
| `No READY sessions found` | CPU 에서 `find ... -name READY` 확인. 없으면 action item 1 |
| `exists but has no READY marker` | 이전 publish 가 중간에 깨진 것. 내용 확인 후 사람이 직접 삭제. 스크립트는 데이터를 지우지 않는다 |
| `another sync is already running` | 다른 실행이 진행 중. `<mirror>/.sync.lock` |
| converter 가 episode 를 못 찾음 | session 에 `READY` 가 있는지, `.incoming` 밖에 있는지 확인 |
| 전송이 끊김 | 그냥 다시 실행. `--partial` 로 이어받는다 |
| CPU 를 고쳤는데 옛 데이터가 계속 쓰임 | `--resync` (STALE 인 것만) 또는 `--force-resync` (전부). 옛 사본은 `.superseded/` 로 이동 |
| `STALE` 이 떴는데 교체하기 싫음 | 그냥 두면 된다. 매 실행마다 다시 보고하고 조용히 넘어가지 않는다 |
| 새 export 가 더 나쁨 | `.superseded/<session>.<stamp>/` 를 `<mirror>/<session>/` 로 되돌린다 |
| `.superseded/` 가 디스크를 먹음 | 새 데이터가 inspect 를 통과한 뒤 `rm -rf <mirror>/.superseded` |

---

## 17. 만들지 않은 것

현재 dataset 규모와 일정에서는 과설계라 만들지 않았다.

```
새 FastAPI download API        GPU → CPU HTTP polling
S3 uploader                    Kafka / message queue
NFS cluster                    실시간 RGB streaming
Android /sessions endpoint 재사용
```

CPU 쪽 설계 자체가 이미 `/srv/processed/v1 → rsync over SSH → GPU` 를
handoff 방식으로 잡고 있다.
