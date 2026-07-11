import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate, useLocation, Navigate, NavLink } from 'react-router-dom'
import ChatWorkspace from './components/chat/ChatWorkspace.jsx'
import ProjectsPage from './components/feed/ProjectsPage.jsx'
import BookmarksPage from './components/bookmarks/BookmarksPage.jsx'
import DashboardPage from './components/dashboard/DashboardPage.jsx'
import AdminPage from './components/admin/AdminPage.jsx'
import GlobalSearch from './components/GlobalSearch.jsx'
import { useAuth } from './contexts/AuthContext.jsx'
import { useSidebarSubsection } from './contexts/SidebarSubsection.jsx'
import { useContextMenu } from './contexts/ContextMenu.jsx'
import { getQueue, removeFromQueue, clearQueue, setQueueUser } from './api/queue.js'
import { useNetworkStatus } from './hooks/useNetworkStatus.js'
import UnpackListener from './components/unpack/UnpackListener.jsx'
import SyncStatus from './components/SyncStatus.jsx'
import { runBackgroundSync } from './lib/backgroundSync.js'
import { getToken } from './api/auth.js'
import { checkIsAdmin } from './api/admin.js'

// ── Icons ─────────────────────────────────────────────────────────────────────

function ClockIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0ZM7.25 4.75a.75.75 0 0 1 1.5 0V8.5h2a.75.75 0 0 1 0 1.5H8a.75.75 0 0 1-.75-.75V4.75Z" />
    </svg>
  )
}

function GearIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M7.84 1.804A1 1 0 0 1 8.82 1h2.36a1 1 0 0 1 .98.804l.331 1.652a6.993 6.993 0 0 1 1.929 1.115l1.598-.54a1 1 0 0 1 1.186.447l1.18 2.044a1 1 0 0 1-.205 1.251l-1.267 1.113a7.047 7.047 0 0 1 0 2.228l1.267 1.113a1 1 0 0 1 .206 1.25l-1.18 2.045a1 1 0 0 1-1.187.447l-1.598-.54a6.993 6.993 0 0 1-1.929 1.115l-.33 1.652a1 1 0 0 1-.98.804H8.82a1 1 0 0 1-.98-.804l-.331-1.652a6.993 6.993 0 0 1-1.929-1.115l-1.598.54a1 1 0 0 1-1.186-.447l-1.18-2.044a1 1 0 0 1 .205-1.251l1.267-1.114a7.05 7.05 0 0 1 0-2.227L1.821 7.773a1 1 0 0 1-.206-1.25l1.18-2.045a1 1 0 0 1 1.187-.447l1.598.54A6.992 6.992 0 0 1 7.51 3.456l.33-1.652ZM10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" clipRule="evenodd" />
    </svg>
  )
}

function FeedIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v11.75A2.75 2.75 0 0 0 16.75 18h-12A2.75 2.75 0 0 1 2 15.25V3.5Zm3.75 7a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5Zm0 3a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5ZM5 5.75A.75.75 0 0 1 5.75 5h4.5a.75.75 0 0 1 .75.75v2.5a.75.75 0 0 1-.75.75h-4.5A.75.75 0 0 1 5 8.25v-2.5Z" clipRule="evenodd" />
      <path d="M16.5 6.5h-1v8.75a1.25 1.25 0 1 0 2.5 0V8A1.5 1.5 0 0 0 16.5 6.5Z" />
    </svg>
  )
}

function ChatIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M10 2c-2.236 0-4.43.18-6.57.524C1.993 2.755 1 4.014 1 5.426v5.148c0 1.413.993 2.67 2.43 2.902.848.138 1.705.248 2.57.33v3.194c0 .202.12.38.303.456a.5.5 0 0 0 .542-.116L10.03 14h.543A21.26 21.26 0 0 0 13 13.74V7.074c0-1.413-.993-2.672-2.43-2.903A21.212 21.212 0 0 0 10 4c0-.34-.003-.678-.01-1H10ZM8.5 7a1.5 1.5 0 1 0 3 0 1.5 1.5 0 0 0-3 0Z" clipRule="evenodd" />
      <path d="M15.5 2c-.126 0-.25.003-.374.008A5.026 5.026 0 0 1 17 5.426v5.148c0 2.034-1.517 3.73-3.512 3.97L12 14.596V16a.5.5 0 0 0 .831.373l1.604-1.473A21.27 21.27 0 0 0 16 14.83c1.437-.232 2.43-1.49 2.43-2.902V5.426c0-1.413-.993-2.671-2.43-2.902A21.258 21.258 0 0 0 15.5 2.5V2Z" />
    </svg>
  )
}

function DashboardIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M1 2.75A.75.75 0 0 1 1.75 2h16.5a.75.75 0 0 1 0 1.5H18v8.75A2.75 2.75 0 0 1 15.25 15h-1.072l.798 3.06a.75.75 0 0 1-1.452.38L13.41 18H6.59l-.114.44a.75.75 0 0 1-1.452-.38L5.823 15H4.75A2.75 2.75 0 0 1 2 12.25V3.5h-.25A.75.75 0 0 1 1 2.75ZM7.373 15l-.391 1.5h6.037l-.392-1.5H7.373ZM13 7.5a.75.75 0 0 0-1.5 0v4.25a.75.75 0 0 0 1.5 0V7.5ZM9.25 9a.75.75 0 0 1 .75.75v2a.75.75 0 0 1-1.5 0v-2A.75.75 0 0 1 9.25 9ZM7 10.75a.75.75 0 0 0-1.5 0v.5a.75.75 0 0 0 1.5 0v-.5Z" clipRule="evenodd" />
    </svg>
  )
}

function BookmarksIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M10 2c-1.716 0-3.408.106-5.07.31C3.806 2.45 3 3.414 3 4.517V17.25a.75.75 0 0 0 1.075.676L10 15.082l5.925 2.844A.75.75 0 0 0 17 17.25V4.517c0-1.103-.806-2.068-1.93-2.207A41.403 41.403 0 0 0 10 2Z" clipRule="evenodd" />
    </svg>
  )
}

function ShieldIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M9.661 2.237a.531.531 0 0 1 .678 0 11.947 11.947 0 0 0 7.078 2.749.5.5 0 0 1 .479.425c.069.52.104 1.05.104 1.59 0 5.162-3.26 9.563-7.834 11.256a.48.48 0 0 1-.332 0C5.26 16.564 2 12.163 2 7c0-.54.035-1.07.104-1.589a.5.5 0 0 1 .48-.425 11.947 11.947 0 0 0 7.077-2.75Zm4.196 5.954a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z" clipRule="evenodd" />
    </svg>
  )
}

const ZONE3_PLACEHOLDER = {
  feed:      'Filter projects…',
  chat:      'Filter conversations…',
  bookmarks: 'Filter collections…',
  readlater: 'Filter queue…',
  dashboard: 'Search…',
}

const NAV_ITEMS = [
  { id: 'feed',      to: '/feed',       label: 'Feed',       icon: FeedIcon      },
  { id: 'chat',      to: '/chat',       label: 'Chat',       icon: ChatIcon      },
  { id: 'dashboard', to: '/dashboard',  label: 'Dashboard',  icon: DashboardIcon },
  { id: 'bookmarks', to: '/bookmarks',  label: 'Bookmarks',  icon: BookmarksIcon },
  { id: 'readlater', to: '/read-later', label: 'Read Later', icon: ClockIcon     },
  // Hidden unless Sidebar receives isAdmin=true — see AppLayout's checkIsAdmin() probe.
  { id: 'admin',     to: '/admin',      label: 'Admin',      icon: ShieldIcon    },
]

