import { useState, useCallback, useEffect, useRef } from 'react'
import ChatWorkspace from './components/chat/ChatWorkspace.jsx'
import ProjectsPage from './components/feed/ProjectsPage.jsx'
import BookmarksPage from './components/bookmarks/BookmarksPage.jsx'
import DashboardPage from './components/dashboard/DashboardPage.jsx'
import GlobalSearch from './components/GlobalSearch.jsx'
import AuthPage from './components/auth/AuthPage.jsx'
import { AuthProvider, useAuth } from './contexts/AuthContext.jsx'
import { getQueue, removeFromQueue, clearQueue, setQueueUser } from './api/queue.js'

function AuthLoadingScreen() {
  return (
    <div className="min-h-screen min-h-dvh bg-slate-950 flex items-center justify-center">
      <div className="flex flex-col items-center gap-5">
        <div className="relative w-12 h-12 flex-shrink-0">
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-blue-500 via-indigo-500 to-violet-600 shadow-lg shadow-violet-950/50 animate-pulse" />
          <div className="absolute inset-0 rounded-2xl flex items-center justify-center">
            <svg style={{ width: '22px', height: '22px' }} viewBox="0 0 20 20" fill="none">
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
        <div className="flex gap-1.5">
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce [animation-delay:-0.3s]" />
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce [animation-delay:-0.15s]" />
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce" />
        </div>
      </div>
    </div>
  )
}

// ── Nav panel components ──────────────────────────────────────────────────────

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

