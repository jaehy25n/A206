package com.ssafy.s15p21a206.tiger.upload

import com.ssafy.s15p21a206.tiger.episode.CaptureSession
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.UploadState
import kotlinx.coroutines.CancellationException
import java.io.File

interface UploadSessionStore {
    suspend fun completedSource(sessionId: String): CaptureSession?

    suspend fun updateUploadState(
        sessionId: String,
        state: UploadState,
    )
}

class SessionUploadService(
    private val store: UploadSessionStore,
    private val uploader: SessionUploadGateway,
) {
    suspend fun upload(sessionId: String): UploadResult {
        val session =
            store.completedSource(sessionId)
                ?: return UploadResult.Failed("Completed session is unavailable")
        store.updateUploadState(sessionId, UploadState.UPLOADING)
        val result =
            try {
                uploader.upload(
                    SessionBundle(
                        sessionId = session.sessionId,
                        displayNumber = session.displayNumber,
                        displayName = "session_%04d".format(session.displayNumber),
                        directory = File(session.bundlePath),
                    ),
                )
            } catch (error: CancellationException) {
                store.updateUploadState(sessionId, UploadState.FAILED)
                throw error
            }
        store.updateUploadState(
            sessionId,
            if (result == UploadResult.Uploaded) UploadState.UPLOADED else UploadState.FAILED,
        )
        return result
    }
}
