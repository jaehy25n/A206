# OMX 제어부 공부 정리

## 1. 프로젝트 개요
- 목표: 폰을 단 핸드헬드 그리퍼로 사람이 시연 → 영상 + IMU로 Follower(OMX-F) 모방학습
- UMI(Stanford Universal Manipulation Interface) 방식
  - 리더암(OMX-L) 대신 폰 + 핸드헬드 그리퍼가 시연 장치 역할
- 강화학습(RL)이 아니라 모방학습(Behavior Cloning)
- 시뮬레이션은 학습용이 아니라 제어 스택 검증용

## 2. 제어부의 역할
- 입력: TCP(그리퍼 끝) 포즈 시퀀스 → 출력: 관절 궤적(`JointTrajectory`)
- 실행 스택: 포즈 명령 → IK → 궤적 생성 → `arm_controller`
- 포즈 공급원만 바뀌고 실행 스택은 동일
  1. 손으로 만든 직선/원호 CSV (실행기 단위 테스트)
  2. 폰 시연 재생 CSV (캘리브레이션·작업공간 검증)
  3. 학습된 정책 출력 스트림 (실시간 토픽)
- IK 실행기는 임시 발판이 아니라 최종 시스템의 영구 부품
  - 시연 데이터엔 로봇 관절 정보가 없음 → 정책은 TCP 포즈만 배울 수 있음

## 3. 최종 시스템의 동작 방식
- 궤적을 미리 계산하지 않음 → 폐루프(closed-loop)로 짧은 예측을 계속 갱신
- 매 주기: 관측(영상, TCP 포즈, 그리퍼) → 정책 → 액션 청크 → 제어부 → 로봇
- 정책 출력 예: `[16, 10]` 텐서
  - 미래 16스텝 × (위치 Δ 3 + 회전 6D 6 + 그리퍼 1)
  - 위치는 상대값(delta) → 일반화에 유리
  - 회전은 6D 표현 → 쿼터니언의 q/−q 이중표현 문제 회피, 학습 안정
  - 청크로 내는 이유: 떨림 방지, 추론 지연 메우기
- 정책은 IK·관절·모터를 모름 → "손이 어디로 갈지"만 담당
- 배포 시 카메라는 학습 때와 같은 위치·시점이어야 함

## 4. 개발 환경
- 구조: Windows 11 → WSL2(Ubuntu) → Docker Engine → 컨테이너(ROS 2 Jazzy)
- Docker Desktop이 아닌 WSL 내부 Docker Engine 사용
  - compose의 `network_mode: host`, `/dev` 마운트, `privileged`가 왜곡 없이 동작
- 소스는 WSL 파일시스템(`~/omx/`)에 두고 컨테이너로 마운트
  - `/mnt/c` 경유는 빌드 I/O가 느리고 권한 문제 발생
- 저장소는 `jazzy` 브랜치 사용 (이미지 5.1.1과 버전 일치)
- 우리 코드는 별도 저장소(`~/omx/omx_control`) + `docker-compose.override.yml`로 추가 마운트
  - override 적용하려면 `docker compose up -d` (container.sh는 `-f`라 병합 안 됨)
- ⚠️ RMW가 zenoh → 매 세션 `zenohd` 먼저 실행 (안 하면 `ros2 topic list`가 빈다)

### 자주 쓰는 명령
| 명령 | 의미 |
|---|---|
| `./container.sh enter` | 실행 중인 컨테이너에 bash 진입 |
| `cb` | `colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release` |
| `--symlink-install` | Python/launch 수정 시 재빌드 없이 반영 |
| `source install/setup.bash` | 빌드된 패키지를 현재 셸에 등록 |
| `zenohd` | zenoh 라우터 (노드 간 발견 중계) |
| `ros2 control list_controllers` | 컨트롤러 상태 확인 |
| `ros2 topic echo <토픽> --once` | 메시지 1개만 출력 |
| `ros2 run tf2_ros tf2_echo A B` | A 기준 B 프레임의 포즈 출력 |

## 5. OMX-F 기구 구조
- 5자유도 팔 + 그리퍼
  - joint1: Z축(요) / joint2~4: Y축(피치) / joint5: X축(롤)
  - gripper_joint_2는 gripper_joint_1을 −1배로 mimic
- TCP = `end_effector_link` (link5에서 +x 0.09193, y −0.0016)
- 영자세 TCP 위치: (0.31288, −0.0016, 0.21065)
- 도달 반경 약 0.32m → 시연 동작도 이 범위 안에서 해야 함
- 5자유도라 6D 포즈를 다 못 맞춤
  - 추종 가능: 위치 3 + 피치 + 롤 / 포기: 도구 요(yaw)
