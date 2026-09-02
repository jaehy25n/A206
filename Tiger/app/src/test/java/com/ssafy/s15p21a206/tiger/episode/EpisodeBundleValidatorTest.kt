package com.ssafy.s15p21a206.tiger.episode

import java.io.File
import java.nio.file.Files
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EpisodeBundleValidatorTest {
    @Test
    fun `complete bundle with commit marker is valid`() {
        val directory = Files.createTempDirectory("episode").toFile()
        writeCompleteBundle(directory)

        assertTrue(EpisodeBundleValidator.validate(directory).isValid)
        directory.deleteRecursively()
    }

    @Test
    fun `bundle without metadata commit marker is invalid`() {
        val directory = Files.createTempDirectory("episode").toFile()
        writeCompleteBundle(directory)
        File(directory, EpisodeBundle.METADATA_FILE).delete()

        assertFalse(EpisodeBundleValidator.validate(directory).isValid)
        directory.deleteRecursively()
    }

    @Test
    fun `display name uses fixed four digit sequence`() {
        val root = Files.createTempDirectory("episodes").toFile()
        val bundle = EpisodeBundleStore(root).createStagingBundle(12)

        assertTrue(bundle.displayName == "episode_0012")
        root.deleteRecursively()
    }

    private fun writeCompleteBundle(directory: File) {
        File(directory, EpisodeBundle.VIDEO_FILE).writeBytes(byteArrayOf(1))
        File(directory, EpisodeBundle.FRAME_TIMESTAMPS_FILE).writeText("frame_number,timestamp_ns,timestamp_source\n")
        File(directory, EpisodeBundle.ACCELEROMETER_FILE).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(directory, EpisodeBundle.GYROSCOPE_FILE).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(directory, EpisodeBundle.ROTATION_VECTOR_FILE).writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        File(directory, EpisodeBundle.METADATA_FILE).writeText("{}")
    }
}
