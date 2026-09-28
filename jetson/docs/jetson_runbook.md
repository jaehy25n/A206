# Jetson 실물 실행 런북 — Docker 격리 (OMX-F, 2026-09-23)

대상: Jetson Orin Nano `<jetson-ip>` (ssh, 비밀번호). OMX-F가 USB로 연결됨.
코드: 팀 저장소 `S15P21A206`의 `jetson/` — `omx_control`, `omx_teach`, 배포 파일 `omx_deploy`. WSL 명령은 저장소 루트에서 실행한다.
젯슨 호스트에는 **Docker만** 필요하다. ROS 2 Humble과 모든 의존성은 컨테이너 안에 있고, 워크스페이스는 컨테이너에 마운트되어 그 안에서 빌드된다.

> 실행 위치 (프롬프트로 구분)
> | 프롬프트 | 위치 | 절 |
> |---|---|---|
> | `<user>@<pc>:$` | WSL | 2절(rsync 전송) |
> | `<user>@<jetson>:~$` | 젯슨 호스트 (ssh 직후, 컨테이너 밖) | 1, 3, 4절 |
> | `omx@<jetson>:/ws$` | 컨테이너 (`./omx.sh shell`) | 5절 이후 모든 `ros2` 명령 |

> 안전 원칙 세 가지
> 1. 토크가 꺼지면 팔이 그대로 떨어진다. 토크를 끄는 명령(IDLE, e_stop, set_torque false) 전에는 팔을 잡거나 받칠 것.
> 2. 영점·방향을 확인하기 전에는 HOME/POLICY를 켜지 말 것. 부호가 틀리면 반대로 움직여 리밋을 친다.
> 3. 12 V 전원 스위치(또는 플러그)를 손 닿는 곳에. 소프트웨어 e_stop보다 확실하다.

---

## 1. Jetson 상태 확인 — 젯슨 호스트

```bash
ssh <user>@<jetson-ip>
```
```bash
lsb_release -rs; cat /etc/nv_tegra_release | head -1; docker --version; docker compose version
```
- Docker 컨테이너 안에서 Humble을 돌리므로 호스트 Ubuntu 버전은 20.04/22.04 어느 쪽이든 된다. `docker compose`가 없으면 `sudo apt install docker-compose-plugin`.
- sudo 없이 docker를 쓰려면 `sudo usermod -aG docker $USER` 후 재접속.

```bash
ls -l /dev/ttyACM* /dev/video* 2>/dev/null; lsusb; docker ps
```
- OMX-F가 `/dev/ttyACM0`으로 보여야 한다. 안 보이면 케이블·전원 확인, `dmesg | tail`.
- `docker ps`에 ROBOTIS 컨테이너가 떠 있으면 포트를 점유한다. `docker stop <이름>`.

## 2. 코드 전송 (WSL 터미널, 팀 저장소 루트에서)

DynamixelSDK는 저장소에 없다. 처음 한 번 humble 브랜치를 받아 둔다(이미 있으면 생략).

```bash
git clone -b humble https://github.com/ROBOTIS-GIT/DynamixelSDK.git ~/omx_thirdparty/DynamixelSDK
```
```bash
ssh <user>@<jetson-ip> "mkdir -p ~/omx_ws/src"
```
```bash
rsync -av jetson/omx_deploy/ <user>@<jetson-ip>:~/omx_ws/
```
```bash
rsync -av --exclude __pycache__ jetson/omx_control jetson/omx_teach <user>@<jetson-ip>:~/omx_ws/src/
rsync -av ~/omx_thirdparty/ <user>@<jetson-ip>:~/omx_ws/src/thirdparty/
```
결과 레이아웃(Jetson): `~/omx_ws/{docker-compose.yml, omx.sh, docker/, src/{omx_control, omx_teach, thirdparty}}`.
rsync가 없으면 `scp -r`로 같은 경로에.

## 3. 이미지 빌드 · 컨테이너 시작 · 워크스페이스 빌드 — 젯슨 호스트

