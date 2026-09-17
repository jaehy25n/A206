# 04. DYNAMIXEL 직접 제어 노트

코드: `../DXL_직접제어/code/`
대상: OMX-AI follower — id 11~16, joint1~3 = XL430-W250, joint4·5·gripper = XL330-M288(또는 M077, 미확인), `/dev/ttyACM0`, 1 Mbps, Protocol 2.0

## 1. 왜 SDK 없이 바이트부터

`dynamixel_sdk`면 `packet.ping(port, 11)` 한 줄이지만 **왜 되는지는 영원히 모른다.**
관절 한계가 소스마다 다름, tick↔각도 오프셋의 위치, 전원을 껐다 켜면 설정이 사라짐 — 전부 "SDK/벤더 스택 안쪽"에 있었다.

> 참고: 프로토콜 코덱을 직접 쓰는 건 이 분야에서 **드문 선택**이다 (LeRobot·ALOHA·ROBOTIS 모두 DynamixelSDK 링크).
> 가시성을 위해 3–4일을 쓴 의도적 트레이드이고, 코덱은 끝났다. 반면 초기화 테이블·캘리브레이션을 직접 쓰는 건 전혀 드물지 않다 — 모든 랩이 한다.

## 2. 프로토콜 — 이게 전부

```
FF FF FD 00 | ID | LEN_L LEN_H | INST | PARAM… | CRC_L CRC_H
  header      id     length      what   args     CRC-16 (앞의 모든 바이트)
```

- **header** `FF FF FD 00` — 스트림 중간에 끼어든 서보가 패킷 시작을 찾는 표식
- **id** 0~252 개별, 254 브로드캐스트(응답 없음)
- **LEN** 자기 뒤 바이트 수 = INST + PARAM + CRC = `len(param) + 3`
- **INST** `01` ping, `02` read, `03` write, `82` sync read, `83` sync write, `08` reboot. 응답은 `55`
- **CRC-16/IBM** 다항식 `0x8005`, 초기값 0, MSB first
- 응답(status packet)은 같은 모양 + **ERR 바이트** 하나. 하위 7비트 = 오류 번호, **최상위 비트(0x80) = 하드웨어 경고**(실패 아님!)
- 전부 **리틀엔디안**
- **byte stuffing**: 페이로드에 `FF FF FD`가 나오면 뒤에 `FD` 삽입 (4바이트 goal position에서 실제로 발생 가능)
- 선은 **한 가닥, 반이중** — 항상 쓰고-읽고, 한 번에 하나, **두 프로세스 금지**

검증: `python3 dxl_raw.py` → ROBOTIS 매뉴얼 예제 패킷 3개와 **바이트 단위 일치** (로봇 불필요)
```
ping id 1         FF FF FD 00 01 03 00 01 19 4E
ping broadcast    FF FF FD 00 FE 03 00 01 31 42
read 132, 4B, id1 FF FF FD 00 01 07 00 02 84 00 04 00 1D 15
```
→ 앞으로 뭐가 안 되든 프로토콜 탓은 아니다. 배선·전원·주소만 남는다.

## 3. EEPROM vs RAM — 가장 중요한 사실

| | 주소 | 전원 끄면 | 토크 ON 상태에서 |
|---|---|---|---|
| **EEPROM** | 0–63 | 유지 | **쓰기 불가** (access error 7) |
| **RAM** | 64– | **기본값으로 리셋** | 쓰기 가능 |

- 유지: Operating Mode, Drive Mode, Return Delay Time, Position Limit
- **리셋**: Position P/I/D Gain(80/82/84), Profile Acceleration(108), Profile Velocity(112), Goal Current, Torque Enable
- **Profile Velocity 0 = 무한대**(0이 아님) → 전원 사이클 직후 첫 목표는 **최대 속도로 튄다**
- → "레지스터가 조용히 리셋되는" 미스터리의 완전한 설명. Goal Position만 쓰는 드라이버는 **자기가 고르지 않은 기본값 위에서** 움직인다. 초기화는 최적화가 아니라 **안전 문제**.
- **Reboot(0x08)도 RAM을 전부 지운다** → 과부하 후 복구는 "토크 다시 켜기"가 아니라 **RAM 초기화 전체 재적용**. 안 그러면 데이터 수집 중 스톨 한 번에 그 관절이 조용히 공장 게인(Kp 640)·프로파일 0으로 돌아간다.

