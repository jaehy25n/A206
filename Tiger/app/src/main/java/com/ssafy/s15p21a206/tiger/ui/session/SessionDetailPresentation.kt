package com.ssafy.s15p21a206.tiger.ui.session

import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.episode.UploadState

internal data class SessionDetailPresentation(
    val durationSeconds: Long,
    val uploadAction: UploadAction?,
) {
    internal enum class UploadAction { Upload, Retry }

    companion object {
        fun from(summary: SessionSummary): SessionDetailPresentation {
            val endTimestamp = summary.recordingEndMonotonicTimestampNs ?: summary.recordingStartMonotonicTimestampNs
            return SessionDetailPresentation(
                durationSeconds = (endTimestamp - summary.recordingStartMonotonicTimestampNs) / NANOS_PER_SECOND,
                uploadAction =
                    when (summary.uploadState) {
                        UploadState.LOCAL_ONLY -> UploadAction.Upload
                        UploadState.FAILED -> UploadAction.Retry
                        UploadState.UPLOADING, UploadState.UPLOADED -> null
                    },
            )
        }

        private const val NANOS_PER_SECOND = 1_000_000_000L
    }
}