```bash
cd ~/omx_ws && chmod +x omx.sh docker/entrypoint.sh && ./omx.sh init
```
- `.env`에 호스트 UID/GID를 쓰고 `~/omx_recordings`를 만들고 이미지를 빌드한다. 첫 회 수 분(arm64 apt 다운로드).
```bash
./omx.sh up
```
- `/dev/ttyACM0`이 없으면 시작에 실패한다. 장치명이 다르면 `docker-compose.yml`의 `devices`를 고친다.
```bash
./omx.sh build
```
- 컨테이너 안에서 `colcon build --symlink-install`. Orin Nano 2~4분. 산출물 `build/ install/`은 호스트 `~/omx_ws`에 호스트 사용자 소유로 남는다.
```bash
./omx.sh shell
```
- ROS와 워크스페이스가 소스된 셸. **이후 모든 `ros2` 명령은 이 셸 안에서** 실행한다. 터미널이 더 필요하면 ssh를 하나 더 열고 같은 명령.
- 한 줄만 실행할 때: `./omx.sh run ros2 topic hz /joint_states`

## 4. USB 권한 — 젯슨 호스트 (컨테이너 밖). 필요할 때만

먼저 컨테이너 셸에서 확인:
```bash
ls -l /dev/ttyACM0
```
- `crw-rw---- root dialout`이면 컨테이너 사용자가 `dialout`(gid 20)이라 그대로 5절로. 이 절은 건너뛴다.
- 5절에서 `failed to open /dev/ttyACM0`가 나올 때만, **젯슨 호스트 셸**(`exit`로 컨테이너를 나가거나 ssh를 하나 더)에서 udev 규칙(MODE 0666, 고정 이름 `/dev/omx_arm`)을 적용한다. `udevadm`은 호스트에만 있다.
```bash
udevadm info -a -n /dev/ttyACM0 | grep -E 'idVendor|idProduct' | head -2
```
  값을 `~/omx_ws/src/omx_control/omx_driver/udev/99-omx.rules`의 XXXX에 넣고
```bash
sudo cp ~/omx_ws/src/omx_control/omx_driver/udev/99-omx.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger
```
- USB를 다시 꽂아 `/dev/ttyACM1`이 되면 컨테이너가 장치를 잃는다: `./omx.sh down && ./omx.sh up`.

## 5. 드라이버 단독 검증 — 토크 OFF (가장 중요) — 컨테이너 셸

컨테이너 셸 A:
```bash
ros2 launch omx_driver driver.launch.py port:=/dev/ttyACM0
```
- 기대 로그: `bus 'dynamixel_sdk' ready (/dev/ttyACM0 @ 1000000), 6 joints, loop 100 Hz`. 토크는 꺼진 상태(`torque_on_start: false`).
- `ping failed`면 ID(11~16)·baud(1 Mbps)·전원 확인. ROBOTIS 설정 그대로면 통과한다. `failed to open`이면 4절 권한.

컨테이너 셸 B:
```bash
ros2 topic hz /joint_states
```
- 100 Hz 근처여야 한다. 80 미만이면 USB 문제.
```bash
ros2 topic echo /joint_states --field position
```

팔을 손으로 움직이며 아래 표대로 부호와 영점을 확인한다. 값은 rad.

| 관절 | 확인 자세 / 동작 | 기대값 |
|---|---|---|
| joint1 | 팔을 로봇 기준 왼쪽(+y)으로 돌림 | 값 증가 |
| joint2 | 팔을 앞으로 수평하게 뻗음 | ≈ 0. 팔끝을 아래로 숙이면 값 증가 |
| joint3 | 팔 전체 일직선(수평) | ≈ 0. 아래로 접으면 값 증가 |
| joint4 | 손목 일직선 | ≈ 0. 아래로 숙이면 값 증가 |
| joint5 | 그리퍼 정방향 | ≈ 0. 뒤(베이스)에서 그리퍼를 바라볼 때 시계 방향 회전이 증가 |
| gripper_joint_1 | 닫힘 | ≈ 0. 벌리면 증가, 완전히 벌려 약 1.7 |

