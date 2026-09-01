# OMX Follower 제어부 — 학습 정리

## 1. 프로젝트 개요
- 목표: 핸드헬드 그리퍼 + 휴대폰(영상·IMU)으로 시연 수집 → Follower(OMX-F) 모방학습 (UMI 방식)
- 리더암 대신 폰+그리퍼가 리더 역할, 학습 방식은 RL이 아닌 모방학습(BC)
- 시뮬레이션은 학습용이 아니라 제어 스택 검증용

## 2. 최종 시스템 동작 구조
- 폐루프 방식: 관측(카메라·현재 포즈) → 정책 → 액션 청크 → 실행기(IK) → 로봇, 매 주기 반복
- 전체 궤적은 미리 존재하지 않음 — 짧은 예측(~1초치)이 계속 갱신되며 이어짐
- 정책 출력 = [미래 스텝 × 액션차원] 실수 텐서 (Δ위치 3 + rotation6d 6 + grip 1)
- 정책은 시연자(사람)를 대체할 뿐, 관절·IK·모터는 모름 → 제어부(IK 실행기)는 영구 부품
- 핸드헬드 시연 데이터에는 로봇 관절 정보가 없으므로 EE 포즈 액션 공간이 강제됨
- 배포 시 관측 카메라는 학습 때와 같은 상대 위치에 장착 필요 (폰을 로봇 그리퍼에 마운트)

## 3. 개발 환경
- 구조: Windows 11 → WSL2(Ubuntu 22.04) → Docker Engine → `robotis/open-manipulator:5.1.1` (ROS 2 Jazzy)
- Docker Desktop 대신 WSL 내 Engine 설치 (host 네트워크·/dev 마운트·privileged 때문)
- 소스는 WSL 파일시스템에 클론(jazzy 브랜치), 컨테이너 워크스페이스에 마운트 (/mnt/c는 느림)
- 자체 패키지는 `docker-compose.override.yml`로 추가 마운트 — 원본 compose 무수정, `-f` 쓰면 병합 안 됨 주의
- RMW가 rmw_zenoh_cpp → 작업 시작 시 항상 `zenohd`(라우터) 먼저 실행 (없으면 노드 간 발견 불가)
- 빌드: `colcon build --symlink-install` (alias `cb`) — 파이썬/런치 수정은 재빌드 불필요
- GUI는 WSLg로 표시, 문제 시 `LIBGL_ALWAYS_SOFTWARE=1`

## 4. OMX-F 모델 분석
- 5자유도: 요(Z) – 피치(Y)×3 – 롤(X) + 그리퍼(gripper_joint_1, joint_2는 mimic ×−1)
- TCP = `end_effector_link` (link5에서 +x로 92mm, 손끝 중앙, RViz 빨간 상자)
- 도달 반경 약 0.32m → 시연도 이 범위 안에서 수행해야 함
- URDF의 rpy 전부 0 — "영자세에서 모든 링크 프레임 평행" 설계 + URDF의 자유 축 지정 덕분 (DH였다면 고정 회전 필수)
- URDF 관절 한계가 ±2π로 사실상 없음 → 제어부에서 자체 클램프 필요
- ROBOTIS MoveIt 설정이 `position_only_ik: True` (방향 무시) → 자체 IK 노드 채택의 결정 근거

## 5. 제어부 설계 결정
- 입력 계약(CSV): `t, x, y, z, qx, qy, qz, qw, grip` — 로봇 베이스 프레임 기준 TCP 포즈 시퀀스
  - 자세는 쿼터니언 (x,y,z,w) 순서 — 짐벌락 없음, ROS 표준
  - grip은 0(닫힘)~1(열림) 정규화 — 기구가 다른 두 그리퍼 간 비율만 전달
- 좌표 변환 사슬: `T_B←TCP = T_B←W · T_W←P(t) · T_P←G`
  - T_P←G: 폰↔그리퍼 고정 변환 (CAD/캘리브레이션), T_B←W: 첫 프레임 앵커링으로 결정
  - 변환은 별도 스크립트 담당, 제어부는 베이스 프레임 포즈만 소비 (책임 분리)
- IK: 자체 가중 미분 IK 노드가 메인라인, MoveIt은 병렬 학습 트랙
  - 5-DOF라 위치3+피치+롤만 추종 가능, 도구 요(yaw)는 가중치 0으로 포기
- 파이프라인 진화: 직선/원호 CSV(단위테스트) → 폰 시연 재생 → 정책 스트림 — 실행기 코어는 동일

## 6. 기구학 이론
- 동차변환 4×4 `[R p; 0 1]`, 합성은 행렬곱, `T_A←B` 방향 표기 유지가 버그 예방 핵심
- URDF 조인트 변환: `T = Trans(xyz)·Rot(rpy)·Rot(axis,q)` — OMX-F는 rpy=0이라 단순화
- FK: 베이스부터 체인 곱 `T01·T12·…·T5E`, 영자세 TCP = (0.31288, −0.0016, 0.21065)
- 기하학적 자코비안: 관절 i의 열 = `[axis_i × (p_TCP − origin_i); axis_i]` — FK 루프에서 부산물로 수집
- 감쇠 최소자승(DLS): `Δq = Jᵀ(JJᵀ + λ²I)⁻¹ W e` — λ가 특이점 폭주 방지, W가 축별 가중
- 쿼터니언 ↔ 회전행렬 변환 공식 구현, q와 −q는 같은 회전 (비교 시 부호 주의)
- /joint_states의 관절 순서는 보장 없음 → 반드시 이름으로 매칭

## 7. 마일스톤 로드맵
- 완료: 환경 구축(도커+빌드+RViz/Gazebo 검증), M1(자체 패키지 뼈대 + hello 노드)
- M2: FK 모듈 — 수학 자체 테스트 + tf2_echo 실측 대조 (이 정리 시점의 진행 단계)
- M3: IK 코어(가중 DLS) / M4: CSV 재생 + RViz 기구학 검증 / M5: Gazebo 물리 검증
- MoveIt 트랙: 데모 조작 → position-only 한계 체험 → Python API로 시작자세 이동

## 8. 자주 쓰는 명령
- 컨테이너: `docker compose up -d` (docker 폴더에서) / `./container.sh enter`
- 세션 시작: `zenohd` → 이후 launch
- 모델 확인: `ros2 launch open_manipulator_description omx_f.launch.py`
- 시뮬레이션: `ros2 launch open_manipulator_bringup omx_f_follower_ai_gazebo.launch.py`
- 상태 확인: `ros2 control list_controllers`, `ros2 topic echo /joint_states --once`, `ros2 run tf2_ros tf2_echo link0 end_effector_link`
