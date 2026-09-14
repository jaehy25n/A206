# Capture Control UX 검증 가이드

## 사전 조건

- 이 저장소용 Android 빌드 환경이 구성돼 있다.
- 수집 검증을 위한 카메라 권한과 ARCore 지원 실제 기기가 있다.
- 업로드 검증을 위해 ingestion server의 `tigerUploadBaseUrl`이 설정돼 있다.

## 자동 검사

저장소 루트에서 실행한다.

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
.\gradlew.bat ktlintCheck
```

모든 명령이 성공해야 한다. 단위 검증에는 저장소 root 필터, Room 벽시계 migration, Episode 상태 전이, Session projection 개수, 업로드 취소, 프리뷰 준비, 화면 상태 콜백이 포함돼야 한다.

## 실제 기기 검사

1. 앱을 시작해 빈 Session 목록에 새 수집 행동이 있는지 확인한다.
2. 새 수집을 시작한다. 라이브 카메라 프리뷰와 task/object 입력을 확인하고, 프리뷰 준비와 두 입력이 모두 유효하기 전에는 재생할 수 없는지 확인한다. 권한을 거부하거나 프리뷰 준비를 실패시켜 Session이 만들어지지 않는지 확인한다.
3. 재생·일시 정지·재생·정지를 수행한다. 완료 Episode 두 개의 Session이 확정되고 업로드가 자동 시작되며, 비결정적 진행 표시와 화면 이탈 경고가 있는 업로드 상태 화면이 열리는지 확인한다.
4. Session Detail에서 전송을 시작한다. 같은 업로드 상태 화면이 열리는지 확인하고, 뒤로 가기·닫기에서 한 번은 취소를 거절하고 다음에는 확인해 Detail에서 재전송 가능한지 확인한다.
5. 업로드를 시작한 뒤 앱을 백그라운드로 보낸다. 앱으로 돌아와 업로드가 중단되고 Detail에 재전송 행동이 있는지 확인한다.
6. 유효한 `201 created` 또는 `200 duplicate` receipt 뒤 완료 상태가 보이는지 확인한다. 네트워크 실패를 재현하고 같은 Session id로 재전송되는지 확인한다.
7. legacy 외부 저장소 bundle이 있는 기기에서, 목록·업로드 대상에서 제외되고 파일이 복사·삭제되지 않는지 확인한다.

이 검증은 단위 테스트만으로 실제 기기의 카메라·ARCore·저장소·서버 동작을 증명하지 않는다. 실제 기기와 ingestion server 결과는 별도로 기록한다.

## 실행 기록

- 2026-09-09, `SM-G973N` (Android 12, 4KB page size): Session 목록에서 새 수집을 실행했다. 전체 작업 공간에서 프리뷰 영역 위 task/object 입력 모달이 즉시 표시됐고, 두 입력이 비어 있을 때 `준비 완료`가 비활성인 것을 확인했다. 두 입력을 확인한 뒤 목록·업로드 상태 문구 없이 프리뷰가 화면을 채우며 하단 중앙에 시작 아이콘 하나만 표시되는 것을 확인했다. X의 접근성 이름은 `수집 작업 공간 닫기`였고, 녹화 전 X를 누르면 Session을 만들지 않고 목록으로 돌아왔다.
- 같은 기기에서 task/object를 입력한 최신 debug APK로 첫 시작을 실행했다. 하단 제어가 `작업 구간 일시 정지`와 `수집 종료` 두 아이콘으로 바뀌는 것을 확인했다. 수집 중 X를 누르면 “현재 녹화를 종료하고 Session을 완료한 뒤 전송을 시작합니다.” 확인 문구가 표시됐다. 종료를 확인한 뒤 업로드 상태 화면에서 `업로드 완료`를 확인했다.
- 같은 기기에서 기존 중복 `Session 1` 기록이 수집 시각 순번으로 정규화되어 목록에 `Session 8`부터 `Session 11`까지 표시되는 것을 확인했다. `Session 11` Detail에서 좌측 상단 뒤로가기 아이콘과 `main_rgb.mp4`의 재생·되감기·빨리감기 컨트롤(6초 길이)을 확인했다.
- 같은 기기에서 Task 홈이 `이름 없는 Task`, `090900`, `DeviceTask`, `device-test` 그룹을 표시하고 각 그룹의 수집 개수를 표시하는 것을 확인했다. `DeviceTask`를 선택하면 수집 시각, 짧은 ID, 완료 Episode 수, 전송 상태로 구성된 목록이 열렸으며 숫자 Session 제목은 표시되지 않았다. 해당 항목의 Detail에서 전체 화면 확장 버튼을 누르면 검은 배경의 별도 재생 화면과 좌측 상단 뒤로가기 아이콘이 표시되고 원본 비율 동영상이 재생되는 것을 확인했다.
- 미완료: 이 기기는 Android 12/4KB 페이지이므로 16KB 기기 검증, 실제 수집의 일시 정지·재생으로 Episode 두 개를 만드는 흐름, 업로드 취소·백그라운드 중단·재전송·legacy 제외는 아직 수행하지 않았다.
# Phase 4 실제 기기 기록

- 2026-09-10, `SM-G973N`(Android 12): debug APK 설치와 카메라 권한 부여 후 새 수집을 열었다. Task/Object 입력을 완료했을 때, 녹화가 시작되기 전 전체 화면 카메라 프리뷰와 하단 중앙 `수집 시작` 아이콘, 우측 상단 닫기 접근성 이름이 표시됐다.
- 로컬 증거: `app/build/capture-preview-before-recording.png`. 이 파일은 build 산출물이므로 커밋하지 않는다.

- 2026-09-10 사용자 추가 확인(T022): `SM-G973N`(Android 12)에서 `.\gradlew.bat connectedDebugAndroidTest --no-daemon`가 성공했다. 녹화 전 전체 화면 프리뷰·Task/Object 입력 모달·하단 중앙 수집 시작 아이콘·우측 상단 닫기 접근성 이름도 확인했다. 이 근거로 T022를 완료 처리하며 이전 connected 검사 재실행 필요 기록을 대체한다. TalkBack 실사용 검증은 이후 2026-09-11 개발용 앱 범위 결정으로 필수 조건에서 제외했다.

## Phase 5 검증 절차

1. 녹화 전 Task/Object 입력을 완료한다. 프리뷰의 첫 프레임이 준비되기 전에는 시작이 비활성이고, 준비 실패 안내는 한 번 표시되는지 확인한다. 권한 거부 시에는 권한 허용 후 화면 재진입 안내를 확인한다.
2. 준비·Episode 진행·Episode 없음·확정 중에 각각 시작 / 일시 정지·종료 / 작업 구간 시작·종료 / 비활성 제어·진행 표시를 확인한다. 시작·일시 정지 저장·확정 처리 중 빠르게 반복 입력해 중복 Session·Episode·종료가 생기지 않는지 확인한다.
3. 수집 중 정지·시스템 뒤로 가기·우측 상단 X로 종료 확인을 연다. 취소하면 수집이 계속되고 확인하면 확정으로 이어져야 한다. 녹화 전 뒤로 가기·X는 Session을 만들지 않고 목록으로 돌아가야 한다.
4. `CaptureControlStateTest`와 `CaptureControlStateScreenTest`로 아이콘 이름·비활성 상태·종료 확인·툴팁 표시를 검증한다. 개발용 앱이므로 TalkBack 실사용 검사는 필수가 아니다.
5. 확정 중 백그라운드로 전환하면 완료 bundle은 보존하되 새 전송을 지속하지 않고 Detail에서 재전송 가능한지 확인한다. 이 실제 수집·전송 경계는 T035의 후속 기기/서버 검증에 포함한다.

### 실행 기록 (2026-09-10)

- 구현: `CaptureScreen`의 `controlPolicy`를 제어 아이콘·종료 확인·BackHandler·X와 실제 콜백에서 함께 사용한다. 시작/일시 정지 저장은 `controlBusy`, 확정은 `finalizing`으로 동기적으로 잠그며 완료·실패 시 해제한다. 첫 preview frame과 메타데이터를 시작 조건으로 사용한다. 툴팁·Snackbar·확정 진행 표시를 리소스 문자열로 제공한다.
- 자동 검사: `.\gradlew.bat ktlintCheck testDebugUnitTest lintDebug assembleDebug connectedDebugAndroidTest --no-daemon` 성공. 단위 검사 52개, `SM-G973N`(Android 12)의 connected 검사 14개가 실패·건너뜀 없이 통과했다. Lint 오류 0건, 경고 62건. 신규 `CaptureControlStateTest` 4개 및 `CaptureControlStateScreenTest` 5개를 포함한다.
- 로컬 산출물: `app/build/test-results/testDebugUnitTest/`, `app/build/outputs/androidTest-results/connected/debug/`, `app/build/reports/lint-results-debug.html` (모두 커밋 제외).
- 범위 변경(2026-09-11): 사용자 지시에 따라 개발용 앱에서 TalkBack 실사용 검증을 제외했다. T025는 기존 자동 검사 성공 근거로 완료 처리했다. TalkBack을 검증했다고 보고하는 것은 아니다. 실제 카메라·센서 수집과 확정 중 백그라운드 전환·서버 재전송은 T035에서 별도로 검증한다.

## Phase 7 부분 실제 기기 검증

- 2026-09-11, `SM-G973N`(Android 12, page size 4096): `./gradlew.bat connectedDebugAndroidTest --no-daemon --offline`가 14개 테스트를 실패·건너뜀 없이 통과했다. 목록·수집 제어·종료 확인·export UI의 Compose semantics와 migration 경로를 확인했다.
- 내부 개발용 앱 범위에서는 `SM-G973N`을 기준 기기로 사용하며, 16KB 페이지 기기 검증은 요구하지 않는다(2026-09-11 사용자 결정). 실제 camera/AR 프리뷰, ingestion server 자동 업로드·취소·백그라운드 중단·재전송, legacy 외부 bundle 제외의 수동 확인은 T035에 남아 있다.
- 2026-09-14, `SM-G973N`(Android 12, page size 4096): Task `T035`/Object `upload`을 입력해 라이브 카메라 프리뷰에서 실제 수집을 시작·종료했다. 종료 확인 뒤 `업로드 중` 비결정적 진행 표시와 “이 화면을 나가면 전송이 중단됩니다.” 경고를 확인했다. 앱을 강제 종료·재시작한 뒤 해당 Session Detail이 `업로드 완료`로 표시되는 것을 확인했다. 이 업로드는 짧은 시간 안에 완료돼 취소 확인·업로드 중 백그라운드 중단·실패 후 재전송은 재현하지 못했다. legacy 외부 bundle 수동 제외도 미검증이다.