- 어긋나는 것을 호스트의 `~/omx_ws/src/omx_control/omx_driver/config/omx_f_driver.yaml`에 반영한다(컨테이너에 바로 보인다, 재빌드 불필요, 런치만 재시작).
  - 부호 반대: `direction`의 해당 항목을 `-1`.
  - 영점 오차 e[rad]: `zero_ticks`의 해당 항목에 `e × 652`(= 4096/2π) 만큼 더하거나 뺀다. 수정 후 다시 확인해 0이 되는지 본다.
  - 그리퍼 완전 개방값이 1.745와 다르면 `omx_bringup/config/joint_limits.yaml`의 `gripper_open_rad`를 고친다. 그 자세에서 턱 사이를 자로 재 `gripper_open_width_m`[m]에 넣는다(지금 값 0.0516은 GPU 시뮬레이터 값이라 실측으로 바꿔야 정책의 그리퍼 폭과 맞는다).
- 각 관절을 기계적 끝까지 살짝 밀어 값을 기록하고, 여유를 두고 `joint_limits.yaml`의 `lower/upper_limits_rad`를 갱신한다(URDF와 같은 값으로).

```bash
ros2 topic echo --once /dxl_driver/status
```
- 모터별 온도·전압·`hardware_error`가 0인지 확인.

## 6. 토크 ON, 단일 관절 미세 명령 — 컨테이너 셸

팔이 지지된 자세(예: 접힌 자세)에서:
```bash
ros2 service call /dxl_driver/set_torque std_srvs/srv/SetBool "{data: true}"
```
- 팔이 현재 자세를 그대로 유지해야 한다. 튀거나 떨리면 즉시 `{data: false}`.

현재 joint1 값에 0.1 rad만 더한 값으로(예시 0.10):
```bash
ros2 topic pub -r 20 /joint_command sensor_msgs/msg/JointState "{name: [joint1], position: [0.10]}"
```
- 베이스가 왼쪽으로 약 6° 돌아 멈추면 부호·영점이 맞은 것. Ctrl+C로 발행을 끊으면 200 ms 뒤 `holding position` 경고와 함께 그 자리에 멈춘다(정상).
- 다른 관절도 같은 방식으로 ±0.1 rad씩 확인.
```bash
ros2 service call /dxl_driver/set_torque std_srvs/srv/SetBool "{data: false}"
```
(팔을 받친 상태에서.) 셸 A 종료.

## 7. 전체 스택 — 컨테이너 셸 (파일 수정은 젯슨 호스트의 `~/omx_ws/src/...`, 컨테이너에 바로 보임)

첫 실물 실행 전 권장 설정 두 가지(선택):
- `omx_driver/config/omx_f_driver.yaml`의 `max_velocity_rad_s`를 `1.5 → 0.5`.
- e_stop 시 팔이 떨어지는 대신 그 자리에 멈추게: `omx_bringup/config/joint_limits.yaml`의 `ros__parameters:` 아래에 `estop_torque_off: false` 추가(`/**` 와일드카드라 mode_manager가 읽는다).

셸 A:
```bash
ros2 launch omx_bringup robot.launch.py port:=/dev/ttyACM0 dummy_policy:=true
```
- IDLE(토크 OFF)로 시작. 팔을 접힌 자세로 받쳐둘 것.

셸 B:
```bash
ros2 topic echo /mode_state
```

셸 C — 팔 주변을 비운 뒤 HOME(ROBOTIS 접힌 자세 [0, −1.57, 1.57, 1.57, 0], 4초 보간):
```bash
ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: HOME}"
```
- 이상하면 즉시:
```bash
ros2 topic pub -1 /e_stop std_msgs/msg/Bool "{data: true}"
```

### 7a. 직접 교시 & 재현 (omx_teach)
셸 D:
```bash
ros2 launch omx_teach teach.launch.py
```
팔을 잡은 상태에서(토크가 꺼진다):
```bash
ros2 run omx_teach teach record demo1
```
시연 후:
```bash
ros2 run omx_teach teach stop
```
팔을 안전한 자세로 두고, 주변을 비운 뒤 느리게 재생:
```bash
ros2 run omx_teach teach play demo1 --speed 0.3 --approach 4
```
- TELEOP 전환 → 4초간 첫 자세로 이동 → 0.3배속 재생 → 마지막 자세 유지. 중단은 `ros2 run omx_teach teach abort`.
- 기록은 호스트 `~/omx_recordings/demo1.csv`, `demo1_ee.csv`.

