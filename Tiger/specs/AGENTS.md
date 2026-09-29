# SDD와 Spec Kit 작업 규칙

이 문서는 `specs/` 아래의 명세 산출물과 `$speckit-*` 작업에 적용된다. 루트 `AGENTS.md`의 지시에 따라 앱 코드만 수정하는 경우에도 task 완료 판정에는 이 규칙을 적용한다.

## Task 완료 판정

- `[X]`는 task의 acceptance criterion 전체가 충족됐다는 뜻이다. 모델, 클래스, 요청 생성기, DAO, 단위 테스트 중 일부만 존재하는 것은 완료 근거가 아니다.
- 구현은 production 호출 경로에 연결돼야 한다. UI·use case·worker·서비스 등 요구사항에 맞는 진입점에서 실제로 호출되지 않는 코드는 `미연결`이며 task를 `[X]`로 표시하지 않는다.
- 외부 의존성이 없는 상태 전이, 오류 처리, 재시도와 데이터 계약은 실제 endpoint·기기·계정이 없어도 fake 또는 mock server로 구현하고 자동 테스트한다. 외부 환경 부재를 이 범위의 미구현 사유로 사용하지 않는다.
- 실기기, 실제 서버, provider 권한처럼 자동화할 수 없는 acceptance criterion은 별도 task로 분리한다. 그 criterion이 남아 있으면 원래 task 전체를 `[X]`로 표시하지 않는다.
- 테스트되지 않았거나 호출 경로가 확인되지 않은 기존 `[X]`를 발견하면, 완료 이력을 꾸며내지 않는다. `[ ]`로 되돌리거나 구현·연결·외부 검증 task로 세분화한다.

## 완료 증거

task를 `[X]`로 바꾸기 전에 `tasks.md`의 해당 task 또는 같은 phase의 검증 기록에 아래 근거를 남긴다.

- 구현: 변경된 파일과 production 호출 경로
- 자동 검증: 테스트 파일·테스트명과 실행 명령·결과
- 외부 검증: 실기기·실서버 등 필요한 환경과 결과, 또는 아직 남은 별도 task

문서 task처럼 코드가 없는 경우에는 해당 산출물 경로와 검토 기준을 근거로 남긴다.

## 완료 전 수렴 검사

- `$speckit-implement`가 모든 task를 완료했다고 판단한 뒤, 완료 보고·commit·push 전에 `$speckit-converge`를 실행한다.
- converge가 spec·plan·tasks와 코드의 불일치를 remediation task로 추가하면, 그 task를 구현·검증한 뒤 다시 converge한다.
- converge 결과가 `converged`이고 위 완료 증거가 갖춰진 경우에만 완료를 보고한다.
- converge는 정적 대조 도구이므로, 실기기·실서버 검증 결과를 대신하지 않는다.
