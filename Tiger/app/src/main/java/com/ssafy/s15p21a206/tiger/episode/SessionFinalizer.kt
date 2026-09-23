package com.ssafy.s15p21a206.tiger.episode

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.security.MessageDigest

class SessionFinalizer(
    private val bundleStore: SessionBundleStore,
) {
    fun finalize(
        bundle: SessionBundle,
        includesUltraWide: Boolean = false,
        // 확보하지 못했으면 null. 메타데이터 부재가 Session 마감을 실패시키지 않는다.
        camera: CameraMetadata? = null,
        // 어떤 촬영 조건으로 찍었는지. 수동 설정을 쓰지 않았으면 null이다.
        captureSettings: CaptureSettingsMetadata? = null,
    ): FinalizeResult {
        val validation = SessionBundleValidator.validate(bundle.directory, includesUltraWide, requireMetadata = false)
        if (validation is BundleValidationResult.Invalid) return FinalizeResult.Failed(validation.reason)
        val manifest =
            bundle.directory
                .listFiles()
                .orEmpty()
                .filter { it.isFile && it.name != SessionBundle.METADATA_FILE }
                .associate { file -> file.name to ManifestEntry(file.length(), sha256(file)) }
        bundle.metadata.writeText(
            Json.encodeToString(
                buildJsonObject {
                    put("session_id", bundle.sessionId)
                    put(
                        "camera_streams",
                        buildJsonObject {
                            put("main", true)
                            put("ultrawide", includesUltraWide)
                        },
                    )
                    camera?.let { put("camera", Json.encodeToJsonElement(CameraMetadata.serializer(), it)) }
                    captureSettings?.let {
                        put("capture_settings", Json.encodeToJsonElement(CaptureSettingsMetadata.serializer(), it))
                    }
                    put(
                        "files",
                        buildJsonArray {
                            manifest.toSortedMap().forEach { (path, entry) ->
                                add(
                                    buildJsonObject {
                                        put("path", path)
                                        put("sizeBytes", entry.sizeBytes)
                                        put("sha256", entry.sha256)
                                    },
                                )
                            }
                        },
                    )
                },
            ),
        )
        return FinalizeResult.Completed(bundleStore.publish(bundle, includesUltraWide), manifest.mapValues { it.value.sha256 })
    }

    private fun sha256(file: File): String =
        MessageDigest
            .getInstance("SHA-256")
            .digest(file.readBytes())
            .joinToString("") { "%02x".format(it) }
}

private data class ManifestEntry(
    val sizeBytes: Long,
    val sha256: String,
)

sealed interface FinalizeResult {
    data class Completed(
        val directory: File,
        val checksums: Map<String, String>,
    ) : FinalizeResult

    data class Failed(
        val reason: String,
    ) : FinalizeResult
}
