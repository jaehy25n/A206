# 설치 및 재현 가이드

빈 Ubuntu 서버에서 이 리포지토리만으로 CPU 수집/정제 서버를 재현하는 절차.

구현 내용과 contract는 [README.md](README.md), preprocessing 상세는 [server/PREPROCESS_V1.md](server/PREPROCESS_V1.md) 참고.

## 검증 환경

현재 운영 서버 기준. 아래 절차는 이 조합에서 실제로 확인했다.

| 항목 | 버전 |
|---|---|
| OS | Ubuntu (Linux 6.17 aws) |
| Python | 3.12.3 (코드 요구사항은 **3.10+**) |
| ffmpeg / ffprobe | 6.1.1 |
| nginx | 시스템 패키지 |

## 0. 먼저 알아야 할 것 — 하드코딩된 경로

이 코드는 경로를 설정으로 받지 않는다. 그대로 재현하려면 아래 경로를 맞춰야 한다.

| 경로 | 하드코딩 위치 | 비고 |
|---|---|---|
| `/srv/incoming`, `/srv/sessions`, `/srv/locks` | `server/main.py` 상단 `ROOT = Path("/srv")` | **애플리케이션이 생성하지 않음 — 4단계에서 직접 만들어야 함** |
| `/srv/processed/v1` | `server/preprocess.py` CLI 기본값 | `--output-root`로 변경 가능 |
| `/srv/sessions` | `server/preprocess.py` CLI 기본값 | `--sessions-root`로 변경 가능 |
| `/home/ubuntu/server` | `deploy/server.service`의 `WorkingDirectory` / `ExecStart` | 다른 경로에 두려면 unit 파일 수정 |

다른 레이아웃을 쓰려면 `main.py`의 `ROOT`와 systemd unit을 함께 고쳐야 한다.

## 1. 시스템 패키지

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg nginx
```

`ffmpeg`와 `ffprobe`는 `preprocess.py`가 직접 호출한다. 없으면 `PreprocessError: Required executable not found`로 실패한다. ingestion API(`main.py`)는 ffmpeg가 필요 없다.

## 2. 코드 배치

```bash
sudo mkdir -p /home/ubuntu/server
sudo chown ubuntu:ubuntu /home/ubuntu/server
# 리포지토리의 server/ 내용을 /home/ubuntu/server 로 복사
cp -r server/. /home/ubuntu/server/
```

## 3. Python 환경

```bash
cd /home/ubuntu/server
python3 -m venv .venv
./.venv/bin/pip install -r /path/to/repo/requirements.txt
```

`requirements.txt`는 운영 서버의 `pip freeze` 결과이며 전이 의존성까지 핀으로 고정돼 있다. 직접 의존성은 `fastapi`, `uvicorn`, `python-multipart` 세 개뿐이고 나머지는 그 의존성이다.

`preprocess.py`는 **표준 라이브러리만** 사용한다 (NumPy·pandas·PyArrow 불필요). venv는 ingestion API를 위한 것이고, preprocessing은 시스템 python3로도 동작한다.

## 4. `/srv` 런타임 디렉터리 생성 ⚠️

**`main.py`는 이 디렉터리들을 만들지 않는다.** 없는 상태로 업로드가 들어오면 `/srv/incoming`에 staging 디렉터리를 만들려다 실패한다. 반드시 미리 만들어야 한다.

```bash
sudo mkdir -p /srv/incoming /srv/sessions /srv/locks /srv/processed/v1
sudo chown ubuntu:ubuntu /srv/incoming /srv/sessions /srv/locks /srv/processed/v1
```

운영 서버의 실제 소유권/권한:

```
drwxr-xr-x root:root      /srv
drwxr-xr-x ubuntu:ubuntu  /srv/incoming
drwxr-xr-x ubuntu:ubuntu  /srv/sessions
drwxr-xr-x ubuntu:ubuntu  /srv/locks
drwxr-xr-x root:root      /srv/processed
drwxr-xr-x ubuntu:ubuntu  /srv/processed/v1
```

`/srv`와 `/srv/processed`만 root 소유이고, 실제로 쓰기가 일어나는 네 디렉터리는 서비스 계정(`ubuntu`) 소유여야 한다. systemd unit의 `User=`/`Group=`과 일치해야 한다.

`/srv/incoming`은 업로드 staging이고 `/srv/sessions`와 **같은 파일시스템**에 있어야 한다. 검증 통과 후 `rename()`으로 원자적 이동을 하기 때문에, 다른 마운트에 두면 `EXDEV`로 실패한다.

## 5. systemd

```bash
sudo cp deploy/server.service /etc/systemd/system/server.service
sudo systemctl daemon-reload
sudo systemctl enable --now server
systemctl status server
```

uvicorn을 `127.0.0.1:8000`에 바인드한다. 외부 노출은 nginx가 담당한다.

## 6. nginx

```bash
sudo cp deploy/nginx-server.conf /etc/nginx/sites-available/server
sudo ln -sf /etc/nginx/sites-available/server /etc/nginx/sites-enabled/server
sudo rm -f /etc/nginx/sites-enabled/default      # ← 기본 사이트 비활성화 필요
sudo nginx -t && sudo systemctl reload nginx
```

**기본 사이트를 반드시 비활성화해야 한다.** Ubuntu 기본 설치의 `default`는 `listen 80 default_server`를 잡고 있어서, `server_name _`인 이 설정과 충돌해 업로드가 기본 사이트로 가버린다. 운영 서버에서도 `sites-enabled`에는 `server`만 있다.

설정에서 중요한 값:

| 항목 | 값 | 이유 |
|---|---|---|
| `client_max_body_size` | 20G | 세션 번들이 MP4를 포함해 수 GB |
| `client_body_timeout`, `proxy_read/send_timeout` | 3600s | 모바일 회선 대용량 업로드 |
| `proxy_request_buffering` | off | nginx가 전체를 디스크에 버퍼링하지 않고 스트리밍 |

## 7. 설치 검증

### 7-1. health

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","service":"ingestion"}
```

