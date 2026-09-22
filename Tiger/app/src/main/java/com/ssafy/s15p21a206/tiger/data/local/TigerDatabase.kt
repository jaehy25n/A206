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
    val recordingStartEpochMs: Long = 0L,
    /**
     * 수집을 시작할 때 입력받은 Task와 Object.
     *
     * 한 Session의 모든 Episode가 같은 값을 갖는 Session 속성이므로 여기에 둔다. Episode 행에서
     * 역산하던 때에는 Episode가 0개인 Session에서 두 이름이 사라졌다. 입력받은 자리에 저장하면
     * Episode 유무와 무관해진다.
     */
    val task: String = "",
    val objectName: String = "",
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
    val objectName: String = "",
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
    /**
     * 목록 정렬은 절대 시각인 [CaptureSessionEntity.recordingStartEpochMs]를 기준으로 한다.
     * `recordingStartNs`는 부팅 이후 경과 시간이라 재부팅하면 0으로 돌아가므로,
     * 재부팅 경계를 걸친 Session끼리 순서가 뒤섞인다. 화면에 표시하는 수집 시각과 같은 값이어야 한다.
     */
    @Query("SELECT * FROM sessions WHERE recordingState = 'COMPLETED' ORDER BY recordingStartEpochMs DESC")
    fun observeCompleted(): Flow<List<CaptureSessionEntity>>

    /**
     * 정렬 기준은 [observeCompleted]와 같다.
     *
     * Task와 Object는 `sessions` 행에서 그대로 읽는다. 전에는 `episode_markers`의 최솟값으로
     * 역산했는데, 그러면 Episode가 하나도 없는 Session에서 두 이름이 빈 문자열로 사라졌다.
     * Episode 조인은 이제 개수를 세기 위해서만 남는다.
     */
    @Query(
        """
        SELECT sessions.sessionId, sessions.displayNumber, sessions.uploadState,
               sessions.recordingStartEpochMs, sessions.recordingStartNs, sessions.recordingEndNs,
               sessions.bundlePath,
               COUNT(CASE WHEN episode_markers.outcome = 'COMPLETED' THEN 1 END) AS completedEpisodeCount,
               sessions.task AS taskName, sessions.objectName AS objectName
        FROM sessions
        LEFT JOIN episode_markers ON episode_markers.sessionId = sessions.sessionId
        WHERE sessions.recordingState = 'COMPLETED'
        GROUP BY sessions.sessionId
        ORDER BY sessions.recordingStartEpochMs DESC
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

    @Query("SELECT * FROM sessions WHERE sessionId = :sessionId AND recordingState = 'COMPLETED' LIMIT 1")
    suspend fun completedSession(sessionId: String): CaptureSessionEntity?

    @Query("SELECT * FROM sessions WHERE sessionId = :sessionId LIMIT 1")
    suspend fun session(sessionId: String): CaptureSessionEntity?

    @Query("SELECT * FROM sessions WHERE recordingState IN ('INITIALIZING', 'READY', 'FINALIZING')")
    suspend fun activeSessions(): List<CaptureSessionEntity>

    /**
     * 마감되지 않은 Session. 구제 대상이므로 이전 실행에서 `INTERRUPTED`로 남은 것도 포함한다.
     * 한 번 중단으로 표시됐더라도 번들이 온전하면 다음 실행에서 정상 마감할 수 있다.
     */
    @Query("SELECT * FROM sessions WHERE recordingState IN ('INITIALIZING', 'READY', 'FINALIZING', 'INTERRUPTED')")
    suspend fun recoverableSessions(): List<CaptureSessionEntity>

    @Query("SELECT * FROM sessions ORDER BY recordingStartEpochMs ASC, recordingStartNs ASC, sessionId ASC")
    suspend fun sessionsInCaptureOrder(): List<CaptureSessionEntity>

    @Query("UPDATE sessions SET displayNumber = :displayNumber WHERE sessionId = :sessionId")
    suspend fun updateDisplayNumber(
        sessionId: String,
        displayNumber: Int,
    )

    @Query("SELECT COALESCE(MAX(displayNumber), 0) + 1 FROM sessions")
    suspend fun nextDisplayNumber(): Int

    @Query("DELETE FROM sessions WHERE sessionId = :sessionId")
    suspend fun delete(sessionId: String)

    /**
     * 색인이 아는 모든 Session의 id. 마감 여부를 가리지 않는다.
     *
     * 고아 번들 회수에 쓴다. 아직 마감되지 않은 Session의 디렉터리를 고아로 오인해 지우면 수집
     * 중인 데이터가 사라지므로, `COMPLETED`만 세어서는 안 된다.
     */
    @Query("SELECT sessionId FROM sessions")
    suspend fun allSessionIds(): List<String>
}

@Dao
interface EpisodeMarkerDao {
    @Query("SELECT * FROM episode_markers WHERE sessionId = :sessionId ORDER BY startTimestampNs")
    fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(marker: EpisodeMarkerEntity)

    @Query("DELETE FROM episode_markers WHERE sessionId = :sessionId")
    suspend fun deleteForSession(sessionId: String)
}

@Dao
interface CaptureLogDao {
    @Insert suspend fun insert(log: CaptureLogEntity)

    @Query("DELETE FROM capture_logs")
    suspend fun clearAll()
}

@Database(entities = [CaptureSessionEntity::class, EpisodeMarkerEntity::class, CaptureLogEntity::class], version = 6, exportSchema = false)
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

val MIGRATION_4_5 =
    object : Migration(4, 5) {
        override fun migrate(db: SupportSQLiteDatabase) {
            SESSION_METADATA_MIGRATION_SQL.forEach(db::execSQL)
        }
    }

/**
 * Task와 Object를 Session 행으로 옮긴다.
 *
 * 컬럼을 더하는 것만으로는 안 된다. 조회가 `episode_markers` 집계를 떠나 `sessions.task`를 읽으므로,
 * 채워 넣지 않으면 이미 쌓인 Session이 모두 이름 없는 Task로 떨어진다. 이 이관이 고치려는 증상을
 * 과거 데이터 전체에 되풀이하는 셈이다. 그래서 같은 이관 안에서 Episode 행의 값으로 채운다.
 *
 * 채우는 식은 떠나는 집계와 같다. Episode가 없는 Session은 채울 값이 없어 빈 문자열로 남는다.
 * 그 행의 두 이름은 애초에 어디에도 저장된 적이 없다.
 */
val SESSION_METADATA_MIGRATION_SQL =
    listOf(
        "ALTER TABLE sessions ADD COLUMN task TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE sessions ADD COLUMN objectName TEXT NOT NULL DEFAULT ''",
        """
        UPDATE sessions SET
            task = COALESCE((
                SELECT MIN(NULLIF(episode_markers.task, ''))
                FROM episode_markers WHERE episode_markers.sessionId = sessions.sessionId
            ), ''),
            objectName = COALESCE((
                SELECT MIN(NULLIF(episode_markers.objectName, ''))
                FROM episode_markers WHERE episode_markers.sessionId = sessions.sessionId
            ), '')
        """,
    )

val MIGRATION_5_6 =
    object : Migration(5, 6) {
        override fun migrate(db: SupportSQLiteDatabase) {
            EXPORT_REMOVAL_MIGRATION_SQL.forEach(db::execSQL)
        }
    }

/**
 * SAF 내보내기를 걷어 내면서 그 세 컬럼을 지운다.
 *
 * `DROP COLUMN`을 쓰지 않는다. SQLite가 그것을 받는 것은 3.35부터이고 minSdk 28의 기기에는 더 낮은
 * 버전이 실린다. 테이블을 다시 만들어 옮긴다.
 *
 * 컬럼을 남겨 두는 쪽이 싸 보이지만 그렇지 않다. Room은 엔티티에서 만든 스키마와 실제 스키마를
 * 견주므로, 엔티티에서만 빼면 불일치로 잡힌다. 남기려면 쓰지 않는 필드를 엔티티에 영구히 들고
 * 있어야 한다.
 *
 * 2→3이 이 컬럼들을 더하는 이관은 그대로 둔다. 버전 2에서 올라오는 기기는 여전히 그 길을 지나야
 * 하고, 이관 이력은 지난 일이라 고쳐 쓰는 것이 아니다.
 */
val EXPORT_REMOVAL_MIGRATION_SQL =
    listOf(
        """
        CREATE TABLE sessions_without_export (
            sessionId TEXT NOT NULL PRIMARY KEY,
            displayNumber INTEGER NOT NULL,
            recordingState TEXT NOT NULL,
            uploadState TEXT NOT NULL,
            recordingStartNs INTEGER NOT NULL,
            recordingEndNs INTEGER,
            bundlePath TEXT NOT NULL,
            recordingStartEpochMs INTEGER NOT NULL,
            task TEXT NOT NULL,
            objectName TEXT NOT NULL
        )
        """,
        """
        INSERT INTO sessions_without_export
        SELECT sessionId, displayNumber, recordingState, uploadState, recordingStartNs, recordingEndNs,
               bundlePath, recordingStartEpochMs, task, objectName
        FROM sessions
        """,
        "DROP TABLE sessions",
        "ALTER TABLE sessions_without_export RENAME TO sessions",
    )
