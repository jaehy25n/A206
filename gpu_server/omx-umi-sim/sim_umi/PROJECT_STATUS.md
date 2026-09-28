# sim_umi — PROJECT STATUS

MuJoCo E2E vertical slice. 이 파일 하나만 읽으면 현재 상태를 알 수 있게 유지한다.

**최종 업데이트**: 2026-09-25
**현재 단계**: scripted pick/place **freeze**. 다음은 policy 실행 contract 연결.

---

## 한 줄 요약

공식 ROBOTIS OMX 팔 + 우리 pivot 그리퍼로, **MoveIt → 5DoF 투영 → ros2_control →
MuJoCo** 경로 위에서 **6개 regression 전부 통과**. 50 mm 흰 스티로폼 공을 집어
빈에 넣는다. synthetic 수집은 늘리지 않는다.

## HEAD regression (2026-09-25)

| 장면 | 결과 | 근거 |
|---|---|---|
| fully open | 51.63 mm | `scripts/check_gripper.py` |
| half close | 26.35 mm | 〃 |
| fully close | 0.13 mm, 자기충돌 0, 폭 곡선 단조 | 〃 |
| grasp | `stalled=True`, jaw 31.38 mm | `ros/pick_moveit.py` |
| lift | 공 z 24.8 → 137 mm | 〃 |
| bin approach-place | 공이 빈 안 (+19.4, −32.0) mm, z 27.2 mm | 〃 |

영상: `outputs/pick_place_h264.mp4`, 요약 `outputs/pick_place.png`.

**planning scene 에 환경이 들어있다** (`ros/scene_objects.py`): table, paper,
bin 바닥 + 벽 4개. `ros/check_collision_scene.py` 가 positive/negative 로 검증하고
MuJoCo 판정과 대조한다 — 책상 아래 60 mm, 빈 바닥 관통, 책상에 접은 자세,
MuJoCo 가 찾아낸 자기충돌 자세가 전부 `valid=False`, 걸리는 링크는 `link3` 등
**팔 링크 전체**.

### 아직 안 된 것 / 주의

- 빈 안으로 내려갈 수 있는 최저 TCP 높이는 **120 mm**(림 높이). 그 아래는 collision
  scene 이 거부해서, 공은 림 높이에서 놓아 떨어뜨린다
- 완전 닫힘이 0.00 → **0.13 mm** 로 바뀌었다. 힘 한계를 2.0 → 0.5 N·m 로 내린 결과
- kp=50 에 의한 정적 평형 오차(1.4°)는 실물 측정 후 **actuator calibration 대상**
- 공 크기 한계는 **44–58 mm** (59 mm 부터 실패). 학습 범위 `object_diameter_range`
  = 30–58 mm
- `omx_ros` conda 환경(3.9 GB)은 저장소에 없다. 이 서버에만 존재

---


## 실측 참조로 시야/외관 맞춤 (`sim_umi/reference/`)

사용자가 **실제 수집기로 찍은 영상과 metadata** 를 넣어줬다. 눈대중이 아니라
여기서 측정해 맞췄다.

### 실제 카메라 intrinsics — TODO(measure) 해소

`진짜참고/metadata.json` (session a28cec73):

```
image 1920x1080   fx 1491.89  fy 1491.65   cx 973.02  cy 541.52
focal 4.32 mm     sensor 5.645 x 4.234 mm

HFOV = 2*atan(1920/(2*1491.89)) = 65.5 deg
VFOV = 2*atan(1080/(2*1491.65)) = 39.8 deg
```

MuJoCo `fovy` 는 **수직** 이므로 39.8. 이전 값 60 은 추측이었고 훨씬 넓었다.

> **부수 발견**: 원본이 **1920x1080** 이다. CPU 서버에 P0 로 물어둔
> "원본 MP4 해상도" 의 답이 여기 있다 — GPU 가 받는 640x480 (4:3) 은
> 네이티브 캡처가 아니다. `REQUESTS_TO_CPU_SERVER.md` 참조.

