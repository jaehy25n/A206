# omx_control — OMX-F policy-control stack (ROS 2 Humble)

Policy 출력(EE action chunk) → 5-DOF IK → Dynamixel 드라이버까지를 자체 구성한 ROS 2 패키지 모음.
ROBOTIS 스택에서는 DynamixelSDK, 모터 설정값, URDF 기하만 가져왔다.
설계 메모: [`docs/design/architecture_draft.md`](../docs/design/architecture_draft.md), 젯슨 실행 절차: [`docs/jetson_runbook.md`](../docs/jetson_runbook.md).

```
omx_msgs          EEState, EEActionChunk, EETarget, ModeState
omx_description   omx_f.urdf (base_link, tcp, wrist_camera_link 포함), meshes, RViz 설정
omx_driver        dxl_driver_node (C++): SyncRead/SyncWrite 100 Hz, timeout hold, 리밋 클램프, mock 모드
omx_task_control  kinematics (해석적 FK/IK, 5-DOF 투영), action_chunk_executor, ik_node
omx_perception    ee_state_node, wrist camera launch (usb_cam)
omx_policy        dummy_policy_node (학습 모델과 같은 토픽 인터페이스)
omx_supervisor    mode_manager: /joint_command 유일 발행자, IDLE/HOME/POLICY/TELEOP/STOP, e_stop, watchdog
omx_bringup       mock.launch.py, robot.launch.py, joint_limits.yaml, graph_dump.py
dummy_exec/       (프로토타입, 참고용) 위 패키지로 승격됨
omx_pose_follower (초기 스켈레톤, 삭제 예정)
```

## 데이터 흐름

```
/wrist_camera/image_raw ─┐
/ee_state ───────────────┴─> policy_node ─/policy/action_chunk─> action_chunk_executor ─/ee_target─> ik_node
                                                                                              │
/ik/joint_command <───────────────────────────────────────────────────────────────────────────┘
        └─> mode_manager ─/joint_command─> dxl_driver_node <─USB─> OMX-F
                                 └─/joint_states─> robot_state_publisher(/tf), ee_state_node, ik_node
```

* action chunk: 관측 시각 TCP 기준 **상대** ΔSE(3) × H, 그리퍼 폭은 **절대**(0 닫힘 ~ 1 열림).
* 명령 경로의 안전: mode_manager만 `/joint_command`를 낸다. 침묵 = hold(드라이버 timeout). 드라이버는 리밋 클램프와 속도 램프를 추가로 건다.

## 빌드

```bash
# 워크스페이스: ~/omx/omx_ws (src/omx_control -> 이 저장소 심볼릭 링크, src/thirdparty/DynamixelSDK)
cd ~/omx/omx_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

시스템 패키지(한 번만): `sudo apt install ros-humble-usb-cam ros-humble-xacro` (카메라 사용 시).
DynamixelSDK는 `src/thirdparty`에서 소스 빌드된다(`ros-humble-dynamixel-sdk`로 대체 가능).

## 실행

```bash
# 하드웨어 없이 전체 그래프 (mock 드라이버 + 더미 policy가 pick 스크립트 수행)
ros2 launch omx_bringup mock.launch.py rviz:=true

# 실제 로봇 (토크 OFF, IDLE로 시작)
ros2 launch omx_bringup robot.launch.py port:=/dev/ttyACM0 camera:=true
ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: HOME}"
ros2 topic pub -1 /mode_cmd std_msgs/msg/String "{data: POLICY}"
ros2 topic pub -1 /e_stop   std_msgs/msg/Bool   "{data: true}"

# 라이브 그래프를 rqt_graph 스타일 DOT/PNG로
ros2 run omx_bringup graph_dump.py -o rosgraph.dot --png

# 모터 진단
ros2 topic echo /dxl_driver/motor_state           # 스택 실행 중: PWM·부하·온도·전압·알람 (10 Hz)
ros2 topic echo /dxl_driver/tracking_error        # 목표 − 실제 [rad], 처짐 확인
ros2 run omx_driver dxl_scan.py                   # 드라이버 OFF: 어떤 ID가 어떤 baud에 응답하나
ros2 run omx_driver dxl_diag.py                   # 드라이버 OFF: EEPROM/RAM 전체 스냅샷
ros2 run omx_driver dxl_diag.py --watch 0.5 --csv hold.csv   # 유지 테스트 기록
ros2 run omx_driver dxl_diag.py --reboot 12       # 특정 모터 알람 해제
ros2 run omx_driver fit_sag.py --duration 90      # 중력 처짐 보정(goal_offset, compliance) 식별
```

중력 처짐 보정: 드라이버가 URDF 질량 + `payload_mass_kg`(웹캠·마운트, link5 기준 `payload_offset_xyz`)로
joint2~4의 중력 토크를 계산해 `offset = goal_offset_rad − sag_compliance_rad_per_nm × τ`를 명령에 더한다.
I 게인은 쓰지 않는다(정지 부하에서 모터가 중력 전체를 떠안아 XL430 과부하 셧다운).

## 테스트

```bash
# 이 PC의 사용자 site-packages에 있는 anyio pytest 플러그인이 시스템 pytest와 충돌하므로 자동 로드를 끈다
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q omx_task_control/test
```

## 하드웨어 투입 전 확인 목록

1. `omx_driver/config/omx_f_driver.yaml`의 `zero_ticks`, `direction` — 토크 OFF 상태에서 관절을 손으로 움직여 RViz와 방향·영점 대조
2. `omx_bringup/config/joint_limits.yaml` — 실제 기계 리밋 측정 후 갱신 (URDF와 동기)
3. `omx_description/urdf/omx_f.urdf`의 `tcp_joint`, `wrist_camera_joint` — 캘리브레이션 값으로 교체
4. `omx_driver/udev/99-omx.rules` — idVendor/idProduct 기입 후 설치
5. 그리퍼 열림/닫힘 방향과 `gripper_open_rad`/`gripper_closed_rad`

## 라이선스

Apache-2.0. `omx_description/meshes/omx_f/*.stl`은 ROBOTIS open_manipulator(Apache-2.0)에서 복사(LICENSE.robotis 참조).
