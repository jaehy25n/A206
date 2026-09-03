package com.ssafy.s15p21a206.tiger.episode

import android.content.Context
import java.io.File
import java.util.UUID

class SessionBundleStore(private val externalFilesRoot: File) {
    constructor(context: Context) : this(
        requireNotNull(context.getExternalFilesDir(null)) { "App-specific external storage is unavailable" }
    )

    val stagingRoot = File(externalFilesRoot, "capture/staging")
    val completedRoot = File(externalFilesRoot, "capture/completed")

    fun createStagingBundle(displayNumber: Int, sessionId: UUID = UUID.randomUUID()): SessionBundle {
        val displayName = "session_%04d".format(displayNumber)
        val directory = File(stagingRoot, sessionId.toString()).apply { mkdirs() }
        return SessionBundle(sessionId.toString(), displayNumber, displayName, directory)
    }

    fun completedDirectory(sessionId: String): File = File(completedRoot, sessionId)
    fun publish(bundle: SessionBundle, includesUltraWide: Boolean = false): File {
        require(SessionBundleValidator.validate(bundle.directory, includesUltraWide).isValid) { "Incomplete session bundle" }
        completedRoot.mkdirs()
        val target = completedDirectory(bundle.sessionId)
        require(!target.exists()) { "Session already published" }
        check(bundle.directory.renameTo(target)) { "Could not publish session bundle" }
        return target
    }

    fun interruptedStagingBundles(): List<File> = stagingRoot.listFiles()?.filter(File::isDirectory).orEmpty()
}

data class SessionBundle(val sessionId: String, val displayNumber: Int, val displayName: String, val directory: File) {
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