### 카메라 자세 — 실사 참조로 확정

```
wrist_cam_pos       (0.0, -0.01, 0.14)
wrist_cam_pitch_deg 42.0
wrist_cam_fovy      39.8                 실측 intrinsics
```

`sim_umi/reference/gripper.png` (실제 수집기 시점) 기준. 팔 두 개가 아래에서
올라와 위로 모이고, 기어 하우징은 프레임 아래로 잘리며, 팔 안쪽 면이 보인다.

눈대중 대신 `scripts/camera_variations.py` 로 **설정값을 제목에 박은 격자**를
뽑아 고르는 방식으로 정했다. 축이 서로 당기는 걸 알아내는 데 여러 번 걸렸다:

| 조작 | 효과 |
|---|---|
| pitch 올림 (아래로) | 그리퍼 커짐, 대신 기어 톱니 노출 |
| pitch 내림 (눕힘) | 몸체 가려짐, 대신 전체가 작아짐 |
| 카메라 뒤로 (y 감소) | 커지지만 **몸체가 더 보임** |
| 카메라 앞으로 (y 증가) | 카메라가 팔을 지나쳐 **거의 안 보임** |

결국 **구도를 고정한 채 시선 방향으로만 거리를 줄이는 것**이 답이었다
(`y-0.03 z0.18` -> `y-0.01 z0.14`, 거리 80%, 크기 1.3배).

### 자세별 안정성 (`scripts/view_check.py`)

4 episode x 8 phase = 32 프레임:

```
4/4 성공        물체 보임 20/32
그리퍼 화면 점유 1.7 ~ 8.4%  (전 구간 몸체는 잘린 상태 유지)
```

| 단계 | 물체 | 비고 |
|---|---|---|
| approach | 0.35~0.39% | 팔 사이 가운데. 빈이 좌측에 보이기도 |
| **align** | **0.00%** | **손목이 돌며 팔이 물체를 가림** |
| grasp~lower | 0.82~1.15% | 렌즈에 물린 채 계속 보임 |
| release / done | 0.00% | 빈 내부가 화면을 채움 / 이미 놓음 |

align 에서 가려지는 건 그리퍼가 물체를 정면에서 감싸는 각도라 구조적이다.
앞뒤 단계에서 보이므로 시간축으로는 추적 가능하다.

### 작업면 밝기 — 물질이 아니라 이미지를 맞춤

검정 전지가 **물리적으로는 검정이지만 교육장 조명 + 폰 자동노출에서 중간 회색으로
찍힌다.** 참조 영상 실측과 시뮬이 10 배 차이였다:

```
실제 영상   RGB (116.8, 113.2, 112.7)
시뮬(이전)  RGB ( 11,    11,    13  )   <- 물질 albedo 0.045 를 그대로 씀
시뮬(현재)  RGB (112.4, 112.4, 115.9)   <- albedo 0.275 로 보정
```

`paper_albedo` 와 `light_diffuse` 는 **렌더 결과를 실측에 맞추도록 보정한 값**
이지 물질의 반사율이 아니다. 정책이 보는 것은 물질이 아니라 이미지다.

---

## pivot gripper 해결 — sweep 40/40 = 100%

### 실제 컨트롤러 설정을 먼저 찾았다

임의로 설계하지 않고 repo 에서 확인했다
(`open_manipulator_description/ros2_control/omx_f.ros2_control.xacro`, dxl16):

```
Operating Mode    5      <- Current-based Position Control
Current Limit   600 / Goal Current 600
Position P Gain 1000 / I 0 / D 1000
Profile Velocity 50 / Acceleration 25
Min/Max Position Limit  없음     <- 팔 관절(Mode 3, 0~4095) 과 다름
```

`omx_f_follower_ai/hardware_controller_manager.yaml`:
JointTrajectoryController 100 Hz, joints `joint1~5 + gripper_joint_1`
(**joint_2 는 명령하지 않는다** — URDF mimic -1 과 일치), interface `position`.

