package com.ssafy.s15p21a206.tiger.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TigerDatabaseMigrationTest {
    @Test
    fun `version four migration adds a non null wall clock start timestamp`() {
        assertEquals(3, MIGRATION_3_4.startVersion)
        assertEquals(4, MIGRATION_3_4.endVersion)
        assertEquals(
            "ALTER TABLE sessions ADD COLUMN recordingStartEpochMs INTEGER NOT NULL DEFAULT 0",
            RECORDING_START_EPOCH_MIGRATION_SQL,
        )
    }

    @Test
    fun `version five migration adds the two session metadata columns`() {
        assertEquals(4, MIGRATION_4_5.startVersion)
        assertEquals(5, MIGRATION_4_5.endVersion)
        assertEquals(
            "ALTER TABLE sessions ADD COLUMN task TEXT NOT NULL DEFAULT ''",
            SESSION_METADATA_MIGRATION_SQL[0],
        )
        assertEquals(
            "ALTER TABLE sessions ADD COLUMN objectName TEXT NOT NULL DEFAULT ''",
            SESSION_METADATA_MIGRATION_SQL[1],
        )
    }

    /**
     * 컬럼만 더하고 끝내면 안 된다. 조회가 `episode_markers` 집계를 떠나 `sessions.task`를 읽으므로,
     * 채워 넣지 않으면 이미 쌓인 Session이 모두 이름 없는 Task로 떨어진다. 실제 SQLite에서 값이
     * 옮겨지는지는 `SessionMetadataMigrationTest`가 확인한다.
     */
    @Test
    fun `version five migration backfills both names from existing episode rows`() {
        val backfill = SESSION_METADATA_MIGRATION_SQL[2]

        assertTrue(backfill.contains("UPDATE sessions SET"))
        assertTrue(backfill.contains("MIN(NULLIF(episode_markers.task, ''))"))
        assertTrue(backfill.contains("MIN(NULLIF(episode_markers.objectName, ''))"))
        assertEquals(3, SESSION_METADATA_MIGRATION_SQL.size)
    }
}
