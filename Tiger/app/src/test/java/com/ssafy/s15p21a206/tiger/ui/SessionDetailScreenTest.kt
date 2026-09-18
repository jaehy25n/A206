package com.ssafy.s15p21a206.tiger.ui

import com.ssafy.s15p21a206.tiger.episode.SessionSummary
import com.ssafy.s15p21a206.tiger.episode.UploadState
import com.ssafy.s15p21a206.tiger.ui.session.SessionDetailPresentation
import org.junit.Assert.assertEquals
import org.junit.Test

class SessionDetailScreenTest {
    @Test
    fun `detail presentation retains duration episode data source and upload action`() {
        val summary = summary(uploadState = UploadState.LOCAL_ONLY, endNs = 5_900_000_000L)
        assertEquals(5L, SessionDetailPresentation.from(summary).durationSeconds)
        assertEquals(SessionDetailPresentation.UploadAction.Upload, SessionDetailPresentation.from(summary).uploadAction)
        assertEquals(3, summary.completedEpisodeCount)
    }

    @Test
    fun `failed session exposes retry while completed upload exposes no action`() {
        assertEquals(SessionDetailPresentation.UploadAction.Retry, SessionDetailPresentation.from(summary(UploadState.FAILED)).uploadAction)
        assertEquals(null, SessionDetailPresentation.from(summary(UploadState.UPLOADED)).uploadAction)
    }

    /** 서버에 DELETE API가 없어 이미 올린 사본은 남는다. 확인 문구가 그 차이를 말해야 한다. */
    @Test
    fun `delete confirmation distinguishes an uploaded session from the only copy`() {
        assertEquals(
            SessionDetailPresentation.DeleteAction.DeleteLocalCopy,
            SessionDetailPresentation.from(summary(UploadState.UPLOADED)).deleteAction,
        )
        assertEquals(
            SessionDetailPresentation.DeleteAction.DeleteOnlyCopy,
            SessionDetailPresentation.from(summary(UploadState.LOCAL_ONLY)).deleteAction,
        )
        assertEquals(
            SessionDetailPresentation.DeleteAction.DeleteOnlyCopy,
            SessionDetailPresentation.from(summary(UploadState.FAILED)).deleteAction,
        )
    }

    @Test
    fun `a session that is uploading exposes no delete action`() {
        assertEquals(null, SessionDetailPresentation.from(summary(UploadState.UPLOADING)).deleteAction)
    }

    private fun summary(
        uploadState: UploadState,
        endNs: Long? = 2_000_000_000L,
    ): SessionSummary =
        SessionSummary(
            "session-id",
            7,
            uploadState,
            10L,
            900_000_000L,
            endNs,
            "/bundle",
            3,
            "task",
        )
}