> **TODO(measure)**: 모터 모델이 이 repo 에 없다 (`dxl_model` 은 런타임 경로).
> current -> torque 상수가 미확정이라 `gripper_force_limit` 기본값 2.0 N*m 은
> XM430 급 정지토크 4.1 N*m 에 600/1193 (약 절반) 을 적용한 추정이다.
> 부품번호가 확정되면 그 값으로 교체할 것.

### MuJoCo 에 같은 의미론으로 구현

```xml
<position joint="..." kp="60" forcerange="-2.0 2.0"/>
```

**폭을 지정하지 않는다.** "닫아" 라고만 명령하고 물체가 멈춘다. 확인:

```
commanded theta 0.00000 rad
actual   theta  L 0.02581  R 0.02765     <- 목표보다 앞에서 멈춤 = preload
```

역기하(jaw width -> 각도) 를 버린 이유는 거기서 **부호/오프셋 버그가 세 번**
나왔고, jaw 테이블과 명령이 같은 site 로 만들어져 **자기검증이 불가능**했기
때문이다.

### 마지막 원인: cavity 보다 물체가 컸다

닫힌 두 초승달이 만드는 렌즈 치수를 윤곽에서 계산하면:

```
뒤쪽 간격 10.9 mm   cavity 내부 22.7 mm   끝단 0 mm (맞닿음)
```

**40 mm 물체는 여기 못 들어간다.** 손가락을 따라 밖으로 밀려나고, jaw 는
"잡고 있다는" 물체를 지나쳐 3 mm 까지 닫혔다. 접촉 법선도 jaw 를 가로지르지
않고 손가락 방향(0.95) 을 향했다.

물체를 20 mm 로 줄이니 통과한다. 법선 `|normal.x|` 이 **0.29 -> 0.771** 로
바뀐다.

| 물체 | cylinder | box |
|---|---|---|
| 16 mm | 실패 | 성공 |
| **20 mm** | **성공** | **성공** |
| 30/40 mm | 실패 | 실패 |

### 최종 검증

```
정지 hold 3s  : 2.5 mm 안착 후 평탄, 낙하 0.00 mm  -> solid
pose sweep 40 : success 40/40 = 100%
                lifted 40/40  in_bin 40/40  settled 40/40
                no_wall_penetration 40/40
                bin clearance  min +11.83 mm  median +11.90 mm
                6개 배치 전부 100%
```

**friction / condim 은 이 과정에서 한 번도 건드리지 않았다.**

### bin 벽 여유는 solver 밖에서 잰다

episode 당 `bin_touch_frames` / `bin_penetration_mm` / `bin_min_clearance_mm`
를 남기고, 음수 여유(벽 통과)면 `success=False`. 재는 방법을 두 번 갈아엎었다:

| 방법 | 결과 |
|---|---|
| `mj_geomDistance` | **못 쓴다.** 이 box 쌍에서 특정 자세마다 가짜 0.0 을 낸다 (실측 25 mm 간격이 0 으로 읽힘) |
| bin geom 에 `margin=gap=0.03` | 재려던 걸 망가뜨린다. 벽 geom 과 전지 사이 접촉까지 켜지는데 그 법선이 **수평** 이라, 옆으로 미는 힘에 빈이 책상 밖으로 날아갔다 |
| finger pad 에 `margin=gap=0.03` | 파지가 깨졌다 (lifted 0/4) |
| **mesh vertex + pad corner 를 벽 box 에 직접 투영** | 채택. 물리에 손대지 않고, 영상에 보이는 **mesh** 기준으로 잰다 |

부수 수정: 벽 geom 이 바닥 slab 위(z=2w)에서 시작하도록 올렸다. 전에는 z=0 까지
내려와 전지와 같은 평면에서 접촉이 깜빡였다.

> 부호만 믿을 것. 점이 벽(두께 3 mm)을 완전히 통과하면 크기는 **1.5 mm 에서
> 포화**한다. 1 mm 들어간 것도, 한참 지나간 것도 -1.5 mm 다.

### 진단이 잡아낸 것 (순서대로)

