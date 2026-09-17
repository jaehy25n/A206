# OMX-AI 더미 실행 파이프라인

학습된 policy 없이, **UMI 형식의 action chunk로 OMX-AI 팔을 실제로 움직이는** 실행 계층.
`DummyPolicy` 자리에 학습된 모델만 끼우면 아래 계층은 그대로 쓴다.

```
/joint_states  →  FK  →  앵커 자세 T_t
                              │
              policy(T_t)  →  chunk [H, 10]
                              │
           T_t @ dT  →  5-DOF projection  →  analytic IK
                              │
              JointTrajectory  →  /leader/joint_trajectory
```

action 한 스텝은 10개 숫자다.

| 구간 | 내용 | 프레임 |
|---|---|---|
| `[0:3]` | Δposition (m) | **상대** (현재 EE 기준) |
| `[3:9]` | Δrotation, 6D 표현 | **상대** |
| `[9]` | gripper width 0~1 | **절대** |

pose는 상대인데 width만 절대다. 물체 크기라는 물리적 의미가 있어서 상대로 쓰면 뜻이 없어진다.
후처리에서 실수하기 가장 쉬운 지점.

---

## 파일

| 파일 | 역할 |
|---|---|
| `omx_kinematics.py` | URDF 치수로 유도한 analytic FK/IK (5-DOF), 관절 한계 |
| `action_format.py` | 6D 회전 변환, chunk 디코딩, 5-DOF projection, elbow 분기 선택 |
| `dummy_policy.py` | 학습 모델 자리의 스크립트 픽 시퀀스 |
| `chunk_executor_node.py` | ROS 2 노드. `--dry-run` / `--hold` 모드 포함 |
| `omx_probe.py` | 읽기 전용 DXL 프로브. 서보 설정·실제 한계 확인용 |

각 모듈은 단독 실행하면 자체 테스트가 돈다.

```bash
python omx_kinematics.py     # IK 왕복 정밀도
python dummy_policy.py       # 픽 시퀀스 전체
python chunk_executor_node.py --dry-run
```

---

## 5-DOF 제약 — 이 팔의 핵심 성질

관절 축이 이렇게 생겼다.

```
J1  Z축  base yaw
J2  Y축  ┐
J3  Y축  ├  같은 수직 평면 안의 pitch 체인
J4  Y축  ┘
J5  X축  wrist roll
```

**EE yaw는 자유 변수가 아니다.** 목표까지의 방위각 `atan2(y, x - BASE_X)`에 강제로 묶인다.
제어 가능한 건 위치 3 + 접근 pitch + roll = 5뿐이고, policy가 낸 yaw는 projection에서 버려진다.

ROBOTIS 예제 코드도 `pan = atan2(y, x)`로 계산한다. 벤더가 같은 제약을 확인해준다.

> **데모 물체는 회전 대칭인 것으로 한정할 것** (컵, 원통, 캔).
> 손잡이처럼 특정 방향으로 잡아야 하는 물체는 강제된 yaw 때문에 반대편을 잡으러 간다.

---

## 실행 순서 (Jetson Orin)

물리 준비부터. 팔을 **접힌 자세**로 두고, 반경 40cm 비우고, launch 띄우는 순간 팔을 받칠 준비.
(`disable_torque_at_init: true`라 시작할 때 팔이 축 늘어진다.)

**1. 전송** — Windows PowerShell

```powershell
scp <이 폴더>\*.py <user>@<jetson-ip>:~/omx_dummy_test/
```

**2. 컨테이너로** — 오린

```bash
docker cp ~/omx_dummy_test/. open_manipulator:/root/omx_dummy_test/
docker exec open_manipulator rm -rf /root/omx_dummy_test/__pycache__
```

**3. zenoh 라우터** — 이거 빠뜨리면 노드끼리 서로를 못 찾는다

```bash
docker exec -d open_manipulator bash -ic "ros2 run rmw_zenoh_cpp rmw_zenohd"
```

**4. 로봇** — 팔 받치고

```bash
docker exec -it open_manipulator bash -ic "ros2 launch open_manipulator_bringup omx_f_follower_ai.launch.py port_name:=/dev/ttyACM0 start_rviz:=false"
```

**5. 통신 검증** — 팔이 움직이면 안 된다

```bash
docker exec -it open_manipulator bash -ic "cd /root/omx_dummy_test && python3 chunk_executor_node.py --hold"
```

현재 자세를 그대로 명령한다. 조금이라도 움찔하면 관절 순서나 프레임이 틀린 것.

**6. 완주** — 물체 없이 먼저

```bash
docker exec -it open_manipulator bash -ic "cd /root/omx_dummy_test && python3 chunk_executor_node.py --time-scale 8.0"
```

`--time-scale`은 클수록 느리다. 8.0이면 전체 50초, 초당 약 3cm.
정상이면 4.0 → 물체 투입 순으로.

**정리**

```bash
docker exec open_manipulator rm -rf /root/omx_dummy_test; rm -rf ~/omx_dummy_test
```

---

## 삽질 기록

같은 곳에서 다시 막히지 않도록.

