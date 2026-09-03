package com.ssafy.s15p21a206.tiger.data.local

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "sessions")
data class CaptureSessionEntity(
    @PrimaryKey val sessionId: String,
    val displayNumber: Int,
    val recordingState: String,
    val uploadState: String,
    val recordingStartNs: Long,
    val recordingEndNs: Long?,
    val bundlePath: String
)

@Entity(tableName = "episode_markers")
data class EpisodeMarkerEntity(
    @PrimaryKey val episodeId: String,
    val sessionId: String,
    val startTimestampNs: Long,
    val endTimestampNs: Long?,
    val task: String,
    val objectName: String,
    val outcome: String
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
    val rotationVectorCount: Long
)

@Dao
interface CaptureSessionDao {
    @Query("SELECT * FROM sessions WHERE recordingState = 'COMPLETED' ORDER BY recordingStartNs DESC")
    fun observeCompleted(): Flow<List<CaptureSessionEntity>>
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsert(session: CaptureSessionEntity)
    @Query("UPDATE sessions SET uploadState = :uploadState WHERE sessionId = :sessionId") suspend fun updateUploadState(sessionId: String, uploadState: String)
    @Query("SELECT * FROM sessions WHERE recordingState IN ('INITIALIZING', 'READY', 'FINALIZING')") suspend fun activeSessions(): List<CaptureSessionEntity>
}

@Dao
interface EpisodeMarkerDao {
    @Query("SELECT * FROM episode_markers WHERE sessionId = :sessionId ORDER BY startTimestampNs") fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>>
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsert(marker: EpisodeMarkerEntity)
}

@Dao
interface CaptureLogDao {
    @Insert suspend fun insert(log: CaptureLogEntity)
    @Query("DELETE FROM capture_logs") suspend fun clearAll()
}

@Database(entities = [CaptureSessionEntity::class, EpisodeMarkerEntity::class, CaptureLogEntity::class], version = 2, exportSchema = false)
abstract class TigerDatabase : RoomDatabase() {
    abstract fun captureSessionDao(): CaptureSessionDao
    abstract fun episodeMarkerDao(): EpisodeMarkerDao
    abstract fun captureLogDao(): CaptureLogDao
}