1. 정지 hold 실패 -> **궤적이 아니다** (회전/속도 분리와 양방향 일치)
2. kp 를 20배 올려도 Fn 0.15~0.40 N -> **접촉이 물렀다**.
   `solref` 0.02 -> 0.004 로 **24~30 N**
3. 평평한 pad = **wedge**. drift 가 파지각을 그대로 따라감
   (27/183/169 mm @ theta 0.18/0.27/0.36)
4. 윤곽 캡슐: 169 -> 2.4 mm. 그러나 얇은 캡슐은 평면에 **선접촉** -> 18 N 에서
   물체가 튕겨나감. **접선 박스**로 면접촉 확보
5. 역기하 폐기 -> current-based position control
6. **cavity 22.7 mm vs 물체 40 mm** -> 물체 크기를 기하에 맞춤

### 이것 때문에 무효가 된 것

- **magenta calibration** — `gripper_calibration.PARALLEL.invalid.json` 로 격리.
  parallel 기준이라 pivot 에서 음수 폭이 나온다. **재측정 필요** (fit/holdout 분리)
- **40/40 sweep** — parallel 기준. pivot 기준으로 다시 돌려야 한다
- **train 60 / heldout 20 데이터셋** — parallel gripper 로 수집됐다. 폐기 대상
- **demo.mp4 / phases.png** — parallel gripper 영상
- smoke training 은 배관 확인용이라 유효하지만, 데이터가 바뀌면 다시 돌려야 한다

### 영상 3종 점검 (요청 항목) — 완료

카메라 위치/FOV 는 **건드리지 않았다**. 확인은 `outputs/check_place.png`
(overview), `outputs/check_wrist.png` (raw | masked 나란히).

- [x] 그리퍼 끝 회색 구형 물체 **0개** — `left_inner`/`right_inner`/`robot_base`
      site 에 `rgba="0 0 0 0"`. MuJoCo 기본 site 색이 불투명 회색이라 보였던 것
- [x] 3 mm magenta patch 가 손가락 표면에 붙어있다 — patch 위치에서 표면을
      다시 재서 **9.59 mm**, patch 는 13.0 mm 에 떠 있었다 (가정했던 1.4 mm 가
      아니라 3.4 mm). offset 을 쓸어본 결과 0.05 mm 에서도 렌더가 안정
      (magenta px 118/114/109 @ 3개 파지각) -> **0.1 mm** 로 고정
- [x] masked RGB 에 halo / 떠다니는 blob 없음, 윤곽 연속
- [x] raw 에서 magenta 검출 133/133, masked 잔여 blob **0**
- [x] bin 벽 관통 0/40, 최소 여유 +11.83 mm, 접촉 프레임 0
- [x] pre-place(림 위 200 mm) -> 수직 하강 -> release -> 후퇴 순서 확인

### 아직 못 한 것

- [ ] pivot 기준 calibration 재실행 + 선형/2차 잔차 비교 + freeze
- [ ] dataset 재수집 (train 60 / heldout 20)
- [ ] 학습

---

## 좌표계 (고정)

```
origin = 책상 상판 중앙, 표면 (z = 0)
+X = 책상 가로
+Y = 로봇에서 책상 안쪽
+Z = 위
OMX base = (0, -0.40)      # TODO(measure): "앞쪽 edge 중앙" 가정
reach    = 0.380 m         # open_manipulator_x.urdf: 0.130+0.124+0.126
```

---

## 씬 — 파라미터에서 생성

`sim_umi/src/scene.py` 의 `SceneConfig` 가 XML 을 만든다. MJCF 를 직접 고치지
않는다. 실측 안 된 값은 전부 `TODO(measure)` 주석이 붙은 필드다.