## 4. 핵심 레지스터

| 이름 | 주소 | 크기 | 영역 | 메모 |
|---|---|---|---|---|
| Model Number | 0 | 2 | E | ping 응답에도 옴. 1060=XL430-W250, 1200=XL330-M288, 1190=XL330-M077 |
| Return Delay Time | 9 | 1 | E | 기본 250 × 2 µs = **서보당 500 µs**, 6개면 읽기마다 3 ms. **0으로 쓰면 루프율 ~3–4배, 영구** — 목록 전체에서 가장 싼 개선 |
| Drive Mode | 10 | 1 | E | **bit2 = 시간 기반 프로파일** → Profile Velocity/Accel 단위가 **ms** |
| Operating Mode | 11 | 1 | E | 3 position / 4 extended position / 5 current-based position / 16 PWM |
| Homing Offset | 20 | 4s | E | 서보가 0이라 부르는 위치를 이동. **Present Position에 이미 포함** → 기계 각 = 읽은 값 − offset |
| Current Limit | 38 | 2 | E | XL330만 해당. **XL430(joint1~3)엔 없음** (Goal Current 102·Mode 5도 없음) |
| Velocity Limit | 44 | 4 | E | |
| Max / Min Position Limit | 48 / 52 | 4s | E | **Mode 3에서만 강제.** Mode 4는 무시 |
| Shutdown | 63 | 1 | E | 그리퍼는 21(과부하 비트 제외, 물체를 계속 쥐려고), 기본 53. **팔 관절에 21 복사 금지** |
| Torque Enable | 64 | 1 | R | |
| Hardware Error Status | 70 | 1 | R | bit0 전압, 2 과열, 3 엔코더, 4 전기충격, 5 과부하 |
| Position D/I/P Gain | 80/82/84 | 2 | R | 벤더 설정 1000/0/1000 |
| Bus Watchdog | 98 | 1 | R | 단위 20 ms. 호스트가 죽으면 **제자리 정지**(토크 유지) — atexit·SIGTERM 핸들러와 달리 Jetson이 죽거나 USB가 뽑혀도 동작 |
| Goal Current | 102 | 2 | R | XL330만 (그리퍼 600) |
| Profile Accel / Velocity | 108 / 112 | 4 | R | 벤더 25 / 50 (Drive Mode 4면 25 ms / 50 ms) |
| Goal Position | 116 | 4s | R | **"움직여라"는 명령 = 이 주소에 4바이트 쓰기** |
| Present Load/Current | 126 | 2s | R | XL430=Load, XL330=Current (같은 주소, 다른 의미) |
| Present Velocity | 128 | 4s | R | |
| Present Position | 132 | 4s | R | 4096 tick/회전, 2048 = 0 (가설, 검증 대상) |

## 5. 스크립트 사다리

| 파일 | 하는 일 | 쓰기 |
|---|---|---|
| `dxl_raw.py` | 코덱(CRC·stuffing·빌드·파싱) + termios 백엔드(pyserial 없으면 표준라이브러리로) + `ping/read/write` | – |
| `s1_ping.py` | id 11~16 ping, **송수신 바이트를 hex로 그대로 출력**, 모델 번호, `--ids scan`(0~252) | 없음 |
| `s2_read.py` | 컨트롤 테이블 덤프: 모드·게인·프로파일·Return Delay, **Homing Offset**, 한계값 + 강제 여부(enforced / NOT ENFORCED / no real limit), 현재 위치, 경고 비트면 주소 70 해독 | 없음 |
| `s3_watch.py` | 현재 상태 표 → (`--torque-off`면 확인 후 해제 + **재확인**) → 실시간 위치 표시, 움직이는 줄 `<-- moving` | 토크 해제만 |

