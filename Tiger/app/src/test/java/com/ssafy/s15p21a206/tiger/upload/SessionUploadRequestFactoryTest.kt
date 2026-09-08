package com.ssafy.s15p21a206.tiger.upload

import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.nio.file.Files

class SessionUploadRequestFactoryTest {
    @Test fun `request sends only idempotency key credential header`() {
        val directory = Files.createTempDirectory("session").toFile()
        val sessionId = "fa8aeb70-2d8f-424e-baa0-b9022544f3fc"
        val bundle = SessionBundle(sessionId, 1, "session_0001", directory)
        listOf(
            bundle.metadata,
            bundle.mainVideo,
            bundle.mainFrameTimestamps,
            bundle.accelerometer,
            bundle.gyroscope,
            bundle.rotationVector,
            bundle.arcorePoses,
            bundle.episodes,
        ).forEach {
            it.writeText("x")
        }
        bundle.metadata.writeText("""{"session_id":"$sessionId","camera_streams":{"main":true,"ultrawide":false}}""")
        val request = SessionUploadRequestFactory("https://collector.example").create(bundle)
        assertEquals(sessionId, request.header("Idempotency-Key"))
        assertNull(request.header("Authorization"))
        assertNull(request.header("Cookie"))
        directory.deleteRecursively()
    }
}
