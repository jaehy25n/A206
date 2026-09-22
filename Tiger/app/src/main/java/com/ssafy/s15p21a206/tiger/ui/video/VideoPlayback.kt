package com.ssafy.s15p21a206.tiger.ui.video

import android.content.Context
import android.net.Uri
import android.view.View
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import com.ssafy.s15p21a206.tiger.R
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.ui.common.LockLandscapeWhilePlaying
import com.ssafy.s15p21a206.tiger.ui.theme.TigerText
import java.io.File

@Composable
@Suppress("FunctionName")
internal fun FullScreenVideoScreen(
    bundlePath: String?,
    sharedPlayer: SharedVideoPlayer,
    onBack: () -> Unit,
) {
    val videoFile = bundlePath?.let { File(it, SessionBundle.MAIN_VIDEO_FILE) }
    val playable = videoFile?.isFile == true && videoFile.length() > 0L
    var landscapeLocked by remember { mutableStateOf(false) }
    // 재생할 영상이 없으면 컨트롤이 뜨지 않으므로, 뒤로 가기가 사라지지 않게 처음부터 보이게 둔다.
    var controlsVisible by remember { mutableStateOf(true) }
    LockLandscapeWhilePlaying(landscapeLocked)
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (playable) {
            VideoPlayer(
                player = sharedPlayer.playerFor(videoFile),
                fullscreen = true,
                onFullscreenClick = onBack,
                modifier = Modifier.fillMaxSize(),
                onControlsVisibilityChanged = { controlsVisible = it },
            )
        } else {
            Text(
                text = stringResource(R.string.session_detail_video_unavailable),
                style = TigerText.onVideoBody,
                modifier = Modifier.align(Alignment.Center),
            )
        }
        if (controlsVisible) {
            // 검은 배경은 화면 끝까지 채우되 컨트롤만 시스템 바를 피한다. 가로로 눕히면 컷아웃이
            // 좌우로 오므로 상단 여백만으로는 모자란다.
            IconButton(
                onClick = onBack,
                modifier = Modifier.align(Alignment.TopStart).safeDrawingPadding(),
            ) {
                Icon(
                    painter = painterResource(R.drawable.ic_navigation_back),
                    contentDescription = stringResource(R.string.navigation_back),
                    tint = Color.White,
                )
            }
            if (playable) {
                LandscapeLockButton(
                    landscapeLocked = landscapeLocked,
                    onToggle = { landscapeLocked = !landscapeLocked },
                    modifier = Modifier.align(Alignment.TopEnd).safeDrawingPadding(),
                )
            }
        }
    }
}

/**
 * 가로 고정을 켜고 끄는 플레이어 컨트롤이다. Media3는 회전 버튼을 제공하지 않아 직접 만든다.
 */
@Composable
@Suppress("FunctionName")
private fun LandscapeLockButton(
    landscapeLocked: Boolean,
    onToggle: () -> Unit,
    modifier: Modifier,
) {
    IconButton(
        onClick = onToggle,
        modifier =
            modifier.background(
                color = if (landscapeLocked) Color.White.copy(alpha = 0.24f) else Color.Transparent,
                shape = CircleShape,
            ),
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_screen_rotation),
            contentDescription =
                stringResource(
                    if (landscapeLocked) {
                        R.string.session_video_unlock_landscape
                    } else {
                        R.string.session_video_lock_landscape
                    },
                ),
            tint = Color.White,
        )
    }
}