### 7b. 더미 policy (pick 스크립트)
기본 `time_scale` 2.0(절반 속도). 작업공간에 물체 없이 먼저:
```bash
ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: POLICY}"
```
```bash
ros2 topic pub -1 /task_cmd std_msgs/msg/String "{data: start}"
```
- 경로: (0.20, 0, 0.18) 위 → (0.22, 0, 0.10) 하강·집기 → 들기 → (0.16, 0.12, 0.18) 이동·놓기. 베이스 앞 22 cm, 좌측 12 cm 안에 장애물이 없어야 한다.
- 끝나면 `/mode_cmd HOME` 또는 팔을 받친 뒤 `IDLE`.

## 7c. 재현이 교시보다 낮게 움직일 때 — 중력 처짐 튜닝 (컨테이너 셸)

원인: 교시는 토크 OFF에서 사람이 받친 각도를 기록하고, 재현은 모터가 P 게인만으로 중력을 버티므로 pitch 관절이 목표보다 1~2° 아래에서 멈춘다. P만 있을 때 팔은 기어 마찰에 "얹혀" 있어 joint2 PWM이 20 %대로 낮다.

**I 게인은 쓰지 않는다.** 적분기가 오차를 0으로 밀면 모터가 중력 전체를 능동적으로 떠안아 joint2 PWM이 56 %로 올라가고, XL430 과부하 보호가 토크를 끊는다(실측). 대신 **피드포워드 오프셋**으로 처짐만큼 미리 높게 명령한다.

1. 드라이버 yaml의 `goal_offset_rad`를 전부 0으로 두고(측정용), `position_p_gains`는 joint2~4 2000, `position_i_gains`는 전부 0.
2. TELEOP(또는 HOME)으로 **작업 자세**(정자세, 리치 0.2~0.25 m)에 세워 둔 채 오차를 본다. 값은 명령 − 실제 [rad]. 처짐이면 joint2~4가 일정한 음수(예: −0.023, −0.015, −0.009). 최대로 뻗은 자세에서 재지 말 것(과부하).
```bash
ros2 topic echo /dxl_driver/tracking_error --field position
```
3. 그 값을 **그대로** `goal_offset_rad`에 넣고 드라이버를 재시작한다. 현재 yaml에는 2026-09-23 정자세 측정값 `[0, -0.023, -0.015, -0.009, 0, 0]`이 들어 있다.
4. 같은 자세에서 다시 보면 오차가 0 근처, `/dxl_driver/motor_state`의 joint2 `pwm_percent`는 여전히 20 %대여야 한다. 45 %를 넘으면 위험.
5. 잔여 오차가 자세에 따라 ±0.5° 남는 것은 상수 오프셋의 한계(처짐이 하중에 비례). 다음 단계는 모델 보상이다.

**모델 보상(스펙 기반 중력 모델 + 식별).** 드라이버가 URDF 질량으로 joint2~4의 중력 토크 τ를 계산해 `offset_j = goal_offset_j − compliance_j × τ_j`를 적용한다. `/dxl_driver/motor_state`의 `gravity_nm`, `offset_rad`로 확인할 수 있다.
1. 웹캠+마운트를 저울로 재서 yaml의 `payload_mass_kg`에 넣는다(kg). 위치 `payload_offset_xyz`는 link5(joint5) 기준 기본값 [0.015, 0, 0.04] = joint5 모터와 그리퍼 모터 사이, 링크 위 4 cm. 실제 위치가 다르면 고친다.
2. 작업 영역 안의 자세 4~5개(리치 0.15~0.30 m, pitch 30~70°)를 각 5초씩 멈추며 지나가는 교시를 하나 기록한다(`teach record sagcal`). 최대 뻗기는 넣지 않는다.
3. 재현하면서 동시에 식별 도구를 돌린다. 도구는 정지 구간만 골라 관절별로 `sag = a + b·τ`를 최소자승으로 맞춘다.
```bash
ros2 run omx_teach teach play sagcal --speed 0.5
```
```bash
ros2 run omx_driver fit_sag.py --duration 90 --csv /home/omx/omx_recordings/sag_samples.csv
```
4. 출력된 `goal_offset_rad`(= a)와 `sag_compliance_rad_per_nm`(= b) 두 줄을 yaml에 붙이고 드라이버를 재시작한다. 이미 들어 있는 보정값은 도구가 `offset_rad`로 읽어 반영하므로 몇 번 반복해도 된다.
5. 같은 재현을 다시 돌려 `tracking_error`가 전 구간에서 ±0.2° 안에 들어오는지, joint2 `pwm_percent`가 여전히 20~30 %대인지 확인한다. P 게인을 바꾸면 compliance가 달라지니 다시 식별한다.