### CRLF

`core.autocrlf=true`로 클론하면 레포 **95개 파일**이 CRLF가 되고 `container.sh`, 모든 launch 파일,
s6 서비스 스크립트가 깨진다. `bad interpreter: /bin/bash^M`.

```bash
git config core.autocrlf false && git rm --cached -r . -q && git reset --hard
```

### zenoh 라우터

v5.0.0부터 `rmw_zenoh_cpp`가 기본 RMW고 `.bashrc`에서 설정된다.
**라우터가 없으면 노드끼리 발견이 안 된다** — `ros2 topic list`에 `/joint_states`가 아예 없고 노드는 영원히 대기.

`bash -c`(비대화형)는 `.bashrc`를 안 읽어 기본 DDS로 폴백되므로 라우터 없이도 동작한다.
`bash -ic`는 zenoh를 켜므로 라우터가 필수. **이 차이 때문에 한참 헤맸다.**

### `container.sh start` 쓰지 말 것

```bash
docker compose pull        # 새 이미지를 당겨온다
docker compose up -d       # 기존 컨테이너를 재생성할 수 있다
sudo tee /etc/udev/rules.d/99-u2d2.rules
```

팀원 환경이 날아간다. 그 udev 규칙은 `ttyUSB*`+`ftdi_sio`용인데 OMX-AI는 `ttyACM0`라 해당 사항도 아니다.

### 시리얼 포트 중복 = segfault

리눅스 tty는 배타적 잠금이 안 된다. `ros2_control_node`가 둘이면 응답이 섞이고
DXL SDK가 깨진 패킷을 받아 `Protocol2PacketHandler::rxPacket`에서 죽는다.

로그에 `Controller already loaded, skipping load_controller`가 보이면 이미 떠 있다는 신호.

```bash
docker exec open_manipulator bash -c "pkill -f ros2_control_node; pkill -f 'ros2 launch'; pkill -f spawner"
```

### 관절 한계는 세 출처가 다 다르다

| 출처 | joint2 / joint3 | 신뢰도 |
|---|---|---|
| URDF | ±2π | 자리표시자, 무시 |
| 데이터시트 | -120 ~ +90 | 너무 빡빡 |
| DXL Position Limit | -107~+95 / -90~+96 | 서보가 실제로 강제 |
| **실측** | joint3이 **98.79°**에 주차돼 있었다 | 위 어느 것도 안 맞음 |

하드웨어 인터페이스가 캘리브레이션 오프셋을 쓰는 듯하다. 현재는 관측값 기준으로 넉넉히 잡았고,
**`omx_probe.py`로 실측해서 확정하는 게 남은 과제.**

### 회전 표현

policy 출력은 **6D**여야 한다. 쿼터니언은 double cover(`q`와 `-q`가 같은 회전)로 불연속,
오일러는 짐벌락 + ±180° 랩어라운드 — 둘 다 회귀가 망가진다.

다만 **관절 인터페이스에서는 오일러가 불가피하다.** 이 팔이 물리적으로 오일러 체인이라
`j1=yaw`, `j2+j3+j4=pitch`, `j5=roll`로 착지할 수밖에 없다.

경계선은 **생성이냐 추출이냐**다.

```
생성 (각도 → 행렬)   항상 안전. 특이점 없음
추출 (행렬 → 각도)   짐벌락이 사는 곳
```

`atan2(R[1,0], R[0,0])`로 yaw를 뽑으면 **pitch가 90°를 넘는 순간 정확히 180° 뒤집힌다.**
`project_to_5dof`는 yaw를 먼저 제거해 pitch/roll 2자유도만 추출하므로 ±90°에서도 정확하다.

### WSLg에서 RViz가 안 보일 때

창은 표시줄에 뜨는데 화면에 안 나오면 `wsl --shutdown` 후 재시작. 대부분 이걸로 풀린다.
`xwininfo -root -tree`로 창이 존재하는지 먼저 확인하면 렌더링 문제인지 구분된다.

### `scp -r` 중첩 함정

대상 디렉터리가 **이미 있으면 그 안으로** 복사된다. `~/omx_dummy_test/dummy_exec/`가 생기고
기존 파일은 그대로 남는다. 코드를 고쳤는데 반영이 안 되는 원인.

```powershell
scp <폴더>\*.py <user>@<jetson-ip>:~/omx_dummy_test/    # -r 빼고 .py만. 멱등
```

---

## 남은 과제

- **관절 한계 실측** — `omx_probe.py`를 ros2_control 정지 상태에서 돌려 확정
- **Jetson 추론 지연 측정** — 이 숫자가 `DT`, `H`, `EXECUTE_STEPS`를 결정한다. 학습 시작하면 못 바꾼다
- **grasp 성공 판정** — 그리퍼 DXL이 이미 Current-Based Position Control(모드 5)이다.
  `<state_interface name="Present Current"/>` 한 줄 추가하면 헛집음 감지가 공짜로 생긴다
- **6-DOF → 5-DOF 데이터 수집 정책** — 수집 단계에서 제약할지, 실행 시 projection할지
