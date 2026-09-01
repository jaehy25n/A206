# 검증 가이드: Episode Recorder MVP

## 사전 조건

- Galaxy S10 SM-G973N USB 디버깅 연결
- Camera 권한·Manifest 변경은 사용자 승인 완료
- 서버 설정·전송 불필요

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
6. completed episode가 `LOCAL_ONLY`로 표시되고 로컬 데이터가 유지되는지 확인한다.
7. episode 한 건을 삭제하고 해당 bundle만 목록에서 사라지는지 확인한다.
8. CaptureLog 전체 삭제 뒤 completed episode가 유지되는지 확인한다.

## 중단 흐름

cancel, 확정된 lifecycle interruption, `onCaptureBufferLost`, `onCaptureFailed`, capture sequence abort, Camera device/session, IMU, encoder/muxer/writer 오류, 앱 강제 종료에서 completed episode가 생성되지 않고 CaptureLog만 남는지 확인한다.
