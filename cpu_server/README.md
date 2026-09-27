# OMX-UMI CPU Server

Galaxy S10 업로드를 받아 학습 가능한 `processed_v1` 데이터셋으로 정제하는 EC2 CPU 서버의 코드와 배포 설정.

수집된 raw 세션과 processed 산출물은 서버의 `/srv` 아래에 있으며 이 리포지토리에 포함되지 않는다.

## 역할 경계

```
Galaxy S10
    ↓  multipart upload
EC2 CPU  ─ main.py         : ingestion API (검증 + 원자적 저장)
         ─ preprocess.py   : processed_v1 빌드 (정렬 + pose 정제)
    ↓  /srv/processed/v1/<session>/READY
GPU      ─ strict gate → UMI Zarr → training
```

**CPU의 마지막 책임은 "시간적으로 정렬되고, pose가 유효하며, 연속적인 trajectory dataset"이다.**
tracking 복구는 CPU 책임이고, GPU는 strict gate만 수행한다.

CPU가 **하지 않는 것**: 30 Hz → 10 Hz policy downsampling, `T_camera_EE` 적용(현재 config는 identity placeholder), rotation 6D 변환, UMI ReplayBuffer/Zarr 생성, CLIP preprocessing, Diffusion Policy action 생성.

## 서버 런타임 레이아웃

```
/srv/
├── incoming/                    업로드 staging (원자적 rename 전)
├── locks/                       session_id 단위 업로드 락
├── sessions/<session_id>/       raw 업로드 — 절대 수정하지 않음
│   ├── metadata.json            files manifest (path/sizeBytes/sha256)
│   ├── main_rgb.mp4
│   ├── main_frame_timestamps.csv
│   ├── arcore_poses.csv
│   ├── episodes.csv
│   ├── accelerometer.csv / gyroscope.csv / rotation_vector.csv
│   └── (선택) ultrawide_rgb.mp4, ultrawide_frame_timestamps.csv
└── processed/v1/
    ├── validation_report.json / .csv
    └── <session_id>/
        ├── session_metadata.json
        ├── episode_<id>/                  publish된 segment (split 시 _seg000, _seg001 …)
        │   ├── frames.csv
        │   ├── rgb_frames/frame_*.jpg
        │   ├── trajectory.npz
        │   ├── metadata.json
        │   ├── quality.json
        │   └── accelerometer.csv / gyroscope.csv / rotation_vector.csv
        ├── rejected_episode_<id>/         진단 메타데이터만 (frames.csv·rgb 없음)
        ├── failed_episode_<id>/           진단 메타데이터만
        └── READY                          ← GPU sync gate
```

`episode_*` 만 publish 대상이다. `rejected_episode_*` / `failed_episode_*` 는 training input처럼 보이는 layout을 의도적으로 만들지 않는다.

## 리포지토리 구성

| 경로 | 내용 |
|---|---|
| `SETUP.md` | 빈 서버에서의 설치·재현 가이드 (의존성, `/srv` 부트스트랩, nginx, 검증 절차) |
| `server/main.py` | FastAPI ingestion API. `POST /sessions` (multipart), `GET /health` |
| `server/preprocess.py` | `processed_v1` 빌더. 표준 라이브러리 + `ffmpeg`/`ffprobe`만 사용 (NumPy/pandas 불필요) |
| `server/preprocess_v1_config.json` | 정렬·품질·pose 정제·calibration 임계값 |
| `server/test_preprocess.py` | 단위 테스트 30건 (`/srv/sessions` 존재 시 통합 테스트 2건 추가 실행) |
| `server/PREPROCESS_V1.md` | preprocessing contract 상세 문서 |
| `deploy/server.service` | systemd unit (uvicorn, 127.0.0.1:8000) |
| `deploy/nginx-server.conf` | reverse proxy (대용량 업로드용 body/timeout 설정) |

## Ingestion API (`main.py`)

`POST /sessions`, `Idempotency-Key: <session UUID>` 헤더 필수.

- multipart part 집합이 `metadata.camera_streams` 선언과 정확히 일치해야 함 (ultrawide 여부 포함)
- 각 part의 filename 고정, metadata의 `files` manifest와 **size + SHA-256 전건 대조**
- 모든 CSV의 헤더 문자열 검증
- `/srv/incoming` staging → 검증 통과 후 `/srv/sessions/<id>`로 원자적 rename
- 동일 `session_id` 재업로드: metadata가 byte 단위로 동일하면 `200 duplicate`, 다르면 `409 IDEMPOTENCY_CONFLICT`
- 업로드 중 중복 요청은 `/srv/locks` 디렉터리 락으로 `409 IDEMPOTENCY_IN_PROGRESS`

## Preprocessing (`preprocess.py`)

```bash
cd /home/ubuntu/server
./.venv/bin/python preprocess.py                      # 전체 세션
./.venv/bin/python preprocess.py --session-id <uuid>  # 개별 (반복 지정 가능)
./.venv/bin/python preprocess.py --force ...          # 기존 출력 교체 (staging 후 swap)
```

### 1. 시간 정렬

