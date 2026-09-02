# 조사: Mobile Episode Transfer

## 1. HTTPS multipart 전송 방식

**결정**: OkHttp로 HTTPS multipart request를 만들고, MockWebServer로 contract test를 작성한다. Retrofit은 사용하지 않는다.

**근거**: OkHttp는 Android API 21 이상을 지원하는 HTTP client이며 multipart request body와 response lifecycle을 제공한다. 파일 기반 `RequestBody`와 `MultipartBody`를 사용하면 episode 동영상을 앱 heap에 전부 적재하지 않고 socket sink에 쓸 수 있다. MockWebServer는 request method·header·multipart part·response fixture를 실제 HTTP 흐름으로 검증한다. 단일 대용량 upload endpoint는 Retrofit annotation/interface보다 OkHttp request builder가 계약 제어와 테스트를 더 직접적으로 표현한다.

**대안**:

- `HttpsURLConnection` 직접 구현: 가능하지만 multipart framing·redirect·error body·test server를 직접 유지해야 하므로 제외한다.
- Retrofit: OkHttp 위에 추가 계층을 두지만 이번 MVP에는 하나의 upload API만 있고, multipart file body·receipt 검증을 직접 제어해야 하므로 제외한다.
- 전체 multipart body buffering: 큰 MP4에서 heap 사용량과 실패 위험이 커서 제외한다.

