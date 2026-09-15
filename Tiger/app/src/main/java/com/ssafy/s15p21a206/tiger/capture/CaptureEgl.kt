package com.ssafy.s15p21a206.tiger.capture

import android.opengl.EGL14
import android.opengl.EGLConfig
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLSurface
import android.view.Surface

/**
 * ARCore가 Camera 텍스처를 채우기 위해 요구하는 GL context를 만든다.
 *
 * [window]가 주어지면 그 Surface에 직접 그릴 수 있는 window surface를, 없으면 화면에 보이지 않는
 * 1×1 pbuffer를 쓴다. 후자는 pose만 수집하면 되는 경우다.
 */
internal class CaptureEgl(
    private val window: Surface?,
) : AutoCloseable {
    private val display: EGLDisplay = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
    private val config: EGLConfig
    private val context: EGLContext
    private val surface: EGLSurface

    val hasWindow: Boolean get() = window != null

    init {
        check(display != EGL14.EGL_NO_DISPLAY) { "EGL display is unavailable" }
        val version = IntArray(2)
        check(EGL14.eglInitialize(display, version, 0, version, 1)) { "Could not initialize EGL" }
        val surfaceType = if (window != null) EGL14.EGL_WINDOW_BIT else EGL14.EGL_PBUFFER_BIT
        val configs = arrayOfNulls<EGLConfig>(1)
        val count = IntArray(1)
        check(
            EGL14.eglChooseConfig(
                display,
                intArrayOf(
                    EGL14.EGL_RENDERABLE_TYPE,
                    EGL14.EGL_OPENGL_ES2_BIT,
                    EGL14.EGL_SURFACE_TYPE,
                    surfaceType,
                    EGL14.EGL_NONE,
                ),
                0,
                configs,
                0,
                1,
                count,
                0,
            ) &&
                count[0] > 0,
        ) { "No EGL ES2 config is available" }
        config = requireNotNull(configs[0])
        context =
            EGL14.eglCreateContext(
                display,
                config,
                EGL14.EGL_NO_CONTEXT,
                intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE),
                0,
            )
        check(context != EGL14.EGL_NO_CONTEXT) { "Could not create EGL context" }
        surface =
            if (window != null) {
                EGL14.eglCreateWindowSurface(display, config, window, intArrayOf(EGL14.EGL_NONE), 0)
            } else {
                EGL14.eglCreatePbufferSurface(display, config, intArrayOf(EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE), 0)
            }
        check(surface != EGL14.EGL_NO_SURFACE) { "Could not create the EGL surface" }
    }

    fun makeCurrent() {
        check(EGL14.eglMakeCurrent(display, surface, surface, context)) { "Could not make EGL context current" }
    }

    fun swapBuffers(): Boolean = EGL14.eglSwapBuffers(display, surface)

    override fun close() {
        EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT)
        EGL14.eglDestroySurface(display, surface)
        EGL14.eglDestroyContext(display, context)
        EGL14.eglTerminate(display)
    }
}
