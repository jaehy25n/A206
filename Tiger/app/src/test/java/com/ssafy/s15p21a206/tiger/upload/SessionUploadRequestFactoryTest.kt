package com.ssafy.s15p21a206.tiger.upload

import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SessionUploadRequestFactoryTest {
    @Test fun `request sends only idempotency key credential header`() {
        val directory = Files.createTempDirectory("session").toFile()
        val bundle = SessionBundle("session-id", 1, "session_0001", directory)
        listOf(bundle.metadata, bundle.mainVideo, bundle.mainFrameTimestamps, bundle.accelerometer, bundle.gyroscope, bundle.rotationVector, bundle.arcorePoses, bundle.episodes).forEach { it.writeText("x") }
        val request = SessionUploadRequestFactory("https://collector.example").create(bundle)
        assertEquals("session-id", request.header("Idempotency-Key"))
        assertNull(request.header("Authorization")); assertNull(request.header("Cookie"))
        directory.deleteRecursively()
    }
}