실행(오린 호스트, 의존성 없음):
```bash
sudo fuser -v /dev/ttyACM0; docker ps                        # 포트 비었나
python3 ~/dxl_basics/dxl_raw.py                              # CRC 자가검증
cd ~/dxl_basics && python3 s1_ping.py  --port /dev/ttyACM0
cd ~/dxl_basics && python3 s2_read.py  --port /dev/ttyACM0
cd ~/dxl_basics && python3 s3_watch.py --port /dev/ttyACM0 [--torque-off]
```
또는 `./run.sh s1_ping.py` (자체 python:3.12-slim 컨테이너, `--rm`, 이미지 `dxl` 빌드 필요). 컨테이너 경로는 pyserial을 쓰므로 termios 백엔드는 실행 안 됨.

**아무 응답이 없으면** (가능성 순): ① 다른 프로세스가 포트 점유 ② baud 다름(57600/115200/2M/3M) ③ 다른 디바이스(`ls -l /dev/ttyACM* /dev/ttyUSB*`) ④ 서보 전원 없음(USB만으론 서보에 전원 안 감)

### 이번에 고친 버그
- **경고 비트를 읽기 실패로 취급** — `err == 0`만 성공으로 봐서, 서보 하나가 과열되면 데이터는 멀쩡한데 모든 레지스터가 `-`, "every read failed". → `err & 0x7F`(진짜 오류)와 `err & 0x80`(경고) 분리
- 컨테이너가 `/dev`를 공유하므로 **호스트에서 돌려도 동일**, 단 컨테이너 안 ros2_control이 포트를 잡으면 호스트도 막힘 → 에러 메시지에 반영

---

## 6. 조사에서 나온 사실들 (숫자 포함)

1. **위치 한계가 실제로 강제되는 건 두 관절뿐.** joint1(id 11)은 Mode 4라 펌웨어가 한계 무시, joint4·5는 0..4095(전 범위), 그리퍼는 Mode 5. 실제 경계는 id 12(830..3129)와 13(1024..3140)뿐. 그런데 joint1이 데이지체인 하네스를 지고 있는 관절.
2. **6.48 mm 처짐은 산수다.** 0.30 m 리치에서 6.48 mm ≈ 14.1 pulse 오차 × 7.8125 PWM/pulse = 110 PWM / 885 = 12.4% duty — 그럴듯한 중력 유지. I=0·피드포워드 없음 → 일정 부하에 일정 오프셋.
3. **그 측정은 최악 자세가 아니었다.** 측정 자세는 joint2에 완전 수평 대비 ~58%의 중력 토크 → 완전 신장 시 **약 11 mm**. 6.48 mm 기준으로 잡은 테이블 여유는 파지가 끝나는 바로 그 지점에서 ~75% 부족.
4. **처지는 세 관절(XL430)은 전류 피드포워드로 도울 수 없다** — Current Limit·Goal Current·Mode 5가 XL430에 없다. 그래서 그리퍼는 되고 어깨는 안 된다.
5. **버스는 제약이 아니다.** 6개 sync_write 44 B = 440 µs, sync_read ~1.1 ms(RDT=0) → 사이클 ~1.5–1.9 ms, 필요는 25 Hz. 진짜 바닥은 USB CDC-ACM 왕복(1–3 ms, 프레임 양자화)이고 **C++로 바꿔도 같다.**
6. **지터를 의미 있는 단위로**: EE 0.2 m/s에서 1 ms = 0.2 mm, 10 ms = 2 mm. 받아들인 6.48 mm 처짐 = 32 ms 타이밍 오차. 비RT Jetson의 CPython p99는 1–3 ms. **파이썬은 문제가 아니고 PREEMPT_RT는 해답이 아니다.** 단, 루프 안 `print()`는 0.05–5 ms — "파이썬이 느리다"는 결론의 흔한 원인.
7. **벤더 JTC에서 속도 피드포워드를 받은 적이 없다.** `command_interfaces: [position]` → JTC는 순수 개루프 스플라인 샘플러였다.
8. **Bus Watchdog은 떨어뜨리지 않고 제자리에 세운다** → 브레이크 없는 이 팔에선 전원 차단 e-stop보다 **나은** 안전장치(전원 차단이 곧 낙하).
9. **그리퍼 Shutdown=21**은 과부하 비트를 일부러 뺀 것 — 팔 관절에 복사하면 테이블에 눌린 관절이 스스로 타는 걸 막는 유일한 자동 보호를 끄는 것. 그리퍼를 53으로 "고치면" 픽 도중 물체를 놓는다.
10. **Goal := Present 없이 Torque ON** — 브링업 중 팔을 망가뜨리는 가장 유력한 경로.
11. sync_write는 **응답 패킷이 없다** → 실패가 조용하다, 다음 읽기로만 확인. sync_read 응답은 요청 순서로 오므로 한 서보가 침묵하면 뒤의 응답이 **전부 한 칸씩 엉뚱한 관절로 밀린다** → ID 바이트로 매칭 (`recv()`는 현재 ID를 버림).
12. termios 백엔드 `VTIME=1`은 100 ms 단위 — 제어 주기 2.5개. ping엔 괜찮지만 루프엔 치명적(select 기반 타임아웃 필요).

