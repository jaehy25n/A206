package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureSessionEntity
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeMarkerEntity
import com.ssafy.s15p21a206.tiger.data.local.SessionSummaryEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

class SessionRepositoryTest {
    @Test
    fun `legacy external completed bundle is excluded from listing and upload`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val managed = store.completedDirectory("managed").apply { mkdirs() }
            val dao = FakeSessionDao(listOf(session("managed", managed.path), session("legacy", root.resolve("legacy").path)))
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            assertEquals(listOf("managed"), repository.observeCompleted().first().map(CaptureSession::sessionId))
            assertNull(repository.completedSource("legacy"))
            root.deleteRecursively()
        }
    }

    /**
     * 수집 시작 때 입력받은 두 이름이 Session 행에 저장된다.
     *
     * 전에는 Episode 행에만 실려, Episode를 시작하지 않고 끝난 Session에서 사라졌다.
     */
    @Test
    fun `saving a session persists the task and object it was started with`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val dao = FakeSessionDao(emptyList())
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            repository.save(
                CaptureSession(
                    sessionId = "ce9c7947",
                    displayNumber = 1,
                    recordingState = RecordingState.COMPLETED,
                    uploadState = UploadState.LOCAL_ONLY,
                    recordingStartMonotonicTimestampNs = 1L,
                    bundlePath = store.completedDirectory("ce9c7947").path,
                    task = "mvi-check",
                    objectName = "cup",
                ),
            )

            val stored = dao.session("ce9c7947")!!
            assertEquals("mvi-check", stored.task)
            assertEquals("cup", stored.objectName)
            root.deleteRecursively()
        }
    }

    /** 수집 화면이 홈 버튼 등으로 중단돼도 모아둔 데이터는 버리지 않는다. */
    @Test
    fun `an interrupted staging bundle is finalized instead of discarded`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val bundle = store.createStagingBundle(1).also(::fillBundle)
            val dao = FakeSessionDao(listOf(session(bundle.sessionId, bundle.directory.path).copy(recordingState = "INTERRUPTED")))
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            repository.recoverInterruptedStaging()

            val recovered = dao.session(bundle.sessionId)!!
            assertEquals("COMPLETED", recovered.recordingState)
            assertEquals(store.completedDirectory(bundle.sessionId).path, recovered.bundlePath)
            assertEquals(listOf(bundle.sessionId), repository.observeCompleted().first().map(CaptureSession::sessionId))
            root.deleteRecursively()
        }
    }

    @Test
    fun `a staging bundle that cannot be finalized stays interrupted`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            // 영상이 없으면 마감할 수 없다.
            val bundle = store.createStagingBundle(1).also { it.episodes.writeText("broken") }
            val dao = FakeSessionDao(listOf(session(bundle.sessionId, bundle.directory.path)))
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            repository.recoverInterruptedStaging()

            assertEquals("INTERRUPTED", dao.session(bundle.sessionId)!!.recordingState)
            root.deleteRecursively()
        }
    }

    private fun fillBundle(bundle: SessionBundle) {
        bundle.mainVideo.writeText("video")
        bundle.mainFrameTimestamps.writeText("frame_number,timestamp_ns,timestamp_source\n0,1,SENSOR_TIMESTAMP\n")
        bundle.accelerometer.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.gyroscope.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.rotationVector.writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        bundle.arcorePoses.writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        bundle.episodes.writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
    }

    @Test
    fun `managed summary keeps only completed episode count`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val managed = store.completedDirectory("managed").apply { mkdirs() }
            val legacy = root.resolve("legacy")
            val summaries =
                listOf(
                    SessionSummaryEntity("managed", 2, "FAILED", 100, 1, 2, managed.path, 3, "Door opening"),
                    SessionSummaryEntity("legacy", 1, "LOCAL_ONLY", 100, 1, 2, legacy.path, 9),
                )
            val repository = SessionRepository(FakeSessionDao(emptyList(), summaries), FakeMarkerDao(), store)

            val summary = repository.observeCompletedSummaries().first().single()

            assertEquals("managed", summary.sessionId)
            assertEquals(3, summary.completedEpisodeCount)
            assertEquals("Door opening", summary.taskName)
            assertEquals(UploadState.FAILED, summary.uploadState)
            root.deleteRecursively()
        }
    }

    @Test
    fun `normalizing display numbers makes existing sessions sequential`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val oldest = store.completedDirectory("oldest").apply { mkdirs() }
            val newest = store.completedDirectory("newest").apply { mkdirs() }
            val dao =
                FakeSessionDao(
                    listOf(
                        session("newest", newest.path).copy(recordingStartEpochMs = 20),
                        session("oldest", oldest.path).copy(recordingStartEpochMs = 10),
                    ),
                )
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            repository.normalizeDisplayNumbers()

            assertEquals(1, dao.session("oldest")?.displayNumber)
            assertEquals(2, dao.session("newest")?.displayNumber)
            assertEquals(3, repository.nextDisplayNumber())
            root.deleteRecursively()
        }
    }

    @Test
    fun `deleting a session removes its index row, markers and bundle`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val directory = store.completedDirectory("target").apply { mkdirs() }
            directory.resolve(SessionBundle.MAIN_VIDEO_FILE).writeText("video")
            val dao = FakeSessionDao(listOf(session("target", directory.path)))
            val markerDao = FakeMarkerDao(mutableListOf(marker("episode", "target")))
            val repository = SessionRepository(dao, markerDao, store)

            assertEquals(SessionDeleteResult.DELETED, repository.delete("target"))

            assertNull(dao.session("target"))
            assertEquals(emptyList<EpisodeMarkerEntity>(), markerDao.markers)
            assertFalse(directory.exists())
            assertEquals(emptyList<CaptureSession>(), repository.observeCompleted().first())
            root.deleteRecursively()
        }
    }

    /** 삭제는 기기 저장 공간을 비우는 동작이다. 업로드가 읽고 있는 번들은 그 대상이 아니다. */
    @Test
    fun `deleting a session that is uploading is refused`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val directory = store.completedDirectory("uploading").apply { mkdirs() }
            val dao = FakeSessionDao(listOf(session("uploading", directory.path).copy(uploadState = "UPLOADING")))
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            assertEquals(SessionDeleteResult.UPLOAD_IN_PROGRESS, repository.delete("uploading"))

            assertNotNull(dao.session("uploading"))
            assertTrue(directory.exists())
            root.deleteRecursively()
        }
    }

    /**
     * 색인을 먼저 지우는 순서 때문에, 디렉터리 삭제가 실패해도 목록에는 남지 않는다.
     * 남은 디렉터리는 고아이며 다음 실행이 회수한다.
     */
    @Test
    fun `a bundle left behind by a failed delete is purged on the next run`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val orphan = store.completedDirectory("orphan").apply { mkdirs() }
            val kept = store.completedDirectory("kept").apply { mkdirs() }
            val repository = SessionRepository(FakeSessionDao(listOf(session("kept", kept.path))), FakeMarkerDao(), store)

            repository.purgeOrphanBundles()

            assertFalse(orphan.exists())
            assertTrue(kept.exists())
            root.deleteRecursively()
        }
    }

    /** 아직 마감되지 않은 Session의 번들은 색인에 행이 있으므로 고아가 아니다. */
    @Test
    fun `purging orphan bundles keeps bundles of sessions that are not completed yet`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val inFlight = store.completedDirectory("in-flight").apply { mkdirs() }
            val dao = FakeSessionDao(listOf(session("in-flight", inFlight.path).copy(recordingState = "FINALIZING")))
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            repository.purgeOrphanBundles()

            assertTrue(inFlight.exists())
            root.deleteRecursively()
        }
    }

    /** 지운 Session은 staging 구제 경로로도 되살아나지 않는다. 색인에 행이 없으면 구제 대상이 아니다. */
    @Test
    fun `a deleted session does not come back through staging recovery`() {
        runBlocking {
            val root = Files.createTempDirectory("session-store").toFile()
            val store = SessionBundleStore(root)
            val bundle = store.createStagingBundle(1).also(::fillBundle)
            val dao = FakeSessionDao(listOf(session(bundle.sessionId, bundle.directory.path).copy(recordingState = "INTERRUPTED")))
            val repository = SessionRepository(dao, FakeMarkerDao(), store)

            repository.delete(bundle.sessionId)
            repository.recoverInterruptedStaging()

            assertNull(dao.session(bundle.sessionId))
            assertEquals(emptyList<CaptureSession>(), repository.observeCompleted().first())
            root.deleteRecursively()
        }
    }

    private fun session(
        id: String,
        path: String,
    ) = CaptureSessionEntity(id, 1, "COMPLETED", "LOCAL_ONLY", 1, 2, path)

    private fun marker(
        episodeId: String,
        sessionId: String,
    ) = EpisodeMarkerEntity(episodeId, sessionId, 1, 2, "task", "object", "COMPLETED")

    private class FakeSessionDao(
        sessions: List<CaptureSessionEntity>,
        private val summaries: List<SessionSummaryEntity> = emptyList(),
    ) : CaptureSessionDao {
        private val values = sessions.associateBy(CaptureSessionEntity::sessionId).toMutableMap()

        override fun observeCompleted(): Flow<List<CaptureSessionEntity>> =
            flowOf(values.values.filter { it.recordingState == "COMPLETED" })

        override fun observeCompletedSummaries(): Flow<List<SessionSummaryEntity>> = flowOf(summaries)

        override suspend fun upsert(session: CaptureSessionEntity) {
            values[session.sessionId] = session
        }

        override suspend fun updateUploadState(
            sessionId: String,
            uploadState: String,
        ) = Unit

        override suspend fun failInterruptedUploads() = Unit

        override suspend fun completedSession(sessionId: String): CaptureSessionEntity? =
            values[sessionId]?.takeIf {
                it.recordingState ==
                    "COMPLETED"
            }

        override suspend fun session(sessionId: String): CaptureSessionEntity? = values[sessionId]

        override suspend fun activeSessions(): List<CaptureSessionEntity> = emptyList()

        override suspend fun recoverableSessions(): List<CaptureSessionEntity> = values.values.toList()

        override suspend fun sessionsInCaptureOrder(): List<CaptureSessionEntity> =
            values.values.sortedWith(
                compareBy(
                    CaptureSessionEntity::recordingStartEpochMs,
                    CaptureSessionEntity::recordingStartNs,
                    CaptureSessionEntity::sessionId,
                ),
            )

        override suspend fun updateDisplayNumber(
            sessionId: String,
            displayNumber: Int,
        ) {
            values[sessionId] = requireNotNull(values[sessionId]).copy(displayNumber = displayNumber)
        }

        override suspend fun nextDisplayNumber(): Int = (values.values.maxOfOrNull(CaptureSessionEntity::displayNumber) ?: 0) + 1

        override suspend fun delete(sessionId: String) {
            values.remove(sessionId)
        }

        override suspend fun allSessionIds(): List<String> = values.keys.toList()
    }

    private class FakeMarkerDao(
        val markers: MutableList<EpisodeMarkerEntity> = mutableListOf(),
    ) : EpisodeMarkerDao {
        override fun observeForSession(sessionId: String): Flow<List<EpisodeMarkerEntity>> =
            flowOf(markers.filter { it.sessionId == sessionId })

        override suspend fun upsert(marker: EpisodeMarkerEntity) {
            markers += marker
        }

        override suspend fun deleteForSession(sessionId: String) {
            markers.removeAll { it.sessionId == sessionId }
        }
    }
}
