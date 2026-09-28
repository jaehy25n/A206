# OMX-UMI Jetson — 실물 로봇 제어

GPU 서버가 학습한 정책의 출력(End-Effector 액션 청크)을 OMX-F 팔의 관절 명령으로 바꿔 실물 로봇을 움직이는 Jetson Orin Nano 쪽 코드와 배포 구성.
ROS 2 Humble 스택을 Docker로 격리해 돌린다. ROBOTIS 패키지는 쓰지 않고 DynamixelSDK, 모터 설정값, URDF 기하만 가져와 직접 구성했다.

## 역할 경계

```
GPU 서버   ─ 학습 → checkpoint + 전달 번들 (액션·영상 전처리 규약 확정)
    ↓  zip 전달 (scp / USB)
Jetson     ─ 정책 추론          ROS 밖 별도 파이썬 환경        ← 연결 노드 구현 전
           ─ omx_control      액션 해석 → 재계획·보간 → 5DoF 투영·IK → 안전 감시 → 드라이버
    ↓  USB, DYNAMIXEL Protocol 2.0 (ID 11~16, 1 Mbps)
OMX-F
```

Jetson이 맡는 것은 GPU 전달 규약([`README_JETSON_HANDOFF.md`](../gpu_server/omx-umi-sim/README_JETSON_HANDOFF.md) 2절)이 정한 대로 **액션 해석, 관측 동기화, 재계획과 안전, 5DoF 투영과 IK**다.

Jetson이 **하지 않는 것**: 학습, 액션 의미 정의(GPU가 확정하고 Jetson은 해석만), 영상 전처리 정의(GPU 정의를 재현만), 궤적 보정(CPU 서버 몫).

## 액션 규약

GPU 쪽 규약을 그대로 따른다. 해석은 [`omx_task_control/action_format.py`](omx_control/omx_task_control/omx_task_control/action_format.py) 한 곳에 있고 [`test_action_contract.py`](omx_control/omx_task_control/test/test_action_contract.py)가 검사한다.

| 항목 | 내용 |
|---|---|
| 형태 | `[16, 10]`: 위치 3 + 회전 6D 6 + 그리퍼 1 |
| 위치·회전 | 마지막 관측의 TCP 자세 T0 기준 상대값, T0 프레임에서 표현. 회전 6D는 첫 두 **행**. 복원 `T_abs = T0 @ T_rel` |
| 그리퍼 | 절대 폭 [m] |
| 시간 | step k = t0 + k × 0.1 s. `action[0]`은 t0의 자세(정렬 기준). 도착 시점에 지난 앞부분은 버린다 |
| 재계획 | 7스텝(0.7 s)마다. GPU 쪽 젯슨 추론 지연 측정 기준([보고서](../gpu_server/omx-umi-sim/REPORT_JETSON_INFERENCE_BRINGUP.md) Part 5) |

GPU 시뮬레이터는 ROS 2 Jazzy지만 Jetson은 Humble이다. 두 쪽은 ROS 메시지가 아니라 번들과 숫자 규약으로만 이어져서 배포판이 경계를 넘지 않는다([설계 문서](docs/design/architecture_draft.md) 12절).

## 구성

| 경로 | 내용 |
|---|---|
| [`omx_control/`](omx_control/) | 제어 스택 본체 8개 패키지: msgs, description(URDF), driver(C++), task_control(규약 해석·실행기·IK), perception, policy(더미), supervisor(mode_manager), bringup. 빌드·실행은 [`omx_control/README.md`](omx_control/README.md) |
| [`omx_teach/`](omx_teach/) | 직접 교시 기록 & 재현 (teach_node, CLI) |
| [`omx_deploy/`](omx_deploy/) | 젯슨용 Docker 구성 (Dockerfile, compose, `omx.sh`) |
| [`docs/design/`](docs/design/) | [`architecture_draft.md`](docs/design/architecture_draft.md) 설계와 논의 기록(v0 → v1, 구현 상태, 팀 저장소 통합), 설계 그래프 |
| [`docs/jetson_runbook.md`](docs/jetson_runbook.md) | 젯슨 실물 실행 절차 (Docker 격리, 드라이버 검증, 처짐 보정 식별, 정책 연결, 문제 대응) |

