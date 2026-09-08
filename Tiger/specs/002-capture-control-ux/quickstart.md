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
