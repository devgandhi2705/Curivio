import { useState, useEffect } from "react"
import { fetchSessionAttachments, fetchAttachmentBlob } from "../../api/chat.js"
import { AttachmentPreviewModal, isAttachmentPastRetention } from "./ChatMessage.jsx"

function CloseIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
    </svg>
  )
}

// One generic type icon for every non-image attachment (PDF/docx/other) —
// no per-subtype icon set, matching this arc's scope discipline.
function FileTypeIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  )
}

export function FilesIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
    </svg>
  )
}

// Real image preview via the same R2-backed blob fetch AttachmentPreviewModal
// uses — a type icon for everything else. No PDF-to-image rendering.
function Thumbnail({ attachment, shareToken }) {
  const isImage = attachment.mime_type?.startsWith("image/")
  const pastRetention = isAttachmentPastRetention(attachment)
  const [url, setUrl] = useState(null)

  useEffect(() => {
    if (!isImage || pastRetention || !attachment.r2_attachment_id) return
    let cancelled = false
    let objectUrl = null
    fetchAttachmentBlob(attachment, shareToken)
      .then(u => { if (!cancelled) { objectUrl = u; setUrl(u) } })
      .catch(() => {})
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attachment.r2_attachment_id])

  if (isImage && url) {
    return <img src={url} alt="" className="w-9 h-9 rounded-lg object-cover flex-shrink-0" />
  }
  return (
    <span className="w-9 h-9 rounded-lg bg-white/[0.06] flex items-center justify-center flex-shrink-0 text-slate-400">
      <FileTypeIcon />
    </span>
  )
}

/**
 * Chat-R16: every attachment across the whole session, browsable in one
 * place, clicking straight into the existing AttachmentPreviewModal.
 *
 * Authenticated (no shareToken): fetches GET /chat/attachments/{sessionId}
 * — unbounded, independent of the caller's own capped in-memory message
 * list.
 * Share view (shareToken set): flatMaps the `messages` prop instead — that
 * data is SharePage's already-loaded, already-unbounded resolve_share_link
 * response, so no separate share-scoped endpoint is needed.
 */
export default function FilesPanel({ sessionId, messages, shareToken, onClose }) {
  const [attachments, setAttachments] = useState(null) // null = loading
  const [previewAttachment, setPreviewAttachment] = useState(null)

  useEffect(() => {
    if (shareToken) {
      setAttachments((messages || []).flatMap(m => m.attachments || []))
      return
    }
    let cancelled = false
    setAttachments(null)
    fetchSessionAttachments(sessionId)
      .then(list => { if (!cancelled) setAttachments(list) })
      .catch(() => { if (!cancelled) setAttachments([]) })
    return () => { cancelled = true }
  }, [sessionId, shareToken, messages])

  return (
    <>
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-md max-h-[80vh] bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-slate-800 flex-shrink-0">
          <h2 className="text-sm font-semibold text-slate-200">Files</h2>
          <button
            onClick={onClose}
            title="Close"
            className="flex items-center justify-center p-1.5 rounded-md text-slate-600 hover:text-slate-400 hover:bg-slate-800/60 transition-colors"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2">
          {attachments === null ? (
            <p className="px-2 py-6 text-center text-xs text-slate-500">Loading…</p>
          ) : attachments.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-slate-500">No files in this chat yet.</p>
          ) : (
            attachments.map((a, i) => {
              const pastRetention = isAttachmentPastRetention(a)
              const isDocScheme = a.uri?.startsWith("doc://")
              const badgeLabel = pastRetention ? (isDocScheme ? "text only" : "expired") : null
              return (
                <button
                  key={`${a.uri}-${i}`}
                  type="button"
                  onClick={() => setPreviewAttachment(a)}
                  className="w-full flex items-center gap-3 px-2 py-2 rounded-xl hover:bg-white/[0.05] transition-colors text-left"
                >
                  <Thumbnail attachment={a} shareToken={shareToken} />
                  <span className="flex-1 min-w-0">
                    <span className="block text-sm text-slate-200 truncate">{a.filename}</span>
                    {a.created_at && (
                      <span className="block text-[10px] text-slate-500">{new Date(a.created_at).toLocaleString()}</span>
                    )}
                  </span>
                  {badgeLabel && <span className="text-amber-500/80 text-[10px] flex-shrink-0">{badgeLabel}</span>}
                </button>
              )
            })
          )}
        </div>
      </div>
    </div>

    {previewAttachment && (
      <AttachmentPreviewModal attachment={previewAttachment} onClose={() => setPreviewAttachment(null)} shareToken={shareToken} />
    )}
    </>
  )
}
