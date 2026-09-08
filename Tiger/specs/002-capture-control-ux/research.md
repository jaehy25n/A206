# 조사: Capture Control UX

## 결정: 원시 데이터는 DB blob이 아닌 내부 파일 bundle로 유지

**근거**: 영상·CSV 스트림은 이미 검증 가능한 불변 bundle이다. 기존 root를 앱 전용 내부 파일 저장소로 옮기면 일반 파일 관리자 삭제를 막으면서 finalize·manifest 검증·export·multipart 업로드 계약을 유지할 수 있다. Room은 목록·상세 색인에 적합하다.

**검토한 대안**:

- 원시 영상·CSV를 Room에 저장: 대용량 binary 저장은 기존 bundle 계약을 개선하지 못하고 export·upload를 불필요하게 복잡하게 만든다.
- 앱 전용 외부 저장소 유지: 파일 삭제에 따른 불일치를 해소하지 못한다.

## 결정: 관리 root 검증으로 legacy 외부 bundle 제외

**근거**: 기존 완료 행은 Room에 남겨도 된다. repository는 canonical bundle path가 내부 completed root 하위일 때만 Session을 노출하고 직접 업로드도 같은 조건으로 막는다. 복사·삭제·DB migration 없이 이전 데이터 제외 요구를 충족한다.

**검토한 대안**:

- legacy bundle을 내부 저장소로 복사: 합의된 범위 밖이다.
- legacy 행이나 파일 삭제: 사용자가 파괴적 정리를 승인하지 않았다.
- 문자열 prefix 필터: 정규화되지 않은 경로에서 안전하지 않다.

## 결정: 업로드 상태 화면이 취소 가능한 전송 작업 소유

**근거**: 현재 업로드 서비스는 종료 상태만 제공한다. 화면이 소유한 coroutine 작업에서 취소를 실제 HTTP 요청까지 전달하면, 확인된 이탈 또는 백그라운드 전환 시 `UPLOADING`을 `FAILED`로 남길 수 있다. 서버 진행률 API는 없으므로 기존 HTTP 응답이 올 때까지 비결정적 진행 표시를 쓴다.

**검토한 대안**:

- 사용자 시작 데이터 전송 작업 또는 전면 서비스로 백그라운드 계속 전송: 백그라운드 전환 시 취소한다는 UX와 맞지 않는다.
- Session Detail에 전송 수명주기 결합: Detail은 시작만 담당하고, 진행·취소는 업로드 상태 화면이 담당해야 한다.

## 결정: 새 navigation 의존성 없이 명시적 화면 상태 사용

**근거**: 현재 앱은 단일 Compose root이고 navigation 라이브러리가 없다. List·Capture Workspace·Detail·Upload Status의 sealed 목적지와 콜백은 의존성 추가 없이 결정론적 뒤로 가기와 테스트 가능한 화면 전환을 제공한다.

**검토한 대안**:

- Navigation Compose 추가: 의존성 추가는 별도 승인 대상이므로 보류한다.

## 결정: 라이브 프리뷰 준비와 녹화 시작 분리

**근거**: 현재 runtime은 카메라·ARCore·writer를 함께 시작하고 화면에 렌더링된 프리뷰가 없다. 작업 공간은 권한·AR preflight 이후 프리뷰 전용 camera surface를 준비하고, 유효한 task/object와 첫 재생 이후에만 원시 녹화를 시작해야 한다. 프리뷰 실패 시 재생을 막고 다음 행동을 안내한다.

**검토한 대안**:

- 녹화 surface를 프리뷰로 간주: Session 생성과 원시 녹화보다 먼저 프리뷰를 보여야 하는 요구와 맞지 않는다.
- 프리뷰 생략: 핵심 사용자 흐름을 충족하지 못한다.

## 결정: 로컬 벽시계 수집 시작 시각 추가

**근거**: 기존 monotonic timestamp로는 길이는 계산할 수 있지만 앱 재시작 뒤 표시할 날짜·시각은 만들 수 없다. Room migration으로 새 Session에만 로컬 벽시계 시작 시각을 기록하며, 원시 bundle과 서버 multipart 계약은 바꾸지 않는다.

**검토한 대안**:

- 길이만 표시: Session Detail의 수집 시각 요구와 맞지 않는다.
- monotonic time에서 벽시계 time 추론: 기기 재시작 뒤 안정적이지 않고 달력 시각을 보장하지 못한다.
