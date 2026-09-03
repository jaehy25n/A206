package com.ssafy.s15p21a206.tiger.episode

import java.io.File
import java.security.MessageDigest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class SessionFinalizer(private val bundleStore: SessionBundleStore) {
    fun finalize(bundle: SessionBundle, includesUltraWide: Boolean = false): FinalizeResult {
        val validation = SessionBundleValidator.validate(bundle.directory, includesUltraWide, requireMetadata = false)
        if (validation is BundleValidationResult.Invalid) return FinalizeResult.Failed(validation.reason)
        val manifest = bundle.directory.listFiles().orEmpty()
            .filter { it.isFile && it.name != SessionBundle.METADATA_FILE }
            .associate { file -> file.name to ManifestEntry(file.length(), sha256(file)) }
        bundle.metadata.writeText(Json.encodeToString(buildJsonObject {
            put("session_id", bundle.sessionId)
            put("camera_streams", buildJsonObject { put("main", true); put("ultrawide", includesUltraWide) })
            put("files", buildJsonArray {
                manifest.toSortedMap().forEach { (path, entry) ->
                    add(buildJsonObject {
                        put("path", path)
                        put("sizeBytes", entry.sizeBytes)
                        put("sha256", entry.sha256)
                    })
                }
            })
        }))
        return FinalizeResult.Completed(bundleStore.publish(bundle, includesUltraWide), manifest.mapValues { it.value.sha256 })
    }

    private fun sha256(file: File): String = MessageDigest.getInstance("SHA-256")
        .digest(file.readBytes()).joinToString("") { "%02x".format(it) }
}

private data class ManifestEntry(val sizeBytes: Long, val sha256: String)

sealed interface FinalizeResult {
    data class Completed(val directory: File, val checksums: Map<String, String>) : FinalizeResult
    data class Failed(val reason: String) : FinalizeResult
}
