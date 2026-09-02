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

@Entity(tableName = "episodes")
data class EpisodeEntity(
    @PrimaryKey val episodeId: String,
    val displayName: String,
    val task: String,
    val objectName: String,
    val recordingState: String,
    val uploadState: String,
    val recordingStartNs: Long,
    val recordingEndNs: Long?,
    val bundlePath: String
)

@Entity(tableName = "capture_logs")
data class CaptureLogEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val episodeId: String?,
    val reason: String,
    val summary: String,
    val timestampNs: Long,
    val frameCount: Long,
    val accelerometerCount: Long,
    val gyroscopeCount: Long,
    val rotationVectorCount: Long
)

@Dao
interface EpisodeDao {
    @Query("SELECT * FROM episodes WHERE recordingState = 'COMPLETED' ORDER BY recordingStartNs DESC")
    fun observeCompleted(): Flow<List<EpisodeEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(episode: EpisodeEntity)

    @Query("UPDATE episodes SET uploadState = :uploadState WHERE episodeId = :episodeId")
    suspend fun updateUploadState(episodeId: String, uploadState: String)
}

@Dao
interface CaptureLogDao {
    @Insert
    suspend fun insert(log: CaptureLogEntity)

    @Query("DELETE FROM capture_logs")
    suspend fun clearAll()
}

@Database(entities = [EpisodeEntity::class, CaptureLogEntity::class], version = 1, exportSchema = false)
abstract class TigerDatabase : RoomDatabase() {
    abstract fun episodeDao(): EpisodeDao
    abstract fun captureLogDao(): CaptureLogDao
}
