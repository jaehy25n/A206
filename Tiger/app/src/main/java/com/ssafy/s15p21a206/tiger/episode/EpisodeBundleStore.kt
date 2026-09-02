package com.ssafy.s15p21a206.tiger.episode

import java.io.File
import java.util.UUID

class EpisodeBundleStore(private val filesRoot: File) {
    val stagingRoot = File(filesRoot, "episodes/staging")
    val completedRoot = File(filesRoot, "episodes/completed")

    fun createStagingBundle(displayIndex: Int, episodeId: UUID = UUID.randomUUID()): EpisodeBundle {
        val displayName = "episode_%04d".format(displayIndex)
        val directory = File(stagingRoot, episodeId.toString()).apply { mkdirs() }
        return EpisodeBundle(episodeId.toString(), displayName, directory)
    }

    fun completedDirectory(episodeId: String): File = File(completedRoot, episodeId)

    fun publish(bundle: EpisodeBundle): File {
        require(EpisodeBundleValidator.validate(bundle.directory).isValid) { "Incomplete episode bundle" }
        completedRoot.mkdirs()
        val target = completedDirectory(bundle.episodeId)
        require(!target.exists()) { "Episode already published" }
        check(bundle.directory.renameTo(target)) { "Could not publish episode bundle" }
        return target
    }

    fun clearStaging() {
        stagingRoot.listFiles()?.forEach(File::deleteRecursively)
    }
}

data class EpisodeBundle(
    val episodeId: String,
    val displayName: String,
    val directory: File
) {
    val video = File(directory, VIDEO_FILE)
    val frameTimestamps = File(directory, FRAME_TIMESTAMPS_FILE)
    val accelerometer = File(directory, ACCELEROMETER_FILE)
    val gyroscope = File(directory, GYROSCOPE_FILE)
    val rotationVector = File(directory, ROTATION_VECTOR_FILE)
    val metadata = File(directory, METADATA_FILE)

    companion object {
        const val VIDEO_FILE = "video.mp4"
        const val FRAME_TIMESTAMPS_FILE = "frame_timestamps.csv"
        const val ACCELEROMETER_FILE = "accelerometer.csv"
        const val GYROSCOPE_FILE = "gyroscope.csv"
        const val ROTATION_VECTOR_FILE = "rotation_vector.csv"
        const val METADATA_FILE = "metadata.json"
    }
}
