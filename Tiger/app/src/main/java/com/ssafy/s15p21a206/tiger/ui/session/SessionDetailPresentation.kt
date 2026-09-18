package com.ssafy.s15p21a206.tiger.ui.session

import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.episode.UploadState

internal data class SessionDetailPresentation(
    val durationSeconds: Long,
    val uploadAction: UploadAction?,
    val deleteAction: DeleteAction?,
) {
    internal enum class UploadAction { Upload, Retry }

    /**
     * 삭제를 확인받는 방식.
     *
     * 되돌릴 수 없는 동작이지만 잃는 것이 상태마다 다르다. 서버에 사본이 있으면 지우는 것은
     * 기기의 저장 공간뿐이고, 아직 올리지 않았으면 수집한 데이터 자체가 사라진다. 두 경우에
     * 같은 문구를 보이면 뒤쪽에서 사용자가 무엇을 잃는지 알 수 없다.
     *
     * 업로드가 진행 중이면 삭제할 수 없으므로 아무 값도 내지 않는다.
     */
    internal enum class DeleteAction { DeleteLocalCopy, DeleteOnlyCopy }

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
                deleteAction =
                    when (summary.uploadState) {
                        UploadState.UPLOADED -> DeleteAction.DeleteLocalCopy
                        UploadState.LOCAL_ONLY, UploadState.FAILED -> DeleteAction.DeleteOnlyCopy
                        // 업로드가 번들을 읽고 있는 동안은 지울 수 없다.
                        UploadState.UPLOADING -> null
                    },
            )
        }

        private const val NANOS_PER_SECOND = 1_000_000_000L
    }
}
