# 조사 원본

2026-09-17에 병렬로 돌린 두 조사의 원본. 각각 독립 관점 6개 + 합성 1개.

| 파일 | 질문 | 관점 |
|---|---|---|
| 조사1_로봇제어_관행지도.json | 로봇 제어는 원래 어떻게 하나 (격리, 노드 그래프, 제어 계층, 공정, 안전, 학습 정책) | isolation / node-graph / control-hierarchy / lifecycle / safety / learning-robot |
| 조사2_직접드라이버_범위.json | 정책 chunk에서 서보 축까지, 직접 만들면 무엇이 얼마나 드나 | vendor-stack / our-position / diy-scope / field-practice / timing / safety |

구조: `synthesis` = 합성 결과 (본문 문서 02~04의 근거), `views` = 관점별 원자료 (파일 경로·줄 번호·출처 포함).
합성의 disagreements / honestNotes 항목은 조사자들이 합의하지 못했거나 근거가 얇은 부분 — 본문에도 "정직한 유보"로 옮겨 둠.
