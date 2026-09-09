package com.ssafy.s15p21a206.tiger.upload

import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import kotlinx.coroutines.async
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class SessionUploaderTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.close()
    }

    @Test
    fun `created receipt uploads a main only bundle`() =
        runBlocking {
            val bundle = createBundle()
            server.enqueue(jsonResponse(201, bundle.sessionId, "created"))

            val result = uploader().upload(bundle)

            assertEquals(UploadResult.Uploaded, result)
            val request = server.takeRequest()
            assertEquals(bundle.sessionId, request.getHeader("Idempotency-Key"))
            val body = request.body.readUtf8()
            assertTrue(body.contains("name=\"main_video\"; filename=\"main_rgb.mp4\""))
            assertTrue(!body.contains("name=\"ultrawide_video\""))
        }

    @Test
    fun `duplicate receipt is also an uploaded result`() =
        runBlocking {
            val bundle = createBundle()
            server.enqueue(jsonResponse(200, bundle.sessionId, "duplicate"))

            assertEquals(UploadResult.Uploaded, uploader().upload(bundle))
        }

    @Test
    fun `ultra wide parts follow the metadata declaration`() =
        runBlocking {
            val bundle = createBundle(includesUltraWide = true)
            server.enqueue(jsonResponse(201, bundle.sessionId, "created"))

            assertEquals(UploadResult.Uploaded, uploader().upload(bundle))
            val body = server.takeRequest().body.readUtf8()
            assertTrue(body.contains("name=\"ultrawide_video\"; filename=\"ultrawide_rgb.mp4\""))
            assertTrue(body.contains("name=\"ultrawide_frame_timestamps\"; filename=\"ultrawide_frame_timestamps.csv\""))
        }

    @Test
    fun `mismatched receipt or non JSON success is failed`() =
        runBlocking {
            val bundle = createBundle()
            server.enqueue(jsonResponse(201, "00000000-0000-0000-0000-000000000000", "created"))
            server.enqueue(MockResponse().setResponseCode(201).setBody("ok"))

            assertTrue(uploader().upload(bundle) is UploadResult.Failed)
            assertTrue(uploader().upload(bundle) is UploadResult.Failed)
        }

    @Test
    fun `HTTP rejection is failed`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(422).setBody("invalid bundle"))

            assertTrue(uploader().upload(createBundle()) is UploadResult.Failed)
        }

    @Test
    fun `cancelling upload cancels the in flight HTTP request`() =
        runBlocking {
            withTimeout(5_000) {
                val bundle = createBundle()
                server.enqueue(MockResponse().setBody("delayed").setBodyDelay(10, TimeUnit.SECONDS))

                val upload = async { uploader().upload(bundle) }
                yield()
                assertTrue(server.takeRequest(5, TimeUnit.SECONDS) != null)
                upload.cancelAndJoin()

                assertTrue(upload.isCancelled)
            }
        }

    private fun uploader(): SessionUploader =
        SessionUploader(
            OkHttpClient(),
            SessionUploadRequestFactory(server.url("/").toString().removeSuffix("/")),
        )

    private fun jsonResponse(
        status: Int,
        sessionId: String,
        result: String,
    ): MockResponse =
        MockResponse()
            .setResponseCode(status)
            .addHeader("Content-Type", "application/json")
            .setBody("""{"session_id":"$sessionId","result":"$result"}""")

    private fun createBundle(includesUltraWide: Boolean = false): SessionBundle {
        val directory = Files.createTempDirectory("session-upload").toFile()
        val sessionId = "fa8aeb70-2d8f-424e-baa0-b9022544f3fc"
        val bundle = SessionBundle(sessionId, 1, "session_0001", directory)
        bundle.mainVideo.writeText("video")
        bundle.mainFrameTimestamps.writeText("frame_number,timestamp_ns,timestamp_source\n")
        bundle.accelerometer.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.gyroscope.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.rotationVector.writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        bundle.arcorePoses.writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        bundle.episodes.writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
        if (includesUltraWide) {
            File(directory, SessionBundle.ULTRAWIDE_VIDEO_FILE).writeText("ultra video")
            File(directory, SessionBundle.ULTRAWIDE_FRAME_TIMESTAMPS_FILE)
                .writeText("frame_number,timestamp_ns,timestamp_source\n")
        }
        val files =
            directory.listFiles().orEmpty().joinToString(",") { file ->
                """{"path":"${file.name}","sizeBytes":${file.length()},"sha256":"${sha256(file)}"}"""
            }
        bundle.metadata.writeText(
            """{"session_id":"$sessionId","camera_streams":{"main":true,"ultrawide":$includesUltraWide},"files":[$files]}""",
        )
        return bundle
    }

    private fun sha256(file: File): String =
        MessageDigest
            .getInstance("SHA-256")
            .digest(file.readBytes())
            .joinToString("") { "%02x".format(it) }
}
