package com.ssafy.s15p21a206.tiger.ui.capture

import com.ssafy.s15p21a206.tiger.capture.ManualCameraCapabilities
import com.ssafy.s15p21a206.tiger.capture.ManualCameraConfig
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class CaptureStateTest {
    private val hd = RecordingResolution(1280, 720)
    private val fullHd = RecordingResolution(1920, 1080)
    private val bundle = SessionBundle("session-1", 3, "0003", File("/tmp/session-1"))

    private fun collecting(): CaptureUiState =
        CaptureUiState()
            .reduce(CaptureIntent.Open("task", hd))
            .reduce(CaptureIntent.ConfirmMetadata)
            .reduce(CaptureIntent.SessionRequested)
            .reduce(CaptureIntent.SessionStarted(bundle, 42L, hd))

    @Test
    fun aNewWorkspaceOpensOnMetadataEntry() {
        val state = CaptureUiState().reduce(CaptureIntent.Open("wiping", hd))

        assertTrue(state.open)
        assertTrue(state.showMetadataDialog)
        assertEquals("wiping", state.task)
        assertEquals(CaptureWorkspaceControlState.Idle, state.phase)
        // 유휴 프리뷰도 고른 크기로 연다.
        assertEquals(hd, state.idlePreviewSize)
    }

    @Test
    fun openingDoesNotInheritTheValuesOfThePreviousSession() {
        val finished =
            collecting()
                .reduce(CaptureIntent.EditObjectName("cup"))
                .reduce(CaptureIntent.FinalizeStarted)
                .reduce(CaptureIntent.Finalized)

        val reopened = finished.reduce(CaptureIntent.Open("", fullHd))

        assertEquals("", reopened.task)
        assertEquals("", reopened.objectName)
        assertEquals(fullHd, reopened.resolution)
        assertNull(reopened.activeBundle)
        assertEquals(0L, reopened.recordingStartNs)
    }

    @Test
    fun theSessionAdoptsTheResolutionArCoreActuallyChose() {
        // 후보 config가 없어 기본값으로 물러난 경우다. 표시와 프리뷰가 그 값을 따라가야 한다.
        val state =
            CaptureUiState()
                .reduce(CaptureIntent.Open("task", hd))
                .reduce(CaptureIntent.SessionStarted(bundle, 42L, fullHd))

        assertEquals(fullHd, state.resolution)
        assertEquals(fullHd, state.idlePreviewSize)
        assertSame(bundle, state.activeBundle)
    }

    @Test
    fun trackingMovesTheSessionBetweenInitializingAndReady() {
        val initializing = collecting()
        assertEquals(CaptureWorkspaceControlState.Initializing, initializing.phase)

        val ready = initializing.reduce(CaptureIntent.TrackingSampled(ready = true, episodeActive = false))
        assertEquals(CaptureWorkspaceControlState.Ready, ready.phase)

        // 유실은 사용자 조작 없이 일어난다. 같은 입구로 되돌아와야 한다.
        val lost = ready.reduce(CaptureIntent.TrackingSampled(ready = false, episodeActive = false))
        assertEquals(CaptureWorkspaceControlState.Initializing, lost.phase)
    }

    @Test
    fun trackingLossClosesAnActiveEpisodeWithoutUserAction() {
        val episodeActive =
            collecting()
                .reduce(CaptureIntent.TrackingSampled(ready = true, episodeActive = false))
                .reduce(CaptureIntent.EpisodeStarted)
        assertEquals(CaptureWorkspaceControlState.EpisodeActive, episodeActive.phase)

        val invalidated = episodeActive.reduce(CaptureIntent.TrackingSampled(ready = false, episodeActive = false))

        assertEquals(CaptureWorkspaceControlState.Initializing, invalidated.phase)
    }

    @Test
    fun aTrackingSampleIsIgnoredBeforeASessionExistsAndWhileFinalizing() {
        val idle = CaptureUiState().reduce(CaptureIntent.Open("task", hd))
        assertEquals(idle, idle.reduce(CaptureIntent.TrackingSampled(ready = true, episodeActive = true)))

        val finalizing = collecting().reduce(CaptureIntent.FinalizeStarted)
        assertEquals(finalizing, finalizing.reduce(CaptureIntent.TrackingSampled(ready = true, episodeActive = true)))
    }

    @Test
    fun anEpisodeCannotStartBeforeTrackingStabilizes() {
        val initializing = collecting()

        assertEquals(initializing, initializing.reduce(CaptureIntent.EpisodeStarted))
    }

    @Test
    fun aFinalizeFailureHoldsTheWorkspaceUntilItIsAcknowledged() {
        val failed =
            collecting()
                .reduce(CaptureIntent.FinalizeStarted)
                .reduce(CaptureIntent.FinalizeFailed("디스크가 가득 찼습니다"))

        assertEquals("디스크가 가득 찼습니다", failed.finalizeFailure)
        assertFalse(failed.chromeVisible)
        assertTrue(failed.open)

        val acknowledged = failed.reduce(CaptureIntent.FinalizeFailureDismissed)

        assertNull(acknowledged.finalizeFailure)
        assertEquals(CaptureWorkspaceControlState.Idle, acknowledged.phase)
        assertTrue(acknowledged.open)
    }

    @Test
    fun readyRequiresAPreviewFrameBothNamesAndNoOpenDialog() {
        val entered =
            CaptureUiState()
                .reduce(CaptureIntent.Open("task", hd))
                .reduce(CaptureIntent.EditObjectName("cup"))
                .reduce(CaptureIntent.PreviewFrameArrived)
        // 다이얼로그가 열려 있는 동안은 준비된 것으로 보지 않는다.
        assertFalse(entered.ready)

        val confirmed = entered.reduce(CaptureIntent.ConfirmMetadata)
        assertTrue(confirmed.ready)
        assertTrue(confirmed.policy.canPlay)

        assertFalse(confirmed.reduce(CaptureIntent.EditObjectName("")).ready)
        assertFalse(confirmed.reduce(CaptureIntent.PreviewFailed("프리뷰 실패")).ready)
    }

    @Test
    fun aFailedPreviewIsNotRevivedByALateFrame() {
        val failed =
            CaptureUiState()
                .reduce(CaptureIntent.Open("task", hd))
                .reduce(CaptureIntent.PreviewFailed("프리뷰 실패"))

        assertFalse(failed.reduce(CaptureIntent.PreviewFrameArrived).previewReady)
    }

    @Test
    fun aNoticeIsClearedOnceItHasBeenShown() {
        val notified = CaptureUiState().reduce(CaptureIntent.Notify("Tracking이 아직 준비되지 않았습니다"))

        assertEquals("", notified.reduce(CaptureIntent.NoticeShown).notice)
    }

    @Test
    fun beingInterruptedInTheBackgroundLeavesAnEmptyWorkspace() {
        val interrupted = collecting().reduce(CaptureIntent.Interrupted)

        assertEquals(CaptureWorkspaceControlState.Idle, interrupted.phase)
        assertNull(interrupted.activeBundle)
        // 작업 공간 자체는 닫지 않는다. 닫는 것은 Close다.
        assertTrue(interrupted.open)
    }

    @Test
    fun everyReachablePhaseIsOneOfTheFive() {
        val reached =
            setOf(
                CaptureUiState().phase,
                collecting().phase,
                collecting().reduce(CaptureIntent.TrackingSampled(ready = true, episodeActive = false)).phase,
                collecting()
                    .reduce(CaptureIntent.TrackingSampled(ready = true, episodeActive = false))
                    .reduce(CaptureIntent.EpisodeStarted)
                    .phase,
                collecting().reduce(CaptureIntent.FinalizeStarted).phase,
            )

        assertEquals(CaptureWorkspaceControlState.entries.toSet(), reached)
    }

    private val capabilities =
        ManualCameraCapabilities(
            cameraId = "0",
            manualSensor = true,
            aeOffSupported = true,
            afOffSupported = true,
            awbOffSupported = true,
            awbLockSupported = true,
            maxFocusDiopter = 10f,
            isoRange = 50..3200,
            exposureRangeNs = 85_000L..100_000_000L,
            maxFrameDurationNs = 142_857_142L,
        )

    private fun profiled(state: CaptureUiState) =
        state.reduce(CaptureIntent.ManualCameraProfiled(capabilities, capabilities.defaultConfig()))

    @Test
    fun theChosenSettingsAreNarrowedToWhatTheCameraAccepts() {
        val state =
            profiled(CaptureUiState().reduce(CaptureIntent.Open("task", hd)))
                .reduce(
                    CaptureIntent.EditManualCamera(
                        ManualCameraConfig(focusDistanceDiopter = 99f, iso = 5, exposureTimeNs = 100_000_000L),
                    ),
                )

        val config = state.manualCamera.config!!
        assertEquals(10f, config.focusDistanceDiopter, 0f)
        assertEquals(50, config.iso)
        // 노출이 프레임 간격을 넘으면 센서가 간격을 늘려 30 fps가 깨진다.
        assertEquals(ManualCameraConfig.TARGET_FRAME_DURATION_NS, config.exposureTimeNs)
    }

    /**
     * 촬영이 시작되면 값이 잠긴다.
     *
     * 화면에서도 막지만 상태 전이로 한 번 더 막는다. 도중에 조건이 바뀌면 그 Session의 데이터를
     * 한 조건으로 찍었다고 말할 수 없기 때문이다.
     */
    @Test
    fun theSettingsStopAcceptingChangesOnceTheSessionStarts() {
        val recording = profiled(collecting())
        val before = recording.manualCamera.config

        val attempted =
            recording.reduce(
                CaptureIntent.EditManualCamera(
                    ManualCameraConfig(focusDistanceDiopter = 1f, iso = 3200, exposureTimeNs = 2_000_000L),
                ),
            )

        assertEquals(before, attempted.manualCamera.config)
    }

    @Test
    fun startingASessionFoldsTheSettingsPanelAway() {
        val opened =
            profiled(CaptureUiState().reduce(CaptureIntent.Open("task", hd)))
                .reduce(CaptureIntent.ToggleManualCameraPanel(true))
        assertTrue(opened.manualCamera.panelOpen)

        val recording =
            opened
                .reduce(CaptureIntent.ConfirmMetadata)
                .reduce(CaptureIntent.SessionRequested)
                .reduce(CaptureIntent.SessionStarted(bundle, 42L, hd))

        assertFalse(recording.manualCamera.panelOpen)
    }

    /** 능력을 읽기 전에는 좁힐 기준이 없다. 범위를 모르는 값을 담아 두면 그대로 카메라에 걸린다. */
    @Test
    fun noSettingIsHeldBeforeTheCameraHasBeenProfiled() {
        val state =
            CaptureUiState()
                .reduce(CaptureIntent.Open("task", hd))
                .reduce(
                    CaptureIntent.EditManualCamera(
                        ManualCameraConfig(focusDistanceDiopter = 4f, iso = 100, exposureTimeNs = 8_333_333L),
                    ),
                )

        assertNull(state.manualCamera.config)
        assertNull(state.manualCamera.appliedConfig)
    }

    /** 수동 제어를 못 하는 기기에서는 수집을 막지 않고 기존 자동 동작으로 찍는다. */
    @Test
    fun aCameraWithoutManualSupportRecordsTheWayItAlwaysDid() {
        val unsupported = capabilities.copy(manualSensor = false)
        val state =
            CaptureUiState()
                .reduce(CaptureIntent.Open("task", hd))
                .reduce(CaptureIntent.ManualCameraProfiled(unsupported, unsupported.defaultConfig()))

        assertNotNull(state.manualCamera.unsupportedReason)
        assertFalse(state.manualCamera.supported)
        assertNull(state.manualCamera.appliedConfig)
    }
}