| 항목 | 값 | 출처 |
|---|---|---|
| 책상 | 1.20 x 0.80 m, 흰색 | 실측 |
| 검정 전지 | 1.10 x 0.80 m | **TODO(measure)** — "약 110x80" |
| 천장등 | overhead 4개 | 근사. 튜닝 안 함 |
| 빈 | 120mm PLA, open-top, 벽 3mm | 실측 |
| ArUco | 60mm, id 0-3, 각 옆면 중앙보다 위 | 실측. dict `4x4_50` **TODO(confirm)** |
| object | 50mm box | **TODO(decide)** — 미정 |
| 카메라 | wrist, fovy 60 | extrinsic **TODO(measure)** |

ArUco 는 **visual texture 로만** 쓴다. marker ID 를 state 나 success 조건에
넣지 않는다. dictionary 가 확정되면
`python sim_umi/scripts/make_aruco_assets.py --dict <name>` 한 번이면 교체된다.

---

## 그리퍼 — 실제 OMX 반영

`ROBOTIS-GIT/open_manipulator` 를 clone 해서 `open_manipulator_x.urdf` 와
`gripper_{left,right}_palm.stl` 을 가져왔다.

```
visual     실제 STL 메시 (scale 0.001, z축 +90도 회전)
collision  단순 box 유지 (invisible)
치수       joint 원점 ±0.021, stroke [-0.011, +0.020]  <- URDF
           palm inner offset 12.2mm                   <- STL bbox
결과       jaw 개구 57.6mm (실제와 동일), 외곽 77.6mm
```

**외곽 77.6mm < 빈 개구 114mm** 이므로 빈 안으로 내려가 내려놓을 수 있다.
이전 추상 그리퍼는 외곽 126mm 라 빈에 못 들어가 떨어뜨려야 했다.

> URDF 프레임 매핑: 손가락이 URDF 에서는 +x 로 뻗고 ±y 로 슬라이드, 이 씬에서는
> +y 로 뻗고 ±x 로 슬라이드 -> 메시를 z축 +90도 회전.
> TCP 는 gripper 원점에서 **44.3mm** 앞 (URDF: 0.126 - 0.0817).

---

## Gripper 색상 / magenta tip / state 추정

실제 OMX 는 **gripper 만 흰색 PLA**, 나머지 arm/link/base 는 검정 계열이다.
wrist 뷰에 들어오는 건 gripper 뿐이라 이게 visual encoder 가 보는 색이다.

collector 는 jaw 에 encoder 가 없으므로 **카메라로 개구를 읽는다**:
손가락 끝 근처의 magenta 패치 두 개를 threshold 후 짝지어 픽셀 간격을 재고,
실측으로 맞춘 선형 스케일로 미터로 바꾼다. ArUco 가 아니라 단순 고채도 색인
이유는 tip 이 영상의 좁고 예측 가능한 영역에만 들어오기 때문이다.

```
raw wrist RGB
   ├─ detect_tips()   ROI -> HSV threshold -> connected component
   │                  -> left/right 중심 -> 픽셀 간격 -> 개구
   └─ mask_magenta()  patch 를 주변 흰색으로 덮음 -> policy RGB
```

### Calibration — fit 과 holdout 을 분리해서 측정

`scripts/verify_gripper_vision.py --freeze`

```
width = 0.000509 * pixel_gap - 0.037038

            RMSE      max abs    검출률
[fit]      0.047 mm   0.159 mm   450/450 = 100%
[holdout]  0.047 mm   0.131 mm   225/225 = 100%     <- fit 에 쓰지 않은 seed
실제 폭 구간 17.6 ~ 56.3 mm
```

**holdout 이 fit 과 동일**하므로 과적합이 아니다. calibration 은
`sim_umi/assets/gripper_calibration.json` 으로 freeze 했고, collector 가
그 파일을 읽어 쓴다.

마스킹 후 남은 magenta blob: **0**.

### 데이터 경로 — 무엇이 학습 입력인가

```
MuJoCo raw wrist RGB
   ├─ detect_tips() -> estimated width -> robot0_gripper_width   <- 학습 입력
   └─ mask_magenta()                   -> camera0_rgb            <- 학습 입력

MuJoCo true width  -> sim_gripper_width_gt      GT/debug 전용
                   -> sim_gripper_width_error   estimated - true
raw RGB            -> npz 의 rgb_raw            검증용
```