### 기존 더미 코드의 알려진 결함 (`../더미데이터/`)
- `omx_kinematics.inverse`가 j5를 (−π, π]로 wrap → roll 179°→180° 명령 시 joint5가 359° 점프, 속도 게이트가 4,488°/s로 읽고 거부 → 팔이 경고 한 줄과 함께 멈춤. 스크립트 픽이 roll=0이라 잠복 중. (`_solve`에서 q_ref 기준 ±2π unwrap으로 해결)
- tick 제수가 파일마다 다름: `omx_kinematics.py` 주석은 /4095, 나머지는 /4096. 스펙은 4096. 수치 차이는 무시 가능하지만 **변환을 소유하는 파일이 하나도 없다**는 게 문제.
- IK 재검증: 20,000 샘플 중 17,200 정확(최악 3.24e-16 m), 2,800 거부는 전부 음의 평면 리치(joint1 축 뒤로 접힌 자세). r ≥ 0으로 제한하면 13,887/13,887. 작업 영역은 전부 정확 영역 안. **코드는 이식되지만 캘리브레이션은 안 된다.**

### 아직 확인 안 된 것 (믿기 전에 확인)
- **Profile Velocity 50의 의미** — 조사자 넷은 Drive Mode 4(bit2=시간 기반) → 50 ms 이동 시간(40 ms 틱보다 약간 길어 스텝이 겹치며 섞임), 하나는 속도 기반으로 읽고 ~1.2 rad/s 상한을 계산. **둘 다 참일 수 없다** → Drive Mode를 서보에서 직접 읽고 분기. 주의: '4' 없이 '50'만 복사하면 50 ms 블렌드가 5배 속도 제한이 되고, 그건 "정책이 안 되는 것"과 똑같아 보인다.
- **LeRobot 상류에 이 로봇 전용 드라이버가 있다는 주장** (`src/lerobot/robots/omx_follower/omx_follower.py`, 231줄, id 11–16, 같은 모델 구성, tick 상수가 평문 `.model` 파일에 0.0015339807878856412 rad/tick = 2π/4096, −π 오프셋). **여섯 조사자 중 하나만** 찾음. 사실이면 캘리브레이션 단계가 크게 줄어듦 — 20분이면 확인 가능.
- 그리퍼 모델: ROBOTIS 하드웨어 페이지는 XL330-M077(1190), LeRobot·ROBOTIS 포크는 M288(1200). `s1_ping.py` 한 번이면 해결.
- XL430 Position D Gain 기본값: 문서마다 4000 / 3600. 레지스터를 읽는 수밖에.
- 브로드캐스트 sync_write가 각 서보의 Bus Watchdog을 리셋하는지(문서 없음), position 모드에서 워치독이 유용하게 동작하는지 — kill -9 20분 실험 먼저.
- 프로파일 도중 Goal Position을 쓰면 현재 속도에서 재생성인지 정지에서 재생성인지 — 정상상태 지연이 ~5배 달라짐, 문서 없음.
- ID↔관절 매핑 — `s3_watch.py --torque-off`로 확정.