function SettingsPanel({ isDark, onToggleTheme }) {
  const { user, logout, updateProfile, changePassword, deleteAccount, verifyPassword } = useAuth()

  // section: "main" | "profile" | "password" | "forgot" | "danger"
  const [section, setSection]           = useState("main")
  const [profileName, setProfileName]   = useState(user?.name || "")
  const [profileEmail, setProfileEmail] = useState(user?.email || "")
  const [profileMsg, setProfileMsg]     = useState("")
  const [profileErr, setProfileErr]     = useState("")
  const [savingProfile, setSavingProfile] = useState(false)

  // password: 2-step — "verify" then "change"
  const [pwStep, setPwStep]   = useState("verify")
  const [curPw, setCurPw]     = useState("")
  const [newPw, setNewPw]     = useState("")
  const [pwMsg, setPwMsg]     = useState("")
  const [pwErr, setPwErr]     = useState("")
  const [savingPw, setSavingPw] = useState(false)

  // forgot password — steps: "send" | "code" (verify) | "newpw" (set new password)
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
      await updateProfile(profileName.trim(), profileEmail.trim())
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
    <div className="absolute right-0 top-full mt-2 z-40 w-72 max-w-[calc(100vw-1rem)] bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 overflow-hidden">
      {/* Header */}
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

          <div className="px-4 py-3 border-b border-slate-800/60">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-2.5">Appearance</p>
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-300">{isDark ? "Night Mode" : "Day Mode"}</span>
              <button
                onClick={onToggleTheme}
                className={`relative w-9 h-5 rounded-full transition-colors duration-200 ${isDark ? "bg-blue-600" : "bg-slate-600"}`}
              >
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${isDark ? "translate-x-4" : "translate-x-0.5"}`} />
              </button>
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
            <input type="email" value={profileEmail} onChange={e => setProfileEmail(e.target.value)} className={inputCls} required />
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
                <PwField
                  value={curPw}
                  onChange={e => { setCurPw(e.target.value); setPwErr("") }}
                  className={inputCls + " pr-8"}
                  placeholder="Your current password"
                  onKeyDown={e => e.key === "Enter" && handleVerifyPassword()}
                />
              </div>
              {pwErr && <p className="text-xs text-red-400">{pwErr}</p>}
              <button onClick={handleVerifyPassword} disabled={savingPw || !curPw} className={btnPrimary}>
                {savingPw ? "Verifying…" : "Verify Password"}
              </button>
              <button
                type="button"
                onClick={() => { back(); setSection("forgot") }}
                className="w-full text-center text-xs text-slate-600 hover:text-blue-400 transition-colors pt-1"
              >
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
                <PwField
                  value={newPw}
                  onChange={e => { setNewPw(e.target.value); setPwErr("") }}
                  className={inputCls + " pr-8"}
                  placeholder="At least 8 characters"
                  onKeyDown={e => e.key === "Enter" && handleChangePassword()}
                />
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

              {/* Step 1 — enter & verify code */}
              <div>
                <label className="block text-xs text-slate-500 mb-1">6-Digit Code</label>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength="6"
                  value={forgotCode}
                  onChange={e => { setForgotCode(e.target.value.replace(/\D/g, "").slice(0, 6)); setForgotErr(""); setCodeVerified(false) }}
                  onKeyDown={e => e.key === "Enter" && !codeVerified && handleVerifyCode()}
                  placeholder="000000"
                  disabled={codeVerified}
                  className={inputCls + " text-center text-xl font-mono tracking-[0.4em] placeholder-slate-700" + (codeVerified ? " opacity-60" : "")}
                />
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

              {/* Step 2 — new password (only after code verified) */}
              {codeVerified && (
                <>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">New Password</label>
                    <PwField
                      value={forgotNewPw}
                      onChange={e => { setForgotNewPw(e.target.value); setForgotErr("") }}
                      className={inputCls + " pr-8"}
                      placeholder="At least 8 characters"
                      autoComplete="new-password"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Confirm Password</label>
                    <input
                      type="password"
                      value={forgotConfirm}
                      onChange={e => { setForgotConfirm(e.target.value); setForgotErr("") }}
                      onKeyDown={e => e.key === "Enter" && handleResetWithCode()}
                      placeholder="Repeat password"
                      className={inputCls}
                      autoComplete="new-password"
                    />
                  </div>
                  {forgotErr && <p className="text-xs text-red-400">{forgotErr}</p>}
                  <button onClick={handleResetWithCode} disabled={forgotLoading || !forgotNewPw || !forgotConfirm} className={btnPrimary}>
                    {forgotLoading ? "Resetting…" : "Reset Password"}
                  </button>
                </>
              )}

              <button
                type="button"
                onClick={handleSendCode}
                disabled={forgotLoading}
                className="w-full text-center text-xs text-slate-600 hover:text-slate-400 transition-colors"
              >
                Resend code
              </button>
            </>
          )}
        </div>
      )}

      {section === "danger" && (
        <div className="px-4 py-4 space-y-3">
          <p className="text-xs text-slate-400">Enter your password to permanently delete your account and all data. This cannot be undone.</p>
          <PwField
            value={deleteConfirm}
            onChange={e => setDeleteConfirm(e.target.value)}
            placeholder="Your password"
            className={inputCls + " pr-8"}
            autoComplete="current-password"
          />
          {delErr && <p className="text-xs text-red-400">{delErr}</p>}
          <button
            onClick={handleDeleteAccount}
            disabled={deleting || !deleteConfirm}
            className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium py-2 rounded-lg transition-colors"
          >
            {deleting ? "Deleting…" : "Delete My Account"}
          </button>
        </div>
      )}
    </div>
  )
}

function groupByDate(items) {
  const today     = new Date(); today.setHours(0,0,0,0)
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  const groups    = {}
  items.forEach(item => {
    const d = item.queuedAt ? new Date(item.queuedAt) : new Date(0)
    const day = new Date(d); day.setHours(0,0,0,0)
    let label
    if (day.getTime() === today.getTime())     label = "Today"
    else if (day.getTime() === yesterday.getTime()) label = "Yesterday"
    else label = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: d.getFullYear() !== today.getFullYear() ? "numeric" : undefined })
    if (!groups[label]) groups[label] = []
    groups[label].push(item)
  })
  return groups
}

function QueuePanel({ queue, onItemClick }) {
  const [search, setSearch] = useState("")

  const filtered = search.trim()
    ? queue.filter(i => i.title?.toLowerCase().includes(search.toLowerCase()) || i.projectName?.toLowerCase().includes(search.toLowerCase()))
    : queue

  const groups = groupByDate(filtered)

  return (
    <div className="absolute right-0 top-full mt-2 z-40 w-72 max-w-[calc(100vw-1rem)] bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 overflow-hidden">
      {/* Header */}
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

      {/* Search */}
      {queue.length > 0 && (
        <div className="px-3 py-2 border-b border-slate-800/60">
          <div className="relative">
            <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-600" viewBox="0 0 16 16" fill="currentColor">
              <path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z"/>
            </svg>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search queue…"
              className="w-full pl-7 pr-3 py-1.5 bg-slate-800/60 border border-slate-700/50 rounded-lg text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-600 transition-colors"
            />
          </div>
        </div>
      )}

      {/* Body */}
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
                  <button
                    onClick={() => onItemClick(item)}
                    className="flex-1 flex items-start gap-2.5 px-4 py-2.5 text-left min-w-0"
                    title={`Go to: ${item.title}`}
                  >
                    <div className="flex-1 min-w-0 pr-4">
                      <p className="text-xs font-medium text-slate-300 leading-snug line-clamp-2 group-hover:text-slate-100 transition-colors">
                        {item.title}
                      </p>
                      {item.projectName && (
                        <p className="text-[10px] text-slate-600 mt-0.5">{item.projectName}</p>
                      )}
                    </div>
                    <svg className="w-3 h-3 text-slate-700 group-hover:text-slate-500 flex-shrink-0 mt-0.5 transition-colors" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z" />
                    </svg>
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); removeFromQueue(item.articleKey) }}
                    title="Remove from queue"
                    className="absolute right-2.5 w-5 h-5 flex items-center justify-center rounded text-slate-600 hover:text-slate-300 hover:bg-slate-700/60 opacity-0 group-hover:opacity-100 transition-all"
                  >
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

const NAV_TABS = [
  { id: 'feed',      label: 'Feed'      },
  { id: 'chat',      label: 'Chat'      },
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'bookmarks', label: 'Bookmarks' },
]

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}

function AppContent() {
  const { isAuthenticated, authChecked, user } = useAuth()
  const [view, setView] = useState('feed')
  const [isDark, setIsDark] = useState(() => {
    const saved = localStorage.getItem('theme')
    if (saved) return saved === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  // Feed → Chat context
  const [feedContext, setFeedContext] = useState(null)

  // Session to load when jumping from Related Discussions → Chat
  const [targetSessionId,    setTargetSessionId]    = useState(null)
  const [targetSessionTitle, setTargetSessionTitle] = useState(null)

  // Global search
  const [showSearch,     setShowSearch]     = useState(false)
  const [targetProjectId, setTargetProjectId] = useState(null)

  // Read-Later queue
  const [queue,            setQueue]            = useState(() => getQueue())
  const [showQueue,        setShowQueue]        = useState(false)
  const queueRef = useRef(null)

  // Settings panel
  const [showSettings, setShowSettings] = useState(false)
  const settingsRef = useRef(null)

  // Queue → Feed navigation targets
  const [targetInsightId,  setTargetInsightId]  = useState(null)
  const [targetArticleKey, setTargetArticleKey] = useState(null)

  // Scope the read-later queue to the current user
  useEffect(() => {
    setQueueUser(user?.user_id || null)
    setQueue(getQueue())
  }, [user?.user_id])

  // Sync queue state from localStorage
  useEffect(() => {
    function onQueueChange() { setQueue(getQueue()) }
    window.addEventListener("queuechange", onQueueChange)
    return () => window.removeEventListener("queuechange", onQueueChange)
  }, [])

  // Close queue panel on outside click
  useEffect(() => {
    if (!showQueue) return
    function onDown(e) {
      if (queueRef.current && !queueRef.current.contains(e.target)) setShowQueue(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [showQueue])

  // Close settings panel on outside click
  useEffect(() => {
    if (!showSettings) return
    function onDown(e) {
      if (settingsRef.current && !settingsRef.current.contains(e.target)) setShowSettings(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [showSettings])

  function toggleTheme() {
    const root = document.documentElement
    root.classList.add('theme-transitioning')
    setIsDark(d => {
      const next = !d
      localStorage.setItem('theme', next ? 'dark' : 'light')
      return next
    })
    setTimeout(() => root.classList.remove('theme-transitioning'), 250)
  }

  // Cmd/Ctrl+K opens search
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
    setTargetSessionId(sessionId)
    setTargetSessionTitle(title)
    setView('chat')
  }, [])

  const handleOpenInChat = useCallback((card, action, projectMeta = {}) => {
    setFeedContext({
      action,
      // explain_simply auto-triggers an immediate AI response on arrival
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
    })
    setView('chat')
  }, [])

  const handleOpenQueueItem = useCallback((item) => {
    setTargetProjectId(item.projectId || null)
    setTargetInsightId(item.insightId || null)
    setTargetArticleKey(item.articleKey || null)
    setShowQueue(false)
    setView('feed')
  }, [])

  const handleClearQueueTarget = useCallback(() => {
    setTargetInsightId(null)
    setTargetArticleKey(null)
  }, [])

  const handleSearchNavigate = useCallback(({ type, projectId, sessionId, sessionTitle }) => {
    if (type === 'feed') {
      setView('feed')
      if (projectId) setTargetProjectId(projectId)
    } else if (type === 'bookmarks') {
      setView('bookmarks')
    } else if (type === 'chat') {
      handleOpenChat(sessionId, sessionTitle)
    }
  }, [handleOpenChat])

  // ── Render ────────────────────────────────────────────────────────────────

  // While verifying the stored token, show a branded loading screen so we never
  // render protected content against an invalid or expired JWT.
  if (!authChecked) return <AuthLoadingScreen />
  if (!isAuthenticated) return <AuthPage />

  return (
    <div className={`min-h-screen min-h-dvh bg-slate-950 text-slate-100 ${isDark ? "" : "theme-light"}`}>

      {/* Sticky top nav */}
      <header className="sticky top-0 z-20 border-b border-slate-800/60 bg-slate-950/95 backdrop-blur-sm">
        <div className="px-5 h-13 flex items-center gap-5 relative" style={{ height: '52px' }}>

          {/* Brand — far left, prominent */}
          <div className="flex items-center gap-2.5 flex-shrink-0">
            <div className="relative w-8 h-8 flex-shrink-0">
              <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-blue-500 via-indigo-500 to-violet-600 shadow-lg shadow-violet-950/50" />
              <div className="absolute inset-0 rounded-xl flex items-center justify-center">
                <svg style={{ width: '18px', height: '18px' }} viewBox="0 0 20 20" fill="none">
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
            <span className="font-bold text-[15px] tracking-tight select-none bg-gradient-to-r from-slate-100 to-slate-300 bg-clip-text text-transparent">
              Curivio
            </span>
          </div>

          {/* Divider — desktop only */}
          <div className="hidden md:block w-px h-5 bg-slate-800 flex-shrink-0" />

          {/* Nav tabs — desktop only */}
          <nav className="hidden md:flex items-center gap-0.5">
            {NAV_TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setView(tab.id)}
                className={`relative px-3.5 py-1.5 rounded-lg text-[13px] font-medium transition-all ${
                  view === tab.id
                    ? 'bg-slate-800 text-slate-100'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-slate-900/70'
                }`}
              >
                {tab.label}
                {view === tab.id && (
                  <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-3 h-0.5 rounded-full bg-blue-500" />
                )}
              </button>
            ))}
          </nav>

          {/* Global search trigger — centered, desktop only */}
          <button
            onClick={() => setShowSearch(true)}
            className="hidden md:flex absolute left-1/2 -translate-x-1/2 items-center gap-2 px-3.5 py-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800/60 border border-slate-800/60 transition-all text-[12px] w-72 pointer-events-auto"
            title="Search (Ctrl+K)"
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
            </svg>
            <span className="flex-1 text-left">Search</span>
            <kbd className="hidden md:flex items-center gap-0.5 px-1.5 py-0.5 text-[9px] rounded bg-slate-800 text-slate-600 border border-slate-700/50 flex-shrink-0">
              ⌘K
            </kbd>
          </button>

          {/* Right corner — pushed to far right */}
          <div className="ml-auto flex items-center gap-0.5 flex-shrink-0">

            {/* Mobile search icon — mobile only */}
            <button
              onClick={() => setShowSearch(true)}
              title="Search"
              className="flex md:hidden items-center justify-center w-8 h-8 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800/60 transition-all"
            >
              <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
              </svg>
            </button>

            {/* Read Later queue */}
            <div ref={queueRef} className="relative">
              <button
                onClick={() => setShowQueue(s => !s)}
                title="Your Queue"
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg transition-all text-[12px] font-medium ${
                  queue.length > 0
                    ? "text-amber-400 hover:text-amber-300 hover:bg-amber-500/10"
                    : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/60"
                }`}
              >
                {/* Text on desktop, icon on mobile */}
                <span className="hidden md:inline">Read Later</span>
                <ClockIcon className="md:hidden w-4 h-4" />
                {queue.length > 0 && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 tabular-nums leading-none">
                    {queue.length}
                  </span>
                )}
              </button>
              {showQueue && <QueuePanel queue={queue} onItemClick={handleOpenQueueItem} />}
            </div>

            <div className="hidden md:block w-px h-4 bg-slate-800 mx-0.5 flex-shrink-0" />

            {/* Settings */}
            <div ref={settingsRef} className="relative">
              <button
                onClick={() => setShowSettings(s => !s)}
                title="Settings"
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg transition-all text-[12px] font-medium ${
                  showSettings
                    ? "text-slate-200 bg-slate-800"
                    : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/60"
                }`}
              >
                <GearIcon className="w-3.5 h-3.5" />
                <span className="hidden md:inline">Settings</span>
              </button>
              {showSettings && (
                <SettingsPanel isDark={isDark} onToggleTheme={toggleTheme} />
              )}
            </div>

          </div>
        </div>
      </header>

      <main
        className={`md:pb-0 ${view === 'feed' || view === 'dashboard' ? 'px-3 py-4 md:px-5 md:py-6' : ''}`}
        style={{ paddingBottom: 'var(--mobile-nav-h)' }}
      >

        {/* ── Chat workspace view ── */}
        {view === 'chat' && (
          <ChatWorkspace
            feedContext={feedContext}
            onClearFeedContext={() => setFeedContext(null)}
            targetSessionId={targetSessionId}
            targetSessionTitle={targetSessionTitle}
            onClearTargetSession={() => { setTargetSessionId(null); setTargetSessionTitle(null) }}
            userName={user?.name}
          />
        )}

        {/* ── Feed view — project-based learning streams ── */}
        {view === 'feed' && (
          <ProjectsPage
            onOpenInChat={handleOpenInChat}
            onOpenChat={handleOpenChat}
            targetProjectId={targetProjectId}
            targetInsightId={targetInsightId}
            targetArticleKey={targetArticleKey}
            onClearQueueTarget={handleClearQueueTarget}
            userId={user?.user_id}
            userName={user?.name}
          />
        )}

        {/* ── Dashboard view ── */}
        {view === 'dashboard' && (
          <DashboardPage onGoToFeed={() => setView('feed')} userName={user?.name} />
        )}

        {/* ── Bookmarks view ── */}
        {view === 'bookmarks' && (
          <BookmarksPage onOpenChat={handleOpenChat} />
        )}

      </main>
      {/* ── Global search overlay ── */}
      {showSearch && (
        <GlobalSearch
          onClose={() => setShowSearch(false)}
          onNavigate={handleSearchNavigate}
        />
      )}

      {/* ── Mobile bottom navigation — md:hidden ── */}
      <nav className="fixed bottom-0 left-0 right-0 z-20 md:hidden border-t border-slate-800/80 bg-slate-950/95 backdrop-blur-sm">
        <div className="flex items-center pb-safe">
          {/* Feed */}
          <button
            onClick={() => setView('feed')}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors ${view === 'feed' ? 'text-blue-400' : 'text-slate-600'}`}
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10.75 16.82A7.462 7.462 0 0 1 10 17c-.25 0-.5-.008-.75-.025V14h1.5v2.82ZM6.25 16.185a7.5 7.5 0 0 1-1.422-.878L6 14.016l1.06 1.06-1.06 1.06.25.05ZM14.75 15.308a7.5 7.5 0 0 1-1.422.877l-.25-.05-1.06-1.06L13.078 14l1.172 1.308ZM3.834 12.75a7.503 7.503 0 0 1-.516-1.562L4.5 10.5l1 1-1 1-.666.25ZM16.682 11.188a7.503 7.503 0 0 1-.516 1.562L15.5 12.5l-1-1 1-1 .682-.688.5 1.376Z" />
              <path fillRule="evenodd" d="M10 3a7 7 0 1 0 0 14A7 7 0 0 0 10 3Zm0 1.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11Z" clipRule="evenodd" />
              <path d="M10 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z" />
            </svg>
            <span className="text-[10px] font-medium">Feed</span>
          </button>
          {/* Chat */}
          <button
            onClick={() => setView('chat')}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors ${view === 'chat' ? 'text-blue-400' : 'text-slate-600'}`}
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 2c-2.236 0-4.43.18-6.57.524C1.993 2.755 1 4.014 1 5.426v5.148c0 1.413.993 2.67 2.43 2.902.848.138 1.705.248 2.57.33v3.194c0 .202.12.38.303.456a.5.5 0 0 0 .542-.116L10.03 14h.543A21.26 21.26 0 0 0 13 13.74V7.074c0-1.413-.993-2.672-2.43-2.903A21.212 21.212 0 0 0 10 4c0-.34-.003-.678-.01-1H10ZM8.5 7a1.5 1.5 0 1 0 3 0 1.5 1.5 0 0 0-3 0Z" clipRule="evenodd" />
              <path d="M15.5 2c-.126 0-.25.003-.374.008A5.026 5.026 0 0 1 17 5.426v5.148c0 2.034-1.517 3.73-3.512 3.97L12 14.596V16a.5.5 0 0 0 .831.373l1.604-1.473A21.27 21.27 0 0 0 16 14.83c1.437-.232 2.43-1.49 2.43-2.902V5.426c0-1.413-.993-2.671-2.43-2.902A21.258 21.258 0 0 0 15.5 2.5V2Z" />
            </svg>
            <span className="text-[10px] font-medium">Chat</span>
          </button>
          {/* Dashboard */}
          <button
            onClick={() => setView('dashboard')}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors ${view === 'dashboard' ? 'text-blue-400' : 'text-slate-600'}`}
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M1 2.75A.75.75 0 0 1 1.75 2h16.5a.75.75 0 0 1 0 1.5H18v8.75A2.75 2.75 0 0 1 15.25 15h-1.072l.798 3.06a.75.75 0 0 1-1.452.38L13.41 18H6.59l-.114.44a.75.75 0 0 1-1.452-.38L5.823 15H4.75A2.75 2.75 0 0 1 2 12.25V3.5h-.25A.75.75 0 0 1 1 2.75ZM7.373 15l-.391 1.5h6.037l-.392-1.5H7.373ZM13 7.5a.75.75 0 0 0-1.5 0v4.25a.75.75 0 0 0 1.5 0V7.5ZM9.25 9a.75.75 0 0 1 .75.75v2a.75.75 0 0 1-1.5 0v-2A.75.75 0 0 1 9.25 9ZM7 10.75a.75.75 0 0 0-1.5 0v.5a.75.75 0 0 0 1.5 0v-.5Z" clipRule="evenodd" />
            </svg>
            <span className="text-[10px] font-medium">Dashboard</span>
          </button>
          {/* Bookmarks */}
          <button
            onClick={() => setView('bookmarks')}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors ${view === 'bookmarks' ? 'text-blue-400' : 'text-slate-600'}`}
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 2c-1.716 0-3.408.106-5.07.31C3.806 2.45 3 3.414 3 4.517V17.25a.75.75 0 0 0 1.075.676L10 15.082l5.925 2.844A.75.75 0 0 0 17 17.25V4.517c0-1.103-.806-2.068-1.93-2.207A41.403 41.403 0 0 0 10 2Z" clipRule="evenodd" />
            </svg>
            <span className="text-[10px] font-medium">Bookmarks</span>
          </button>
        </div>
      </nav>
    </div>
  )
}