## 7e. 중력 처짐 식별 — 실제 작업 순서 (약 10분)

셸 위치: WSL = `<user>@<pc>`, 젯슨 호스트 = `<user>@<jetson>:~/omx_ws`, 컨테이너 = `omx@<jetson>:/ws`.

**0. 코드 반영**
- 젯슨의 드라이버 yaml을 직접 고친 게 있으면(zero_ticks, direction, 리밋) 먼저 백업: 젯슨 호스트에서 `cp ~/omx_ws/src/omx_control/omx_driver/config/omx_f_driver.yaml ~/omx_f_driver.backup.yaml`. rsync가 덮어쓴다.
- WSL(저장소 루트):
```bash
rsync -av jetson/omx_deploy/ <user>@<jetson-ip>:~/omx_ws/ && rsync -av --exclude __pycache__ jetson/omx_control <user>@<jetson-ip>:~/omx_ws/src/
```
- 젯슨 호스트(메시지가 바뀌어 전체 빌드, 2~4분):
```bash
cd ~/omx_ws && ./omx.sh build
```
- 백업했던 zero_ticks/direction/리밋 값을 새 yaml에 다시 적는다.

**1. payload 입력** — 젯슨 호스트에서 `nano ~/omx_ws/src/omx_control/omx_driver/config/omx_f_driver.yaml`
- 웹캠+마운트+케이블 토막을 저울로 재서 `payload_mass_kg`에 kg으로(예: 68 g → 0.068).
- `payload_offset_xyz`: joint5(손목 롤 모터) 축에서 그리퍼 방향으로 x, 위로 z [m]. 기본 [0.015, 0.0, 0.04]. 대충 맞으면 그대로.
- 확인: `position_i_gains` 전부 0, `sag_compliance_rad_per_nm` 전부 0(첫 식별), `goal_offset_rad`는 현재값 그대로 둬도 된다(도구가 되돌려 계산).

**2. 스택 기동** — 컨테이너 셸 A. 팔은 접힌 자세로 받쳐둔 상태.
```bash
ros2 launch omx_bringup robot.launch.py port:=/dev/ttyACM0
```
컨테이너 셸 B: 주변 비우고 HOME(4초 보간) → 도착 후 TELEOP(토크 유지, `/teleop/joint_command` 중계).
```bash
ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: HOME}"
```
```bash
ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: TELEOP}"
```

**3. 식별 도구 시작** — 컨테이너 셸 C. 5초마다 `stationary samples` 수가 늘어나야 정상.
```bash
ros2 run omx_driver fit_sag.py --duration 150 --csv /home/omx/omx_recordings/sag_samples.csv
```

**4. 자세 5개를 각 12초씩** — 셸 B에서 순서대로. 명령이 끊기면(12초 후) 드라이버가 그 자리에서 hold한다. 팔이 웅웅거리거나 이상하면 `ros2 topic pub -1 /e_stop std_msgs/msg/Bool "{data: true}"`.
```bash
timeout 12 ros2 topic pub -r 20 /teleop/joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2, joint3, joint4, joint5, gripper_joint_1], position: [0.0, -0.5708, 0.3256, 1.2925, 0.0, 1.0]}"
```
```bash
timeout 12 ros2 topic pub -r 20 /teleop/joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2, joint3, joint4, joint5, gripper_joint_1], position: [0.0, -0.5233, 0.0829, 1.2257, 0.0, 1.0]}"
```
```bash
timeout 12 ros2 topic pub -r 20 /teleop/joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2, joint3, joint4, joint5, gripper_joint_1], position: [0.0, -0.4584, 0.6574, 0.5863, 0.0, 1.0]}"
```
```bash
timeout 12 ros2 topic pub -r 20 /teleop/joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2, joint3, joint4, joint5, gripper_joint_1], position: [0.0, -0.1132, 0.3265, 0.3103, 0.0, 1.0]}"
```
```bash
timeout 12 ros2 topic pub -r 20 /teleop/joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2, joint3, joint4, joint5, gripper_joint_1], position: [0.0, -0.6992, 0.8072, 1.1138, 0.0, 1.0]}"
```
| 자세 | TCP (x, z) | pitch | 리치 |
|---|---|---|---|
| A ready | 0.18, 0.15 | 60° | 0.19 m |
| B 중간 높이 | 0.20, 0.20 | 45° | 0.21 m |
| C 중간 낮이 | 0.22, 0.10 | 45° | 0.23 m |
| D 멀리 | 0.28, 0.12 | 30° | 0.29 m |
| E 가까이 급경사 | 0.15, 0.08 | 70° | 0.16 m |