function PanelLeftIcon({ collapsed }) {
  return (
    <svg
      className={`w-[15px] h-[15px] transition-transform duration-200 ${collapsed ? 'rotate-180' : ''}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <line x1="9" y1="3" x2="9" y2="21" />
    </svg>
  )
}

// ── PwField ───────────────────────────────────────────────────────────────────

function PwField({ value, onChange, placeholder, required, className, onKeyDown, autoComplete }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        type={show ? "text" : "password"}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        className={className}
        onKeyDown={onKeyDown}
        autoComplete={autoComplete ?? "current-password"}
      />
      <button
        type="button"
        onClick={() => setShow(s => !s)}
        tabIndex={-1}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400 transition-colors"
        aria-label={show ? "Hide" : "Show"}
      >
        {show ? (
          <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
            <path d="M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
            <path fillRule="evenodd" d="M.664 10.59a1.651 1.651 0 0 1 0-1.186A10.004 10.004 0 0 1 10 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0 1 10 17c-4.257 0-7.893-2.66-9.336-6.41ZM14 10a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z" clipRule="evenodd" />
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M3.28 2.22a.75.75 0 0 0-1.06 1.06l14.5 14.5a.75.75 0 1 0 1.06-1.06l-1.745-1.745a10.029 10.029 0 0 0 3.3-4.38 1.651 1.651 0 0 0 0-1.185A10.004 10.004 0 0 0 9.999 3a9.956 9.956 0 0 0-4.744 1.194L3.28 2.22ZM7.752 6.69l1.092 1.092a2.5 2.5 0 0 1 3.374 3.373l1.091 1.092a4 4 0 0 0-5.557-5.557Z" clipRule="evenodd" />
            <path d="M10.748 13.93l2.523 2.523a10.003 10.003 0 0 1-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 0 1 0-1.186A10.007 10.007 0 0 1 2.839 6.02L6.07 9.252a4 4 0 0 0 4.678 4.678Z" />
          </svg>
        )}
      </button>
    </div>
  )
}

// ── SettingsPanel ─────────────────────────────────────────────────────────────

function SettingsPanel({ positionClass = "absolute right-0 top-full mt-2 z-40" }) {
  const { user, logout, updateProfile, changePassword, deleteAccount, verifyPassword } = useAuth()

  const [section, setSection]           = useState("main")
  const [profileName, setProfileName]   = useState(user?.name || "")

  useEffect(() => {
    if (user?.name !== undefined) setProfileName(user.name)
  }, [user?.name])

  const [profileMsg, setProfileMsg]     = useState("")
  const [profileErr, setProfileErr]     = useState("")
  const [savingProfile, setSavingProfile] = useState(false)

  const [pwStep, setPwStep]   = useState("verify")
  const [curPw, setCurPw]     = useState("")
  const [newPw, setNewPw]     = useState("")
  const [pwMsg, setPwMsg]     = useState("")
  const [pwErr, setPwErr]     = useState("")
  const [savingPw, setSavingPw] = useState(false)

  const [forgotStep,     setForgotStep]     = useState("send")
  const [forgotCode,     setForgotCode]     = useState("")
  const [forgotNewPw,    setForgotNewPw]    = useState("")
  const [forgotConfirm,  setForgotConfirm]  = useState("")
  const [forgotMsg,      setForgotMsg]      = useState("")
  const [forgotErr,      setForgotErr]      = useState("")
  const [forgotLoading,  setForgotLoading]  = useState(false)
  const [codeVerified,   setCodeVerified]   = useState(false)

  const [deleteConfirm, setDeleteConfirm] = useState("")
  const [delErr, setDelErr]               = useState("")
  const [deleting, setDeleting]           = useState(false)

  async function handleSaveProfile(e) {
    e.preventDefault()
    setSavingProfile(true); setProfileMsg(""); setProfileErr("")
    try {
      await updateProfile(profileName.trim(), null)
      setProfileMsg("Profile updated.")
    } catch (err) {
      setProfileErr(err.message)
    } finally {
      setSavingProfile(false)
    }
  }

  async function handleVerifyPassword() {
    if (!curPw) return
    setSavingPw(true); setPwErr("")
    try {
      await verifyPassword(curPw)
      setPwStep("change")
    } catch (err) {
      setPwErr(err.message || "Current password is incorrect.")
    } finally {
      setSavingPw(false)
    }
  }

  async function handleChangePassword() {
    if (newPw.length < 8) { setPwErr("New password must be at least 8 characters."); return }
    setSavingPw(true); setPwMsg(""); setPwErr("")
    try {
      await changePassword(curPw, newPw)
      setPwMsg("Password changed successfully.")
      setCurPw(""); setNewPw(""); setPwStep("verify")
    } catch (err) {
      setPwErr(err.message)
    } finally {
      setSavingPw(false)
    }
  }

  async function handleSendCode() {
    setForgotLoading(true); setForgotErr(""); setCodeVerified(false); setForgotCode("")
    try {
      const { forgotPassword: apiForgot } = await import('./api/auth.js')
      await apiForgot(user?.email || "")
      setForgotStep("code")
    } catch (err) {
      setForgotErr(err.message || "Failed to send code.")
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleVerifyCode() {
    if (forgotCode.length !== 6) { setForgotErr("Enter the 6-digit code from your email."); return }
    setForgotLoading(true); setForgotErr("")
    try {
      const { verifyResetCode } = await import('./api/auth.js')
      await verifyResetCode(user?.email || "", forgotCode)
      setCodeVerified(true)
    } catch (err) {
      setForgotErr(err.message || "Incorrect code. Please try again.")
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleResetWithCode() {
    setForgotErr("")
    if (forgotNewPw.length < 8)  { setForgotErr("Password must be at least 8 characters."); return }
    if (forgotNewPw !== forgotConfirm) { setForgotErr("Passwords do not match."); return }
    setForgotLoading(true)
    try {
      const { resetPassword } = await import('./api/auth.js')
      await resetPassword(user?.email || "", forgotCode, forgotNewPw)
      setForgotMsg("Password changed successfully!")
    } catch (err) {
      setForgotErr(err.message || "Invalid or expired code.")
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleDeleteAccount() {
    setDeleting(true); setDelErr("")
    try {
      await deleteAccount(deleteConfirm)
    } catch (err) {
      setDelErr(err.message)
      setDeleting(false)
    }
  }

  function back() {
    setSection("main")
    setProfileMsg(""); setProfileErr("")
    setPwMsg(""); setPwErr(""); setPwStep("verify"); setCurPw(""); setNewPw("")
    setForgotStep("send"); setForgotCode(""); setForgotNewPw(""); setForgotConfirm(""); setForgotMsg(""); setForgotErr("")
    setDelErr("")
  }

  const SECTION_TITLE = {
    main: "Settings", profile: "Edit Profile",
    password: "Change Password", forgot: "Forgot Password", danger: "Delete Account",
  }
  const inputCls = "w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500"
  const btnPrimary = "w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium py-2 rounded-lg transition-colors"

  return (
    <div className={`${positionClass} w-72 max-w-[calc(100vw-1rem)] bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 overflow-hidden`}>
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        {section !== "main" && (
          <button onClick={back} className="text-slate-500 hover:text-slate-300 transition-colors mr-1">
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path fillRule="evenodd" d="M9.78 4.22a.75.75 0 0 1 0 1.06L7.06 8l2.72 2.72a.75.75 0 1 1-1.06 1.06L5.47 8.53a.75.75 0 0 1 0-1.06l3.25-3.25a.75.75 0 0 1 1.06 0Z" clipRule="evenodd" />
            </svg>
          </button>
        )}
        <span className="text-sm font-semibold text-slate-200">{SECTION_TITLE[section]}</span>
      </div>

      {section === "main" && (
        <>
          <div className="px-4 py-3 border-b border-slate-800/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                {(user?.name || user?.email || "?")[0].toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-200 truncate">{user?.name || "User"}</p>
                <p className="text-[11px] text-slate-500 truncate">{user?.email}</p>
              </div>
            </div>
          </div>

          <div className="px-4 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-1.5 mt-1">Account</p>
            {[
              { label: "Edit Profile",    id: "profile"  },
              { label: "Change Password", id: "password" },
            ].map(({ label, id }) => (
              <button key={id} onClick={() => setSection(id)}
                className="w-full text-left px-2 py-2 text-sm text-slate-300 hover:text-slate-100 hover:bg-slate-800/50 rounded-lg transition-colors flex items-center justify-between">
                {label}
                <svg className="w-3.5 h-3.5 text-slate-600" viewBox="0 0 16 16" fill="currentColor">
                  <path fillRule="evenodd" d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
                </svg>
              </button>
            ))}
            <button onClick={logout}
              className="w-full text-left px-2 py-2 text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 rounded-lg transition-colors mt-0.5">
              Sign Out
            </button>
          </div>

          <div className="px-4 py-2 border-t border-slate-800/60 mt-1">
            <button onClick={() => setSection("danger")}
              className="w-full text-left px-2 py-2 text-sm text-red-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors">
              Delete Account…
            </button>
          </div>
        </>
      )}

      {section === "profile" && (
        <form onSubmit={handleSaveProfile} className="px-4 py-4 space-y-3">
          <div>
            <label className="block text-xs text-slate-500 mb-1">Name</label>
            <input value={profileName} onChange={e => setProfileName(e.target.value)} className={inputCls} placeholder="Your name" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Email</label>
            <input type="email" value={user?.email || ""} disabled
              className="w-full bg-[#0a0c12] border border-white/5 rounded-lg px-4 py-2.5 text-slate-600 text-sm cursor-not-allowed select-none" />
          </div>
          {profileErr && <p className="text-xs text-red-400">{profileErr}</p>}
          {profileMsg && <p className="text-xs text-green-400">{profileMsg}</p>}
          <button type="submit" disabled={savingProfile} className={btnPrimary}>
            {savingProfile ? "Saving…" : "Save Changes"}
          </button>
        </form>
      )}

      {section === "password" && (
        <div className="px-4 py-4 space-y-3">
          {pwStep === "verify" ? (
            <>
              <p className="text-xs text-slate-500">Enter your current password to continue.</p>
              <div>
                <label className="block text-xs text-slate-500 mb-1">Current Password</label>
                <PwField value={curPw} onChange={e => { setCurPw(e.target.value); setPwErr("") }}
                  className={inputCls + " pr-8"} placeholder="Your current password"
                  onKeyDown={e => e.key === "Enter" && handleVerifyPassword()} />
              </div>
              {pwErr && <p className="text-xs text-red-400">{pwErr}</p>}
              <button onClick={handleVerifyPassword} disabled={savingPw || !curPw} className={btnPrimary}>
                {savingPw ? "Verifying…" : "Verify Password"}
              </button>
              <button type="button" onClick={() => { back(); setSection("forgot") }}
                className="w-full text-center text-xs text-slate-600 hover:text-blue-400 transition-colors pt-1">
                Forgot password?
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <svg className="w-3 h-3 text-emerald-400 flex-shrink-0" viewBox="0 0 12 12" fill="currentColor">
                  <path fillRule="evenodd" d="M10.28 2.28a.75.75 0 0 0-1.06 0L4.5 6.99 2.78 5.27a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.06 0l5.25-5.25a.75.75 0 0 0 0-1.06Z" clipRule="evenodd" />
                </svg>
                <span className="text-[11px] text-emerald-400">Password verified. Set your new password below.</span>
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">New Password</label>
                <PwField value={newPw} onChange={e => { setNewPw(e.target.value); setPwErr("") }}
                  className={inputCls + " pr-8"} placeholder="At least 8 characters"
                  onKeyDown={e => e.key === "Enter" && handleChangePassword()} />
              </div>
              {pwErr && <p className="text-xs text-red-400">{pwErr}</p>}
              {pwMsg && <p className="text-xs text-green-400">{pwMsg}</p>}
              <button onClick={handleChangePassword} disabled={savingPw || !newPw} className={btnPrimary}>
                {savingPw ? "Saving…" : "Change Password"}
              </button>
            </>
          )}
        </div>
      )}

      {section === "forgot" && (
        <div className="px-4 py-4 space-y-3">
          {forgotMsg ? (
            <div className="space-y-3">
              <div className="flex items-start gap-2 px-3 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                <svg className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5" viewBox="0 0 12 12" fill="currentColor">
                  <path fillRule="evenodd" d="M10.28 2.28a.75.75 0 0 0-1.06 0L4.5 6.99 2.78 5.27a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.06 0l5.25-5.25a.75.75 0 0 0 0-1.06Z" clipRule="evenodd"/>
                </svg>
                <p className="text-xs text-emerald-300 leading-relaxed">{forgotMsg}</p>
              </div>
              <button onClick={back} className={btnPrimary}>Done</button>
            </div>
          ) : forgotStep === "send" ? (
            <>
              <p className="text-xs text-slate-400 leading-relaxed">
                We'll send a 6-digit code to:<br />
                <span className="text-slate-200 font-medium">{user?.email}</span>
              </p>
              {forgotErr && <p className="text-xs text-red-400">{forgotErr}</p>}
              <button onClick={handleSendCode} disabled={forgotLoading} className={btnPrimary}>
                {forgotLoading ? "Sending…" : "Send Code"}
              </button>
            </>
          ) : (
            <>
              <p className="text-xs text-slate-500">
                Code sent to <span className="text-slate-300">{user?.email}</span>. Enter it below.
              </p>
              <div>
                <label className="block text-xs text-slate-500 mb-1">6-Digit Code</label>
                <input type="text" inputMode="numeric" pattern="[0-9]*" maxLength="6"
                  value={forgotCode}
                  onChange={e => { setForgotCode(e.target.value.replace(/\D/g, "").slice(0, 6)); setForgotErr(""); setCodeVerified(false) }}
                  onKeyDown={e => e.key === "Enter" && !codeVerified && handleVerifyCode()}
                  placeholder="000000" disabled={codeVerified}
                  className={inputCls + " text-center text-xl font-mono tracking-[0.4em] placeholder-slate-700" + (codeVerified ? " opacity-60" : "")} />
              </div>
              {codeVerified ? (
                <p className="text-xs text-emerald-400 flex items-center gap-1.5">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M8 16A8 8 0 1 1 8 0a8 8 0 0 1 0 16Zm3.78-9.72a.75.75 0 0 0-1.06-1.06L6.75 9.19 5.28 7.72a.75.75 0 0 0-1.06 1.06l2 2a.75.75 0 0 0 1.06 0l4.5-4.5Z"/></svg>
                  Code verified — set your new password below
                </p>
              ) : (
                <>
                  {forgotErr && <p className="text-xs text-red-400">{forgotErr}</p>}
                  <button onClick={handleVerifyCode} disabled={forgotLoading || forgotCode.length < 6} className={btnPrimary}>
                    {forgotLoading ? "Verifying…" : "Verify Code"}
                  </button>
                </>
              )}
              {codeVerified && (
                <>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">New Password</label>
                    <PwField value={forgotNewPw} onChange={e => { setForgotNewPw(e.target.value); setForgotErr("") }}
                      className={inputCls + " pr-8"} placeholder="At least 8 characters" autoComplete="new-password" />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Confirm Password</label>
                    <input type="password" value={forgotConfirm}
                      onChange={e => { setForgotConfirm(e.target.value); setForgotErr("") }}
                      onKeyDown={e => e.key === "Enter" && handleResetWithCode()}
                      placeholder="Repeat password" className={inputCls} autoComplete="new-password" />
                  </div>
                  {forgotErr && <p className="text-xs text-red-400">{forgotErr}</p>}
                  <button onClick={handleResetWithCode} disabled={forgotLoading || !forgotNewPw || !forgotConfirm} className={btnPrimary}>
                    {forgotLoading ? "Resetting…" : "Reset Password"}
                  </button>
                </>
              )}
              <button type="button" onClick={handleSendCode} disabled={forgotLoading}
                className="w-full text-center text-xs text-slate-600 hover:text-slate-400 transition-colors">
                Resend code
              </button>
            </>
          )}
        </div>
      )}

      {section === "danger" && (
        <div className="px-4 py-4 space-y-3">
          <p className="text-xs text-slate-400">Enter your password to permanently delete your account and all data. This cannot be undone.</p>
          <PwField value={deleteConfirm} onChange={e => setDeleteConfirm(e.target.value)}
            placeholder="Your password" className={inputCls + " pr-8"} autoComplete="current-password" />
          {delErr && <p className="text-xs text-red-400">{delErr}</p>}
          <button onClick={handleDeleteAccount} disabled={deleting || !deleteConfirm}
            className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium py-2 rounded-lg transition-colors">
            {deleting ? "Deleting…" : "Delete My Account"}
          </button>
        </div>
      )}
    </div>
  )
}

// ── QueuePanel ────────────────────────────────────────────────────────────────

function groupByDate(items) {
  const today     = new Date(); today.setHours(0,0,0,0)
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  const groups    = {}
  items.forEach(item => {
    const d = item.queuedAt ? new Date(item.queuedAt) : new Date(0)
    const day = new Date(d); day.setHours(0,0,0,0)
    let label
    if (day.getTime() === today.getTime())          label = "Today"
    else if (day.getTime() === yesterday.getTime()) label = "Yesterday"
    else label = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: d.getFullYear() !== today.getFullYear() ? "numeric" : undefined })
    if (!groups[label]) groups[label] = []
    groups[label].push(item)
  })
  return groups
}

function QueuePanel({ queue, onItemClick, positionClass = "absolute right-0 top-full mt-2 z-40" }) {
  const [search, setSearch] = useState("")

  const filtered = search.trim()
    ? queue.filter(i => i.title?.toLowerCase().includes(search.toLowerCase()) || i.projectName?.toLowerCase().includes(search.toLowerCase()))
    : queue

  const groups = groupByDate(filtered)

  return (
    <div className={`${positionClass} w-72 max-w-[calc(100vw-1rem)] bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 overflow-hidden`}>
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ClockIcon className="w-3.5 h-3.5 text-amber-400" />
          <span className="text-sm font-semibold text-slate-200">Your Queue</span>
          {queue.length > 0 && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 tabular-nums">
              {queue.length}
            </span>
          )}
        </div>
        {queue.length > 1 && (
          <button onClick={() => clearQueue()} className="text-[11px] text-slate-600 hover:text-slate-400 transition-colors">
            Clear all
          </button>
        )}
      </div>

      {queue.length > 0 && (
        <div className="px-3 py-2 border-b border-slate-800/60">
          <div className="relative">
            <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-600" viewBox="0 0 16 16" fill="currentColor">
              <path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z"/>
            </svg>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search queue…"
              className="w-full pl-7 pr-3 py-1.5 bg-slate-800/60 border border-slate-700/50 rounded-lg text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-600 transition-colors" />
          </div>
        </div>
      )}

      {queue.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <p className="text-sm text-slate-500">No cards queued yet.</p>
          <p className="text-[11px] text-slate-600 mt-1">Click "Read Later" on any card.</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="px-4 py-6 text-center">
          <p className="text-xs text-slate-500">No results for "{search}"</p>
        </div>
      ) : (
        <div className="max-h-80 overflow-y-auto py-1.5">
          {Object.entries(groups).map(([label, items]) => (
            <div key={label}>
              <p className="px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">{label}</p>
              {items.map(item => (
                <div key={item.articleKey} className="relative flex items-center hover:bg-slate-800/40 transition-colors group">
                  <button onClick={() => onItemClick(item)}
                    className="flex-1 flex items-start gap-2.5 px-4 py-2.5 text-left min-w-0"
                    title={`Go to: ${item.title}`}>
                    <div className="flex-1 min-w-0 pr-4">
                      <p className="text-xs font-medium text-slate-300 leading-snug line-clamp-2 group-hover:text-slate-100 transition-colors">{item.title}</p>
                      {item.projectName && <p className="text-[10px] text-slate-600 mt-0.5">{item.projectName}</p>}
                    </div>
                    <svg className="w-3 h-3 text-slate-700 group-hover:text-slate-500 flex-shrink-0 mt-0.5 transition-colors" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" />
                    </svg>
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); removeFromQueue(item.articleKey) }}
                    title="Remove from queue"
                    className="absolute right-2.5 w-5 h-5 flex items-center justify-center rounded text-slate-600 hover:text-slate-300 hover:bg-slate-700/60 opacity-0 group-hover:opacity-100 transition-all">
                    <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Sidebar components ────────────────────────────────────────────────────────

function LogoMark() {
  return (
    <div className="relative w-7 h-7 flex-shrink-0">
      <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-blue-500 via-indigo-500 to-violet-600 shadow-lg shadow-violet-950/50" />
      <div className="absolute inset-0 rounded-xl flex items-center justify-center">
        <svg style={{ width: '16px', height: '16px' }} viewBox="0 0 20 20" fill="none">
          <circle cx="10" cy="8" r="4" fill="white" fillOpacity="0.95" />
          <rect x="8.25" y="12" width="3.5" height="1.2" rx="0.6" fill="white" fillOpacity="0.8" />
          <rect x="8.75" y="13.6" width="2.5" height="1.1" rx="0.55" fill="white" fillOpacity="0.6" />
          <path d="M10 4 L10 2.5" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M13.5 5.5 L14.6 4.4" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M6.5 5.5 L5.4 4.4" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M14.5 8 L16 8" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
          <path d="M5.5 8 L4 8" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
        </svg>
      </div>
    </div>
  )
}

function NavItem({ item, collapsed, onClick, badge }) {
  const Icon = item.icon
  return (
    <div className="relative group">
      <NavLink
        to={item.to}
        onClick={onClick}
        className={({ isActive }) => [
          'w-full flex items-center gap-2.5 rounded-lg text-[13px] font-medium transition-colors',
          isActive
            ? 'bg-white/[0.07] text-white'
            : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]',
          collapsed ? 'md:justify-center md:w-9 md:h-9 md:p-0 px-3 py-2' : 'px-3 py-2',
        ].join(' ')}
      >
        <Icon className="w-[15px] h-[15px] flex-shrink-0" />
        <span className={`flex-1 text-left ${collapsed ? 'md:hidden' : ''}`}>{item.label}</span>
        {badge > 0 && (
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 tabular-nums leading-none ${collapsed ? 'md:hidden' : ''}`}>
            {badge}
          </span>
        )}
      </NavLink>
      {/* Tooltip — desktop collapsed mode only */}
      <span className={[
        'pointer-events-none absolute left-full ml-2 top-1/2 -translate-y-1/2 z-[70]',
        'bg-slate-800 border border-white/[0.08] text-slate-200 text-[12px] font-medium',
        'px-2.5 py-1 rounded-lg shadow-xl whitespace-nowrap',
        'opacity-0 transition-opacity duration-150 group-hover:opacity-100',
        collapsed ? 'hidden md:block' : 'hidden',
      ].join(' ')}>
        {item.label}
      </span>
    </div>
  )
}

