# 검증 가이드: Mobile Episode Transfer

## 사전 조건

- Galaxy S10 SM-G973N 또는 Android API 28 이상 실기기
- completed 상태의 여섯 파일 episode bundle
- build-time으로 주입된 HTTPS server base URL
- 대상 기기에서 신뢰되는 서버 인증서
- [episode upload 계약](contracts/episode-upload.md)을 구현한 테스트 서버 또는 실제 서버
- 네트워크 권한·network security config Manifest 변경에 대한 사용자 승인

실제 base URL, 인증서, private network 정보는 이 문서나 저장소에 기록하지 않는다.

## 자동 검증

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat lintDebug
.\gradlew.bat assembleDebug
```

단위 테스트는 multipart 구성, receipt 검증, 오류 분류, 원본 불변성, 상태 전이를 다룬다. 이 결과만으로 실제 Galaxy S10의 TLS 인증서 신뢰·네트워크 연결·대용량 파일 전송을 검증했다고 판단하지 않는다.

## 계약 테스트 시나리오

1. 유효한 completed bundle을 업로드한다. 서버가 `201`과 일치하는 `{ episode_id, result: "created" }`를 반환하고 앱이 `UPLOADED`가 되는지 확인한다.
2. 같은 episode를 같은 `Idempotency-Key`로 다시 업로드한다. 서버가 `200`과 `{ episode_id, result: "duplicate" }`를 반환하고 앱이 `UPLOADED`를 유지하는지 확인한다.
3. receipt의 `episode_id` 또는 `result`가 계약과 다르게 응답하도록 한다. 앱이 성공으로 표시하지 않고 원본을 보존하는지 확인한다.
4. 연결 실패, `408`, `429`, `5xx`, redirect를 재현한다. 앱이 `FAILED`와 실패 요약을 표시하는지 확인한다.
5. `4xx`를 재현한다. 앱이 `FAILED`를 표시하는지 확인한다.

## Galaxy S10 수동 검증

1. episode 목록에서 `LOCAL_ONLY` completed bundle 하나를 선택한다.
2. 수동 업로드 직후 `UPLOADING` 상태가 5초 이내에 표시되는지 확인한다.
3. 신규 성공 응답 뒤 `UPLOADED`와 마지막 결과 `created`가 표시되고, 여섯 로컬 파일의 size·SHA-256이 변하지 않는지 확인한다.
4. 연결을 끊어 request를 중단한다. `FAILED`가 표시되고 원본이 유지되는지 확인한다.
5. 같은 episode를 다시 전송한다. six-file bundle 전체를 새 요청으로 보내고, 동일 `Idempotency-Key`가 사용되는지 서버 로그 또는 계약 test double로 확인한다.
6. 신뢰되지 않는 인증서 또는 HTTP base URL로 실행을 시도한다. 앱이 request를 시작하지 않는지 확인한다.
