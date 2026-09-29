# SAF Export 조사

> (2026-09-22) SAF 내보내기가 철회되어 아래 결정은 모두 더 이상 유효하지 않다. export 상태 컬럼은
> 이관 5→6에서 지웠다. 무엇을 거뒀는지는 [기능 명세](spec.md)의 철회된 범위에 있고, 이 문서는
> 기록으로 남긴다.

## Decision: Storage Access Framework tree URI를 사용한다

**Rationale:** 사용자가 선택한 directory provider 하위에서만 문서를 생성할 수 있고, broad storage permission 없이 Documents를 포함한 사용자 선택 저장소에 쓸 수 있다. picker는 Documents 위치에서 시작하지만 선택된 tree URI의 범위를 넘지 않는다.

**Alternatives considered:** 공유 저장소 파일 API와 broad storage permission은 사용자 선택·권한 경계 요구사항에 맞지 않아 제외한다.

## Decision: persistable URI grant를 재시도용으로 보존한다

**Rationale:** 마지막 선택 tree를 앱 재시작 후에도 재사용해야 한다. 매 export 전 grant 유효성을 확인하고, 철회된 경우 새 picker 선택으로 복구한다.

**Alternatives considered:** 매번 tree를 선택하는 방식은 확정된 UX와 맞지 않아 제외한다.

## Decision: source와 destination을 모두 bundle validator로 검증한다

**Rationale:** `metadata.json`이 마지막 commit marker인 completed source만 복사하고, destination에서는 required files, CSV headers, metadata stream declaration 및 manifest size/SHA-256을 다시 검사해야 한다.

**Alternatives considered:** copy 완료만으로 성공 처리하면 provider I/O 오류나 불완전 bundle을 발견하지 못해 제외한다.

## Decision: 임시 attempt directory 검증 뒤 최종 directory로 publish한다

**Rationale:** 일반적인 document/file export 방식처럼 새 임시 directory에 전체 bundle을 복사·검증한 뒤 최종 이름으로 publish하면, final directory에 unvalidated partial file이 남는 것을 막을 수 있다. failed attempt directory는 자동 삭제하지 않고, retry는 새 attempt로 처음부터 수행한다.

**Alternatives considered:** final directory로 직접 copy하면 partial/stale document가 exact-bundle 계약과 충돌한다. failed attempt cleanup은 destructive operation이므로 제외한다. provider가 create/write/enumerate/rename/delete를 지원하지 않으면 안전한 publish가 불가능하므로 다른 tree를 선택해야 한다.

## Decision: export state는 session catalog에 영속화한다

**Rationale:** export state·마지막 tree URI·failure reason은 재시작 retry에 필요하다. Room schema migration은 프로젝트 규칙상 구현 전 별도 승인을 받아야 한다.

**Alternatives considered:** 메모리만 사용하는 상태는 재시작 retry 요구를 만족하지 못한다.