CSV 카메라 타임스탬프와 MP4 PTS를 각자 첫 샘플 기준으로 rebase해 비교한다. common prefix를 순서 인덱스로 매핑하고, 인코딩된 프레임이 없는 CSV tail row는 제외한다. `frame_number` 컬럼은 프레임 인덱스로 해석하지 않는다. rebase는 cadence만 검증하므로 `timestamp_timebase_verified`는 false로 유지된다.

### 2. Pose validity 판정

다음을 **모두** 만족할 때만 valid:

- `tracking_state ∈ pose_validity.usable_tracking_states`
- `tx, ty, tz` 존재 + finite
- `qx, qy, qz, qw` 존재 + finite
- `abs(||q|| - 1) <= pose_validity.quaternion_norm_tolerance`

**tracking_state가 primary gate다.** 실제 업로드에서 PAUSED/MISSING row는 빈 값이 아니라
`tx=ty=tz=0`, `q=(-2.98e-8, -2.98e-8, -0.7071067, 0.7071067)` 형태의 **norm 1.0짜리 dummy pose**를 담고 있어, 숫자 검증만으로는 통과한다. 반대로 usable state인데 숫자를 읽을 수 없는 row는 `INVALID_TRACKING_POSE`로 기록하고 valid로 취급하지 않는다.

### 3. 정제 순서 (고정)

```
raw episode
  → pose validity 판정
  → start/end invalid run trim
  → short internal gap interpolation
  → long internal gap split
  → segment length 검증
  → 짧은 segment drop
  → usable segment 0개면 episode reject
  → quality / lineage 기록
  → session에 usable segment ≥ 1이면 READY
```

이 순서는 바뀌면 안 된다. split 전에 무조건 trim하거나 threshold를 넘는 gap을 이어붙이면 실제로 존재하지 않은 trajectory가 만들어진다.

**Interpolation**: `interpolate_max_frames` 이하 **그리고** 양 끝 valid pose 사이 간격이 `interpolate_max_gap_ms` 이하일 때만 복구한다. Position은 타임스탬프 기준 linear, rotation은 **shortest-arc SLERP**. quaternion component-wise LERP + normalize는 일반 방식으로 쓰지 않고, SLERP와 수치적으로 같아지는 소각도 fallback에서만 사용한다.

**Split**: 더 긴 tracking loss는 이어붙이지 않고 segment를 끊는다. 구간 내 프레임은 drop되며 `dropped_gap_frames`로 집계된다.

### 4. Interpolation provenance contract

보간된 row의 의미는 다음으로 확정한다:

| 컬럼 | 값 |
|---|---|
| `pose_valid` | `true` |
| `pose_interpolated` | `true` |
| `pose_valid_original` | `false` |
| `tracking_state` | ARCore 원본 보존 (예: `PAUSED`) |

`tracking_state`를 `TRACKING`으로 조작하지 않는다. `tracking_state`는 센서 원본 provenance이고 `pose_interpolated`는 CPU가 복구했는지 여부로, 의미가 다르기 때문이다. 컬럼명은 정확히 `pose_interpolated`.

publish된 `frames.csv`에는 최소 `pose_valid`, `pose_valid_original`, `pose_interpolated`, `tracking_state`가 존재한다.

### 5. Publish gate

`trajectory_quality.min_publish_segment_frames` (source frame 기준) 미만 segment는 publish하지 않는다. 이보다 짧으면 GPU의 `SequenceSampler(action_padding=False)`에서 usable sample이 나오지 않고, GPU validation이 contract error로 처리한다.

config loader가 `ceil(action_horizon × source_hz / policy_hz)`를 계산해 설정값이 그보다 작으면 **기동을 거부한다**. GPU가 reject할 segment를 publish하는 건 실패를 막는 대신 내보내는 것이므로, 조용히 올려 쓰지 않고 시작 시점에 실패시킨다.

### 6. READY

READY는 "preprocessing이 안 죽었다"가 아니다. 다음이 **모두** 충족될 때만 생성한다:

- preprocessing 완료 **AND** validation 완료 **AND** 모든 output file publish 완료
- **AND** training-usable segment가 최소 1개 존재

생성 순서는 항상 `session directory commit → 마지막 operation → READY.touch()`. `_publish_ready()`는 대상 디렉터리에 `session_metadata.json`이 없으면 쓰기를 거부한다.

### 7. Handoff contract

`session_metadata.json`, 각 segment의 `metadata.json`, rejected episode의 `metadata.json`, `validation_report.json` 전부에 기록된다:

```json
"handoff_contract": {
  "version": "omx_processed_v1_posefix_1",
  "source_hz_reference": 30.0,
  "policy_hz_reference": 10.0,
  "action_horizon_reference": 16,
  "min_publish_segment_frames": 48
}
```

