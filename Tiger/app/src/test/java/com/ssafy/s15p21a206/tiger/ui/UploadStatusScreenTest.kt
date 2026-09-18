package com.ssafy.s15p21a206.tiger.ui

import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.upload.UploadExitAction
import com.ssafy.s15p21a206.tiger.ui.upload.cancelUploadOnStop
import com.ssafy.s15p21a206.tiger.ui.upload.closeOnUploadCompletion
import com.ssafy.s15p21a206.tiger.ui.upload.uploadExitAction
import org.junit.Assert.assertEquals
import org.junit.Test

class UploadStatusScreenTest {
    @Test
    fun `uploading requires cancellation confirmation before leaving`() {
        assertEquals(UploadExitAction.ConfirmCancellation, uploadExitAction(UploadState.UPLOADING))
    }

    @Test
    fun `terminal and local upload states return directly to detail`() {
        listOf(null, UploadState.LOCAL_ONLY, UploadState.UPLOADED, UploadState.FAILED).forEach { state ->
            assertEquals(UploadExitAction.ReturnToDetail, uploadExitAction(state))
        }
    }

    @Test
    fun `lifecycle stop cancels only an upload status job`() {
        assertEquals(true, cancelUploadOnStop(isUploadStatusDestination = true))
        assertEquals(false, cancelUploadOnStop(isUploadStatusDestination = false))
    }

    @Test
    fun `a finished upload closes the status screen`() {
        assertEquals(true, closeOnUploadCompletion(UploadState.UPLOADED))
    }

    @Test
    fun `an unfinished upload keeps the status screen`() {
        listOf(null, UploadState.LOCAL_ONLY, UploadState.UPLOADING, UploadState.FAILED).forEach { state ->
            assertEquals(false, closeOnUploadCompletion(state))
        }
    }
}
