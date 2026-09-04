package com.ssafy.s15p21a206.tiger.episode

import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import java.io.InputStream
import java.io.OutputStream

data class DocumentNode(val uri: String, val name: String, val isDirectory: Boolean)

interface DocumentTreeGateway {
    fun hasPersistedWriteGrant(treeUri: String): Boolean
    fun hasRequiredCapabilities(treeUri: String): Boolean = true
    fun isWithinTree(treeUri: String, documentUri: String): Boolean = true
    fun list(directoryUri: String): List<DocumentNode>
    fun createDirectory(parentUri: String, name: String): DocumentNode?
    fun createFile(parentUri: String, name: String, mimeType: String): DocumentNode?
    fun openInput(uri: String): InputStream?
    fun openOutput(uri: String): OutputStream?
    fun rename(uri: String, name: String): DocumentNode?
    fun delete(uri: String): Boolean

    fun supportsPublish(treeUri: String): Boolean = hasPersistedWriteGrant(treeUri) && hasRequiredCapabilities(treeUri)
}

class SafDocumentTreeGateway(private val context: Context) : DocumentTreeGateway {
    private val resolver: ContentResolver = context.contentResolver

    fun createTreePickerIntent(): Intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        putExtra(DocumentsContract.EXTRA_INITIAL_URI, Uri.parse("content://com.android.externalstorage.documents/root/home"))
    }

    fun persistGrant(uri: Uri, flags: Int) {
        resolver.takePersistableUriPermission(uri, flags and (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION))
    }

    override fun hasPersistedWriteGrant(treeUri: String): Boolean = resolver.persistedUriPermissions.any {
        it.uri.toString() == treeUri && it.isReadPermission && it.isWritePermission
    }

    override fun hasRequiredCapabilities(treeUri: String): Boolean {
        val tree = documentUri(treeUri)
        return resolver.query(tree, arrayOf(DocumentsContract.Document.COLUMN_FLAGS), null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) return@use false
            val flags = cursor.getLong(0)
            flags and DocumentsContract.Document.FLAG_DIR_SUPPORTS_CREATE.toLong() != 0L &&
                flags and DocumentsContract.Document.FLAG_SUPPORTS_DELETE.toLong() != 0L &&
                flags and DocumentsContract.Document.FLAG_SUPPORTS_RENAME.toLong() != 0L
        } ?: false
    }

    override fun isWithinTree(treeUri: String, documentUri: String): Boolean = runCatching {
        val treeId = DocumentsContract.getTreeDocumentId(Uri.parse(treeUri))
        documentId(Uri.parse(documentUri)).startsWith(treeId)
    }.getOrDefault(false)

    override fun list(directoryUri: String): List<DocumentNode> {
        val parent = documentUri(directoryUri)
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(parent, documentId(parent))
        return resolver.query(children, arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE), null, null, null)?.use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    val id = cursor.getString(0)
                    add(DocumentNode(DocumentsContract.buildDocumentUriUsingTree(parent, id).toString(), cursor.getString(1), cursor.getString(2) == DocumentsContract.Document.MIME_TYPE_DIR))
                }
            }
        }.orEmpty()
    }

    override fun createDirectory(parentUri: String, name: String): DocumentNode? = create(parentUri, DocumentsContract.Document.MIME_TYPE_DIR, name, true)
    override fun createFile(parentUri: String, name: String, mimeType: String): DocumentNode? = create(parentUri, mimeType, name, false)
    override fun openInput(uri: String): InputStream? = resolver.openInputStream(Uri.parse(uri))
    override fun openOutput(uri: String): OutputStream? = resolver.openOutputStream(Uri.parse(uri), "w")
    override fun rename(uri: String, name: String): DocumentNode? = DocumentsContract.renameDocument(resolver, Uri.parse(uri), name)?.let { renamed -> DocumentNode(renamed.toString(), name, true) }
    override fun delete(uri: String): Boolean = DocumentsContract.deleteDocument(resolver, Uri.parse(uri))

    private fun create(parentUri: String, mimeType: String, name: String, directory: Boolean): DocumentNode? =
        DocumentsContract.createDocument(resolver, documentUri(parentUri), mimeType, name)?.let { uri -> DocumentNode(uri.toString(), name, directory) }

    private fun documentUri(uri: String): Uri {
        val parsed = Uri.parse(uri)
        return runCatching { DocumentsContract.getDocumentId(parsed) }
            .map { parsed }
            .getOrElse { DocumentsContract.buildDocumentUriUsingTree(parsed, DocumentsContract.getTreeDocumentId(parsed)) }
    }

    private fun documentId(uri: Uri): String = runCatching { DocumentsContract.getDocumentId(uri) }
        .getOrElse { DocumentsContract.getTreeDocumentId(uri) }
}
