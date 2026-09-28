# omx_deploy — Jetson에서 격리 실행 (Docker)

젯슨 호스트에는 Docker만 있으면 된다. ROS 2 Humble, 빌드 도구, 의존 패키지는 모두 컨테이너 안에 있고,
워크스페이스(`~/omx_ws`)는 컨테이너에 마운트되어 컨테이너 안에서 빌드된다.
컨테이너 사용자는 호스트 UID/GID와 같아서 생성 파일 소유권 문제가 없다.

```
~/omx_ws/                     (Jetson)
├── docker-compose.yml        control 컨테이너 정의 (policy GPU 컨테이너는 주석으로 준비)
├── omx.sh                    init / up / build / shell / run / down / logs
├── docker/Dockerfile         ros:humble-ros-base + colcon, numpy, robot_state_publisher, usb_cam
├── docker/entrypoint.sh
└── src/
    ├── omx_control/          (rsync)
    ├── omx_teach/            (rsync)
    └── thirdparty/DynamixelSDK/   (rsync, humble 브랜치 소스 빌드)
```

## 젯슨 준비 (1회)

```bash
docker --version && docker compose version
```
- `docker compose`가 없으면 `sudo apt install docker-compose-plugin` (또는 `docker-compose`).
- sudo 없이 쓰려면 `sudo usermod -aG docker $USER` 후 재접속.
- ROBOTIS 컨테이너가 자동 실행 중이면 포트를 점유한다: `docker ps`로 확인 후 `docker stop`.

## 전송 (WSL, 팀 저장소 루트에서)

DynamixelSDK(humble 브랜치)는 저장소에 없어서 따로 받아 둔다. 절차는 [런북](../docs/jetson_runbook.md) 2절.

```bash
ssh <user>@<jetson-ip> "mkdir -p ~/omx_ws/src"
rsync -av jetson/omx_deploy/ <user>@<jetson-ip>:~/omx_ws/
rsync -av --exclude __pycache__ jetson/omx_control jetson/omx_teach <user>@<jetson-ip>:~/omx_ws/src/
rsync -av ~/omx_thirdparty/ <user>@<jetson-ip>:~/omx_ws/src/thirdparty/
```

## 빌드·실행 (Jetson)

```bash
cd ~/omx_ws && chmod +x omx.sh
./omx.sh init          # 이미지 빌드 (첫 회 수 분)
./omx.sh up            # 컨테이너 시작 (/dev/ttyACM0 이 있어야 함)
./omx.sh build         # colcon build --symlink-install  (Orin Nano 2~4분)
./omx.sh shell         # ROS 환경이 잡힌 셸. 터미널마다 하나씩
```

컨테이너 셸 안에서는 [런북](../docs/jetson_runbook.md) 5절 이후의 `ros2 ...` 명령을 그대로 쓴다.

```bash
ros2 launch omx_driver driver.launch.py port:=/dev/ttyACM0
ros2 launch omx_bringup robot.launch.py port:=/dev/ttyACM0 dummy_policy:=true
ros2 launch omx_teach teach.launch.py
```

한 줄 실행: `./omx.sh run ros2 topic hz /joint_states`

## 자주 걸리는 것

- **USB 재연결로 `/dev/ttyACM1`이 되면** 컨테이너가 장치를 잃는다. `./omx.sh down && ./omx.sh up` 하거나, 호스트 udev 규칙(`src/omx_control/omx_driver/udev/99-omx.rules`)으로 이름을 고정하고 compose의 `devices`를 바꾼다.
- **권한**: 호스트에서 `/dev/ttyACM0`이 `root:dialout 0660`이면 컨테이너 사용자가 `dialout`이라 그대로 읽고 쓸 수 있다. 다르면 호스트에서 udev 규칙(MODE 0666) 적용.
- **소스 수정**: 호스트의 `~/omx_ws/src`를 고치면 컨테이너에 바로 보인다. Python·launch·yaml은 재빌드 없이, C++는 `./omx.sh build omx_driver`.
- **기록 파일**: `~/omx_recordings`(호스트) = `/home/omx/omx_recordings`(컨테이너).
- **노트북에서 토픽 보기**: `network_mode: host`라 호스트와 같은 조건. [런북](../docs/jetson_runbook.md) 9절.
- **학습된 정책**: 추론은 ROS 컨테이너 밖 별도 파이썬 환경에서 돌린다(GPU 쪽이 젯슨에서 검증한 방식). 절차는 [런북](../docs/jetson_runbook.md) 10절. `docker-compose.yml`의 `policy` 서비스 주석은 초기 안이며 검증하지 않았다.
