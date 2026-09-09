package com.ssafy.s15p21a206.tiger.data.local

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "sessions")
data class CaptureSessionEntity(
    @PrimaryKey val sessionId: String,
    val displayNumber: Int,
    val recordingState: String,
    val uploadState: String,
    val recordingStartNs: Long,
    val recordingEndNs: Long?,
    val bundlePath: String,
    val exportState: String = "NOT_EXPORTED",
    val exportTreeUri: String? = null,
    val exportFailureReason: String? = null,
    val recordingStartEpochMs: Long = 0L,
)

data class SessionSummaryEntity(
    val sessionId: String,
    val displayNumber: Int,
    val uploadState: String,
    val recordingStartEpochMs: Long,
    val recordingStartNs: Long,
    val recordingEndNs: Long?,
    val bundlePath: String,
    val completedEpisodeCount: Int,
    val taskName: String = "",
)

@Entity(tableName = "episode_markers")
data class EpisodeMarkerEntity(
    @PrimaryKey val episodeId: String,
    val sessionId: String,
    val startTimestampNs: Long,
    val endTimestampNs: Long?,
    val task: String,
    val objectName: String,
    val outcome: String,
)

@Entity(tableName = "capture_logs")
data class CaptureLogEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val sessionId: String?,
    val reason: String,
    val summary: String,
    val timestampNs: Long,
    val frameCount: Long,
    val accelerometerCount: Long,
    val gyroscopeCount: Long,
    val rotationVectorCount: Long,
)

@Dao
interface CaptureSessionDao {
    @Query("SELECT * FROM sessions WHERE recordingState = 'COMPLETED' ORDER BY recordingStartNs DESC")
    fun observeCompleted(): Flow<List<CaptureSessionEntity>>

    @Query(
        """
        SELECT sessions.sessionId, sessions.displayNumber, sessions.uploadState,
               sessions.recordingStartEpochMs, sessions.recordingStartNs, sessions.recordingEndNs,
               sessions.bundlePath,
               COUNT(CASE WHEN episode_markers.outcome = 'COMPLETED' THEN 1 END) AS completedEpisodeCount,
               COALESCE(MIN(NULLIF(episode_markers.task, '')), '') AS taskName
        FROM sessions
        LEFT JOIN episode_markers ON episode_markers.sessionId = sessions.sessionId
        WHERE sessions.recordingState = 'COMPLETED'
        GROUP BY sessions.sessionId
        ORDER BY sessions.recordingStartNs DESC
        """,
    )
    fun observeCompletedSummaries(): Flow<List<SessionSummaryEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(session: CaptureSessionEntity)

    @Query("UPDATE sessions SET uploadState = :uploadState WHERE sessionId = :sessionId")
    suspend fun updateUploadState(
        sessionId: String,
        uploadState: String,
    )

    @Query("UPDATE sessions SET uploadState = 'FAILED' WHERE uploadState = 'UPLOADING'")
    suspend fun failInterruptedUploads()

    @Query(
        "UPDATE sessions SET exportState = :state, exportTreeUri = :treeUri, exportFailureReason = :failureReason WHERE sessionId = :sessionId",
    )
    suspend fun updateExport(
        sessionId: String,
        state: String,
        treeUri: String?,
        failureReason: String?,
    )

    @Query("SELECT * FROM sessions WHERE sessionId = :sessionId AND recordingState = 'COMPLETED' LIMIT 1")
    suspend fun completedSession(sessionId: String): CaptureSessionEntity?

    @Query("SELECT * FROM sessions WHERE sessionId = :sessionId LIMIT 1")
    suspend fun session(sessionId: String): CaptureSessionEntity?

    @Query("SELECT * FROM sessions WHERE recordingState IN ('INITIALIZING', 'READY', 'FINALIZING')")
    suspend fun activeSessions(): List<CaptureSessionEntity>

    @Query("SELECT * FROM sessions ORDER BY recordingStartEpochMs ASC, recordingStartNs ASC, sessionId ASC")
    suspend fun sessionsInCaptureOrder(): List<CaptureSessionEntity>

    @Query("UPDATE sessions SET displayNumber = :displayNumber WHERE sessionId = :sessionId")
    suspend fun updateDisplayNumber(
        sessionId: String,
        displayNumber: Int,
    )

    @Query("SELECT COALESCE(MAX(displayNumber), 0) + 1 FROM sessions")
    suspend fun nextDisplayNumber(): Int
}

@Dao
interface EpisodeMarkerDao {
    @Query("SELECT * FROM episode_markers WHERE sessionId = :sessionId ORDER BY startTimestampNs")
    fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(marker: EpisodeMarkerEntity)
}

@Dao
interface CaptureLogDao {
    @Insert suspend fun insert(log: CaptureLogEntity)

    @Query("DELETE FROM capture_logs")
    suspend fun clearAll()
}

@Database(entities = [CaptureSessionEntity::class, EpisodeMarkerEntity::class, CaptureLogEntity::class], version = 4, exportSchema = false)
abstract class TigerDatabase : RoomDatabase() {
    abstract fun captureSessionDao(): CaptureSessionDao

    abstract fun episodeMarkerDao(): EpisodeMarkerDao

    abstract fun captureLogDao(): CaptureLogDao
}

val MIGRATION_2_3 =
    object : Migration(2, 3) {
        override fun migrate(db: SupportSQLiteDatabase) {
            EXPORT_MIGRATION_SQL.forEach(db::execSQL)
        }
    }

val EXPORT_MIGRATION_SQL =
    listOf(
        "ALTER TABLE sessions ADD COLUMN exportState TEXT NOT NULL DEFAULT 'NOT_EXPORTED'",
        "ALTER TABLE sessions ADD COLUMN exportTreeUri TEXT",
        "ALTER TABLE sessions ADD COLUMN exportFailureReason TEXT",
    )

val MIGRATION_3_4 =
    object : Migration(3, 4) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("ALTER TABLE sessions ADD COLUMN recordingStartEpochMs INTEGER NOT NULL DEFAULT 0")
        }
    }
