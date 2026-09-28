# OMX 제어 스택

Policy가 내는 End-Effector 궤적을 OMX-F 팔로워 팔의 관절 명령으로 바꾸는 ROS 2 Humble 제어 스택.
ROBOTIS 패키지는 쓰지 않고 DynamixelSDK, 모터 설정값, URDF 기하만 가져와 직접 구성했다.

## 구성

| 경로 | 내용 |
|---|---|
| [`omx_control/`](omx_control/) | 제어 스택 본체 8개 패키지: msgs, description(URDF), driver(C++), task_control(IK·실행기), perception, policy(더미), supervisor(mode_manager), bringup. 빌드 방법은 [`omx_control/README.md`](omx_control/README.md) |
| [`omx_teach/`](omx_teach/) | 직접 교시 기록 & 재현 (teach_node, CLI) |
| [`omx_deploy/`](omx_deploy/) | 젯슨용 Docker 구성 (Dockerfile, compose, `omx.sh`) |
| [`docs/design/`](docs/design/) | [`architecture_draft.md`](docs/design/architecture_draft.md) 설계와 논의 기록(v0 → v1, 구현 상태), `rqt_graph_draft.dot/.png` 설계 그래프 |
| [`docs/jetson_runbook.md`](docs/jetson_runbook.md) | 젯슨 실물 실행 절차 (Docker 격리, 드라이버 검증, 처짐 보정 식별, 문제 대응) |
| [`docs/robot_control_basics/`](docs/robot_control_basics/) | 로봇 제어 아키텍처·공정 정리와 조사 원본 (9/17) |
| [`docs/notes/`](docs/notes/) | 초기 학습 정리 (9/1, ROBOTIS 스택 전제 — 이후 설계로 대체됨) |
| [`prototypes/dummy_pipeline/`](prototypes/dummy_pipeline/) | ROBOTIS 스택 위에서 돌린 액션 청크 더미 파이프라인, 실물 구동 후 수정본 (참고용) |
| [`prototypes/dxl_basics/`](prototypes/dxl_basics/) | DYNAMIXEL Protocol 2.0 직접 제어 스크립트 (참고용) |

실행 가능한 코드는 `omx_control`, `omx_teach`, `omx_deploy` 세 곳이다.
`omx_control/dummy_exec/`는 9/8 초기 프로토타입(수정본은 `prototypes/dummy_pipeline/`), `omx_control/omx_pose_follower/`는 초기 스켈레톤이다.

문서의 `<jetson-ip>`, `<user>`, `<pc>`, `<jetson>`은 각자 환경의 젯슨 IP, 계정, 호스트 이름으로 바꿔 쓴다.

## 작업 흐름

| 날짜 | 단계 |
|---|---|
| 9/1 | ROBOTIS Jazzy 환경 구축, 패키지 스켈레톤 (M1) |
| 9/8 ~ 9/17 | UMI 액션 청크 더미 파이프라인, ROBOTIS 스택 위 실물 구동 |
| 9/17 | 기본기 점검, DYNAMIXEL 직접 제어 |
| 9/18 | 자체 스택(v1)으로 설계 개정, Humble로 전환 |
| 9/23 | v1 구현과 mock 검증, 교시·Docker 배포, 젯슨 실물 검증(드라이버 진단, 처짐 보정) |

## 현재 상태

**검증 완료**
- mock(하드웨어 없음): 7노드 전체 그래프, joint_states 100 Hz, 더미 pick 완주, HOME·e_stop·heartbeat watchdog, 교시 재현 추종 오차 RMS 0.05°
- Docker 컨테이너: 이미지 빌드, 컨테이너 안 전체 빌드, mock 실행
- 젯슨 실물: 드라이버 통신(ID 11~16, 1 Mbps), 래치된 하드웨어 알람 진단과 reboot, 교시 재현 1회, 처짐 측정(정자세 joint2 −1.3°, 최대 뻗기 −2.0°), 모터 텔레메트리 토픽

**실물에서 확인된 제약**
- I 게인을 넣으면 joint2가 PWM −56 %로 중력 전체를 떠안아 XL430 과부하 셧다운 → **I 게인은 0**, 처짐은 피드포워드로 보정
- 최대 리치 근처 정지 자세는 joint2 과부하 위험 → IK가 수평 리치 0.32 m 밖 목표를 거부

**구현됐지만 실물 미검증**
- 중력 모델 기반 처짐 보정(`goal_offset_rad` + `sag_compliance_rad_per_nm × τ`), 식별 도구 `fit_sag.py`
- 웹캠·마운트는 `payload_mass_kg`, `payload_offset_xyz`(link5 기준) 파라미터

## 다음 할 일

1. 젯슨 루트 디스크 99 % → Docker 저장소와 워크스페이스를 NVMe로 이동 ([런북](docs/jetson_runbook.md) 11절)
2. 웹캠·마운트 무게 측정 → `payload_mass_kg` 입력
3. 처짐 보정 식별: 자세 5개 × 12초 유지 + `fit_sag.py` ([런북](docs/jetson_runbook.md) 7e절) → yaml 반영 → ±0.2° 이내 확인
4. 교시 재현으로 높이 오차가 사라졌는지 확인

## 이력에 대해

`M1: package skeleton`과 `Add in-house ROS 2 Humble stack for the OMX-F arm (v1)` 두 커밋은 원래 `omx_control` 저장소의 커밋을 `omx_control/` 아래로 옮긴 것이다.
나머지는 커밋되지 않았거나 git 밖에 있던 작업을 원래 작업 시각에 맞춰 재구성한 커밋이며, 각 커밋 본문에 날짜의 근거(파일 수정 시각 / 문서 내용으로 추정)를 적었다.
재구성하면서 젯슨 IP, 계정·호스트 이름, 개인 PC 경로는 이력 전체에서 위의 자리표시자로 바꿨고, 실수로 들어간 `.pyc` 캐시는 뺐다.
문서 안의 상대 링크는 원래 폴더 구성을 가리키던 것을 이 저장소 구성에 맞게 9/28 정리 커밋에서 고쳤다.
