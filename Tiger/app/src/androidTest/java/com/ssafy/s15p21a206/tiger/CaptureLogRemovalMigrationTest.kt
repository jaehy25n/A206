package com.ssafy.s15p21a206.tiger

import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_6_7
import org.junit.Assert.assertEquals
import org.junit.Test

class CaptureLogRemovalMigrationTest {
    /**
     * 쓰이지 않던 `capture_logs`를 걷어낸다.
     *
     * 테이블만 지우는 이관이라 단순해 보이지만, 남겨 두면 Room이 엔티티에서 만든 스키마와 실제
     * 스키마를 견줄 때 불일치로 잡는다. 실제 SQLite에서 테이블이 사라지는지와, 같은 데이터베이스의
     * 다른 테이블이 그대로 남는지를 함께 본다.
     */
    @Test
    fun migrationDropsTheCaptureLogTableAndLeavesTheRest() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val helper =
            FrameworkSQLiteOpenHelperFactory().create(
                SupportSQLiteOpenHelper.Configuration
                    .builder(context)
                    .name("capture-log-removal-test.db")
                    .callback(
                        object : SupportSQLiteOpenHelper.Callback(6) {
                            override fun onCreate(db: SupportSQLiteDatabase) {
                                db.execSQL(
                                    "CREATE TABLE capture_logs (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                                        "sessionId TEXT, reason TEXT NOT NULL, summary TEXT NOT NULL, " +
                                        "timestampNs INTEGER NOT NULL, frameCount INTEGER NOT NULL, " +
                                        "accelerometerCount INTEGER NOT NULL, gyroscopeCount INTEGER NOT NULL, " +
                                        "rotationVectorCount INTEGER NOT NULL)",
                                )
                                db.execSQL(
                                    "CREATE TABLE episode_markers (episodeId TEXT NOT NULL PRIMARY KEY, " +
                                        "sessionId TEXT NOT NULL, startTimestampNs INTEGER NOT NULL, " +
                                        "endTimestampNs INTEGER, task TEXT NOT NULL, objectName TEXT NOT NULL, " +
                                        "outcome TEXT NOT NULL)",
                                )
                                db.execSQL(
                                    "INSERT INTO episode_markers VALUES ('episode-1', 'session-1', 10, 20, 'open', 'cup', 'COMPLETED')",
                                )
                            }

                            override fun onUpgrade(
                                db: SupportSQLiteDatabase,
                                oldVersion: Int,
                                newVersion: Int,
                            ) = Unit
                        },
                    ).build(),
            )
        val db = helper.writableDatabase

        MIGRATION_6_7.migrate(db)

        val tables =
            db.query("SELECT name FROM sqlite_master WHERE type = 'table'").use { cursor ->
                buildSet { while (cursor.moveToNext()) add(cursor.getString(0)) }
            }
        assertEquals("capture_logs가 남아 있다: $tables", false, tables.contains("capture_logs"))
        assertEquals("episode_markers가 사라졌다: $tables", true, tables.contains("episode_markers"))

        val markers =
            db.query("SELECT COUNT(*) FROM episode_markers").use { cursor ->
                cursor.moveToFirst()
                cursor.getInt(0)
            }
        assertEquals(1, markers)

        helper.close()
        context.deleteDatabase("capture-log-removal-test.db")
    }
}
