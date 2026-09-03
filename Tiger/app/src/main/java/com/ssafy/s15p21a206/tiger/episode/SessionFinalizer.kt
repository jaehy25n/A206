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
            .associate { it.name to sha256(it) }
        bundle.metadata.writeText(Json.encodeToString(buildJsonObject {
            put("session_id", bundle.sessionId)
            put("camera_streams", buildJsonObject { put("main", true); put("ultrawide", includesUltraWide) })
            put("files", buildJsonArray { manifest.keys.sorted().forEach { add(JsonPrimitive(it)) } })
        }))
        return FinalizeResult.Completed(bundleStore.publish(bundle, includesUltraWide), manifest)
    }

    private fun sha256(file: File): String = MessageDigest.getInstance("SHA-256")
        .digest(file.readBytes()).joinToString("") { "%02x".format(it) }
}

sealed interface FinalizeResult {
    data class Completed(val directory: File, val checksums: Map<String, String>) : FinalizeResult
    data class Failed(val reason: String) : FinalizeResult
}
