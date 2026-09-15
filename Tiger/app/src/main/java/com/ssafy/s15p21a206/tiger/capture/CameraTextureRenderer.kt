package com.ssafy.s15p21a206.tiger.capture

import android.opengl.GLES11Ext
import android.opengl.GLES20
import com.google.ar.core.Coordinates2d
import com.google.ar.core.Frame
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer

/**
 * ARCore가 채우는 Camera 텍스처를 화면 프리뷰에 그린다.
 *
 * Camera2 출력 surface를 하나 더 여는 대신 이 경로를 쓴다. 대상 기기가 ARCore 2개 + MediaRecorder에
 * preview까지 더한 4개 stream 조합을 거부하기 때문이다. 이 방식은 stream을 늘리지 않는다.
 */
internal class CameraTextureRenderer {
    private var program = 0
    private var positionHandle = 0
    private var texCoordHandle = 0
    private var textureHandle = 0
    private var coordinatesReady = false

    private val ndcCoords: FloatBuffer = floatBufferOf(-1f, -1f, +1f, -1f, -1f, +1f, +1f, +1f)
    private val texCoords: FloatBuffer = floatBufferOf(0f, 0f, 0f, 0f, 0f, 0f, 0f, 0f)

    /** OES 텍스처를 만들어 ARCore에 넘길 이름을 돌려준다. GL context가 current인 상태에서 호출한다. */
    fun createTexture(): Int {
        val ids = IntArray(1)
        GLES20.glGenTextures(1, ids, 0)
        val textureId = ids[0]
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        program = buildProgram()
        positionHandle = GLES20.glGetAttribLocation(program, "a_Position")
        texCoordHandle = GLES20.glGetAttribLocation(program, "a_TexCoord")
        textureHandle = GLES20.glGetUniformLocation(program, "u_Texture")
        return textureId
    }

    fun draw(
        frame: Frame,
        textureId: Int,
        width: Int,
        height: Int,
    ) {
        // 표시 기하가 바뀔 때만 UV를 다시 받는다. 첫 프레임에서는 반드시 한 번 받아야 한다.
        if (!coordinatesReady || frame.hasDisplayGeometryChanged()) {
            frame.transformCoordinates2d(
                Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES,
                ndcCoords,
                Coordinates2d.TEXTURE_NORMALIZED,
                texCoords,
            )
            ndcCoords.position(0)
            texCoords.position(0)
            coordinatesReady = true
        }
        GLES20.glViewport(0, 0, width, height)
        GLES20.glDisable(GLES20.GL_DEPTH_TEST)
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT)
        GLES20.glUseProgram(program)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
        GLES20.glUniform1i(textureHandle, 0)
        GLES20.glEnableVertexAttribArray(positionHandle)
        GLES20.glVertexAttribPointer(positionHandle, 2, GLES20.GL_FLOAT, false, 0, ndcCoords)
        GLES20.glEnableVertexAttribArray(texCoordHandle)
        GLES20.glVertexAttribPointer(texCoordHandle, 2, GLES20.GL_FLOAT, false, 0, texCoords)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
        GLES20.glDisableVertexAttribArray(positionHandle)
        GLES20.glDisableVertexAttribArray(texCoordHandle)
    }

    private fun buildProgram(): Int {
        val vertex = compile(GLES20.GL_VERTEX_SHADER, VERTEX_SHADER)
        val fragment = compile(GLES20.GL_FRAGMENT_SHADER, FRAGMENT_SHADER)
        val id = GLES20.glCreateProgram()
        GLES20.glAttachShader(id, vertex)
        GLES20.glAttachShader(id, fragment)
        GLES20.glLinkProgram(id)
        val linked = IntArray(1)
        GLES20.glGetProgramiv(id, GLES20.GL_LINK_STATUS, linked, 0)
        check(linked[0] != 0) { "Could not link the camera preview program: ${GLES20.glGetProgramInfoLog(id)}" }
        GLES20.glDeleteShader(vertex)
        GLES20.glDeleteShader(fragment)
        return id
    }

    private fun compile(
        type: Int,
        source: String,
    ): Int {
        val id = GLES20.glCreateShader(type)
        GLES20.glShaderSource(id, source)
        GLES20.glCompileShader(id)
        val compiled = IntArray(1)
        GLES20.glGetShaderiv(id, GLES20.GL_COMPILE_STATUS, compiled, 0)
        check(compiled[0] != 0) { "Could not compile the camera preview shader: ${GLES20.glGetShaderInfoLog(id)}" }
        return id
    }

    private fun floatBufferOf(vararg values: Float): FloatBuffer =
        ByteBuffer
            .allocateDirect(values.size * Float.SIZE_BYTES)
            .order(ByteOrder.nativeOrder())
            .asFloatBuffer()
            .apply {
                put(values)
                position(0)
            }

    private companion object {
        const val VERTEX_SHADER =
            """
            attribute vec4 a_Position;
            attribute vec2 a_TexCoord;
            varying vec2 v_TexCoord;
            void main() {
                gl_Position = a_Position;
                v_TexCoord = a_TexCoord;
            }
            """

        const val FRAGMENT_SHADER =
            """
            #extension GL_OES_EGL_image_external : require
            precision mediump float;
            varying vec2 v_TexCoord;
            uniform samplerExternalOES u_Texture;
            void main() {
                gl_FragColor = texture2D(u_Texture, v_TexCoord);
            }
            """
    }
}
