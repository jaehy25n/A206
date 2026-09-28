-- Tiger 앱 로컬 DB 덤프 (SQLite, Room)
--   DB 파일 : /data/data/com.ssafy.s15p21a206.tigermask/databases/tiger.db
--   스키마  : Room version 7 (Tiger/app/src/main/java/com/ssafy/s15p21a206/tiger/data/local/TigerDatabase.kt)
--   작성일  : 2026-09-28
--
-- 스키마는 엔티티 정의 그대로다. 수집 기기의 실제 행은 들어 있지 않다.
-- 기기에서 최신본을 뽑는 방법은 README.md 에 있다.

PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;

-- 한 번의 수집(Session). 마감된 번들은 bundlePath 아래 capture/completed/<sessionId>/ 에 있다.
CREATE TABLE IF NOT EXISTS `sessions` (
    `sessionId`             TEXT    NOT NULL,   -- UUID. 서버 업로드의 Idempotency-Key
    `displayNumber`         INTEGER NOT NULL,   -- 화면에 보이는 "Session N"
    `recordingState`        TEXT    NOT NULL,   -- INITIALIZING | READY | FINALIZING | COMPLETED | INTERRUPTED
    `uploadState`           TEXT    NOT NULL,   -- LOCAL_ONLY | UPLOADING | UPLOADED | FAILED
    `recordingStartNs`      INTEGER NOT NULL,   -- 부팅 기준 경과 시간(ns)
    `recordingEndNs`        INTEGER,
    `bundlePath`            TEXT    NOT NULL,
    `recordingStartEpochMs` INTEGER NOT NULL,   -- 절대 시각(ms). 목록 정렬 기준
    `task`                  TEXT    NOT NULL,   -- 수집 정보 입력의 Task
    `objectName`            TEXT    NOT NULL,   -- 수집 정보 입력의 Object
    PRIMARY KEY(`sessionId`)
);

-- Session 안의 작업 구간(Episode). sessionId 로 sessions 를 참조한다 (FK 제약은 선언하지 않음).
CREATE TABLE IF NOT EXISTS `episode_markers` (
    `episodeId`        TEXT    NOT NULL,
    `sessionId`        TEXT    NOT NULL,        -- → sessions.sessionId (N:1)
    `startTimestampNs` INTEGER NOT NULL,        -- 카메라 SENSOR_TIMESTAMP 기준
    `endTimestampNs`   INTEGER,
    `task`             TEXT    NOT NULL,
    `objectName`       TEXT    NOT NULL,
    `outcome`          TEXT    NOT NULL,        -- ACTIVE | COMPLETED | INVALID_TRACKING
    PRIMARY KEY(`episodeId`)
);

-- Room 내부 테이블
CREATE TABLE IF NOT EXISTS room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT);
PRAGMA user_version = 7;

COMMIT;