---

## 7. 직접 드라이버 사다리 (19단계, 9/17 기준 상태 갱신)

위험: none / 팔 늘어짐 / 팔 움직임 / 손상 가능

| # | 단계 | 확인 방법 | 위험 | 상태 |
|---|---|---|---|---|
| 1 | Protocol 2.0 코덱 | 매뉴얼 예제 패킷 3개 바이트 일치 | none | ✅ |
| 2 | 해석적 FK/IK + chunk 디코더 + 스크립트 정책 | 20,000 샘플 왕복 최악 3.24e-16 m | none | ✅ (더미데이터) |
| 3 | **버스 단독 소유** — `os.open` 직후 `fcntl.flock` 또는 `TIOCEXCL`, 컨테이너 s6 자동기동 중지, fuser 확인 | s1_ping 두 개 동시 실행 시 두 번째가 EBUSY로 깔끔히 실패 | none | ⬜ |
| 4 | 실기에서 6개 ping (컨테이너 말고 호스트 → termios 경로 실행) | 6개 응답, 모델 1060×3 + 1200(또는 1190)×3 | none | 🟡 코드 완료, 실기 미실행 |
| 5 | 컨트롤 테이블 전체 읽기 | 모드·Drive Mode·tick 한계·Homing Offset이 문서가 아니라 서보에서 나온 표 | none | 🟡 경고비트 수정·레지스터 추가 완료, 실기 미실행 |
| 6 | write(0x03) + 재확인 — 첫 실사용은 Return Delay Time(9) ← 0 (EEPROM, 토크 OFF 필요) | 6개 모두 주소 9에서 0 읽힘, 테이블 스윕 ~3배 빨라짐 | none | 🟡 `write()` 구현(토크 해제에 사용), RDT 미적용 |
| 7 | sync_read(0x82) + 루프 측정 (60초, 미리 할당한 배열에 로그) | p50/p95/p99/max 틱 시간 출력 — **이 숫자 없이는 위층을 못 짓는다** | none | ⬜ |
| 8 | **토크 끄고 벤치 캘리브레이션** — 관절당 알려진 자세 두 개, tick 기록, 부호·오프셋 풀기, 실제 기계 스톱·그리퍼 진짜 행정 | 알려진 자세에서 읽은 각도가 기구학 기대값과 1° 이내 | 늘어짐 | 🟡 `s3_watch.py` 준비됨 |
| 9 | **초기화 테이블 + 읽기-비교** — 토크 OFF → EEPROM(모드·한계·전류·셧다운) → RAM(게인·프로파일·Goal Current) → Goal := Present → 토크 ON | 쓴 레지스터 전부 재확인·diff, 불일치 시 진행 거부. 전원 사이클 후 재실행 결과 동일 | 움직임 | ⬜ |
| 10 | sync_write(0x83) + 첫 명령 동작 — 한 관절, 작은 델타, Goal := Present에서, 느린 프로파일 | Present가 명령 tick에 수렴·유지 | 손상 가능 | ⬜ |
| 11 | Bus Watchdog 실험 — 98 ← 4–5 (80–100 ms), 느린 이동 중 kill -9, 이어서 USB 뽑기 | 쾅 떨어지지 않고 제자리 정지, 98이 −1로 읽힘, 0 → 값으로 복구. 브로드캐스트 sync_write가 워치독을 먹이는지도 확인 | 손상 가능 | ⬜ |
| 12 | 프로파일 지연 실험 — 등속 관절 램프, 매 틱 Goal vs Present, Profile 50/25와 0에서 | 정상상태 지연(tick) 실측 → 희소 vs 조밀 논쟁과 Drive Mode 의미를 자체 데이터로 결론 | 움직임 | ⬜ |
| 13 | 결함 주입과 복구 — 관절을 막아 과부하 → 경고 비트 감지 → 70 읽기 → Reboot → RAM 전체 재적용 → goal 재동기 → 토크 ON | 과부하 후 P Gain이 640이 아니라 1000으로 읽힘 | 손상 가능 | ⬜ |
| 14 | 디코더·기구학·더미 정책을 드라이버 위로 — ROS 노드 제거, `--hold` 먼저(ticks→rad→ticks 왕복까지 증명) | 전체 디코드 경로를 통과해 측정 자세 유지, 눈에 보이는 크리프 없음 | 움직임 | ⬜ |
| 15 | 명령 게이트 — 측정 스톱 기반 관절 클램프, 실제 펌웨어 한계 대비 틱당 속도, 테이블 z바닥, NaN·비직교 회전 거부, IK 실패 시 유지 | 일부러 미친 chunk(NaN, 180° 손목, 테이블 아래)를 넣어 각각 이름 붙은 사유로 거부 | 움직임 | ⬜ |
| 16 | roll 180° wrap 수정 | roll 170→190° 스윕에 joint5 단조 증가, 거부 0 | 움직임 | ⬜ |
| 17 | 종단 폐루프 — 고정 주기 루프 + chunk 버퍼 + 스크립트 정책, TIME_SCALE 2.0 → 1.0 | 실속도 픽, p99 지터 < 3 ms, 거부 0 | 손상 가능 | ⬜ |
| 18 | 처짐 공략 — I Gain 올리기(RAM → 초기화 테이블에) / P 올리기 / 관절별 오프셋 표 중 택1 | **완전 수평 신장**에서 재측정 (6.48 mm 측정 자세 말고) | 움직임 | ⬜ |
| 19 | 데이터 문제 결정 — 카메라+관절 시간정렬 녹화기를 만들지, 스크립트/사전학습 정책으로 갈지 | 문서로 된 결정. **이 선택이 아래 전부보다 총 범위를 더 바꾼다** | none | ⬜ |

