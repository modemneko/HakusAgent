package com.hakusai.folderpicker

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.activity.result.ActivityResult
import app.tauri.annotation.ActivityCallback
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

private const val DIRECTORY_MIME = "vnd.android.document/directory"
private const val RUNTIME_STATE_DIR = ".hakus"

@InvokeArg
class PickFolderArgs {
  var destination: String = ""
}

@InvokeArg
class SyncFolderArgs {
  var uri: String = ""
  var path: String = ""
}

@TauriPlugin
class FolderPickerPlugin(private val activity: Activity) : Plugin(activity) {
  private var pickArgs: PickFolderArgs? = null

  @Command
  fun pickFolder(invoke: Invoke) {
    val args = invoke.parseArgs(PickFolderArgs::class.java)
    if (args.destination.isBlank()) {
      invoke.reject("Project destination is required")
      return
    }
    pickArgs = args

    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
      addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
      addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
      addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
      putExtra("android.content.extra.SHOW_ADVANCED", true)
    }
    startActivityForResult(invoke, intent, "folderPickerResult")
  }

  @ActivityCallback
  fun folderPickerResult(invoke: Invoke, result: ActivityResult) {
    try {
      if (result.resultCode != Activity.RESULT_OK || result.data?.data == null) {
        invoke.reject("Folder picker cancelled")
        return
      }

      val uri = result.data!!.data!!
      val flags = result.data!!.flags and
        (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
      try {
        activity.contentResolver.takePersistableUriPermission(uri, flags)
      } catch (_: SecurityException) {
        // Some document providers grant a transient permission only. The
        // current operation can still continue, but a later sync may fail.
      }

      val args = pickArgs ?: throw IllegalStateException("folder picker state expired")
      pickArgs = null
      val destination = File(args.destination)
      if (!destination.exists() && !destination.mkdirs()) {
        invoke.reject("Could not create project workspace")
        return
      }
      copyTreeToLocal(uri, destination)

      val response = JSObject()
      response.put("uri", uri.toString())
      response.put("name", displayName(uri) ?: uri.lastPathSegment ?: "Project")
      invoke.resolve(response)
    } catch (error: Exception) {
      invoke.reject(error.message ?: "Could not import selected folder")
    }
  }

  @Command
  fun refreshFolder(invoke: Invoke) {
    try {
      val args = invoke.parseArgs(SyncFolderArgs::class.java)
      copyTreeToLocal(Uri.parse(args.uri), File(args.path))
      invoke.resolve(JSObject().apply { put("ok", true) })
    } catch (error: Exception) {
      invoke.reject(error.message ?: "Could not refresh project")
    }
  }

  @Command
  fun syncFolder(invoke: Invoke) {
    try {
      val args = invoke.parseArgs(SyncFolderArgs::class.java)
      syncLocalToTree(Uri.parse(args.uri), File(args.path))
      invoke.resolve(JSObject().apply { put("ok", true) })
    } catch (error: Exception) {
      invoke.reject(error.message ?: "Could not sync project")
    }
  }

  private fun displayName(uri: Uri): String? {
    val projection = arrayOf(OpenableColumns.DISPLAY_NAME)
    activity.contentResolver.query(uri, projection, null, null, null)?.use { cursor ->
      if (cursor.moveToFirst()) {
        val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (index >= 0) return cursor.getString(index)
      }
    }
    return null
  }

  private fun childDocumentsUri(treeUri: Uri, documentId: String): Uri =
    DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, documentId)

  private fun rootDocumentId(treeUri: Uri): String =
    DocumentsContract.getTreeDocumentId(treeUri)

  private fun copyTreeToLocal(treeUri: Uri, destination: File) {
    destination.mkdirs()
    // The app-private directory is a mirror, so remove files that were
    // deleted from the selected SAF tree before importing the latest state.
    // Keep the runtime's private workspace state between refreshes.
    destination.listFiles()
      ?.filter { it.name != RUNTIME_STATE_DIR }
      ?.forEach { it.deleteRecursively() }
    copyChildrenToLocal(treeUri, rootDocumentId(treeUri), destination)
  }

  private fun copyChildrenToLocal(treeUri: Uri, parentId: String, destination: File) {
    val projection = arrayOf(
      DocumentsContract.Document.COLUMN_DOCUMENT_ID,
      DocumentsContract.Document.COLUMN_DISPLAY_NAME,
      DocumentsContract.Document.COLUMN_MIME_TYPE,
    )
    listChildren(treeUri, parentId)
      .filter { it.name != RUNTIME_STATE_DIR }
      .forEach { child ->
      val local = File(destination, child.name)
      if (child.mimeType == DIRECTORY_MIME) {
        local.mkdirs()
        copyChildrenToLocal(treeUri, child.documentId, local)
      } else {
        activity.contentResolver.openInputStream(child.uri)?.use { input ->
          FileOutputStream(local, false).use { output -> input.copyTo(output) }
        }
      }
    }
  }

  private fun syncLocalToTree(treeUri: Uri, source: File) {
    syncChildrenToTree(treeUri, rootDocumentId(treeUri), source)
  }

  private fun syncChildrenToTree(treeUri: Uri, parentId: String, source: File) {
    val localChildren = source.listFiles()
      ?.filter { it.name != RUNTIME_STATE_DIR }
      .orEmpty()
    val localNames = localChildren.map { it.name }.toSet()

    // Mirror deletions made by the agent back to the user-selected folder.
    // The folder is the user-granted source of truth; only its own children
    // are considered, and the SAF provider still enforces its permissions.
    listChildren(treeUri, parentId)
      .filter { it.name != RUNTIME_STATE_DIR && it.name !in localNames }
      .forEach { child ->
        activity.contentResolver.delete(child.uri, null, null)
      }

    localChildren.forEach { local ->
      val existing = findChild(treeUri, parentId, local.name)
      if (local.isDirectory) {
        val directory = when {
          existing == null -> createDirectory(treeUri, parentId, local.name)
          existing.mimeType == DIRECTORY_MIME -> existing.uri
          else -> {
            activity.contentResolver.delete(existing.uri, null, null)
            createDirectory(treeUri, parentId, local.name)
          }
        } ?: return@forEach
        val id = DocumentsContract.getDocumentId(directory)
        syncChildrenToTree(treeUri, id, local)
      } else {
        val target = when {
          existing == null -> createFile(treeUri, parentId, local.name)
          existing.mimeType != DIRECTORY_MIME -> existing.uri
          else -> {
            activity.contentResolver.delete(existing.uri, null, null)
            createFile(treeUri, parentId, local.name)
          }
        } ?: return@forEach
        activity.contentResolver.openOutputStream(target, "wt")?.use { output ->
          FileInputStream(local).use { input -> input.copyTo(output) }
        }
      }
    }
  }

  private data class ChildDocument(
    val documentId: String,
    val uri: Uri,
    val name: String,
    val mimeType: String,
  )

  private fun listChildren(treeUri: Uri, parentId: String): List<ChildDocument> {
    val children = mutableListOf<ChildDocument>()
    val projection = arrayOf(
      DocumentsContract.Document.COLUMN_DOCUMENT_ID,
      DocumentsContract.Document.COLUMN_DISPLAY_NAME,
      DocumentsContract.Document.COLUMN_MIME_TYPE,
    )
    activity.contentResolver.query(
      childDocumentsUri(treeUri, parentId), projection, null, null, null,
    )?.use { cursor ->
      val idIndex = cursor.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_DOCUMENT_ID)
      val nameIndex = cursor.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
      val mimeIndex = cursor.getColumnIndexOrThrow(DocumentsContract.Document.COLUMN_MIME_TYPE)
      while (cursor.moveToNext()) {
        val documentId = cursor.getString(idIndex)
        children += ChildDocument(
          documentId = documentId,
          uri = DocumentsContract.buildDocumentUriUsingTree(treeUri, documentId),
          name = safeName(cursor.getString(nameIndex)),
          mimeType = cursor.getString(mimeIndex),
        )
      }
    }
    return children
  }

  private fun findChild(treeUri: Uri, parentId: String, name: String): ChildDocument? =
    listChildren(treeUri, parentId).firstOrNull { it.name == name }

  private fun createDirectory(treeUri: Uri, parentId: String, name: String): Uri? =
    DocumentsContract.createDocument(
      activity.contentResolver,
      DocumentsContract.buildDocumentUriUsingTree(treeUri, parentId),
      DIRECTORY_MIME,
      name,
    )

  private fun createFile(treeUri: Uri, parentId: String, name: String): Uri? =
    DocumentsContract.createDocument(
      activity.contentResolver,
      DocumentsContract.buildDocumentUriUsingTree(treeUri, parentId),
      "application/octet-stream",
      name,
    )
  }

  private fun safeName(name: String?): String {
    val cleaned = (name ?: "unnamed").replace(Regex("[\\\\/:*?\"<>|]"), "_").trim()
    return cleaned.ifEmpty { "unnamed" }
  }
}