- URDF의 모든 rpy = 0
  - "영자세에서 모든 링크 프레임이 베이스와 평행"하도록 작성된 규약
  - URDF는 회전축을 자유 지정(`<axis>`) → DH처럼 고정 회전이 필요 없음
  - 그래서 관절 변환이 `T(q) = Trans(xyz) · Rot(axis, q)`로 단순화
- URDF 관절 한계가 ±2π로 열려 있음 → 제어부에서 한계 클램프 직접 구현 필요

## 6. 입력 포맷 (CSV)
- 컬럼: `t, x, y, z, qx, qy, qz, qw, grip`
  - `t`: 궤적 시작 기준 상대시간(초)
  - 위치: 미터, 로봇 베이스(link0) 기준
  - 자세: 쿼터니언 (x,y,z,w) 순서 — 오일러는 짐벌락, 회전행렬은 제약 문제
  - `grip`: 0(닫힘)~1(열림) 정규화 — 두 그리퍼의 기구가 달라서
- CSV인 이유: 어디서든 생성·확인 가능, 나중에 LeRobot(parquet)으로 이식 쉬움
- 폰 데이터 없이 테스트 궤적으로 제어부를 먼저 개발 가능

## 7. 좌표 변환
- `T_B←TCP(t) = T_B←W · T_W←P(t) · T_P←G`
  - `T_W←P(t)`: 폰 VIO(ARCore/ARKit)가 주는 폰 포즈
  - `T_P←G`: 폰↔그리퍼 TCP 고정 변환 (CAD → 캘리브레이션)
  - `T_B←W`: 세션 앵커링 (1차: 첫 프레임 = 로봇 시작 자세)
- 축 규약 차이: ROS(REP-103: x전방 y좌측 z상방) vs AR 카메라 좌표계
- CSV에는 변환이 끝난 로봇 베이스 기준 포즈만 → 제어부는 좌표계 고민 X

## 8. IK 방식
- MoveIt 기본 설정이 `position_only_ik: True` → 방향 제어 불가
- 메인: 자체 가중 미분 IK (가중 DLS)
  1. 오차 `e` = 위치 차 3 + 회전 차 3 (회전벡터)
  2. 가중 `W = diag(1,1,1, w_roll, w_pitch, w_yaw≈0)` → 요 무시
  3. `Δq = Jᵀ(JJᵀ + λ²I)⁻¹ · W·e` → 감쇠항이 특이점 폭주 방지
  4. 관절 한계 클램프, 속도 제한, `JointTrajectory` 발행
- 병렬 트랙: MoveIt 학습 (연속 추종은 플래너보다 MoveIt Servo가 맞는 도구)

## 9. FK (순기구학)
- 동차변환 4×4 = `[R p; 0 1]`, 합성 = 행렬곱 (`T_A←C = T_A←B · T_B←C`)
- `T_base←TCP = T01 · T12 · T23 · T34 · T45 · T5E`
- 체인은 상수 테이블 + 범용 루프로 구현
- FK 루프에서 각 관절의 축·원점을 모아두면 자코비안에 그대로 사용
  - 관절 i의 열 = `[axis_i × (p_TCP − origin_i); axis_i]`
- 검증: 영자세 손계산 대조 → `tf2_echo` 실측과 대조 (3개 이상 자세, <0.1mm)
  - `/joint_states`의 `name` 순서는 보장 안 됨 → 이름으로 인덱스 매칭
  - 쿼터니언 q와 −q는 같은 회전

## 10. 시뮬레이터 비교
| | 용도 | 비고 |
|---|---|---|
| Gazebo | ROS 2 제어 스택 검증 | 저장소에 launch 있음, 실기와 동일 인터페이스 → **제어부에 사용** |
| MuJoCo | 정책 학습/평가 | 접촉 물리 우수, ROBOTIS 모델 제공 |
| Isaac Sim | 대규모 병렬 학습 | RTX GPU 필수, 이 프로젝트엔 과함 |

## 11. 로드맵
- [x] 환경 구축 (WSL2 + Docker + 빌드)
- [x] 모델·프레임 확인 (RViz, TF)
- [x] 입력 포맷 · 좌표 변환 · IK 방식 결정
- [x] M1: 패키지 뼈대 (`omx_pose_follower`)
- [ ] M2: FK 모듈 + TF 대조 검증
- [ ] M3: 가중 DLS IK 코어
- [ ] M4: CSV 재생 노드 → RViz 기구학 검증
- [ ] M5: Gazebo 물리 검증
- [ ] 실기 이전