// PlayerView는 Media3의 unstable API다. 앱이 직접 쓰는 유일한 지점이라 여기서만 opt-in한다.
@androidx.annotation.OptIn(UnstableApi::class)
@Composable
@Suppress("FunctionName")
internal fun VideoPlayer(
    player: ExoPlayer,
    fullscreen: Boolean,
    onFullscreenClick: () -> Unit,
    modifier: Modifier,
    onControlsVisibilityChanged: (Boolean) -> Unit = {},
) {
    // listener를 factory에서 한 번만 걸기 때문에, 콜백은 최신 값을 따라가게 감싼다.
    val currentFullscreenClick by rememberUpdatedState(onFullscreenClick)
    val currentControlsVisibilityChanged by rememberUpdatedState(onControlsVisibilityChanged)
    AndroidView(
        factory = { viewContext ->
            PlayerView(viewContext).apply {
                // 버튼 상태를 먼저 맞추고 listener를 건다. `setFullscreenButtonState`는 상태만
                // 바꾸지 않고 listener까지 호출하므로, 순서를 바꾸면 전체화면에 들어가자마자
                // 콜백이 불려 곧바로 상세 화면으로 되돌아간다.
                setFullscreenButtonState(fullscreen)
                // 전체화면 버튼과 콜백만 Media3가 주고, 화면 전환은 앱이 한다.
                setFullscreenButtonClickListener { currentFullscreenClick() }
                setControllerVisibilityListener(
                    PlayerView.ControllerVisibilityListener { visibility ->
                        currentControlsVisibilityChanged(visibility == View.VISIBLE)
                    },
                )
            }
        },
        update = { view -> view.player = player },
        onRelease = { view -> view.player = null },
        modifier = modifier,
    )
}

/**
 * 영상의 가로세로 비율을 따라간다. 회전 metadata가 적용된 크기를 쓰므로, `video_rotation_degrees`가
 * 90인 기존 수집분은 세로 비율로 나온다.
 */
@Composable
internal fun rememberVideoAspectRatio(player: ExoPlayer): Float {
    var aspectRatio by remember(player) { mutableFloatStateOf(DEFAULT_VIDEO_ASPECT_RATIO) }
    DisposableEffect(player) {
        fun apply(videoSize: VideoSize) {
            if (videoSize.width > 0 && videoSize.height > 0) {
                aspectRatio = videoSize.width * videoSize.pixelWidthHeightRatio / videoSize.height
            }
        }
        apply(player.videoSize)
        val listener =
            object : Player.Listener {
                override fun onVideoSizeChanged(videoSize: VideoSize) = apply(videoSize)
            }
        player.addListener(listener)
        onDispose { player.removeListener(listener) }
    }
    return aspectRatio
}

/** 영상 크기를 아직 모를 때 쓰는 비율. 크기를 알게 되면 즉시 교체된다. */
private const val DEFAULT_VIDEO_ASPECT_RATIO = 16f / 9f

/**
 * 상세 화면과 전체화면이 같은 ExoPlayer를 쓰게 한다.
 *
 * 두 화면은 서로 다른 destination이라 Composable이 새로 만들어지지만, 재생기는 이 객체가 들고
 * 있으므로 화면을 오갈 때도 재생 위치가 유지된다.
 */
internal class SharedVideoPlayer(
    private val context: Context,
) {
    private var player: ExoPlayer? = null
    private var preparedPath: String? = null

    /** 같은 파일이면 쓰던 재생기를 그대로 준다. 다른 파일이면 그 파일로 다시 적재한다. */
    fun playerFor(videoFile: File): ExoPlayer {
        val current = player ?: ExoPlayer.Builder(context).build().also { player = it }
        val path = videoFile.absolutePath
        if (preparedPath != path) {
            current.setMediaItem(MediaItem.fromUri(Uri.fromFile(videoFile)))
            current.prepare()
            preparedPath = path
        }
        return current
    }

    /**
     * 재생을 멈춘다. 적재한 파일은 그대로 두므로 다시 누르면 이어서 재생한다.
     *
     * 화면을 덮는 판이 뜨는 동안 쓴다. 놓지 않고 멈추기만 하는 이유는, 놓으면 판 뒤의 재생 영역이
     * 빈 화면이 되어 무엇을 덮고 있는지 알 수 없게 되기 때문이다.
     */
    fun pause() {
        player?.pause()
    }

    fun release() {
        player?.release()
        player = null
        preparedPath = null
    }
}

@Composable
internal fun rememberSharedVideoPlayer(): SharedVideoPlayer {
    val context = LocalContext.current.applicationContext
    val sharedPlayer = remember(context) { SharedVideoPlayer(context) }
    DisposableEffect(sharedPlayer) { onDispose(sharedPlayer::release) }
    return sharedPlayer
}