### 범위에 대한 정직한 평가
- 대체 드라이버 총량: 파이썬 **~1,200줄, 1인 2–3주**로 "믿을 만한" 수준. 비교: DynamixelSDK protocol-2 경로만 ~1,272줄, 그 위 `dynamixel_hardware_interface` C++ 4,710줄.
- 남은 일의 집중점 네 곳: 그룹 트랜잭션(~150줄), 재확인 포함 초기화 테이블(~250–350), 캘리브레이션(~40줄 + 벤치 반나절), 페일세이프 + 결함 복구(~250).
- **캡스톤에서 합법적으로 건너뛸 수 있는 것**: MoveIt, URDF/TF/RViz, ros2_control 전체, FCL 자기충돌(관절공간 금지 박스 20줄), SW 보간(서보 프로파일에 맡김), Fast Sync Read, 중력보상 토크 제어.
- **못 건너뛰는 것 (각각 이미 누군가를 물었다)**: 포트 배타성(flock 3줄 — 팀원 PWM 충돌이 정확히 이 버그), 토크 ON 전 Goal := Present, 모든 레지스터 쓰기의 재확인·diff, Hardware Error Status(70) 폴링, 관절별 SW 클램프, 루프 주기를 가정하지 말고 측정.
- **벤치 캘리브레이션은 코드가 아니라 시간이고, 위의 모든 것을 막고 있다.** 끝나기 전까지 3.24e-16 m 정확한 기구학은 틀린 숫자 위의 정확한 산수이고, 오차는 캘리브레이션이 아니라 기구학 버그처럼 보인다.
- **재작성이 원래 문제를 자동으로 고치지 않는다.** 잘못된 게인은 처짐으로, 잘못된 프로파일 의미는 지연으로, 100 ms 타임아웃은 지터로 나타나고 — 전부 "나쁜 정책"처럼 보인다. 고치는 건 읽기-비교 + 틱마다 명령 vs 실측 로그(합쳐서 ~60줄). 없으면 자기 코드에서 같은 불투명성을 재생산한다.
- 가장 큰 범위 결정은 서보 층이 아니다: **캡스톤이 자체 시연을 녹화하는가.** 벤더 트리엔 녹화·시간정렬 코드가 없다(physical_ai_tools는 README 링크뿐). 늦게 결정하면 예산이 터진다.