실제 OMX 배포 시에는 encoder/motor position 에서 **같은 물리 단위·같은
normalization** 으로 얻는다. collector 와 OMX 는 **센서만 다르고 policy 가
받는 state 의 물리적 의미는 동일**하다.

> 패치 크기는 실제와 같은 **3 x 3 mm**. 처음엔 6 x 12 mm 였는데 3 mm 로 줄이자
> 960x720 에서도 **0 px** 이 나왔다 — 해상도가 아니라 z-fighting 이었다.
> 곡면 위에 flush 로 두면 3 mm 패치는 전부 메시에 가려진다. 표면(11.59 mm)에서
> 1.4 mm 띄워 해결. 큰 패치는 이 문제를 견뎌서 가리고 있었다.

---

## Randomization

object 와 bin 을 **둘 다** 매 episode 랜덤 배치한다. 축별 범위가 아니라
**rejection sampling** 이다 — 제약이 축에 정렬돼 있지 않기 때문이다:
reach 는 base 중심 원, 전지는 사각형, 둘은 겹치면 안 된다.

```
r        [0.14, 0.34] m    base 중심
theta    ±(pi/2.2)         base 정면 방향
제약     전지 안 (여유 0.06) AND reach 안 (여유 0.03)
         object-bin 중심 거리 >= 0.20
yaw      object ±40도, bin ±40도
```

**yaw ±40도인 이유**: 물체가 정육면체라 yaw θ 와 θ±90도 가 동일하게 렌더링된다.
둘 다 가르치면 같은 그림에 서로 다른 손목 각도를 요구하게 된다.

### 실제 sampled 범위 (40 sweep)

```
object_x  [-0.311, +0.316]    bin_x  [-0.288, +0.272]
object_y  [-0.335, -0.067]    bin_y  [-0.318, -0.081]
object_yaw [-35.5, +36.3]도   bin_yaw [-38.0, +38.4]도
```

### 상대 배치 분포 (400 샘플)

| 배치 | 비율 |
|---|---|
| bin_right / bin_near | 21% |
| bin_left / bin_far | 21% |
| bin_left / bin_near | 18% |
| bin_right / bin_same | 14% |
| bin_left / bin_same | 14% |
| bin_right / bin_far | 12% |

한 배치가 지배하지 않는다. **"항상 정면 30cm 물체를 정면 55cm 빈에" 를 외울 수
없다.**

---

## Pose sweep — 수집 전 검증

`python sim_umi/scripts/sweep_poses.py -n 40`

```
success  40/40 = 100%
  lifted  40/40
  in_bin  40/40
  settled 40/40
```

sweep 이 실제로 잡아낸 것 (수집 전에):

1. **0/40** — 그리퍼 alpha 매핑 반전. alpha=0 이 open 이어야 하는데 closed 였다.
   에러 없이 그냥 아무것도 안 집혔다
2. **lift OK / 이송 중 낙하** — TCP 가 y=0.120 인데 손가락은 0.065 까지만 닿았다.
   **파지점이 손가락 바깥**. URDF 기준 0.0443 으로 교정
3. **축 뒤집고 제어 부호 안 고침** — 왼쪽 관절이 조용히 limit 에 clamp 됐다
4. **37/40, 실패 3건 전부 settled=False** — 빈 안에서 튀는 중에 판정.
   마지막 정착 구간 0.4s -> 1.0s

> 노션 지시대로 randomization 후 바로 대량 수집하지 않고 sweep 을 먼저 돌렸다.
> 위 4건은 전부 수집 전에 잡혔다.

---

## Dataset (새 씬 기준, 2026-09-24 재수집)

기존 회색바닥/초록zone 데이터는 **폐기**했다. 섞지 않는다.

```
train    60/60 success   4,500 frames @ 10 Hz   31.5 MB   seed_base 0
heldout  20/20 success   1,500 frames @ 10 Hz   10.4 MB   seed_base 1,000,000
```

