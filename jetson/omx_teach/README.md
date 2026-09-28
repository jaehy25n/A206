# omx_teach — OMX-F 직접 교시(teach) & 재현(replay)

팔로워 팔을 **토크 OFF 상태에서 손으로 움직여** 관절 궤적을 기록하고, 나중에 같은 궤적을 재현한다.
리더 팔은 쓰지 않는다. `omx_control` 스택은 수정하지 않고 공개 인터페이스만 사용한다.

| 동작 | 사용하는 omx_control 인터페이스 |
|---|---|
| 기록 | `/joint_states` 구독, `/mode_cmd IDLE`(토크 OFF) |
| 재현 | `/mode_cmd TELEOP`(토크 ON), `/mode_state`로 전환 확인, `/teleop/joint_command`로 스트리밍 → mode_manager가 드라이버로 중계 |

```
omx_teach_msgs   StartRecording.srv, PlayRecording.srv
omx_teach        teach_node, teach(CLI), recording.py(CSV 포맷), teach.launch.py
```

## 빌드

워크스페이스의 `src/omx_teach`가 `jetson/omx_teach`를 가리키게 둔다(심볼릭 링크, [`omx_control` 빌드](../omx_control/README.md#빌드)와 같은 워크스페이스).

```bash
cd ~/omx_ws && source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select omx_teach_msgs omx_teach
source install/setup.bash
```

## 사용

```bash
# 1) 로봇 스택 (또는 mock)
ros2 launch omx_bringup robot.launch.py        # 실물: IDLE(토크 OFF)로 시작
ros2 launch omx_bringup mock.launch.py         # 하드웨어 없이

# 2) teach 노드
ros2 launch omx_teach teach.launch.py

# 3) 기록 — 팔을 먼저 손으로 잡은 뒤 실행 (토크가 꺼지며 팔이 늘어진다)
ros2 run omx_teach teach record cup1
#    ... 팔을 움직여 시연 ...
ros2 run omx_teach teach stop                  # ~/omx_recordings/cup1.csv, cup1_ee.csv 저장

# 4) 재현 — TELEOP 모드로 전환(토크 ON) → 첫 자세로 3초 이동 → 기록 속도로 재생
ros2 run omx_teach teach play cup1 --speed 0.5
ros2 run omx_teach teach abort                 # 즉시 중단 (STOP)
ros2 run omx_teach teach list
ros2 topic echo /teach/status
```

재생이 끝나면 노드는 발행을 멈추고 드라이버가 마지막 자세를 유지한다(침묵 = hold). 모드는 TELEOP에 남으므로 필요하면 `/mode_cmd HOME` 또는 `IDLE`로 바꾼다.

## 기록 포맷

`<name>.csv`: `t, joint1..joint5, gripper_joint_1` [s, rad], `/joint_states` 원본 주기(100 Hz).
`<name>_ee.csv`: `t, x, y, z, qx, qy, qz, qw, gripper_width` — `omx_task_control` 기구학으로 계산한 TCP 궤적(base_link). 수집기 파이프라인의 Task Representation과 대조하는 데 쓸 수 있다.

## 제약과 주의

- joint1~3의 XL430은 전류 기반 위치 모드가 없어 "부드럽게 버티는" 교시가 불가능하다. 기록 중 토크는 완전히 꺼지므로 **팔을 잡고 있어야** 한다. `--keep-torque`로 토크를 유지한 채(다른 것이 팔을 움직일 때) 기록만 할 수도 있다.
- 재생 전 안전 검사: 관절 이름 일치, 샘플 간 최대 점프(기본 0.5 rad) 초과 시 거부. 속도는 0.1~2.0배로 제한. 드라이버의 리밋 클램프·속도 램프와 mode_manager의 e_stop은 그대로 적용된다.
- 재생 시작은 현재 자세에서 첫 샘플까지 smooth-step 보간(기본 3 s)으로 접근한다. 접근 경로상 충돌은 검사하지 않는다.