마지막 자세 뒤 셸 C에서 Ctrl+C(또는 150초 대기) → 관절별 표와 yaml 두 줄이 출력된다.

**5. 값 붙이기와 재시작**
- 출력된 `goal_offset_rad`, `sag_compliance_rad_per_nm` 두 줄로 yaml의 해당 줄을 교체. 정상 범위: joint2~4 compliance 양수 0.02~0.10, offset 절대값 0.02 이하. compliance가 음수면 payload 값이나 자세 범위 문제 → 결과 표를 보낼 것.
- 재시작 전 팔을 내려놓기: 셸 B에서 `{data: HOME}` → 도착 후 `{data: IDLE}`(토크 OFF, 접힌 자세로 쉼) → 셸 A Ctrl+C → 다시 `ros2 launch ...`.

**6. 검증** — 2~4단계를 반복하되 셸 C에서는 오차와 PWM을 본다.
```bash
ros2 topic echo /dxl_driver/tracking_error --field position
```
```bash
ros2 topic echo /dxl_driver/motor_state --field pwm_percent
```
- 다섯 자세 모두 joint2~4 오차 ±0.0035 rad(±0.2°) 안, joint2 PWM 35 % 이하이면 성공. 그 뒤 교시 재현으로 높이가 맞는지 확인.

## 7d. 모터 진단 도구 (컨테이너 셸)

두 층으로 나뉜다. 시리얼 포트는 한 프로세스만 쓸 수 있어서, 드라이버가 켜져 있으면 토픽으로, 꺼져 있으면 독립 스크립트로 본다.

**스택이 돌아가는 중** — 드라이버가 10 Hz로 모터별 텔레메트리를 낸다.
```bash
ros2 topic echo /dxl_driver/motor_state
```
- `pwm_percent`: 모터가 얼마나 세게 밀고 있는지(±100). 80 % 넘게 몇 초 유지되면 과부하 셧다운 직전.
- `error_deg`: 목표 − 실제. 처짐 진단용.
- `temperature_c`, `voltage_v`(1 Hz 갱신), `hardware_error_text`: 알람 원인.
- 특정 필드만: `--field pwm_percent`, `--field hardware_error_text`.

**드라이버를 끈 상태** — 설정(EEPROM)까지 전부 읽는다. 드라이버가 켜져 있으면 스크립트가 거부한다.
```bash
ros2 run omx_driver dxl_diag.py
```
- 모터별로 baud, drive/operating mode, 전압·온도 리밋, PWM 리밋, 위치 리밋, shutdown 마스크, PID 게인, 프로파일, 토크, 알람, PWM, 부하, 위치, 전압, 온도가 한 번에 나온다.
```bash
ros2 run omx_driver dxl_diag.py --watch 0.5 --csv /home/omx/omx_recordings/hold_test.csv
```
- 0.5초마다 표로 갱신하며 CSV로 남긴다. 유지 테스트 중 PWM과 온도가 어떻게 올라가 죽는지 기록할 때 쓴다. `pwm high Ns -> overload risk` 표시가 붙는다.
```bash
ros2 run omx_driver dxl_diag.py --reboot 12
```
- 특정 모터만 재부팅(알람 해제, 토크 OFF). 팔을 받친 뒤 실행.

