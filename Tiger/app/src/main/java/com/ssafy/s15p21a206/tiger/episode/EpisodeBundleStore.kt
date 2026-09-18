package com.ssafy.s15p21a206.tiger.episode

import android.content.Context
import java.io.File
import java.util.UUID

class SessionBundleStore(
    private val internalFilesRoot: File,
) {
    constructor(context: Context) : this(
        context.filesDir,
    )

    val stagingRoot = File(internalFilesRoot, "capture/staging")
    val completedRoot = File(internalFilesRoot, "capture/completed")

    fun createStagingBundle(
        displayNumber: Int,
        sessionId: UUID = UUID.randomUUID(),
    ): SessionBundle {
        val displayName = "session_%04d".format(displayNumber)
        val directory = File(stagingRoot, sessionId.toString()).apply { mkdirs() }
        return SessionBundle(sessionId.toString(), displayNumber, displayName, directory)
    }

    fun completedDirectory(sessionId: String): File = File(completedRoot, sessionId)

    fun isManagedCompletedDirectory(path: String): Boolean {
        val root = completedRoot.canonicalFile
        val candidate = File(path).canonicalFile
        return candidate.parentFile == root && candidate.isDirectory
    }

    fun publish(
        bundle: SessionBundle,
        includesUltraWide: Boolean = false,
    ): File {
        require(SessionBundleValidator.validate(bundle.directory, includesUltraWide).isValid) { "Incomplete session bundle" }
        completedRoot.mkdirs()
        val target = completedDirectory(bundle.sessionId)
        require(!target.exists()) { "Session already published" }
        check(bundle.directory.renameTo(target)) { "Could not publish session bundle" }
        return target
    }

    fun interruptedStagingBundles(): List<File> = stagingRoot.listFiles()?.filter(File::isDirectory).orEmpty()

    /**
     * 번들 디렉터리를 통째로 지운다. 이미 없으면 지워진 것으로 본다.
     *
     * 이 저장소가 관리하지 않는 경로는 건드리지 않는다. 앱 바깥으로 내보낸 사본까지 지우는 동작이
     * 아니고, 예전 버전이 남긴 외부 경로가 색인에 남아 있을 수 있다.
     */
    fun deleteCompletedBundle(path: String): Boolean {
        if (!isManagedCompletedDirectory(path)) return true
        return File(path).deleteRecursively()
    }

    /**
     * 색인에 대응하는 행이 없는 completed 번들.
     *
     * 삭제는 Room 행을 먼저 지우므로 디렉터리 삭제가 실패하면 여기 남는다. 다음 실행에서 회수한다.
     */
    fun orphanCompletedBundles(knownSessionIds: Set<String>): List<File> =
        completedRoot
            .listFiles()
            ?.filter { it.isDirectory && it.name !in knownSessionIds }
            .orEmpty()
}

data class SessionBundle(
    val sessionId: String,
    val displayNumber: Int,
    val displayName: String,
    val directory: File,
) {
    val mainVideo = File(directory, MAIN_VIDEO_FILE)
    val mainFrameTimestamps = File(directory, MAIN_FRAME_TIMESTAMPS_FILE)
    val accelerometer = File(directory, ACCELEROMETER_FILE)
    val gyroscope = File(directory, GYROSCOPE_FILE)
    val rotationVector = File(directory, ROTATION_VECTOR_FILE)
    val arcorePoses = File(directory, ARCORE_POSES_FILE)
    val episodes = File(directory, EPISODES_FILE)
    val metadata = File(directory, METADATA_FILE)

    companion object {
        const val MAIN_VIDEO_FILE = "main_rgb.mp4"
        const val MAIN_FRAME_TIMESTAMPS_FILE = "main_frame_timestamps.csv"
        const val ACCELEROMETER_FILE = "accelerometer.csv"
        const val GYROSCOPE_FILE = "gyroscope.csv"
        const val ROTATION_VECTOR_FILE = "rotation_vector.csv"
        const val ARCORE_POSES_FILE = "arcore_poses.csv"
        const val EPISODES_FILE = "episodes.csv"
        const val ULTRAWIDE_VIDEO_FILE = "ultrawide_rgb.mp4"
        const val ULTRAWIDE_FRAME_TIMESTAMPS_FILE = "ultrawide_frame_timestamps.csv"
        const val METADATA_FILE = "metadata.json"
    }
}
