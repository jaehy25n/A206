# 검증 가이드: Episode Recorder MVP

## 사전 조건

- Galaxy S10 SM-G973N USB 디버깅 연결
- Camera 권한·Manifest 변경은 사용자 승인 완료
- 신뢰 가능한 인증서의 HTTPS를 사용하는 인증 없는 폐쇄망 서버 base URL이 빌드 시 주입되고, 수신 응답 계약이 제공됨

## 자동 검증

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
```

모든 명령은 `BUILD SUCCESSFUL`이어야 한다. 이 결과만으로 실기기 Camera·센서·권한·저장소 검증을 주장하지 않는다.

## Galaxy S10 수동 수집

1. 세 센서, physical main camera, 선택한 1080p/720p 30 FPS capability를 확인한다.
2. task·object를 입력하고 프리뷰·경과 시간·Camera/IMU 상태를 확인한다.
3. 정상 종료 뒤 목록의 task, object, 시각, 길이, sync state를 확인한다.
4. 여섯 파일, CSV 헤더, metadata의 실제 S10 camera ID·focal length·sensor size·active array·OIS/EIS·timestamp source·timebase status를 확인한다. calibration/pose key가 없는지 확인한다.
5. 성공한 Camera capture의 frame number·timestamp·source가 `frame_timestamps.csv`에 기록됐는지 확인한다.
6. completed episode가 초기 `LOCAL_ONLY`로 표시되고 로컬 데이터가 유지되는지 확인한다.
7. episode 한 건을 수동 업로드해 `UPLOADING`과 `UPLOADED` 상태를 확인하고, 성공 후에도 로컬 bundle이 유지되는지 확인한다.
8. 네트워크 연결을 끊거나 서버 오류를 재현해 `FAILED` 상태와, 여섯 파일 전체를 다시 보내는 수동 재전송 후 결과를 확인한다.
9. 입력 거부를 재현해 `FAILED` 상태와 오류 구분을 확인한다.
10. episode 한 건을 삭제하고 해당 bundle만 목록에서 사라지는지 확인한다.
11. CaptureLog 전체 삭제 뒤 completed episode가 유지되는지 확인한다.

## 중단 흐름

cancel, 확정된 lifecycle interruption, `onCaptureBufferLost`, `onCaptureFailed`, capture sequence abort, Camera device/session, IMU, encoder/muxer/writer 오류, 앱 강제 종료에서 completed episode가 생성되지 않고 CaptureLog만 남는지 확인한다.