같은 분포, 다른 seed stream. **IID heldout** 이지 OOD 가 아니다.

### 실제 sampled pose 범위

| | train | heldout |
|---|---|---|
| object_x | [-0.303, +0.333] | [-0.322, +0.284] |
| object_y | [-0.339, -0.086] | [-0.331, -0.078] |
| bin_x | [-0.310, +0.291] | [-0.192, +0.278] |
| bin_y | [-0.338, -0.073] | [-0.319, -0.104] |
| object_yaw | [-36.8, +38.6]도 | [-39.5, +23.3]도 |
| bin_yaw | [-39.6, +39.6]도 | [-39.6, +27.2]도 |

### 상대 배치 (train 60)

bin_right/near 14, bin_right/far 11, bin_left/far 10, bin_left/same 9,
bin_left/near 8, bin_right/same 7, bin_centre/far 1

### gripper vision 추정 오차 (episode 별)

```
train    RMSE 0.042 ~ 0.055 mm
heldout  RMSE 0.043 ~ 0.055 mm
```

### action 차원별 신호 (400 샘플)

| dim | train std | heldout std | |
|---|---|---|---|
| px | 0.0786 | 0.0752 | signal |
| py | 0.0429 | 0.0427 | signal |
| pz | 0.0934 | 0.0932 | signal |
| r6_0 | 0.0535 | 0.0399 | signal |
| r6_1 | 0.1926 | 0.1734 | signal |
| r6_2 | 0.00003 | 0.00003 | **yaw-only 이므로 구조적으로 0** |
| r6_3 | 0.1926 | 0.1734 | signal |
| r6_4 | 0.0535 | 0.0399 | signal |
| r6_5 | 0.00015 | 0.00015 | **구조적으로 0** |
| grip | 0.0025 | 0.0026 | signal |

**8/10 신호.** bin 까지 랜덤화한 효과로 **px std 가 0.035 -> 0.079** 로 두 배
넘게 늘었다. grip std 가 작아 보이는 건(0.0195 -> 0.0025) 실제 OMX jaw 구간이
17.6~56.2mm 로 이전 34~94mm 보다 좁기 때문이지 신호가 준 게 아니다.

zarr 키에 `sim_gripper_width_gt` 와 `sim_gripper_width_error` 가 같이 들어간다.
`robot0_gripper_width` 는 **vision 추정치**다.

---

## 아직 안 된 것 (명시)

- 학습을 한 번도 안 돌렸다
- OMX 5DoF execution scene 없음 (link1~5 메시와 joint 는 URDF 에 있고 가져오면 됨)
- IK / 5DoF projector 없음, trajectory manager 없음, closed loop 없음
- **정책 성공률 수치 없음.** sweep 100% 는 **scripted 궤적의 성공률**이지
  정책 성능이 아니다. 만들지 말 것

---

## NEXT ACTION

1. **학습 실행** — 기존 `train_diffusion_unet_timm_omx_workspace` 재사용.
   GPU 5. task config 의 `dataset_path` 를 `sim_umi/data/sim_umi_train.zarr.zip`
   으로만 바꾸면 된다. `val_ratio` 로 내부 validation 분리.
2. inference 에서 `(16, 10)` chunk 가 반복 생성되는지 확인 (노션 Phase C 완료조건)
3. Phase D — OMX 5DoF MJCF + IK/projector. **yaw 만 다루면 된다**
4. Phase E — trajectory manager
5. Phase F — closed loop
6. heldout 20개로 평가 (노션 P1)

## 아직 안 된 것 (명시)

- 학습 자체를 한 번도 돌리지 않았다
- OMX 5DoF MuJoCo scene 이 없다 (현재 scene 은 free 6DoF collector box)
- IK / 5DoF projector 없음
- trajectory manager 없음
- closed loop 없음
- **정책 성공률 수치 없음** — 학습을 안 돌렸으므로 당연. **만들지 말 것. 실측만 사용**
- heldout zarr 는 만들었지만 아직 평가에 쓰지 않았다
- demonstration 은 전부 scripted 다. teleop 없음
- 수집기 성공률(80/80)은 **scripted 궤적의 성공률**이지 정책 성능이 아니다

