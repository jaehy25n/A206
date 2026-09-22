package com.ssafy.s15p21a206.tiger

import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_4_5
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Task와 Object를 Session 행으로 옮기는 이관.
 *
 * 컬럼이 생기는지만 보지 않는다. 이관 뒤 조회는 `episode_markers` 집계가 아니라 `sessions.task`를
 * 읽으므로, 채워 넣기가 빠지면 이미 쌓인 Session이 전부 이름 없는 Task로 떨어진다. 그 채워 넣기가
 * 실제 SQLite에서 동작하는지 여기서 확인한다.
 */
class SessionMetadataMigrationTest {
    @Test
    fun migrationMovesTaskAndObjectFromEpisodeRowsOntoTheirSession() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val helper = openVersionFourDatabase()
        val db = helper.writableDatabase

        MIGRATION_4_5.migrate(db)

        val columns =
            db.query("PRAGMA table_info(sessions)").use { cursor ->
                buildSet { while (cursor.moveToNext()) add(cursor.getString(1)) }
            }
        assertTrue(columns.containsAll(setOf("task", "objectName")))

        // Episode가 있는 Session은 그 행의 값으로 채워진다. 두 Episode가 같은 값을 갖는 것은
        // 다이얼로그가 Session당 한 번만 열리기 때문이다.
        assertEquals("Door opening" to "cup", namesOf(db, "with-episodes"))
        // 값이 빈 Episode 행은 건너뛴다. 떠나는 집계의 `NULLIF`와 같은 판정이다.
        assertEquals("pick" to "block", namesOf(db, "blank-first-episode"))
        // 채울 행이 없는 Session은 빈 채로 남는다. 이관 시점에 두 이름은 어디에도 없었다.
        assertEquals("" to "", namesOf(db, "no-episodes"))

        helper.close()
        context.deleteDatabase(DATABASE_NAME)
    }

    private fun namesOf(
        db: SupportSQLiteDatabase,
        sessionId: String,
    ): Pair<String, String> =
        db.query("SELECT task, objectName FROM sessions WHERE sessionId = ?", arrayOf(sessionId)).use { cursor ->
            assertTrue(cursor.moveToFirst())
            cursor.getString(0) to cursor.getString(1)
        }

    /** 이관 직전 상태를 만든다. `sessions`에는 두 이름이 없고 `episode_markers`에만 있다. */
    private fun openVersionFourDatabase(): SupportSQLiteOpenHelper =
        FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration
                .builder(ApplicationProvider.getApplicationContext())
                .name(DATABASE_NAME)
                .callback(
                    object : SupportSQLiteOpenHelper.Callback(4) {
                        override fun onCreate(db: SupportSQLiteDatabase) {
                            db.execSQL(
                                "CREATE TABLE sessions (sessionId TEXT NOT NULL PRIMARY KEY, displayNumber INTEGER NOT NULL, " +
                                    "recordingState TEXT NOT NULL, uploadState TEXT NOT NULL, recordingStartNs INTEGER NOT NULL, " +
                                    "recordingEndNs INTEGER, bundlePath TEXT NOT NULL, exportState TEXT NOT NULL DEFAULT 'NOT_EXPORTED', " +
                                    "exportTreeUri TEXT, exportFailureReason TEXT, recordingStartEpochMs INTEGER NOT NULL DEFAULT 0)",
                            )
                            db.execSQL(
                                "CREATE TABLE episode_markers (episodeId TEXT NOT NULL PRIMARY KEY, sessionId TEXT NOT NULL, " +
                                    "startTimestampNs INTEGER NOT NULL, endTimestampNs INTEGER, task TEXT NOT NULL, " +
                                    "objectName TEXT NOT NULL, outcome TEXT NOT NULL)",
                            )
                            listOf("with-episodes", "blank-first-episode", "no-episodes").forEachIndexed { index, sessionId ->
                                db.execSQL(
                                    "INSERT INTO sessions VALUES (?, ?, 'COMPLETED', 'LOCAL_ONLY', 1, 2, ?, 'NOT_EXPORTED', NULL, NULL, 100)",
                                    arrayOf<Any>(sessionId, index + 1, "/bundles/$sessionId"),
                                )
                            }
                            insertEpisode(db, "e1", "with-episodes", "Door opening", "cup")
                            insertEpisode(db, "e2", "with-episodes", "Door opening", "cup")
                            insertEpisode(db, "e3", "blank-first-episode", "", "")
                            insertEpisode(db, "e4", "blank-first-episode", "pick", "block")
                        }

                        override fun onUpgrade(
                            db: SupportSQLiteDatabase,
                            oldVersion: Int,
                            newVersion: Int,
                        ) = Unit
                    },
                ).build(),
        )

    private fun insertEpisode(
        db: SupportSQLiteDatabase,
        episodeId: String,
        sessionId: String,
        task: String,
        objectName: String,
    ) = db.execSQL(
        "INSERT INTO episode_markers VALUES (?, ?, 1, 2, ?, ?, 'COMPLETED')",
        arrayOf(episodeId, sessionId, task, objectName),
    )

    private companion object {
        const val DATABASE_NAME = "session-metadata-migration-test.db"
    }
}
