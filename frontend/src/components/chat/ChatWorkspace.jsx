import { useState, useEffect, useRef, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { sendMessageStream, cancelStream, fetchHistory, fetchSessions, clearHistory, renameSession, deleteSession, deleteLastTurn } from "../../api/chat.js"
import { createFeedChatLink, articleKeyFromTitle } from "../../api/feed.js"
import { useSidebarSubsection } from "../../contexts/SidebarSubsection.jsx"
import { useContextMenu } from "../../contexts/ContextMenu.jsx"
import ChatMessage from "./ChatMessage.jsx"
import ChatInput from "./ChatInput.jsx"
import { SessionListContent } from "./SessionList.jsx"
import ShareButton from "../ShareButton.jsx"
import FilesPanel, { FilesIcon } from "./FilesPanel.jsx"

function RenameModal({ heading, initialValue, onConfirm, onClose }) {
  const [value, setValue] = useState(initialValue)
  const inputRef = useRef(null)
  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select() }, [])
  function handleKeyDown(e) {
    if (e.key === 'Enter' && value.trim()) { e.preventDefault(); onConfirm(value.trim()) }
    if (e.key === 'Escape') onClose()
    e.stopPropagation()
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-xs bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl p-5 space-y-3" onClick={e => e.stopPropagation()}>
        <h2 className="text-sm font-semibold text-slate-200">{heading}</h2>
        <input
          ref={inputRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={120}
          className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500/60"
        />
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2 text-sm rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">Cancel</button>
          <button onClick={() => value.trim() && onConfirm(value.trim())} disabled={!value.trim()} className="flex-1 py-2 text-sm rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-medium transition-colors">Rename</button>
        </div>
      </div>
    </div>
  )
}

function generateSessionId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function apiMessageToLocal(msg) {
  return {
    id: msg.id ?? `hist-${Math.random()}`,
    role: msg.role,
    content: msg.content,
    action: null,
    recommendations: null,
    contextUsed: null,
    attachments: msg.attachments ?? null, // no previewUrl — history has no bytes, see ChatMessage's expiry chip
    thinking: msg.thinking ?? null,
    blocks: msg.blocks ?? null, // Chat-R10e: ordered thinking/tool_call/text segments; null for pre-R10d rows
    created_at: msg.created_at ?? null,
  }
}

const GREETINGS = {
  morning:   ["Rise and shine", "Good morning", "Ready to go", "Fresh start", "Early bird mode", "Seize the day", "Morning momentum", "Let's get it"],
  afternoon: ["Good afternoon", "Crushing it today", "Midday momentum", "Keep the energy up", "Still going strong", "On a roll", "Power hour", "Afternoon check-in"],
  evening:   ["Good evening", "Golden hour", "Evening vibes", "Day well spent", "Winding down strong", "Finishing strong", "Almost there", "End of day power"],
  night:     ["Burning the midnight oil", "Night owl mode", "Owning the night", "The night is yours", "After-hours mode", "Midnight grind", "Stars are out", "Big ideas after dark"],
}

function getGreeting(name, rand) {
  const now  = new Date()
  const mins = now.getHours() * 60 + now.getMinutes()
  let pool
  if      (mins >= 240 && mins < 660)  pool = GREETINGS.morning
  else if (mins >= 660 && mins < 960)  pool = GREETINGS.afternoon
  else if (mins >= 960 && mins < 1170) pool = GREETINGS.evening
  else                                  pool = GREETINGS.night
  const time      = pool[Math.floor(rand * pool.length)]
  const firstName = (name || "").split(" ")[0]
  return firstName ? `${time}, ${firstName}` : time
}