---

## COMMANDS USED

```bash
conda activate umi          # python 3.9.18, MuJoCo 3.3.7
export MUJOCO_GL=egl
export MUJOCO_EGL_DEVICE_ID=5

# A. demo 수집 (이미 실행됨)
python sim_umi/scripts/collect_scripted.py
python sim_umi/scripts/inspect_episode.py

# 1. randomized demo 수집
python sim_umi/scripts/collect_episodes.py -n 60 --split train
python sim_umi/scripts/collect_episodes.py -n 20 --split heldout
#   범위 옵션: --x-range --y-range --yaw-deg --place-x-range --place-y-range
#   실패 episode 는 기본 폐기. 남기려면 --keep-failures

# 2. UMI zarr 변환
python sim_umi/scripts/sim_to_umi_zarr.py -i sim_umi/data/train \
    -o sim_umi/data/sim_umi_train.zarr.zip --overwrite
python sim_umi/scripts/sim_to_umi_zarr.py -i sim_umi/data/heldout \
    -o sim_umi/data/sim_umi_heldout.zarr.zip --overwrite

# 3. 검증 (ReplayBuffer 재개봉 + UmiDataset 샘플 + 차원별 신호)
python sim_umi/scripts/verify_dataset.py sim_umi/data/sim_umi_train.zarr.zip
```

---

## FILES GENERATED

| 경로 | 내용 |
|---|---|
| `sim_umi/mjcf/collector_scene.xml` | free 6DoF collector + mocap weld + wrist cam |
| `sim_umi/scripts/collect_scripted.py` | scripted pick-place, npz 저장 |
| `sim_umi/scripts/inspect_episode.py` | npz → mp4 / frame jpg |
| `sim_umi/src/collector.py` | **신규** 파라미터화 collector, `EpisodeSpec`, `sample_spec` |
| `sim_umi/scripts/collect_episodes.py` | **신규** randomized 수집 CLI, split/seed 관리 |
| `sim_umi/scripts/sim_to_umi_zarr.py` | **신규** npz → UMI ReplayBuffer zarr |
| `sim_umi/scripts/verify_dataset.py` | **신규** zarr/dataset/신호 검증 |
| `sim_umi/data/train/` | 60 ep + `episodes.json` |
| `sim_umi/data/heldout/` | 20 ep + `episodes.json` |
| `sim_umi/data/sim_umi_train.zarr.zip` | 3660 프레임 @ 10 Hz, 22.7 MB |
| `sim_umi/data/sim_umi_heldout.zarr.zip` | 1220 프레임 @ 10 Hz, 7.5 MB |
| `sim_umi/outputs/episode_0000.mp4` | wrist 시점 영상 |
| `sim_umi/logs/pip_freeze_20260924.txt` | 환경 스냅샷 |
| `sim_umi/logs/conda_env_20260924.yml` | 환경 스냅샷 |

---

## 계약 (변경 금지)

노션 §4 및 기존 runtime 검증 결과. 임의로 바꾸지 않는다.

```
action horizon      16
action dim          10   = pos 3 + rot6d 6 + gripper 1
rot6d               첫 두 행, row-major
decoder             R_abs = R_base @ R_rel
action_dt_s         0.1
first_action_offset 0.0
RGB                 BGR->RGB, center crop, INTER_AREA, [0,1]
policy              Diffusion Policy, Conditional Temporal 1D U-Net
                    (Transformer/DiT 로 바꾸지 않는다)
```

관측 키 5개 (`UmiDataset` 이 요구):
`camera0_rgb`, `robot0_eef_pos`, `robot0_eef_rot_axis_angle`,
`robot0_gripper_width`, `robot0_eef_rot_axis_angle_wrt_start`

zarr 저장 키 6개 (`_wrt_start` 는 dataset 이 파생):
위 4개 + `robot0_demo_start_pose`, `robot0_demo_end_pose`
