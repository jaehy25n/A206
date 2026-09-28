# 3. DB 덤프

## 이 프로젝트의 저장소 구성

서버 측 RDBMS(MySQL, PostgreSQL 등)는 없다. 데이터는 두 곳에 있다.

| 저장소 | 위치 | 내용 |
|---|---|---|
| **SQLite (Room)** | 수집 기기 `/data/data/com.ssafy.s15p21a206.tigermask/databases/tiger.db` | Session·Episode 색인 (이 폴더의 덤프 대상) |
| 파일시스템 | 기기 `capture/completed/<sessionId>/`, EC2 `/srv/sessions`, `/srv/processed/v1` | 영상·CSV·metadata.json 번들. DB가 아니므로 덤프 대상 아님 |

## 파일

| 파일 | 내용 |
|---|---|
| `tiger_db_dump.sql` | Room 스키마 version 7의 DDL. 엔티티 정의(`TigerDatabase.kt`)에서 옮겼다 |

`tiger_db_dump.sql` 에는 **스키마만 있고 행은 없다.** 이 앱의 행은 수집 기기마다 따로 쌓인다. 기기에서 최신본을 뽑으려면 아래를 실행한다.

## ERD

```text
┌──────────────────────────────┐         ┌──────────────────────────────┐
│ sessions                     │         │ episode_markers              │
├──────────────────────────────┤         ├──────────────────────────────┤
│ PK sessionId      TEXT       │ 1     N │ PK episodeId        TEXT     │
│    displayNumber  INTEGER    │◀────────│    sessionId        TEXT     │
│    recordingState TEXT       │         │    startTimestampNs INTEGER  │
│    uploadState    TEXT       │         │    endTimestampNs   INTEGER? │
│    recordingStartNs INTEGER  │         │    task             TEXT     │
│    recordingEndNs INTEGER?   │         │    objectName       TEXT     │
│    bundlePath     TEXT       │         │    outcome          TEXT     │
│    recordingStartEpochMs INT │         └──────────────────────────────┘
│    task           TEXT       │
│    objectName     TEXT       │
└──────────────────────────────┘
```

외래키 제약은 선언돼 있지 않다. Session을 지울 때 앱이 `episode_markers` 를 먼저 지운다.

## 기기에서 최신 덤프 뽑기

debug 빌드는 `run-as` 로 앱 데이터에 접근할 수 있다.

```bash
adb exec-out run-as com.ssafy.s15p21a206.tigermask cat databases/tiger.db > tiger.db
adb exec-out run-as com.ssafy.s15p21a206.tigermask cat databases/tiger.db-wal > tiger.db-wal
sqlite3 tiger.db .dump > tiger_db_dump_full.sql
```

WAL 파일을 함께 받아야 마지막 쓰기까지 들어간다. 앱을 완전히 종료한 뒤 받는 것이 안전하다.
