package com.ssafy.s15p21a206.tiger.episode

import java.io.File
import java.nio.file.Files
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionBundleStoreTest {
    @Test
    fun `staging bundle uses immutable session id directory`() {
        val root = Files.createTempDirectory("sessions").toFile()
        val sessionId = UUID.randomUUID()

        val bundle = SessionBundleStore(root).createStagingBundle(displayNumber = 12, sessionId = sessionId)

        assertEquals(File(root, "capture/staging/$sessionId"), bundle.directory)
        root.deleteRecursively()
    }

    @Test
    fun `publish moves metadata committed staging bundle to completed session path`() {
        val root = Files.createTempDirectory("sessions").toFile()
        val store = SessionBundleStore(root)
        val bundle = store.createStagingBundle(displayNumber = 12)
        writeCompleteBundle(bundle.directory, bundle.sessionId)

        val completed = store.publish(bundle)

        assertEquals(store.completedDirectory(bundle.sessionId), completed)
        assertTrue(completed.isDirectory)
        assertFalse(bundle.directory.exists())
        root.deleteRecursively()
    }

    @Test(expected = IllegalArgumentException::class)
    fun `publish rejects staging bundle before metadata commit`() {
        val root = Files.createTempDirectory("sessions").toFile()
        val store = SessionBundleStore(root)
        val bundle = store.createStagingBundle(displayNumber = 12)
        writeRawFiles(bundle.directory)

        try {
            store.publish(bundle)
        } finally {
            root.deleteRecursively()
        }
    }

    private fun writeCompleteBundle(directory: File, sessionId: String) {
        writeRawFiles(directory)
        File(directory, SessionBundle.METADATA_FILE).writeText(metadataJson(sessionId))
    }

    private fun writeRawFiles(directory: File) {
        File(directory, SessionBundle.MAIN_VIDEO_FILE).writeBytes(byteArrayOf(1))
        File(directory, SessionBundle.MAIN_FRAME_TIMESTAMPS_FILE).writeText("frame_number,timestamp_ns,timestamp_source\n")
        File(directory, SessionBundle.ACCELEROMETER_FILE).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(directory, SessionBundle.GYROSCOPE_FILE).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(directory, SessionBundle.ROTATION_VECTOR_FILE).writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        File(directory, SessionBundle.ARCORE_POSES_FILE).writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        File(directory, SessionBundle.EPISODES_FILE).writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
    }

    private fun metadataJson(sessionId: String) = """{"session_id":"$sessionId","camera_streams":{"main":true,"ultrawide":false},"files":[]}"""
}