function Sidebar({
  view, onSearchOpen,
  queue, onQueueItemClick,
  showSettings, onSettingsToggle, settingsRef, user,
  collapsed, setCollapsed, open, setOpen,
  isAdmin,
}) {
  const navigate = useNavigate()
  const { subsections } = useSidebarSubsection()
  const { actionsByView } = useContextMenu()
  const [sidebarQuery, setSidebarQuery] = useState('')
  useEffect(() => { setSidebarQuery('') }, [view])

  // Undo state for sidebar Read Later removals
  const [sidebarPendingRemove, setSidebarPendingRemove] = useState({})
  const sidebarRemoveTimers = useRef({})
  useEffect(() => () => {
    Object.entries(sidebarRemoveTimers.current).forEach(([key, timer]) => {
      clearTimeout(timer)
      removeFromQueue(key)
    })
  }, [])

  function handleSidebarRemove(e, key) {
    e.stopPropagation()
    setSidebarPendingRemove(prev => ({ ...prev, [key]: true }))
    sidebarRemoveTimers.current[key] = setTimeout(() => {
      removeFromQueue(key)
      setSidebarPendingRemove(prev => { const n = { ...prev }; delete n[key]; return n })
      delete sidebarRemoveTimers.current[key]
    }, 5000)
  }

  function handleSidebarUndo(key) {
    clearTimeout(sidebarRemoveTimers.current[key])
    delete sidebarRemoveTimers.current[key]
    setSidebarPendingRemove(prev => { const n = { ...prev }; delete n[key]; return n })
  }

  // Lock body scroll while mobile drawer is open
  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [open])

  const q = sidebarQuery.trim().toLowerCase()
  const visibleQueue = q
    ? queue.filter(i =>
        i.title?.toLowerCase().includes(q) ||
        i.projectName?.toLowerCase().includes(q)
      )
    : queue

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className={[
          'fixed inset-0 bg-black/50 z-[55] md:hidden',
          'transition-opacity duration-300',
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none',
        ].join(' ')}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      <aside
        className={[
          'fixed inset-y-0 left-0 z-[56] flex flex-col',
          'bg-slate-900 border-r border-white/[0.04]',
          'transition-[width,transform] duration-200 ease-in-out',
          'md:relative md:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
          'w-[280px]',
          collapsed ? 'md:w-[68px]' : 'md:w-[280px]',
        ].join(' ')}
        style={{ willChange: 'width, transform' }}
      >

        {/* Zone 1: Logo + sidebar toggle */}
        <div className={`flex items-center h-12 flex-shrink-0 px-3 ${collapsed ? 'md:px-1' : ''}`}>
          {/* Logo — navigates to landing ONLY, never controls sidebar state */}
          <button
            onClick={() => { navigate('/'); setOpen(false) }}
            className="flex items-center gap-2.5 hover:opacity-80 transition-opacity min-w-0"
          >
            <LogoMark />
            <span className={`font-bold text-[15px] tracking-tight select-none bg-gradient-to-r from-slate-100 to-slate-300 bg-clip-text text-transparent truncate ${collapsed ? 'md:hidden' : ''}`}>
              Curivio
            </span>
          </button>

          {/* Desktop sidebar toggle — the ONLY element that collapses/expands sidebar */}
          <button
            onClick={() => setCollapsed(c => !c)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="hidden md:flex items-center justify-center w-7 h-7 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/[0.06] transition-colors flex-shrink-0 ml-auto"
          >
            <PanelLeftIcon collapsed={collapsed} />
          </button>

          {/* Mobile close button — mobile only */}
          <button
            onClick={() => setOpen(false)}
            aria-label="Close sidebar"
            className="md:hidden ml-auto flex items-center justify-center w-7 h-7 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/[0.06] transition-colors flex-shrink-0"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
            </svg>
          </button>
        </div>

        {/* Zone 2: Primary nav — never scrolls */}
        <nav className={`flex-shrink-0 py-2 space-y-0.5 ${collapsed ? 'md:px-1.5 px-2' : 'px-2'}`}>
          {NAV_ITEMS.filter(item => item.id !== 'admin' || isAdmin).map(item => (
            <NavItem
              key={item.id}
              item={item}
              collapsed={collapsed}
              onClick={() => setOpen(false)}
              badge={item.id === 'readlater' ? queue.length : 0}
            />
          ))}
        </nav>

        {/* Zone 3: Search + dynamic subsection — ONLY scrollable section */}
        <div className={[
          'flex-1 flex flex-col min-h-0',
          collapsed ? 'md:hidden' : '',
        ].join(' ')}>
          {/* Contextual search */}
          <div className="px-2 pt-2 pb-1 flex-shrink-0">
            <div className="relative">
              <svg
                className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-600 pointer-events-none"
                viewBox="0 0 16 16" fill="currentColor"
              >
                <path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z" />
              </svg>
              <input
                type="text"
                value={sidebarQuery}
                onChange={e => setSidebarQuery(e.target.value)}
                placeholder={ZONE3_PLACEHOLDER[view] ?? 'Filter…'}
                className="w-full pl-7 pr-6 py-1.5 bg-white/[0.04] rounded-lg text-[12px] text-slate-300 placeholder-slate-600 focus:outline-none focus:bg-white/[0.07] transition-colors"
              />
              {sidebarQuery && (
                <button
                  onClick={() => setSidebarQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400 transition-colors"
                >
                  <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                  </svg>
                </button>
              )}
            </div>
          </div>

          {/* Read Later inline queue list */}
          {view === 'readlater' && (
            <div className="flex-1 overflow-y-auto min-h-0 px-2 pb-2">
              <div className="flex items-center justify-between px-1 py-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Queued</span>
                {queue.length > 0 && (
                  <button onClick={() => clearQueue()} className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors">
                    Clear all
                  </button>
                )}
              </div>
              {visibleQueue.length === 0 ? (
                <p className="text-xs text-slate-600 px-1 py-2">{q ? 'No matches.' : 'No queued items.'}</p>
              ) : (
                <div className="space-y-0.5">
                  {visibleQueue.map(item => {
                    const isPending = !!sidebarPendingRemove[item.articleKey]
                    if (isPending) {
                      return (
                        <div
                          key={item.articleKey}
                          className="flex items-center justify-between px-2 py-2 rounded-lg"
                        >
                          <p className="text-[11px] text-slate-600 italic truncate mr-2 flex-1 min-w-0">{item.title}</p>
                          <button
                            onClick={() => handleSidebarUndo(item.articleKey)}
                            className="flex-shrink-0 text-[11px] font-medium text-blue-400 hover:text-blue-300 transition-colors"
                          >
                            Undo
                          </button>
                        </div>
                      )
                    }
                    return (
                      <div
                        key={item.articleKey}
                        className="group flex items-start gap-2 px-2 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-white/[0.04] transition-colors cursor-pointer"
                        onClick={() => onQueueItemClick(item)}
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium leading-snug line-clamp-2">{item.title}</p>
                          {item.projectName && <p className="text-[10px] text-slate-500 mt-0.5">{item.projectName}</p>}
                        </div>
                        <button
                          onClick={e => handleSidebarRemove(e, item.articleKey)}
                          className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-slate-600 hover:text-slate-300 flex-shrink-0 mt-0.5 transition-all"
                        >
                          <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor">
                            <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                          </svg>
                        </button>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* Feed / Bookmarks / Chat / Dashboard — subsection context */}
          {view !== 'readlater' && subsections[view] && (
            <div className="flex-1 overflow-y-auto min-h-0 px-2 pb-2">
              {subsections[view](sidebarQuery)}
            </div>
          )}
        </div>

        {/* Spacer: pushes Zone 4 to bottom on desktop when collapsed */}
        {collapsed && <div className="hidden md:flex flex-1" />}

        {/* Zone 4: User / Settings — always pinned at bottom */}
        <div className={`flex-shrink-0 pt-1 pb-2 ${collapsed ? 'md:px-1.5 px-2' : 'px-2'}`}>
          <div ref={settingsRef} className="relative">
            <button
              onClick={onSettingsToggle}
              title={collapsed ? 'Settings' : undefined}
              className={[
                'flex items-center gap-2.5 rounded-lg text-[13px] font-medium transition-colors',
                showSettings ? 'bg-white/[0.07] text-white' : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]',
                collapsed ? 'md:justify-center md:w-9 md:h-9 md:p-0 w-full px-3 py-2' : 'w-full px-3 py-2',
              ].join(' ')}
            >
              <div className="w-[22px] h-[22px] rounded-full bg-blue-600 flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0">
                {(user?.name || user?.email || "?")[0].toUpperCase()}
              </div>
              <span className={`flex-1 text-left truncate ${collapsed ? 'md:hidden' : ''}`}>
                {user?.name || 'Settings'}
              </span>
              <SyncStatus />
              <GearIcon className={`w-3.5 h-3.5 text-slate-600 flex-shrink-0 ${collapsed ? 'md:hidden' : ''}`} />
            </button>
            {showSettings && (
              <SettingsPanel
                positionClass="absolute bottom-full left-0 mb-1.5 z-50"
              />
            )}
          </div>
        </div>
      </aside>
    </>
  )
}

// ── Read Later page ───────────────────────────────────────────────────────────

function ReadLaterPage({ queue, onItemClick, onRemove }) {
  const [pendingRemove, setPendingRemove] = useState({})
  const timers = useRef({})
  const onRemoveRef = useRef(onRemove)
  useEffect(() => { onRemoveRef.current = onRemove }, [onRemove])

  // On unmount, finalize all pending removes immediately (user navigated away)
  useEffect(() => () => {
    Object.entries(timers.current).forEach(([key, timer]) => {
      clearTimeout(timer)
      onRemoveRef.current(key)
    })
  }, [])

  function handleRemove(e, item) {
    e.stopPropagation()
    const key = item.articleKey
    setPendingRemove(prev => ({ ...prev, [key]: true }))
    timers.current[key] = setTimeout(() => {
      onRemove(key)
      setPendingRemove(prev => { const n = { ...prev }; delete n[key]; return n })
      delete timers.current[key]
    }, 5000)
  }

  function handleUndo(key) {
    clearTimeout(timers.current[key])
    delete timers.current[key]
    setPendingRemove(prev => { const n = { ...prev }; delete n[key]; return n })
  }

  const allPending = queue.length > 0 && queue.every(item => pendingRemove[item.articleKey])

  if (queue.length === 0 && Object.keys(pendingRemove).length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] text-center px-8">
        <div className="w-12 h-12 rounded-2xl bg-slate-800/80 border border-slate-700/60 flex items-center justify-center mb-4">
          <ClockIcon className="w-5 h-5 text-slate-500" />
        </div>
        <h3 className="text-sm font-semibold text-slate-300 mb-1">Queue is empty</h3>
        <p className="text-xs text-slate-600 max-w-xs leading-relaxed">
          Click "Read Later" on any article to save it here.
        </p>
      </div>
    )
  }

  return (
    <div className="pt-14 pb-6 px-4 sm:px-8 md:pt-6">
      {/* Clear all — fixed top-right on mobile, inline on desktop */}
      {!allPending && (
        <>
          <button
            onClick={() => clearQueue()}
            className="md:hidden fixed top-3.5 right-14 z-40 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            Clear all
          </button>
          <div className="hidden md:flex justify-end mb-4">
            <button
              onClick={() => clearQueue()}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              Clear all
            </button>
          </div>
        </>
      )}
      <div className="space-y-2 max-w-2xl">
        {queue.map(item => {
          const isRemoving = !!pendingRemove[item.articleKey]

          if (isRemoving) {
            return (
              <div
                key={item.articleKey}
                className="flex items-center justify-between px-4 py-2.5 rounded-xl border border-white/[0.03] bg-white/[0.01]"
              >
                <p className="text-xs text-slate-600 italic truncate mr-3">{item.title}</p>
                <button
                  onClick={() => handleUndo(item.articleKey)}
                  className="flex-shrink-0 text-xs font-medium text-blue-400 hover:text-blue-300 transition-colors"
                >
                  Undo
                </button>
              </div>
            )
          }

          return (
            <div
              key={item.articleKey}
              className="flex items-center gap-4 p-4 bg-white/[0.03] border border-white/[0.05] rounded-xl hover:bg-white/[0.05] transition-colors cursor-pointer"
              onClick={() => onItemClick(item)}
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-200 leading-snug hover:text-white transition-colors line-clamp-2">
                  {item.title}
                </p>
                {item.projectName && (
                  <p className="text-xs text-slate-500 mt-1">{item.projectName}</p>
                )}
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <button
                  onClick={e => handleRemove(e, item)}
                  className="p-1.5 rounded-lg text-slate-600 hover:text-slate-300 hover:bg-slate-800 transition-all"
                  title="Remove"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                  </svg>
                </button>
                <svg className="w-3.5 h-3.5 text-slate-700" viewBox="0 0 16 16" fill="currentColor">
                  <path fillRule="evenodd" d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
                </svg>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── App root ──────────────────────────────────────────────────────────────────

export default function AppLayout() {
  const { user } = useAuth()
  const { actionsByView } = useContextMenu()
  const { isOnline } = useNetworkStatus()
  const navigate = useNavigate()
  const location = useLocation()
  const pathname = location.pathname

  const isKnownSection = pathname.startsWith('/feed') || pathname.startsWith('/chat')
    || pathname.startsWith('/dashboard') || pathname.startsWith('/bookmarks') || pathname.startsWith('/read-later')
    || pathname.startsWith('/admin')

  const view = pathname.startsWith('/chat')       ? 'chat'
    : pathname.startsWith('/dashboard')  ? 'dashboard'
    : pathname.startsWith('/admin')      ? 'admin'
    : pathname.startsWith('/bookmarks')  ? 'bookmarks'
    : pathname.startsWith('/read-later') ? 'readlater'
    : 'feed'

  // Deep-link targets — derived from the URL instead of App-level state.
  let targetProjectId = null, targetInsightId = null, targetArticleKey = null
  if (pathname.startsWith('/feed/')) {
    const parts = pathname.slice('/feed/'.length).split('/').filter(Boolean)
    targetProjectId  = parts[0] ? decodeURIComponent(parts[0]) : null
    targetInsightId  = parts[1] ? Number(parts[1]) : null
    targetArticleKey = parts[2] ? decodeURIComponent(parts[2]) : null
  }
  let targetSessionId = null
  if (pathname.startsWith('/chat/')) {
    targetSessionId = decodeURIComponent(pathname.slice('/chat/'.length).split('/')[0] || '') || null
  }
  const targetSessionTitle = location.state?.sessionTitle ?? null

  const [feedContext, setFeedContext] = useState(null)
  const [showSearch,  setShowSearch]  = useState(false)
  const [queue,        setQueue]      = useState(() => getQueue())
  // Nav-visibility only — real enforcement is the backend's get_current_admin_user().
  // Probes a real admin endpoint rather than shipping ADMIN_EMAILS in the client bundle.
  const [isAdmin, setIsAdmin] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const settingsRef = useRef(null)
  const [showOverflow, setShowOverflow] = useState(false)
  const overflowRef = useRef(null)
  const [showDesktopOverflow, setShowDesktopOverflow] = useState(false)
  const desktopOverflowRef = useRef(null)

  // Sidebar state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() =>
    localStorage.getItem('sidebar_collapsed') !== 'false'
  )
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const handleSidebarClose = useCallback(() => setSidebarOpen(false), [])
  const handleBeforeModal  = useCallback((fn) => {
    if (sidebarOpen) { setSidebarOpen(false); setTimeout(fn, 300) } else { fn() }
  }, [sidebarOpen])

  useEffect(() => {
    localStorage.setItem('sidebar_collapsed', sidebarCollapsed ? 'true' : 'false')
  }, [sidebarCollapsed])

  useEffect(() => {
    setQueueUser(user?.user_id || null)
    setQueue(getQueue())
  }, [user?.user_id])

  useEffect(() => {
    if (!user) { setIsAdmin(false); return }
    let cancelled = false
    checkIsAdmin().then(v => { if (!cancelled) setIsAdmin(v) })
    return () => { cancelled = true }
  }, [user?.user_id])

  useEffect(() => {
    function onQueueChange() { setQueue(getQueue()) }
    window.addEventListener("queuechange", onQueueChange)
    return () => window.removeEventListener("queuechange", onQueueChange)
  }, [])

  // Background sync: pre-cache the user's data for offline use. Delayed so it
  // never competes with the app's first paint.
  useEffect(() => {
    const token = getToken()
    if (token && navigator.onLine) {
      const t = setTimeout(() => runBackgroundSync(token), 2000)
      return () => clearTimeout(t)
    }
  }, [])

  // Re-sync whenever connectivity returns.
  useEffect(() => {
    function handleOnline() {
      const token = getToken()
      if (token) runBackgroundSync(token)
    }
    window.addEventListener('online', handleOnline)
    return () => window.removeEventListener('online', handleOnline)
  }, [])

  useEffect(() => {
    if (!showSettings) return
    function onDown(e) {
      if (settingsRef.current && !settingsRef.current.contains(e.target)) setShowSettings(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [showSettings])

  useEffect(() => {
    if (!showOverflow) return
    function onDown(e) {
      if (overflowRef.current && !overflowRef.current.contains(e.target)) setShowOverflow(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [showOverflow])

  useEffect(() => { setShowOverflow(false) }, [view])

  useEffect(() => {
    if (!showDesktopOverflow) return
    function onDown(e) {
      if (desktopOverflowRef.current && !desktopOverflowRef.current.contains(e.target)) setShowDesktopOverflow(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [showDesktopOverflow])

  useEffect(() => { setShowDesktopOverflow(false) }, [view])

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setShowSearch(s => !s)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleOpenChat = useCallback((sessionId, title = null) => {
    navigate(`/chat/${encodeURIComponent(sessionId)}`, { state: { sessionTitle: title } })
  }, [navigate])

  const handleOpenInChat = useCallback((card, action, projectMeta = {}) => {
    const ctx = {
      action,
      auto_trigger:     action === "explain_simply",
      insight_title:    card.title    || "",
      insight_summary:  card.summary  || "",
      why_it_matters:   card.why_it_matters || "",
      educational_explanation: card.educational_explanation || "",
      source_urls:      (card.source_links || []).map(l => l.url || l).filter(Boolean),
      project_name:     projectMeta.name       || "",
      project_keywords: projectMeta.keywords   || [],
      project_id:       projectMeta.project_id || "",
      insight_id:       projectMeta.insight_id ?? null,
      category:         card.category    || null,
      content_type:     card.content_type || "news",
      domain:           projectMeta.domain || "default",
    }
    setFeedContext(ctx)
    navigate('/chat')
  }, [navigate])

  const handleOpenQueueItem = useCallback((item) => {
    const pid  = item.projectId  || null
    const iid  = item.insightId  || null
    const akey = item.articleKey || null
    setSidebarOpen(false)
    if (pid && iid) {
      navigate(`/feed/${encodeURIComponent(pid)}/${iid}${akey ? `/${encodeURIComponent(akey)}` : ''}`)
    } else if (pid) {
      navigate(`/feed/${encodeURIComponent(pid)}`)
    } else {
      navigate('/feed')
    }
  }, [navigate])

  // No-op: targetInsightId/targetArticleKey are derived from the URL, so they
  // only change when the route changes — nothing to clear between renders.
  const handleClearQueueTarget = useCallback(() => {}, [])

  const handleSearchNavigate = useCallback(({ type, projectId, sessionId, sessionTitle }) => {
    if (type === 'feed') {
      navigate(projectId ? `/feed/${encodeURIComponent(projectId)}` : '/feed')
    } else if (type === 'bookmarks') {
      navigate('/bookmarks')
    } else if (type === 'chat') {
      handleOpenChat(sessionId, sessionTitle)
    }
  }, [navigate, handleOpenChat])

  // ── Render ────────────────────────────────────────────────────────────────

  if (!isKnownSection) return <Navigate to="/feed" replace />

  return (
    <div
      className="flex bg-slate-950 text-slate-100 overflow-hidden"
      style={{ height: '100dvh' }}
    >
      <Sidebar
        view={view}
        onSearchOpen={() => setShowSearch(true)}
        queue={queue}
        onQueueItemClick={handleOpenQueueItem}
        showSettings={showSettings}
        onSettingsToggle={() => setShowSettings(s => !s)}
        settingsRef={settingsRef}
        user={user}
        collapsed={sidebarCollapsed}
        setCollapsed={setSidebarCollapsed}
        open={sidebarOpen}
        setOpen={setSidebarOpen}
        isAdmin={isAdmin}
      />

      {/* Floating mobile sidebar trigger — only visible when sidebar is closed on mobile */}
      <button
        onClick={() => setSidebarOpen(true)}
        aria-label="Open navigation"
        className={[
          'md:hidden fixed top-3.5 left-3.5 z-50',
          'w-8 h-8 flex items-center justify-center rounded-lg',
          'bg-slate-950/70 backdrop-blur-sm text-slate-500 hover:text-slate-200 transition-all duration-200',
          sidebarOpen ? 'opacity-0 pointer-events-none' : 'opacity-100',
        ].join(' ')}
      >
        <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
          <path fillRule="evenodd" d="M1.75 2h12.5a.75.75 0 0 1 0 1.5H1.75a.75.75 0 0 1 0-1.5ZM1.75 7h12.5a.75.75 0 0 1 0 1.5H1.75A.75.75 0 0 1 1.75 7Zm0 5h12.5a.75.75 0 0 1 0 1.5H1.75a.75.75 0 0 1 0-1.5Z" clipRule="evenodd" />
        </svg>
      </button>

      {/* Mobile ⋮ overflow menu — all actions, hidden on desktop */}
      {(actionsByView[view] ?? []).length > 0 && (
        <div
          ref={overflowRef}
          className={[
            'md:hidden fixed top-3.5 right-3.5 z-50 transition-all duration-200',
            sidebarOpen ? 'opacity-0 pointer-events-none' : 'opacity-100',
          ].join(' ')}
        >
          <button
            onClick={() => setShowOverflow(s => !s)}
            aria-label="More options"
            className={[
              'w-8 h-8 flex items-center justify-center rounded-lg',
              'bg-slate-950/70 backdrop-blur-sm transition-colors',
              showOverflow
                ? 'text-slate-200 bg-slate-800/80'
                : 'text-slate-500 hover:text-slate-200',
            ].join(' ')}
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM1.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM14.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
            </svg>
          </button>
          {showOverflow && (
            <div className="absolute top-full right-0 mt-1.5 w-52 bg-slate-900 border border-slate-700/60 rounded-xl shadow-2xl shadow-black/60 py-1 overflow-hidden">
              {(actionsByView[view] ?? []).map((action, i) => (
                <button
                  key={i}
                  onClick={() => { action.onClick(); setShowOverflow(false) }}
                  className={[
                    'w-full text-left px-3.5 py-2 text-[13px] transition-colors',
                    action.variant === 'danger'
                      ? 'text-red-400 hover:text-red-300 hover:bg-red-500/10'
                      : 'text-slate-300 hover:text-slate-100 hover:bg-white/[0.05]',
                  ].join(' ')}
                >
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Desktop ⋮ overflow menu — feed export actions only, hidden on mobile */}
      {view === 'feed' && (actionsByView['feed'] ?? []).filter(a => a.export).length > 0 && (
        <div
          ref={desktopOverflowRef}
          className="hidden md:block fixed top-3.5 right-3.5 z-50"
        >
          <button
            onClick={() => setShowDesktopOverflow(s => !s)}
            aria-label="Export options"
            className={[
              'w-8 h-8 flex items-center justify-center rounded-lg',
              'bg-slate-950/70 backdrop-blur-sm transition-colors',
              showDesktopOverflow
                ? 'text-slate-200 bg-slate-800/80'
                : 'text-slate-500 hover:text-slate-200',
            ].join(' ')}
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM1.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM14.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
            </svg>
          </button>
          {showDesktopOverflow && (
            <div className="absolute top-full right-0 mt-1.5 w-52 bg-slate-900 border border-slate-700/60 rounded-xl shadow-2xl shadow-black/60 py-1 overflow-hidden">
              {(actionsByView['feed'] ?? []).filter(a => a.export).map((action, i) => (
                <button
                  key={i}
                  onClick={() => { action.onClick(); setShowDesktopOverflow(false) }}
                  className="w-full text-left px-3.5 py-2 text-[13px] text-slate-300 hover:text-slate-100 hover:bg-white/[0.05] transition-colors"
                >
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Content area */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">

        {/* Offline banner — auto-hides once back online */}
        {!isOnline && (
          <div className="flex-shrink-0 px-3 py-1.5 text-center text-[12px] font-medium text-amber-300 bg-amber-500/10 border-b border-amber-500/20">
            You're offline — showing saved articles
          </div>
        )}

        {/* Chat workspace — fills all space on mobile */}
        <div className={[
          'overflow-hidden',
          view !== 'chat' ? 'hidden' : 'flex-1 flex flex-col',
        ].join(' ')}>
          <ChatWorkspace
            feedContext={feedContext}
            onClearFeedContext={() => setFeedContext(null)}
            targetSessionId={targetSessionId}
            targetSessionTitle={targetSessionTitle}
            onClearTargetSession={() => {}}
            userName={user?.name}
            onSidebarClose={handleSidebarClose}
            onBeforeModal={handleBeforeModal}
          />
        </div>

        {/* Scrollable main — feed, dashboard, bookmarks */}
        <main className={[
          'flex-1 overflow-y-auto',
          view === 'chat' ? 'hidden' : '',
        ].join(' ')}>
          <div className={[
            view === 'admin' ? 'max-w-[1600px]' : 'max-w-5xl',
            'mx-auto w-full',
            view === 'feed' || view === 'dashboard' || view === 'admin' ? 'px-4 pt-16 pb-8 md:px-8 md:pt-16 md:pb-10' : '',
          ].join(' ')}>

          {/* Feed — always mounted so generating state survives view switches */}
          <div className={view !== 'feed' ? 'hidden' : ''}>
            <ProjectsPage
              onOpenInChat={handleOpenInChat}
              onOpenChat={handleOpenChat}
              targetProjectId={targetProjectId}
              targetInsightId={targetInsightId}
              targetArticleKey={targetArticleKey}
              onClearQueueTarget={handleClearQueueTarget}
              userId={user?.user_id}
              userName={user?.name}
              onSidebarClose={handleSidebarClose}
              onBeforeModal={handleBeforeModal}
              isOnline={isOnline}
            />
          </div>

          {view === 'dashboard' && (
            <DashboardPage onGoToFeed={() => navigate('/feed')} userName={user?.name} />
          )}

          {view === 'admin' && <AdminPage />}

          {view === 'bookmarks' && (
            <BookmarksPage onOpenChat={handleOpenChat} onSidebarClose={handleSidebarClose} onBeforeModal={handleBeforeModal} />
          )}

          {view === 'readlater' && (
            <ReadLaterPage
              queue={queue}
              onItemClick={handleOpenQueueItem}
              onRemove={removeFromQueue}
            />
          )}

          </div>
        </main>
      </div>

      {showSearch && (
        <GlobalSearch
          onClose={() => setShowSearch(false)}
          onNavigate={handleSearchNavigate}
        />
      )}

      <UnpackListener />
    </div>
  )
}