export default function ChatWorkspace({ feedContext = null, onClearFeedContext, targetSessionId = null, targetSessionTitle = null, onClearTargetSession, userName, onSidebarClose, onBeforeModal }) {
  const navigate = useNavigate()
  const [sessionId, setSessionId]     = useState(() => generateSessionId())
  const [messages, setMessages]       = useState([])
  const [sessions, setSessions]       = useState([])
  const [isLoading, setIsLoading]     = useState(false)
  const [error, setError]             = useState(null)
  const [chatMode, setChatMode]         = useState("normal")
  const [statusMsg, setStatusMsg]       = useState(null)
  const [statusHistory, setStatusHistory] = useState([])
  const [autoMode, setAutoMode]         = useState(null)
  // Tracks whether the current session was started in layman / explain-simply mode.
  // Persists across manual chatMode changes so all turns stay simplified.
  const [conversationMode, setConversationMode] = useState(null)
  // Signals that the next render should auto-fire a send (used by explain_simply flow)
  const [autoSendPending, setAutoSendPending] = useState(false)

  // Active feed context drives the context-header UI and is consumed on first send
  const [activeFeedCtx, setActiveFeedCtx] = useState(null)
  // Prevents creating more than one feed-chat link per session
  const feedLinkCreated = useRef(false)

  const bottomRef      = useRef(null)
  const streamAbortRef = useRef(null)
  const greetingRandRef = useRef(Math.random())  // stable random per session for varied greeting

  // Cancel any in-flight stream on unmount
  useEffect(() => () => { streamAbortRef.current?.() }, [])

  // Load sessions list on mount
  useEffect(() => {
    fetchSessions()
      .then(setSessions)
      .catch(() => {})
  }, [])

  // When a feed context arrives, store it and (for explain_simply) schedule auto-send.
  useEffect(() => {
    if (!feedContext) return
    setActiveFeedCtx(feedContext)
    feedLinkCreated.current = false
    onClearFeedContext?.()
    if (feedContext.action === "explain_simply") {
      setConversationMode("layman")
      setAutoSendPending(true)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedContext])

  // Fire the auto-send once activeFeedCtx is committed to state.
  useEffect(() => {
    if (!autoSendPending || !activeFeedCtx || activeFeedCtx.action !== "explain_simply") return
    if (isLoading) return
    setAutoSendPending(false)
    handleSend("Explain this simply.")
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSendPending, activeFeedCtx, isLoading])

  // When navigating from Related Discussions: load the target session's history.
  useEffect(() => {
    if (!targetSessionId) return
    onClearTargetSession?.()
    handleSelectSession({ session_id: targetSessionId, title: targetSessionTitle })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetSessionId])

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, isLoading])

  const handleSend = useCallback((text, attachments = [], { retryMode = false } = {}) => {
    if (isLoading) return
    setError(null)
    setStatusMsg(null)

    // Consume and clear the active feed context on this send
    const feedCtx = activeFeedCtx
    setActiveFeedCtx(null)

    // Derive effective chat mode — feed context > conversationMode > chatMode toggle
    const _FEED_ACTION_TO_MODE = { ask_about: "normal", explain_simply: "layman" }
    const effectiveMode = feedCtx
      ? (_FEED_ACTION_TO_MODE[feedCtx.action] ?? "normal")
      : (conversationMode === "layman" ? "layman" : chatMode)

    const userMsg = {
      id:              `user-${Date.now()}`,
      role:            "user",
      content:         text,
      created_at:      new Date().toISOString(),
      streaming:       false,
      action:          null,
      recommendations: null,
      contextUsed:     null,
      chatMode:        effectiveMode,
      attachments:     attachments.length ? attachments : null,
    }

    // Placeholder assistant message — grows as chunks arrive
    const streamId = `stream-${Date.now()}`
    const streamMsg = {
      id:              streamId,
      role:            "assistant",
      content:         "",
      created_at:      new Date().toISOString(),
      statusMsg:       "",
      thinking:        "",
      thinkingGap:     null,
      codeExecutionGap:    null,
      searchStatus:    null,
      codeBlocks:      [],
      blocks:          [],
      streaming:       true,
      action:          null,
      recommendations: null,
      contextUsed:     null,
      chatMode:        effectiveMode,
    }

    setMessages(prev => retryMode ? [...prev, streamMsg] : [...prev, userMsg, streamMsg])
    setStatusHistory([])
    setIsLoading(true)

    let accumulated = ""
    let thinkingAccumulated = ""
    let thinkingGapText = null
    let codeExecutionGapText = null
    let codeBlocksAccumulated = []
    let toolStatusText = null
    let sawFirstStatus = false // chat_service always yields a generic "Generating response…" ping first (chat_service.py:295), then real tool_start labels — skip only that first one

    // Chat-R10e: live ordered blocks[], built from R10d's seq/block_id-tagged
    // events as they stream — mirrors chat_service.py's own _block_entry fold
    // (same block_id = same contiguous run; a tool_start/tool_end pair for
    // one call shares a block_id). Kept alongside thinkingAccumulated/
    // codeBlocksAccumulated above, not replacing them, for backward compat
    // this phase. Events with no block_id (the two non-tool status pings)
    // are skipped — nothing to fold them into.
    let blocksAccumulated = []
    const blockIndexById = new Map()
    function upsertBlock(blockId, factory, mutate) {
      if (blockId == null) return
      let idx = blockIndexById.get(blockId)
      if (idx === undefined) {
        idx = blocksAccumulated.length
        blockIndexById.set(blockId, idx)
        blocksAccumulated = [...blocksAccumulated, mutate(factory())]
      } else {
        blocksAccumulated = blocksAccumulated.map((b, i) => i === idx ? mutate(b) : b)
      }
    }

    streamAbortRef.current = sendMessageStream(sessionId, text, {
      onChunk(chunk, seq, blockId) {
        accumulated += chunk
        upsertBlock(blockId, () => ({ type: "text", text: "" }), b => ({ ...b, text: b.text + chunk }))
        setStatusMsg(null)
        setMessages(prev =>
          prev.map(m => m.id === streamId ? { ...m, content: accumulated, blocks: blocksAccumulated } : m)
        )
      },
      onThinking(chunk, seq, blockId) {
        thinkingAccumulated += chunk
        upsertBlock(blockId, () => ({ type: "thinking", text: "" }), b => ({ ...b, text: b.text + chunk }))
        setStatusMsg(null)
        setMessages(prev =>
          prev.map(m => m.id === streamId ? { ...m, thinking: thinkingAccumulated, blocks: blocksAccumulated } : m)
        )
      },
      onThinkingGap(text) {
        thinkingGapText = text
        setMessages(prev =>
          prev.map(m => m.id === streamId ? { ...m, thinkingGap: text } : m)
        )
      },
      onCodeExecutionGap(text) {
        codeExecutionGapText = text
        setMessages(prev =>
          prev.map(m => m.id === streamId ? { ...m, codeExecutionGap: text } : m)
        )
      },
      onCode(source, language) {
        codeBlocksAccumulated = [...codeBlocksAccumulated, { code: source, language, output: null, success: null }]
        const snapshot = codeBlocksAccumulated
        setMessages(prev =>
          prev.map(m => m.id === streamId ? { ...m, codeBlocks: snapshot } : m)
        )
      },
      onCodeOutput(output, success) {
        // Fills the most recently pushed block still missing its result —
        // executable_code and code_execution_result stream as two separate
        // chunks for the same call (see chat_agent._split_content_chunks).
        codeBlocksAccumulated = codeBlocksAccumulated.map((b, i) =>
          i === codeBlocksAccumulated.length - 1 ? { ...b, output, success } : b
        )
        const snapshot = codeBlocksAccumulated
        setMessages(prev =>
          prev.map(m => m.id === streamId ? { ...m, codeBlocks: snapshot } : m)
        )
      },
      onTitle(title) {
        setSessions(prev => {
          const exists = prev.some(s => s.session_id === sessionId)
          if (exists) {
            const updated = prev.map(s => s.session_id === sessionId ? { ...s, title } : s)
            const idx = updated.findIndex(s => s.session_id === sessionId)
            if (idx > 0) { const [item] = updated.splice(idx, 1); return [item, ...updated] }
            return updated
          }
          return [{ session_id: sessionId, title, message_count: 0, last_active_at: new Date().toISOString() }, ...prev]
        })
      },
      onStatus(msg, seq, blockId, tool, query, sources) {
        setStatusMsg(msg)
        setStatusHistory(prev => [...prev, msg])
        setMessages(prev =>
          prev.map(m => m.id === streamId ? { ...m, statusMsg: msg } : m)
        )
        // Real tool signal (e.g. "Searching the web…") — persist onto the message
        // itself so it survives past the first content chunk, unlike statusMsg
        // above which TypingIndicator clears on first token.
        if (sawFirstStatus) {
          toolStatusText = msg
          setMessages(prev =>
            prev.map(m => m.id === streamId ? { ...m, searchStatus: msg } : m)
          )
        }
        sawFirstStatus = true
        // Chat-R10e: tool is only set on the two tool-derived status lines
        // (tool_start carries query, tool_end carries sources — same block_id,
        // see chat_service.chat_stream's docstring) — the plain status pings
        // have no tool and are skipped here, same as upsertBlock(null, ...).
        if (tool) {
          upsertBlock(
            blockId,
            () => ({ type: "tool_call", tool, query: query ?? null, sources: [] }),
            b => ({
              ...b,
              tool,
              query:   query   !== undefined ? query   : b.query,
              sources: sources !== undefined ? sources : b.sources,
            }),
          )
          setMessages(prev =>
            prev.map(m => m.id === streamId ? { ...m, blocks: blocksAccumulated } : m)
          )
        }
      },
      onDone(meta) {
        setStatusMsg(null)
        setStatusHistory([])
        if (meta.auto_mode) setAutoMode(meta.chat_mode ?? null)
        else setAutoMode(null)
        if (meta.title) {
          setSessions(prev => {
            const exists = prev.some(s => s.session_id === sessionId)
            if (exists) return prev.map(s => s.session_id === sessionId ? { ...s, title: meta.title } : s)
            return [{ session_id: sessionId, title: meta.title, message_count: 0, last_active_at: new Date().toISOString() }, ...prev]
          })
        }
        setMessages(prev =>
          prev.map(m =>
            m.id === streamId
              ? {
                  id:                  `asst-${meta.message_id ?? Date.now()}`,
                  role:                "assistant",
                  content:             accumulated,
                  created_at:          m.created_at,
                  statusMsg:           "",
                  thinking:            thinkingAccumulated || null,
                  thinkingGap:         thinkingGapText,
                  codeExecutionGap:    codeExecutionGapText,
                  searchStatus:        toolStatusText,
                  codeBlocks:          codeBlocksAccumulated.length ? codeBlocksAccumulated : null,
                  blocks:              blocksAccumulated.length ? blocksAccumulated : null,
                  streaming:           false,
                  action:              meta.action          ?? null,
                  recommendations:     meta.recommendations ?? null,
                  contextUsed:         meta.context_used    ?? null,
                  sources:             meta.sources?.length  ? meta.sources : null,
                  chatMode:            meta.chat_mode       ?? chatMode,
                  autoMode:            meta.auto_mode       ?? false,
                  structured_response: meta.structured_response ?? null,
                }
              : m
          )
        )
        setIsLoading(false)
        // Optimistically increment turn count for the active session
        setSessions(prev => prev.map(s =>
          s.session_id === sessionId
            ? { ...s, message_count: (s.message_count || 0) + 1, last_active_at: new Date().toISOString() }
            : s
        ))
        fetchSessions()
          .then(data => setSessions(data.sort((a, b) => new Date(b.last_active_at) - new Date(a.last_active_at))))
          .catch(() => {})

        // Persist feed→chat link on first successful message (non-blocking)
        if (feedCtx && !feedLinkCreated.current && feedCtx.project_id) {
          feedLinkCreated.current = true
          createFeedChatLink({
            sessionId,
            projectId:       feedCtx.project_id,
            articleKey:      articleKeyFromTitle(feedCtx.insight_title || ""),
            articleTitle:    feedCtx.insight_title || "",
            interactionType: feedCtx.action || "ask_about",
            insightId:       feedCtx.insight_id ?? null,
          }).catch(() => {})
        }
      },
      onError(err) {
        setStatusMsg(null)
        setStatusHistory([])
        setMessages(prev => prev.filter(m => m.id !== streamId))
        setError(err || "Something went wrong. Please try again.")
        setIsLoading(false)
      },
    }, effectiveMode, feedCtx, attachments.map(({ previewUrl, ...a }) => a))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, isLoading, chatMode, activeFeedCtx, conversationMode])

  const handleNewChat = useCallback(() => {
    setSessionId(generateSessionId())
    setMessages([])
    setError(null)
    setConversationMode(null)
    setChatMode("normal")
    navigate('/chat')
  }, [navigate])

  const handleSelectSession = useCallback(async (session) => {
    if (session.session_id === sessionId) return
    navigate(`/chat/${session.session_id}`)
    setSessionId(session.session_id)
    setMessages([])
    setError(null)
    setConversationMode(null)
    setChatMode("normal")
    setIsLoading(true)
    try {
      const history = await fetchHistory(session.session_id, 50)
      setMessages(history.map(apiMessageToLocal))
      // Ensure the session appears in the sidebar (feed-linked sessions are excluded
      // from fetchSessions, so they won't be in the list otherwise)
      setSessions(prev => {
        if (prev.some(s => s.session_id === session.session_id)) return prev
        return [{
          session_id:     session.session_id,
          title:          session.title ?? null,
          message_count:  Math.floor(history.length / 2),
          last_active_at: new Date().toISOString(),
        }, ...prev]
      })
    } catch (e) {
      setError("Could not load session history.")
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, navigate])

  const handleClearSession = useCallback(async () => {
    if (!messages.length) return
    try {
      await clearHistory(sessionId)
      setMessages([])
    } catch (e) {
      setError("Could not clear history.")
    }
  }, [sessionId, messages.length])

  const handleRename = useCallback(async (sid, newTitle) => {
    try {
      await renameSession(sid, newTitle)
      setSessions(prev => prev.map(s => s.session_id === sid ? { ...s, title: newTitle } : s))
    } catch (e) {
      // silently ignore rename failures
    }
  }, [])

  const handleDeleteSession = useCallback(async (sid) => {
    try {
      await deleteSession(sid)
    } catch (e) {}
    setSessions(prev => prev.filter(s => s.session_id !== sid))
    if (sid === sessionId) {
      setSessionId(generateSessionId())
      setMessages([])
      setError(null)
      navigate('/chat')
    }
  }, [sessionId, navigate])

  const handleRetry = useCallback(async (msgIndex) => {
    const userMsg = messages[msgIndex - 1]
    if (!userMsg || userMsg.role !== "user") return
    try { await deleteLastTurn(sessionId) } catch (e) {}
    setMessages(prev => prev.slice(0, msgIndex))
    handleSend(userMsg.content, userMsg.attachments || [], { retryMode: true })
  }, [messages, sessionId, handleSend])

  const handleEditMessage = useCallback((msgIndex, newText) => {
    const userMsg = messages[msgIndex]
    setMessages(prev => prev.slice(0, msgIndex))
    handleSend(newText, userMsg?.attachments || [])
  }, [handleSend, messages])

  // sendMessageStream's abort() short-circuits before onDone/onError fire
  // (AbortError is swallowed on purpose there), so the streaming placeholder
  // never gets finalized on its own — do it here, keeping whatever partial
  // content already streamed in instead of discarding it.
  const handleStop = useCallback(() => {
    streamAbortRef.current?.()
    streamAbortRef.current = null
    setStatusMsg(null)
    setStatusHistory([])
    setIsLoading(false)
    setMessages(prev => prev.map(m => m.streaming ? { ...m, streaming: false } : m))
  }, [])

  // Context menu — rename modal state
  const [showRenameModal,   setShowRenameModal]   = useState(false)
  const [renameDraft,       setRenameDraft]       = useState('')
  const [renamingSessionId, setRenamingSessionId] = useState(null)

  // Chat-R16 files panel
  const [filesPanelOpen, setFilesPanelOpen] = useState(false)

  // Register contextual ⋮ actions for the chat view
  const { setViewActions, clearViewActions } = useContextMenu()
  useEffect(() => {
    if (!messages.length) { clearViewActions('chat'); return }
    const currentSession = sessions.find(s => s.session_id === sessionId)
    setViewActions('chat', [
      {
        label: 'Rename chat',
        onClick: () => {
          setRenameDraft(currentSession?.title || currentSession?.first_topic_hint || '')
          setShowRenameModal(true)
        },
      },
      { label: 'New chat', onClick: handleNewChat },
      { label: 'Delete chat', variant: 'danger', onClick: () => handleDeleteSession(sessionId) },
    ])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, sessions, sessionId, handleNewChat, handleDeleteSession])

  // Register conversation list into unified sidebar Zone 3 (after all callbacks are declared)
  const { register, unregister } = useSidebarSubsection()
  useEffect(() => {
    register('chat', (query) => (
      <SessionListContent
        query={query}
        sessions={sessions}
        currentSessionId={sessionId}
        onSelect={(s) => { handleSelectSession(s); onSidebarClose?.() }}
        onNew={() => { handleNewChat(); onSidebarClose?.() }}
        onRename={(session) => {
          const open = () => {
            setRenamingSessionId(session.session_id)
            setRenameDraft(session.title || session.first_topic_hint || '')
            setShowRenameModal(true)
          }
          onBeforeModal ? onBeforeModal(open) : open()
        }}
        onDelete={(session) => handleDeleteSession(session.session_id)}
      />
    ))
    return () => unregister('chat')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, sessionId, handleSelectSession, handleNewChat, handleRename, handleDeleteSession, onSidebarClose, onBeforeModal, register, unregister])

  return (
    <div className="flex flex-col h-full">

      {showRenameModal && (
        <RenameModal
          heading="Rename chat"
          initialValue={renameDraft}
          onConfirm={async (value) => { await handleRename(renamingSessionId ?? sessionId, value); setShowRenameModal(false) }}
          onClose={() => setShowRenameModal(false)}
        />
      )}

      {/* Files panel toggle + share current thread — desktop controls */}
      {messages.length > 0 && (
        <>
        <div className="md:hidden flex items-center gap-1.5 fixed top-3.5 right-14 z-50">
          <button
            onClick={() => setFilesPanelOpen(true)}
            title="Files"
            aria-label="Files"
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-slate-400 hover:text-blue-300 bg-slate-950 hover:bg-blue-500/10 transition-all"
          >
            <FilesIcon />
          </button>
          <ShareButton
            type="chat"
            resourceId={sessionId}
            shareTitle="Check out this conversation on Curivio"
            buttonClassName="w-8 h-8 justify-center p-0 !bg-slate-950 hover:!bg-blue-500/10 border-transparent"
          />
        </div>
        <div className="hidden md:flex items-center gap-1.5 fixed top-3.5 right-3.5 z-50">
          <button
            onClick={() => setFilesPanelOpen(true)}
            title="Files"
            aria-label="Files"
            className="inline-flex items-center justify-center w-7 h-7 rounded-lg text-slate-400 hover:text-blue-300 bg-slate-800/40 hover:bg-blue-500/10 border border-slate-700/40 hover:border-blue-500/30 transition-all"
          >
            <FilesIcon />
          </button>
          <ShareButton type="chat" resourceId={sessionId} shareTitle="Check out this conversation on Curivio" />
        </div>
        </>
      )}

      {filesPanelOpen && (
        <FilesPanel sessionId={sessionId} onClose={() => setFilesPanelOpen(false)} />
      )}

      {/* Feed context header */}
      <FeedContextHeader ctx={activeFeedCtx} onDismiss={() => setActiveFeedCtx(null)} />

      {/* Messages — scrollable */}
      <div className="flex-1 overflow-y-auto pt-16 pb-3 px-4 sm:pt-5 sm:pb-5 sm:px-4">
        <div className="max-w-4xl mx-auto space-y-3 sm:space-y-4">
          {messages.length === 0 && !isLoading && (
            <EmptyState onSend={handleSend} sessions={sessions} activeFeedCtx={activeFeedCtx} userName={userName} greetingRand={greetingRandRef.current} onSelectSession={handleSelectSession} />
          )}

          {messages.map((msg, idx) => {
            const isLastAssistant =
              msg.role === "assistant" &&
              !msg.streaming &&
              idx === messages.length - 1
            return (
              <ChatMessage
                key={msg.id}
                message={msg}
                msgIndex={idx}
                sessionId={sessionId}
                isLastAssistant={isLastAssistant}
                onRetry={isLastAssistant ? handleRetry : undefined}
                onEdit={msg.role === "user" ? handleEditMessage : undefined}
              />
            )
          })}

          {error && (
            <div className="flex items-start gap-2 p-3 bg-red-950/40 border border-red-900/50 rounded-xl text-red-300 text-sm">
              <span className="flex-shrink-0">⚠</span>
              <span>{error}</span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="flex-shrink-0">
        <div className="max-w-4xl mx-auto">
          <ChatInput
            onSend={handleSend}
            onStop={handleStop}
            disabled={isLoading}
            chatMode={conversationMode === "layman" ? "layman" : chatMode}
            onModeChange={(mode) => {
              setChatMode(mode)
              if (mode === "layman") setConversationMode("layman")
              else if (conversationMode === "layman" && mode !== "layman") setConversationMode(null)
            }}
            autoMode={autoMode}
          />
        </div>
      </div>
    </div>
  )
}

// ─── Feed context header ──────────────────────────────────────────────────────

const _ACTION_LABEL = {
  ask_about:      "Asking about",
  explain_simply: "Explaining simply",
}

function FeedContextHeader({ ctx, onDismiss }) {
  if (!ctx) return null

  const tags = [
    ctx.category,
    ctx.domain && ctx.domain !== "default" ? ctx.domain : null,
    ctx.content_type,
  ].filter(Boolean)

  const isLayman = ctx.action === "explain_simply"
  return (
    <div className={`flex items-start gap-3 px-4 py-2.5 border-b ${
      isLayman
        ? "bg-amber-500/5 border-amber-500/20"
        : "bg-blue-500/5 border-blue-500/20"
    }`}>
      <div className="flex-1 min-w-0">
        <p className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${
          isLayman ? "text-amber-400/70" : "text-blue-400/70"
        }`}>
          {_ACTION_LABEL[ctx.action] ?? "Researching"}
        </p>
        <p className="text-sm text-slate-200 font-medium leading-snug truncate">
          &ldquo;{ctx.insight_title || "this topic"}&rdquo;
        </p>
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {tags.map((tag, i) => (
              <span
                key={i}
                className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-slate-500 border border-slate-700/50"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
      <button
        onClick={onDismiss}
        title="Dismiss context"
        className="flex-shrink-0 mt-0.5 p-1 rounded text-slate-600 hover:text-slate-400 hover:bg-slate-800/60 transition-colors"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
          <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
        </svg>
      </button>
    </div>
  )
}


const SUGGESTIONS = [
  { text: "Compare Indian vs Chinese pharma exports",         hint: "auto-compare"   },
  { text: "Research AI in manufacturing",                     hint: "auto-research"  },
  { text: "What's happening in semiconductor supply chains?", hint: "auto-analyze"   },
  { text: "Learning roadmap for machine learning",            hint: "instant answer" },
]

function EmptyState({ onSend, sessions = [], activeFeedCtx, onSelectSession, userName, greetingRand = 0.5 }) {
  const recentSessions = sessions.slice(0, 3)

  if (activeFeedCtx) {
    const actionLabel = { ask_about: "Ask about", explain_simply: "Generating simple explanation for" }
    const isLayman = activeFeedCtx.action === "explain_simply"
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4 pb-16">
        <div className={`w-9 h-9 rounded-2xl flex items-center justify-center shadow-lg mb-3 ${
          isLayman
            ? "bg-gradient-to-br from-amber-400 to-orange-500 shadow-amber-950/50"
            : "bg-gradient-to-br from-blue-500 to-violet-600 shadow-violet-950/50"
        }`}>
          {isLayman ? (
            <svg className="w-4.5 h-4.5 text-white" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10 1a6 6 0 0 1 3.479 10.907A1 1 0 0 1 13 13H7a1 1 0 0 1-.479-1.093A6 6 0 0 1 10 1ZM8.5 15.5a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3Zm.25 2a.25.25 0 0 0 0 .5h2.5a.25.25 0 0 0 0-.5h-2.5Z" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-white" viewBox="0 0 16 16" fill="currentColor">
              <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
            </svg>
          )}
        </div>
        <p className={`text-[11px] font-semibold uppercase tracking-wider mb-2 ${
          isLayman ? "text-amber-400/70" : "text-blue-400/70"
        }`}>
          {actionLabel[activeFeedCtx.action] ?? "Exploring"}
        </p>
        <h2 className="text-sm font-semibold text-slate-100 mb-1 max-w-[280px] leading-snug">
          &ldquo;{activeFeedCtx.insight_title || "this topic"}&rdquo;
        </h2>
        {activeFeedCtx.project_name && (
          <p className="text-xs text-slate-500 mb-3">from <span className="text-slate-400">{activeFeedCtx.project_name}</span></p>
        )}
        <p className="text-xs text-slate-600 max-w-[220px] leading-relaxed">
          {isLayman
            ? "Generating a plain-language explanation — no jargon, just intuition."
            : "Type your question below — the article context is ready to use."}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4 pb-16">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shadow-lg shadow-violet-950/50 mb-2.5">
        <svg className="w-4 h-4 text-white" viewBox="0 0 16 16" fill="currentColor">
          <path d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Z" />
        </svg>
      </div>
      <h2 className="text-sm font-semibold text-slate-200 mb-1">{getGreeting(userName, greetingRand)}</h2>
      <p className="text-xs text-slate-500 mb-4 max-w-[210px] leading-relaxed">
        Use <span className="text-blue-400/80">Web Search</span> for live data.
      </p>

      {recentSessions.length > 0 ? (
        <div className="w-full max-w-[280px]">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-1.5 text-left">Recent</p>
          <div className="flex flex-col gap-1">
            {recentSessions.map(s => (
              <button
                key={s.session_id}
                onClick={() => onSelectSession?.(s)}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.05] text-left hover:border-white/[0.08] hover:bg-white/[0.06] transition-all"
              >
                <svg className="w-3 h-3 text-slate-600 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M14 1a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4.414A2 2 0 0 0 3 11.586l-2 2V2a1 1 0 0 1 1-1h12Z" />
                </svg>
                <span className="text-xs text-slate-400 truncate leading-snug">{s.title || "Untitled session"}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5 w-full max-w-[280px]">
          {SUGGESTIONS.map((s, i) => (
            <button
              key={i}
              onClick={() => onSend(s.text)}
              className="group text-left px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.05] hover:border-white/[0.08] hover:bg-white/[0.06] transition-all"
            >
              <span className="text-xs text-slate-400 group-hover:text-slate-200 transition-colors leading-snug block">
                {s.text}
              </span>
              <span className="text-[10px] text-slate-600 group-hover:text-slate-500 mt-0.5 block">
                {s.hint}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
