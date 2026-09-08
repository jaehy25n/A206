package com.ssafy.s15p21a206.tiger.upload

import com.ssafy.s15p21a206.tiger.episode.CaptureSession
import com.ssafy.s15p21a206.tiger.episode.RecordingState
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.UploadState
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class SessionUploadServiceTest {
    @Test
    fun `successful upload persists uploading then uploaded`() = runBlocking {
        val store = FakeStore(completedSession())
        val service = SessionUploadService(store, FakeGateway(UploadResult.Uploaded))

        assertEquals(UploadResult.Uploaded, service.upload(store.session.sessionId))
        assertEquals(listOf(UploadState.UPLOADING, UploadState.UPLOADED), store.states)
    }

    @Test
    fun `failed upload persists failed and retry uses the same session`() = runBlocking {
        val store = FakeStore(completedSession(uploadState = UploadState.FAILED))
        val gateway = FakeGateway(UploadResult.Failed("network error"))
        val service = SessionUploadService(store, gateway)

        assertEquals(UploadResult.Failed("network error"), service.upload(store.session.sessionId))
        assertEquals(listOf(UploadState.UPLOADING, UploadState.FAILED), store.states)
        assertEquals(store.session.sessionId, gateway.uploadedBundle?.sessionId)
    }

    private fun completedSession(uploadState: UploadState = UploadState.LOCAL_ONLY): CaptureSession {
        val sessionId = "fa8aeb70-2d8f-424e-baa0-b9022544f3fc"
        return CaptureSession(sessionId, 1, RecordingState.COMPLETED, uploadState, 1L, 2L, Files.createTempDirectory("upload-service").toString())
    }

    private class FakeStore(val session: CaptureSession) : UploadSessionStore {
        val states = mutableListOf<UploadState>()

        override suspend fun completedSource(sessionId: String): CaptureSession? = session.takeIf { it.sessionId == sessionId }

        override suspend fun updateUploadState(sessionId: String, state: UploadState) {
            states += state
        }
    }

    private class FakeGateway(private val result: UploadResult) : SessionUploadGateway {
        var uploadedBundle: SessionBundle? = null

        override suspend fun upload(bundle: SessionBundle): UploadResult {
            uploadedBundle = bundle
            return result
        }
    }
}
