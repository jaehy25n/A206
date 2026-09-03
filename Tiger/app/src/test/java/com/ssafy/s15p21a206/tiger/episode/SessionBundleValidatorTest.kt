package com.ssafy.s15p21a206.tiger.episode

import java.io.File
import java.nio.file.Files
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionBundleValidatorTest {
    @Test
    fun `main only bundle with metadata commit marker is valid`() {
        val directory = Files.createTempDirectory("session").toFile()
        writeCompleteBundle(directory)

        assertTrue(SessionBundleValidator.validate(directory).isValid)
        directory.deleteRecursively()
    }

    @Test
    fun `bundle without metadata commit marker is invalid`() {
        val directory = Files.createTempDirectory("session").toFile()
        writeCompleteBundle(directory)
        File(directory, SessionBundle.METADATA_FILE).delete()

        assertFalse(SessionBundleValidator.validate(directory).isValid)
        directory.deleteRecursively()
    }

    @Test
    fun `ultrawide declaration requires both ultrawide files`() {
        val directory = Files.createTempDirectory("session").toFile()
        writeCompleteBundle(directory)
        File(directory, SessionBundle.ULTRAWIDE_VIDEO_FILE).writeBytes(byteArrayOf(1))

        assertFalse(SessionBundleValidator.validate(directory, includesUltraWide = true).isValid)
        directory.deleteRecursively()
    }

    @Test
    fun `display name uses fixed four digit sequence`() {
        val root = Files.createTempDirectory("sessions").toFile()
        val bundle = SessionBundleStore(root).createStagingBundle(12)

        assertTrue(bundle.displayName == "session_0012")
        root.deleteRecursively()
    }

    private fun writeCompleteBundle(directory: File) {
        File(directory, SessionBundle.MAIN_VIDEO_FILE).writeBytes(byteArrayOf(1))
        File(directory, SessionBundle.MAIN_FRAME_TIMESTAMPS_FILE).writeText("frame_number,timestamp_ns,timestamp_source\n")
        File(directory, SessionBundle.ACCELEROMETER_FILE).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(directory, SessionBundle.GYROSCOPE_FILE).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(directory, SessionBundle.ROTATION_VECTOR_FILE).writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        File(directory, SessionBundle.ARCORE_POSES_FILE).writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        File(directory, SessionBundle.EPISODES_FILE).writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
        File(directory, SessionBundle.METADATA_FILE).writeText("{}")
    }
}
