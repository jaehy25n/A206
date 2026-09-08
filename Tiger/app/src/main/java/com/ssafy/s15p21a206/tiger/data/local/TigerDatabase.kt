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
            db.execSQL(RECORDING_START_EPOCH_MIGRATION_SQL)
        }
    }

const val RECORDING_START_EPOCH_MIGRATION_SQL =
    "ALTER TABLE sessions ADD COLUMN recordingStartEpochMs INTEGER NOT NULL DEFAULT 0"