**유지 테스트를 안전하게 기록하는 순서**: 드라이버로 자세를 잡고 토크 ON → 드라이버 종료(토크는 모터에 남는다) → `dxl_diag.py --watch 0.5 --csv ...` → 죽는 순간까지 PWM·온도·에러 비트가 CSV에 남는다.

## 8. 문제 대응

| 증상 | 조치 |
|---|---|
| `./omx.sh up` 실패: device not found | `/dev/ttyACM0` 확인, compose `devices` 수정 |
| `failed to open /dev/ttyACM0` | 호스트 권한(4절), 다른 프로세스/컨테이너 점유 |
| `ping failed` | 전원 12 V, USB, ID/baud, ROBOTIS 컨테이너 |
| `read failed` 반복 | 케이블, 점유, `ros2 topic hz`로 주기 확인 |
| 관절이 갑자기 힘이 빠짐(퍼짐), 드라이버 로그 `ALARM SHUTDOWN` | 모터 알람 셧다운. `/dxl_driver/status`의 해당 관절 `hardware_error_text`(Overload/Overheating/InputVoltage)와 온도·전압 확인. **팔을 받친 뒤** `ros2 service call /dxl_driver/reboot std_srvs/srv/Trigger`(전체 재부팅, 토크 OFF). joint2 과부하는 팔을 멀리 뻗은 정지 자세에서 흔함: 리치 0.3 m 안에서 작업, joint2의 I 게인 0~50, 웹캠 무게 확인 |
| 관절이 리밋에서 멈춤 | 드라이버 클램프 동작. `joint_limits.yaml` 확인 |
| HOME이 이상한 방향으로 | 5절 부호·영점 재확인. 즉시 e_stop |
| mode가 STOP으로 튐 (`policy heartbeat lost`) | 더미 heartbeat 4 Hz 대비 timeout 300 ms가 빡빡함. 메모 10절 |
| 소스 수정 반영 | Python·launch·yaml은 재시작만, C++는 `./omx.sh build omx_driver` |

## 9. 노트북(WSL)에서 RViz로 보기 — 선택

컨테이너가 `network_mode: host`라 젯슨 호스트에서 직접 돌리는 것과 같은 조건이다. WSL2 기본 NAT에서는 Jetson이 WSL 쪽으로 데이터를 보낼 수 없어 Discovery Server만으로는 부족하다.
1. 젯슨에 모니터를 붙이고 컨테이너에서 RViz: compose의 X11 주석(`/tmp/.X11-unix`, `DISPLAY`)을 풀고 호스트에서 `xhost +local:`, 컨테이너에 `sudo apt install ros-humble-rviz2`, `ros2 launch omx_bringup robot.launch.py rviz:=true`.
2. Windows 11 WSL2 mirrored 네트워킹(`%USERPROFILE%\.wslconfig`에 `[wsl2]` `networkingMode=mirrored`, `wsl --shutdown`) + Jetson에서 `fastdds discovery -i 0 -l 0.0.0.0 -p 11811` + 양쪽에 `export ROS_DISCOVERY_SERVER=<jetson-ip>:11811`(노드 시작 전에, `ros2 daemon stop`).

우선은 ssh 셸의 `ros2 topic echo`로 충분하다.

## 11. 루트 디스크 꽉 찼을 때 — Docker와 워크스페이스를 NVMe로 이동 (젯슨 호스트)

상황: `/dev/mmcblk0p1` 27 GB 99 %, `/mnt/nvme` 198 GB 여유.

**1. 무엇이 큰지 확인**
```bash
sudo du -xh -d1 / 2>/dev/null | sort -h | tail -8; echo; docker system df
```

**2. NVMe가 부팅 때 자동 마운트되는지 확인** (아니면 Docker가 부팅 후 저장소를 못 찾는다)
```bash
grep -E 'nvme|/mnt/nvme' /etc/fstab || echo "fstab에 없음"
```
- 없으면: `blkid /dev/nvme0n1p1`로 UUID를 얻어 `/etc/fstab`에 `UUID=<uuid>  /mnt/nvme  ext4  defaults,nofail  0 2` 한 줄 추가. (파일시스템 종류는 `lsblk -f`로 확인)