CPU는 GPU 설정을 볼 수 없으므로 위 config 검증은 **이쪽이 먼저 움직일 때만** 드리프트를 잡는다. GPU가 action_horizon을 32로 올리고 CPU config가 16인 채로 남으면 CPU는 아무것도 실패하지 않고 옛 contract로 만든 출력을 내보낸다. **GPU inspector/converter가 이 블록과 자기 설정을 대조해 FAIL하는 것이 실제 안전장치다.** segment 단위에도 기록되므로 session 디렉터리와 분리되어 이동해도 자기 출처를 설명할 수 있다. `version`은 숫자 하나가 바뀔 때가 아니라 publish된 출력의 의미가 바뀔 때 올린다.

## Config 레퍼런스 (`preprocess_v1_config.json`)

| 키 | 기본값 | 의미 |
|---|---|---|
| `timestamp_alignment.max_interval_error_ms` | 2.0 | CSV/MP4 구간 간격 오차 한계 |
| `timestamp_alignment.max_relative_error_ms` | 10.0 | 누적 상대 타임라인 오차 한계 |
| `quality_thresholds.*` | — | 잠정 품질 라벨 임계값 (`thresholds_finalized: false`) |
| `pose_validity.usable_tracking_states` | `["TRACKING"]` | pose를 신뢰할 수 있는 ARCore 상태 |
| `pose_validity.quaternion_norm_tolerance` | 0.1 | `abs(‖q‖ - 1)` 허용치 |
| `pose_gap.interpolate_max_frames` | 2 | 보간 가능한 최대 연속 dropout (30 Hz ≈ 67 ms) |
| `pose_gap.interpolate_max_gap_ms` | 100.0 | 보간 가능한 최대 시간 간격 |
| `trajectory_quality.min_publish_segment_frames` | 48 | publish 최소 길이 (CPU/GPU 공유 기준값) |
| `trajectory_quality.source_hz_reference` | 30.0 | 기준 계산용 source rate |
| `trajectory_quality.policy_hz_reference` | 10.0 | 기준 계산용 policy rate |
| `trajectory_quality.action_horizon_reference` | 16 | 기준 계산용 action horizon |
| `calibration.T_camera_EE` | identity | **placeholder — 학습용 EE 라벨 아님** |
| `rgb.jpeg_qscale` | 2 | 추출 JPEG 품질 |

## 테스트

```bash
cd /home/ubuntu/server
./.venv/bin/python -m unittest test_preprocess -v
```

30건. pose validity(PAUSED dummy pose 거부, flag/숫자 불일치), SLERP 정확도 및 최단호, trim/interpolate/split/drop/reject 경계, publish gate 경계(47 drop / 48 keep), contract 미달 config 거부, handoff contract 일관성, 그리고 `/srv/sessions`가 있을 때 실행되는 통합 테스트 2건:

- `test_ready_is_written_last_and_only_after_everything_is_published` — `_commit_directory` / `_publish_ready`를 감싸 각 시점의 디스크 상태를 기록하고, staging 디렉터리에 READY가 없으며 READY 작성 시점에 나머지 출력이 모두 존재함을 검증
- `test_a_session_without_a_usable_segment_gets_no_ready_and_no_episode_layout` — rejected 디렉터리 내용물이 `metadata.json` + `quality.json` 뿐임을 검증

## 설치 / 재현

빈 서버에서의 전체 설치 절차는 **[SETUP.md](SETUP.md)** 참고. 요약하면:

```bash
sudo apt install -y python3-venv ffmpeg nginx
# server/ 를 /home/ubuntu/server 로 복사 후
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
sudo mkdir -p /srv/{incoming,sessions,locks,processed/v1}   # ← main.py가 만들지 않음
sudo chown ubuntu:ubuntu /srv/incoming /srv/sessions /srv/locks /srv/processed/v1
sudo cp deploy/server.service /etc/systemd/system/ && sudo systemctl enable --now server
sudo cp deploy/nginx-server.conf /etc/nginx/sites-available/server
sudo ln -sf /etc/nginx/sites-available/server /etc/nginx/sites-enabled/server
sudo rm -f /etc/nginx/sites-enabled/default                 # ← 기본 사이트 충돌 방지
sudo nginx -t && sudo systemctl reload nginx
```

경로(`/srv`, `/home/ubuntu/server`)는 코드와 systemd unit에 하드코딩돼 있다. 인증은 없다. 상세와 검증 절차는 SETUP.md에 있다.

## 알려진 미확정 사항

- `calibration.T_camera_EE`가 identity placeholder이므로 `T_world_EE`, `T_episode0_EE`, 그리고 여기서 파생된 action은 **파이프라인/인터페이스 검증용이며 calibrated EE 학습 라벨이 아니다** (`calibration_status: placeholder_identity_not_for_training`).
- 업로더가 ARCore SDK 버전을 기록하지 않아, ARCore 1.5 이하의 legacy camera-axis 동작을 배제할 수 없다 (`sdk_version_verified: false`).
- 품질 라벨 임계값은 잠정이다 (`thresholds_finalized: false`).
- `trajectory.npz`의 transform-matrix action은 인터페이스 산출물이며 최종 UMI action contract가 아니다. position/rotation/gripper 인코딩은 GPU contract 확정 대기 중.
- gripper_width는 아직 수집 파이프라인에 없다.