문서의 `<jetson-ip>`, `<user>`, `<pc>`, `<jetson>`은 각자 환경의 젯슨 IP, 계정, 호스트 이름으로 바꿔 쓴다.

## 작업 흐름

| 날짜 | 단계 |
|---|---|
| 9/1 | ROBOTIS Jazzy 환경 구축, 패키지 뼈대 |
| 9/8 ~ 9/17 | UMI 액션 청크 더미 파이프라인, ROBOTIS 스택 위 실물 구동 |
| 9/17 | 기본기 점검, DYNAMIXEL 직접 제어 |
| 9/18 | 자체 스택(v1)으로 설계 개정, Humble로 전환 |
| 9/23 | v1 구현과 mock 검증, 교시·Docker 배포, 젯슨 실물 검증(드라이버 진단, 처짐 보정) |
| 9/28 | 팀 저장소로 통합, GPU 전달 규약에 맞춰 액션 해석·카메라 설정 정렬 |

ROBOTIS 스택 위에서 돌린 더미 파이프라인과 초기 학습 노트는 현재 설계로 대체되어 트리에서 뺐다. 저장소 이력(9/1 ~ 9/17 커밋)에 남아 있다.

## 현재 상태

**검증 완료**
- mock(하드웨어 없음): 7노드 전체 그래프, joint_states 100 Hz, 더미 pick 완주, HOME·e_stop·heartbeat watchdog, 교시 재현 추종 오차 RMS 0.05°
- GPU 규약 해석: 규약 확인 항목 테스트 통과, mock에서 규약대로 낸 청크(0.1 s 간격, 0.7 s 재계획)로 더미 pick 완주, `/ee_target` 50 Hz 끊김 없음
- Docker 컨테이너: 이미지 빌드, 컨테이너 안 전체 빌드, mock 실행
- 젯슨 실물: 드라이버 통신(ID 11~16, 1 Mbps), 래치된 하드웨어 알람 진단과 reboot, 교시 재현 1회, 처짐 측정(정자세 joint2 −1.3°, 최대 뻗기 −2.0°), 모터 텔레메트리 토픽

**실물에서 확인된 제약**
- I 게인을 넣으면 joint2가 PWM −56 %로 중력 전체를 떠안아 XL430 과부하 셧다운 → **I 게인은 0**, 처짐은 피드포워드로 보정
- 최대 리치 근처 정지 자세는 joint2 과부하 위험 → IK가 수평 리치 0.32 m 밖 목표를 거부

**구현됐지만 실물 미검증**
- 중력 모델 기반 처짐 보정(`goal_offset_rad` + `sag_compliance_rad_per_nm × τ`), 식별 도구 `fit_sag.py`
- 규약에 맞춘 액션 해석과 재계획(9/28 변경분)

## 다음 할 일

1. GPU 전달 번들로 액션 해석 직접 비교: `OMX_HANDOFF_DIR=<jetson_handoff> python3 -m pytest omx_task_control/test` ([런북](docs/jetson_runbook.md) 10절)
2. 실측으로 규약 값 채우기: 그리퍼 완전 개방 폭(`gripper_open_width_m`, 지금은 GPU 시뮬레이터 값), TCP 위치, 손목 카메라 장착 자세, 카메라·마운트 무게(`payload_mass_kg`)
3. 정책 연결 노드: 추론 프로세스 ↔ `policy_node`. 이어서 카메라부터 관절 명령까지의 전체 지연 측정(GPU 보고서 Part 5의 다음 순서)
4. 젯슨 루트 디스크 99 % → Docker 저장소와 워크스페이스를 NVMe로 이동 ([런북](docs/jetson_runbook.md) 11절)
5. 처짐 보정 식별: 자세 5개 × 12초 유지 + `fit_sag.py` ([런북](docs/jetson_runbook.md) 7e절) → yaml 반영 → 교시 재현으로 높이 오차 확인
