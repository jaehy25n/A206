package com.ssafy.s15p21a206.tiger.ui.session

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.ssafy.s15p21a206.tiger.episode.ExportState
import com.ssafy.s15p21a206.tiger.episode.SessionBundleExporter
import com.ssafy.s15p21a206.tiger.episode.SessionDeleteResult
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.upload.SessionUploadService
import com.ssafy.s15p21a206.tiger.upload.UploadResult
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 삭제가 막힌 이유. 문구는 화면이 붙인다. 여기는 무엇이 막았는지만 말한다. */
internal enum class SessionDeleteFailure {
    /** 업로드가 번들을 읽고 있어 거절됐다. */
    UploadInProgress,

    /** 저장소 접근이 실패했다. */
    Unavailable,
}

/**
 * 세션 하나에 할 수 있는 일들을 모은다. 내보내기·전송·삭제와 그 결과 상태다.
 *
 * 조회 흐름에는 수집 같은 상태 기계가 없다. Room Flow에서 목록이 나오고 화면은 값과 콜백만
 * 받으므로 intent와 reducer를 두지 않는다. 여기 있는 것은 "지금 무엇이 진행 중이고 무엇이
 * 막혔는지" 뿐이다.
 *
 * **목적지는 모른다.** 삭제가 실제로 일어났는지는 [delete]의 콜백으로 알리고, 어디로 갈지는
 * 호출한 쪽이 정한다. 전송도 걸기만 하고 화면 이동은 하지 않는다.
 *
 * Compose 바깥의 평범한 클래스다. Android 의존이 없어 fake DAO만으로 단위 테스트할 수 있다.
 */
internal class SessionOperations(
    private val repository: SessionRepository,
    private val uploadService: SessionUploadService?,
    private val exporter: SessionBundleExporter,
    private val scope: CoroutineScope,
    /** 내보내기가 예외로 끝나 이유를 못 얻었을 때 쓰는 문구. */
    private val exportFailedUnexpected: String,
    /** 단위 테스트가 같은 스레드에서 돌리기 위한 자리다. production은 기본값을 쓴다. */
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) {
    var exportState by mutableStateOf(ExportState.NOT_EXPORTED)
        private set
    var exportMessage by mutableStateOf<String?>(null)
        private set

    /**
     * 전송이 막힌 이유.
     *
     * 화면에만 쓰고 저장하지 않는다. 업로드에는 내보내기의 `exportFailureReason`에 해당하는
     * 컬럼이 없고, 무엇이 막았는지는 실패한 자리에서 보면 되는 값이다.
     */
    var uploadFailureReason by mutableStateOf<String?>(null)
        private set
    var deleteFailure by mutableStateOf<SessionDeleteFailure?>(null)
        private set

    private var uploadJob: Job? = null

    /** 전송 endpoint가 빌드에 주입되지 않았으면 전송 기능이 없다. */
    val canUpload: Boolean get() = uploadService != null

    val uploadInFlight: Boolean get() = uploadJob?.isActive == true

    fun cancelUpload() {
        uploadJob?.cancel()
    }

    /** 전송을 걸고 실패 사유를 받아 둔다. 화면 이동은 하지 않는다. */
    fun upload(sessionId: String) {
        val service = uploadService ?: return
        uploadFailureReason = null
        uploadJob =
            scope.launch {
                val result = runCatching { service.upload(sessionId) }.getOrNull()
                uploadFailureReason = (result as? UploadResult.Failed)?.reason
            }
    }

    /** 사용자가 고른 tree로 번들을 내보낸다. 권한 확보는 호출한 쪽이 이미 끝냈다. */
    fun export(
        sessionId: String,
        treeUri: String,
    ) {
        scope.launch {
            exportState = ExportState.EXPORTING
            when (
                val result =
                    runCatching { exporter.exportCompleted(repository, sessionId, treeUri) }
                        .getOrElse { SessionBundleExporter.ExportAttemptResult.Failed(it.message ?: exportFailedUnexpected, "") }
            ) {
                is SessionBundleExporter.ExportAttemptResult.Exported -> {
                    exportState = ExportState.EXPORTED
                    exportMessage = null
                }
                is SessionBundleExporter.ExportAttemptResult.Failed -> {
                    exportState = ExportState.EXPORT_FAILED
                    exportMessage = result.reason
                }
            }
        }
    }

    /** 사용자가 고르기도 전에 picker가 닫혔거나 권한을 얻지 못했다. */
    fun exportUnavailable(reason: String) {
        exportState = ExportState.EXPORT_FAILED
        exportMessage = reason
    }

    /**
     * Session을 기기에서 지운다.
     *
     * 지워졌으면 [onDeleted]를 부른다. 상세에서 지웠으면 그 화면은 "찾을 수 없음"이 되므로
     * 나가야 하는데, 어디에 있는지는 호출한 쪽이 안다. 거절당하면 부르지 않고 [deleteFailure]만
     * 남긴다.
     */
    fun delete(
        sessionId: String,
        onDeleted: () -> Unit,
    ) {
        scope.launch {
            val result =
                runCatching { withContext(ioDispatcher) { repository.delete(sessionId) } }
                    .getOrElse {
                        deleteFailure = SessionDeleteFailure.Unavailable
                        return@launch
                    }
            when (result) {
                // 디렉터리가 남았더라도 목록과 색인에서는 사라졌다. 남은 것은 다음 실행이 회수한다.
                SessionDeleteResult.DELETED, SessionDeleteResult.BUNDLE_RETAINED -> {
                    deleteFailure = null
                    onDeleted()
                }
                SessionDeleteResult.UPLOAD_IN_PROGRESS -> deleteFailure = SessionDeleteFailure.UploadInProgress
            }
        }
    }
}
