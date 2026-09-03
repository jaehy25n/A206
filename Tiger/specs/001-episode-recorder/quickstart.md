# Deprecated: Episode Recorder 검증 가이드

이 문서는 episode별 raw recording 전제를 사용하므로 더 이상 유효하지 않다.

현재 검증 범위와 작업 순서는 [작업 목록](tasks.md)을 따른다.

## Automated verification (2026-09-03)

- `./gradlew.bat testDebugUnitTest`: passed
- `./gradlew.bat lintDebug`: passed
- `./gradlew.bat assembleDebug`: passed

Galaxy S10 실기기 capture, tracking loss, interrupted recovery, upload retry 및 Ultra-wide probe는 별도 기기 검증이 필요하다.
