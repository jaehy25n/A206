package com.ssafy.s15p21a206.tiger.episode

import org.junit.Assert.assertFalse
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream

class DocumentTreeGatewayTest {
    @Test
    fun `export is blocked when persisted write grant is unavailable`() {
        val gateway =
            object : DocumentTreeGateway {
                override fun hasPersistedWriteGrant(treeUri: String) = false

                override fun list(directoryUri: String) = emptyList<DocumentNode>()

                override fun createDirectory(
                    parentUri: String,
                    name: String,
                ) = null

                override fun createFile(
                    parentUri: String,
                    name: String,
                    mimeType: String,
                ) = null

                override fun openInput(uri: String): InputStream? = ByteArrayInputStream(byteArrayOf())

                override fun openOutput(uri: String): OutputStream? = ByteArrayOutputStream()

                override fun rename(
                    uri: String,
                    name: String,
                ) = null

                override fun delete(uri: String) = false
            }

        assertFalse(gateway.supportsPublish("content://revoked-tree"))
    }

    @Test
    fun `export is blocked when provider lacks publish capability`() {
        val gateway =
            object : DocumentTreeGateway {
                override fun hasPersistedWriteGrant(treeUri: String) = true

                override fun hasRequiredCapabilities(treeUri: String) = false

                override fun list(directoryUri: String) = emptyList<DocumentNode>()

                override fun createDirectory(
                    parentUri: String,
                    name: String,
                ) = null

                override fun createFile(
                    parentUri: String,
                    name: String,
                    mimeType: String,
                ) = null

                override fun openInput(uri: String): InputStream? = null

                override fun openOutput(uri: String): OutputStream? = null

                override fun rename(
                    uri: String,
                    name: String,
                ) = null

                override fun delete(uri: String) = false
            }

        assertFalse(gateway.supportsPublish("content://limited-tree"))
    }
}