**3. 컨테이너와 Docker 정지**
```bash
cd ~/omx_ws && ./omx.sh down; docker ps -q | xargs -r docker stop; sudo systemctl stop docker docker.socket
```

**4. Docker 저장소 이동**
```bash
sudo rsync -aHAX --info=progress2 /var/lib/docker/ /mnt/nvme/docker/
```
`/etc/docker/daemon.json`에 `data-root`를 추가한다. 젯슨에는 이미 nvidia 런타임 설정이 들어 있으니 **덮어쓰지 말고 한 줄만 추가**:
```bash
sudo nano /etc/docker/daemon.json
```
```json
{
    "data-root": "/mnt/nvme/docker",
    "runtimes": {
        "nvidia": {
            "path": "nvidia-container-runtime",
            "runtimeArgs": []
        }
    }
}
```
(기존 내용은 그대로 두고 첫 줄 `"data-root": ...,` 만 끼워 넣는다.)
```bash
sudo systemctl start docker && docker info | grep "Docker Root Dir" && docker images
```
- Root Dir가 `/mnt/nvme/docker`이고 이미지 목록이 이전과 같으면 성공. 그때 옛 것을 지운다:
```bash
sudo rm -rf /var/lib/docker
```

**5. 워크스페이스와 기록 폴더 이동** (심볼릭 링크로 경로 유지 → compose 파일, 런북 명령 모두 그대로)
```bash
mv ~/omx_ws /mnt/nvme/omx_ws && ln -s /mnt/nvme/omx_ws ~/omx_ws && mv ~/omx_recordings /mnt/nvme/omx_recordings && ln -s /mnt/nvme/omx_recordings ~/omx_recordings
```
- 컨테이너 안 경로는 `/ws`로 변하지 않으므로 재빌드 불필요.

**6. 다시 올리기**
```bash
cd ~/omx_ws && ./omx.sh up && ./omx.sh run ros2 pkg list | grep omx_ && df -h / /mnt/nvme
```

**7. 루트 정리(선택)**
```bash
sudo apt clean; sudo journalctl --vacuum-size=200M; rm -rf ~/.cache/pip
```
- ROBOTIS 이미지가 필요 없으면 `docker images`에서 확인 후 `docker rmi <이미지>`.

## 10. 나중: 학습된 정책 연결

정책 추론은 ROS 컨테이너 밖, 별도 파이썬 환경에서 돌린다. GPU 쪽이 이 젯슨에서 checkpoint load, `predict_action()`, 지연 측정까지 확인한 방식이다([`README_JETSON_SETUP.md`](../../gpu_server/omx-umi-sim/README_JETSON_SETUP.md) 2절: ROS 컨테이너에 torch를 넣지 않고 JetPack 대응 PyTorch를 쓴다).

- 규약: [`README_JETSON_HANDOFF.md`](../../gpu_server/omx-umi-sim/README_JETSON_HANDOFF.md) — `[16, 10]` 액션, 0.1 s 간격, `action[0]` = t0 자세, 그리퍼 폭 [m]. `omx_task_control/action_format.py`가 같은 해석을 구현하고 `test_action_contract.py`가 검사한다.
- 전달 번들을 받으면 해석이 GPU와 같은지 먼저 확인한다(`decoder_reference.npz` 비교).
  ```bash
  OMX_HANDOFF_DIR=~/omx_policy/jetson_handoff PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q omx_task_control/test
  ```
- 연결(구현 전): 정책 프로세스와 ROS 쪽 `policy_node`를 로컬 소켓으로 잇는다. GPU 시뮬레이터의 `sim_umi/ros/policy_server.py`와 같은 구조다. `policy_node`는 `/wrist_camera/image_raw`와 `/ee_state`를 관측으로 넘기고, 받은 `[16, 10]`을 `EEActionChunk`(stamp = 마지막 관측 시각 t0)로 낸다. 영상 전처리(가운데 자르기, 224 축소)는 정책 프로세스에서 GPU 정의대로 한다.
- `docker-compose.yml`의 `policy` 서비스 주석(`dustynv/ros:humble-pytorch-l4t`)은 초기 안이다. 위 방식으로 바꿀 예정이고 검증하지 않았다.
