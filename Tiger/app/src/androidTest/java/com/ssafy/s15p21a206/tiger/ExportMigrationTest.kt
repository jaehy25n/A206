package com.ssafy.s15p21a206.tiger

import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_2_3
import org.junit.Assert.assertTrue
import org.junit.Test

class ExportMigrationTest {
    @Test
    fun migrationAddsExportPersistenceColumnsToVersionTwoSessionsTable() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-test.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(2) {
                    override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                        db.execSQL("CREATE TABLE sessions (sessionId TEXT NOT NULL PRIMARY KEY, displayNumber INTEGER NOT NULL, recordingState TEXT NOT NULL, uploadState TEXT NOT NULL, recordingStartNs INTEGER NOT NULL, recordingEndNs INTEGER, bundlePath TEXT NOT NULL)")
                    }
                    override fun onUpgrade(db: androidx.sqlite.db.SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
                }).build()
        )
        val db = helper.writableDatabase
        MIGRATION_2_3.migrate(db)
        val columns = db.query("PRAGMA table_info(sessions)").use { cursor -> buildSet { while (cursor.moveToNext()) add(cursor.getString(1)) } }

        assertTrue(columns.containsAll(setOf("exportState", "exportTreeUri", "exportFailureReason")))
        helper.close()
        context.deleteDatabase("migration-test.db")
    }
}
