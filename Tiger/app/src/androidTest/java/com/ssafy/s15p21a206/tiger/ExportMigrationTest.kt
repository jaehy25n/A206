package com.ssafy.s15p21a206.tiger

import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_2_3
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_5_6
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ExportMigrationTest {
    @Test
    fun migrationAddsExportPersistenceColumnsToVersionTwoSessionsTable() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val helper =
            FrameworkSQLiteOpenHelperFactory().create(
                SupportSQLiteOpenHelper.Configuration
                    .builder(context)
                    .name("migration-test.db")
                    .callback(
                        object : SupportSQLiteOpenHelper.Callback(2) {
                            override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                                db.execSQL(
                                    "CREATE TABLE sessions (sessionId TEXT NOT NULL PRIMARY KEY, displayNumber INTEGER NOT NULL, recordingState TEXT NOT NULL, uploadState TEXT NOT NULL, recordingStartNs INTEGER NOT NULL, recordingEndNs INTEGER, bundlePath TEXT NOT NULL)",
                                )
                            }

                            override fun onUpgrade(
                                db: androidx.sqlite.db.SupportSQLiteDatabase,
                                oldVersion: Int,
                                newVersion: Int,
                            ) = Unit
                        },
                    ).build(),
            )
        val db = helper.writableDatabase
        MIGRATION_2_3.migrate(db)
        val columns =
            db.query("PRAGMA table_info(sessions)").use { cursor ->
                buildSet { while (cursor.moveToNext()) add(cursor.getString(1)) }
            }

        assertTrue(columns.containsAll(setOf("exportState", "exportTreeUri", "exportFailureReason")))
        helper.close()
        context.deleteDatabase("migration-test.db")
    }

    /**
     * 내보내기를 걷어 내면서 그 세 컬럼을 지운다. `DROP COLUMN`을 쓸 수 없어 테이블을 다시 만드는
     * 이관이므로, 컬럼이 사라졌는지만이 아니라 이미 쌓인 Session이 그대로 옮겨졌는지도 본다.
     */
    @Test
    fun migrationDropsExportColumnsAndKeepsEverySession() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val helper =
            FrameworkSQLiteOpenHelperFactory().create(
                SupportSQLiteOpenHelper.Configuration
                    .builder(context)
                    .name("export-removal-test.db")
                    .callback(
                        object : SupportSQLiteOpenHelper.Callback(5) {
                            override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                                db.execSQL(VERSION_FIVE_SESSIONS_TABLE)
                                db.execSQL(
                                    "INSERT INTO sessions VALUES " +
                                        "('session-1', 1, 'COMPLETED', 'UPLOADED', 10, 20, '/managed/session-1', " +
                                        "'EXPORTED', 'content://tree', NULL, 1700, 'Door opening', 'cup')",
                                )
                            }

                            override fun onUpgrade(
                                db: androidx.sqlite.db.SupportSQLiteDatabase,
                                oldVersion: Int,
                                newVersion: Int,
                            ) = Unit
                        },
                    ).build(),
            )
        val db = helper.writableDatabase

        MIGRATION_5_6.migrate(db)

        val columns =
            db.query("PRAGMA table_info(sessions)").use { cursor ->
                buildSet { while (cursor.moveToNext()) add(cursor.getString(1)) }
            }
        assertTrue(
            "내보내기 컬럼이 남아 있다: $columns",
            columns.none { it in setOf("exportState", "exportTreeUri", "exportFailureReason") },
        )
        db.query("SELECT sessionId, bundlePath, task, objectName FROM sessions").use { cursor ->
            assertTrue("Session이 옮겨지지 않았다", cursor.moveToNext())
            assertEquals("session-1", cursor.getString(0))
            assertEquals("/managed/session-1", cursor.getString(1))
            assertEquals("Door opening", cursor.getString(2))
            assertEquals("cup", cursor.getString(3))
            assertFalse("옮기면서 행이 늘었다", cursor.moveToNext())
        }
        helper.close()
        context.deleteDatabase("export-removal-test.db")
    }

    private companion object {
        const val VERSION_FIVE_SESSIONS_TABLE =
            "CREATE TABLE sessions (" +
                "sessionId TEXT NOT NULL PRIMARY KEY, displayNumber INTEGER NOT NULL, " +
                "recordingState TEXT NOT NULL, uploadState TEXT NOT NULL, " +
                "recordingStartNs INTEGER NOT NULL, recordingEndNs INTEGER, bundlePath TEXT NOT NULL, " +
                "exportState TEXT NOT NULL DEFAULT 'NOT_EXPORTED', exportTreeUri TEXT, exportFailureReason TEXT, " +
                "recordingStartEpochMs INTEGER NOT NULL DEFAULT 0, " +
                "task TEXT NOT NULL DEFAULT '', objectName TEXT NOT NULL DEFAULT '')"
    }
}