**출처**: [OkHttp 공식 저장소](https://github.com/square/okhttp), [Android network operations overview](https://developer.android.com/develop/connectivity/network-ops?hl=en)

## 2. HTTPS와 인증서 신뢰

**결정**: build-time base URL은 `https`만 허용하고, 기본 Android trust store가 신뢰하는 인증서만 사용한다. custom `TrustManager`, self-signed certificate 우회, cleartext 예외는 만들지 않는다.

**근거**: MVP가 인증 없는 폐쇄망이라도 영상·IMU 원본의 기밀성과 무결성을 위해 TLS가 필요하다. Android network security configuration은 cleartext 차단과 trust anchor 설정을 선언적으로 지원한다. 서버 인증서가 대상 Galaxy S10에서 신뢰되지 않으면 앱은 업로드를 시도하지 않으며, 서버 운영 측이 신뢰 가능한 인증서를 제공해야 한다.

**대안**:

- HTTP 허용: 사용자 결정인 HTTPS 전용 제약과 맞지 않아 제외한다.
- 인증서 검증 우회 또는 모든 self-signed 인증서 허용: 중간자 공격을 허용하므로 제외한다.
- certificate pinning: 서버 인증서 교체 절차가 정의되지 않아 MVP에는 추가하지 않는다.

**출처**: [Android Network Security Configuration](https://developer.android.com/privacy-and-security/security-config), [Android cleartext communications guidance](https://developer.android.com/privacy-and-security/risks/cleartext-communications?hl=en)

## 3. 네트워크 권한과 상태 확인

**결정**: 구현 전에 `INTERNET`과 `ACCESS_NETWORK_STATE` 권한 및 cleartext 차단 network security config를 사용자 승인 후 Manifest에 선언한다. network state는 사전 안내 용도일 뿐, 실제 request 결과가 최종 성공/실패 판단 기준이다.

**근거**: Android는 네트워크 연결에 `INTERNET`을 요구하며, `ACCESS_NETWORK_STATE`로 연결 상태를 확인할 수 있다. 연결되어 보이더라도 서버 도달·TLS 검증·HTTP 응답이 보장되지 않으므로 업로드 상태는 실제 request 결과로만 확정해야 한다.

**대안**:

- 연결 상태만 보고 성공 처리: captive portal, 서버 장애, TLS 실패를 놓치므로 제외한다.
- 권한 없이 platform client 사용: 네트워크 요청 자체가 불가능하므로 제외한다.

**출처**: [Android network connection guidance](https://developer.android.com/develop/connectivity/network-ops/connecting)

## 4. URL 주입과 운영값

**결정**: 서버 base URL은 빌드 시 주입하고 앱 내 설정 화면·저장소·문서에 실제 값을 두지 않는다. 앱 timeout은 API 계약의 connect 10초/read 30초/write 120초를 사용한다. server body-size limit는 배포 설정이지만 모바일 계약에는 숫자를 고정하지 않고 `413 PAYLOAD_TOO_LARGE` 응답으로만 드러낸다.

**근거**: 사용자가 URL을 입력하면 잘못된 endpoint로 원본을 보내는 위험이 있고, MVP는 정해진 폐쇄망 서버에 연결한다. 실제 운영 값은 환경별로 다르며 저장소에 넣으면 private URL 노출 위험이 있다.

**대안**:

- 앱 내 URL 설정 UI: 사용자 결정과 반대이며 운영 오류 범위가 넓어진다.
- source code 상수: private URL을 버전 관리에 남길 수 있어 제외한다.

## 5. 중복·재시도·상태 전이

**결정**: `episode_id`를 매 요청의 `Idempotency-Key`로 사용한다. 신규 `201 Created`와 중복 `200 OK`의 JSON receipt가 일치할 때만 `UPLOADED`로 전이한다. 성공 조건을 만족하지 않는 모든 HTTP·transport 결과는 `FAILED` 마지막 시도로 저장하며, 수집자는 필요할 때 six-file bundle 전체를 수동 재전송한다.

**근거**: timeout 뒤 서버가 실제로 저장했는지 앱이 모르는 경우가 있으므로, 같은 key와 duplicate receipt가 중복 생성을 막고 결과를 복구한다. 업로드 재개 세션을 배제한 MVP에서도 전체 재전송과 idempotency가 정확한 단순 모델을 제공한다.

**대안**:

- 매 재시도마다 새 식별자 사용: 서버 중복 수집을 만들 수 있어 제외한다.
- 모든 오류를 재시도: 데이터 검증 오류가 끝없이 반복될 수 있어 제외한다.
- offset 재개: 별도 업로드 세션·오프셋 계약이 필요하며 범위 밖이다.

## 6. 로컬 episode catalog 영속화

**결정**: completed episode의 목록·UploadState·UploadAttempt·CaptureLog는 Room database로 저장한다. 영상과 CSV 원본은 기존 앱 전용 파일 저장소에 유지하며 Room에는 상대 경로와 query용 metadata만 저장한다.

**근거**: episode 목록은 recording state, upload state, 마지막 시도 결과, 시간 순 정렬·삭제를 함께 다루는 구조화된 데이터다. Room은 SQLite 위의 Android Jetpack abstraction으로 compile-time query 검증과 migration 경로를 제공한다. upload 중 앱이 종료된 episode도 다음 시작에서 `FAILED` 마지막 시도로 복구하는 기준을 Room transaction으로 일관되게 갱신할 수 있다.

**대안**:

- DataStore: key-value 설정에는 적합하지만 다수 episode의 정렬·상태 갱신·삭제 query에는 맞지 않아 제외한다.
- 파일 기반 catalog JSON: 작은 prototype에는 가능하지만 상태 recovery와 schema 변경 검증이 약해 제외한다.

**출처**: [Android Room guide](https://developer.android.com/training/data-storage/room?hl=en)

## 7. 비동기·UI 상태·JSON schema

**결정**: Coroutines Android로 camera/file/database/network I/O를 main thread 밖에서 실행하고, Room Flow를 `collectAsStateWithLifecycle`로 Compose UI에 수집한다. Kotlinx Serialization으로 `metadata.json`, server receipt, API error model을 직렬화한다.

**근거**: Android는 Compose UI에서 lifecycle-aware Flow 수집과 장기 작업의 coroutine 사용을 권장한다. metadata와 API receipt는 명시적 field name(`episode_id`, 나노초 문자열)을 가진 계약이므로 typed serialization이 수동 JSON parsing보다 안전하다.

**대안**:

- `org.json`: 작은 response에는 가능하지만 metadata와 error schema의 compile-time 구조 검증을 제공하지 않아 제외한다.
- Hilt: 현재 단일 app·작은 객체 graph에는 수동 constructor injection보다 설정 비용이 크다.

**출처**: [Compose Lifecycle guidance](https://developer.android.com/topic/libraries/architecture/lifecycle?hl=en)