### 7-2. 업로드 end-to-end

기존 세션 파일을 재활용해 새 `session_id`로 넣어보는 것이 가장 확실하다. 원본 raw 세션은 건드리지 않는다.

```bash
S=/srv/sessions/<기존_session_id>
NEW=$(python3 -c "import uuid;print(uuid.uuid4())")
python3 -c "
import json; m=json.load(open('$S/metadata.json')); m['session_id']='$NEW'
open('/tmp/smoke_metadata.json','w').write(json.dumps(m))"

curl -s -w ' HTTP %{http_code}\n' -X POST http://127.0.0.1:8000/sessions \
  -H "Idempotency-Key: $NEW" \
  -F "metadata=@/tmp/smoke_metadata.json;filename=metadata.json" \
  -F "main_video=@$S/main_rgb.mp4;filename=main_rgb.mp4" \
  -F "main_frame_timestamps=@$S/main_frame_timestamps.csv;filename=main_frame_timestamps.csv" \
  -F "arcore_poses=@$S/arcore_poses.csv;filename=arcore_poses.csv" \
  -F "episodes=@$S/episodes.csv;filename=episodes.csv" \
  -F "accelerometer=@$S/accelerometer.csv;filename=accelerometer.csv" \
  -F "gyroscope=@$S/gyroscope.csv;filename=gyroscope.csv" \
  -F "rotation_vector=@$S/rotation_vector.csv;filename=rotation_vector.csv"
```

기대 결과:

- 최초 요청 → `HTTP 201`, `{"result":"created"}`
- 동일 요청 반복 → `HTTP 200`, `{"result":"duplicate"}` (metadata byte 동일 시 멱등)
- `/srv/sessions/$NEW/`에 8개 파일 생성
- `/srv/incoming`, `/srv/locks`는 다시 비어 있어야 함 (staging·락 정리 확인)

검증 후 정리: `rm -rf /srv/sessions/$NEW`

metadata의 `session_id`가 `Idempotency-Key`와 다르면 `409`, manifest의 size/SHA-256이 안 맞으면 `422`가 나오는 것도 정상 동작이다.

### 7-3. preprocessing

```bash
cd /home/ubuntu/server
./.venv/bin/python -m unittest test_preprocess            # 30 tests
./.venv/bin/python preprocess.py --session-id <uuid>      # 한 세션만
```

`/srv/sessions`가 있으면 통합 테스트 2건이 함께 돌고, 없으면 자동 skip된다.

성공 시 `/srv/processed/v1/<session_id>/`에 `episode_*`와 `READY`가 생긴다. `READY`가 없으면 usable segment가 0개라는 뜻이며, `rejected_episode_*/quality.json`의 `reject_reason`에 이유가 남는다.

## 8. 운영

```bash
sudo systemctl restart server          # API 재시작
journalctl -u server -f                # API 로그
sudo journalctl -u nginx -f            # 프록시 로그

cd /home/ubuntu/server
./.venv/bin/python preprocess.py                       # 전체 세션 처리
./.venv/bin/python preprocess.py --force --session-id <uuid>   # 기존 출력 교체
```

`preprocess.py`는 서비스가 아니라 수동/배치 실행이다. 기존 출력이 있으면 `--force` 없이는 건드리지 않고, `--force`도 staging 후 원자적 swap이라 중간 상태가 publish되지 않는다.

GPU 측은 `/srv/processed/v1/<session>/READY`가 있는 세션만 가져간다. **rsync는 삭제를 전파하지 않으므로**, CPU에서 READY가 사라진 세션(재처리 후 reject된 경우)은 GPU에서 직접 제거해야 한다.

## 9. 알려진 제약

- **인증 없음.** `POST /sessions`에 인증이 없고 nginx도 80포트 평문이다. 보안 경계는 네트워크 레벨(보안그룹/VPC)에 의존한다. 공개망에 노출하려면 TLS와 인증을 앞단에 추가해야 한다.
- **경로 하드코딩.** 0단계 표 참고.
- **`/srv` 디렉터리 자동 생성 없음.** 4단계를 건너뛰면 첫 업로드에서 실패한다. 애플리케이션이 시작 시 생성하도록 고칠 수도 있으나, 현재 구현은 인프라 준비를 전제한다.
- **디스크.** raw 세션과 processed 산출물이 모두 `/srv`에 쌓인다. processed 쪽은 episode별 JPEG를 복사하므로 원본 MP4보다 커질 수 있다.
- **ARCore SDK 버전 미기록.** 업로더가 기록하지 않아 legacy camera-axis 동작을 배제할 수 없다 (README의 "알려진 미확정 사항" 참고).
