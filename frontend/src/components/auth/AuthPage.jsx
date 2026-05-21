import { useState } from "react"
import { useAuth } from "../../contexts/AuthContext"
import { forgotPassword, verifyResetCode, resetPassword } from "../../api/auth"

function EyeIcon({ open }) {
  return open ? (
    <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
      <path d="M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
      <path fillRule="evenodd" d="M.664 10.59a1.651 1.651 0 0 1 0-1.186A10.004 10.004 0 0 1 10 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0 1 10 17c-4.257 0-7.893-2.66-9.336-6.41ZM14 10a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z" clipRule="evenodd" />
    </svg>
  ) : (
    <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M3.28 2.22a.75.75 0 0 0-1.06 1.06l14.5 14.5a.75.75 0 1 0 1.06-1.06l-1.745-1.745a10.029 10.029 0 0 0 3.3-4.38 1.651 1.651 0 0 0 0-1.185A10.004 10.004 0 0 0 9.999 3a9.956 9.956 0 0 0-4.744 1.194L3.28 2.22ZM7.752 6.69l1.092 1.092a2.5 2.5 0 0 1 3.374 3.373l1.091 1.092a4 4 0 0 0-5.557-5.557Z" clipRule="evenodd" />
      <path d="M10.748 13.93l2.523 2.523a10.003 10.003 0 0 1-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 0 1 0-1.186A10.007 10.007 0 0 1 2.839 6.02L6.07 9.252a4 4 0 0 0 4.678 4.678Z" />
    </svg>
  )
}

function PasswordInput({ value, onChange, placeholder, required, id }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        id={id}
        type={show ? "text" : "password"}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        className="w-full bg-[#0f1117] border border-white/10 rounded-lg px-4 py-2.5 pr-10 text-white placeholder-gray-600 focus:outline-none focus:border-blue-500 text-sm"
      />
      <button
        type="button"
        onClick={() => setShow(s => !s)}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
        tabIndex={-1}
        aria-label={show ? "Hide password" : "Show password"}
      >
        <EyeIcon open={show} />
      </button>
    </div>
  )
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

export default function AuthPage() {
  const [mode, setMode]             = useState("login") // "login" | "signup" | "forgot"
  const [email, setEmail]           = useState("")
  const [emailError, setEmailError] = useState("")
  const [name, setName]             = useState("")
  const [password, setPassword]     = useState("")
  const [confirm, setConfirm]       = useState("")
  const [localError, setLocalError] = useState("")

  // forgot password state
  const [forgotStep,    setForgotStep]    = useState("send") // "send" | "code"
  const [forgotEmail,   setForgotEmail]   = useState("")
  const [forgotEmailErr,setForgotEmailErr]= useState("")
  const [forgotCode,    setForgotCode]    = useState("")
  const [forgotNewPw,   setForgotNewPw]   = useState("")
  const [forgotConfirm, setForgotConfirm] = useState("")
  const [forgotMsg,     setForgotMsg]     = useState("")
  const [forgotErr,     setForgotErr]     = useState("")
  const [forgotLoading, setForgotLoading] = useState(false)
  const [codeVerified,  setCodeVerified]  = useState(false)

  const { login, register, loading, error, clearError } = useAuth()

  const inputCls = "w-full bg-[#0f1117] border border-white/10 rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-blue-500 text-sm"
  const btnPrimary = "w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium py-2.5 rounded-lg transition-colors text-sm"

  function handleEmailChange(e) {
    const val = e.target.value
    setEmail(val)
    if (val && !EMAIL_RE.test(val)) {
      setEmailError("Enter a valid email address.")
    } else {
      setEmailError("")
    }
  }

  function switchMode(m) {
    setMode(m)
    setLocalError("")
    setEmailError("")
    clearError()
  }

  function openForgot() {
    setForgotEmail(email) // pre-fill from whatever the user typed
    setForgotEmailErr("")
    setForgotStep("send")
    setForgotCode("")
    setForgotNewPw("")
    setForgotConfirm("")
    setForgotMsg("")
    setForgotErr("")
    setForgotLoading(false)
    setCodeVerified(false)
    setMode("forgot")
  }

  function backToLogin() {
    setMode("login")
    setForgotStep("send")
    setForgotMsg("")
    setForgotErr("")
    setCodeVerified(false)
  }

  async function handleSendCode() {
    if (!EMAIL_RE.test(forgotEmail.trim())) {
      setForgotEmailErr("Enter a valid email address.")
      return
    }
    setForgotEmailErr("")
    setForgotLoading(true)
    setForgotErr("")
    setCodeVerified(false)
    setForgotCode("")
    try {
      await forgotPassword(forgotEmail.trim())
      setForgotStep("code")
    } catch (err) {
      setForgotErr(err.message || "Failed to send code.")
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleVerifyCode() {
    if (forgotCode.length !== 6) { setForgotErr("Enter the 6-digit code from your email."); return }
    setForgotLoading(true)
    setForgotErr("")
    try {
      await verifyResetCode(forgotEmail.trim(), forgotCode)
      setCodeVerified(true)
    } catch (err) {
      setForgotErr(err.message || "Incorrect code. Please try again.")
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleResetWithCode() {
    setForgotErr("")
    if (forgotNewPw.length < 8) { setForgotErr("Password must be at least 8 characters."); return }
    if (forgotNewPw !== forgotConfirm) { setForgotErr("Passwords do not match."); return }
    setForgotLoading(true)
    try {
      await resetPassword(forgotEmail.trim(), forgotCode, forgotNewPw)
      setForgotMsg("Password changed successfully!")
    } catch (err) {
      setForgotErr(err.message || "Invalid or expired code.")
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setLocalError("")
    clearError()

    if (!EMAIL_RE.test(email.trim())) {
      setEmailError("Enter a valid email address.")
      return
    }

    if (mode === "signup") {
      if (!name.trim()) {
        setLocalError("Please enter your name.")
        return
      }
      if (password !== confirm) {
        setLocalError("Passwords do not match.")
        return
      }
      if (password.length < 8) {
        setLocalError("Password must be at least 8 characters.")
        return
      }
      try {
        await register(email.trim(), name.trim(), password)
      } catch {
        // error shown via context
      }
    } else {
      try {
        await login(email.trim(), password)
      } catch {
        // error shown via context
      }
    }
  }

  const displayError = localError || error

  return (
    <div className="min-h-screen min-h-dvh bg-[#0f1117] flex items-center justify-center p-4 pt-safe">
      <div className="w-full max-w-md">
        {/* Logo / brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-blue-600 mb-4">
            <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-white">Curivio</h1>
          <p className="text-gray-400 text-sm mt-1">Learn smarter, a few minutes every day.</p>
        </div>

        {/* Card */}
        <div className="bg-[#1a1d27] border border-white/10 rounded-2xl px-5 py-6 sm:p-8">

          {/* ── Forgot password flow ── */}
          {mode === "forgot" ? (
            <div className="space-y-3">
              {/* Header */}
              <div className="flex items-center gap-2 mb-1">
                <button
                  type="button"
                  onClick={backToLogin}
                  className="text-gray-500 hover:text-gray-300 transition-colors"
                  aria-label="Back to sign in"
                >
                  <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
                    <path fillRule="evenodd" d="M14 8a.75.75 0 0 1-.75.75H4.56l3.22 3.22a.75.75 0 1 1-1.06 1.06l-4.5-4.5a.75.75 0 0 1 0-1.06l4.5-4.5a.75.75 0 0 1 1.06 1.06L4.56 7.25h8.69A.75.75 0 0 1 14 8Z" clipRule="evenodd"/>
                  </svg>
                </button>
                <h2 className="text-sm font-semibold text-white">Forgot Password</h2>
              </div>

              {forgotMsg ? (
                <div className="space-y-3">
                  <div className="flex items-start gap-2 px-3 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                    <svg className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5" viewBox="0 0 12 12" fill="currentColor">
                      <path fillRule="evenodd" d="M10.28 2.28a.75.75 0 0 0-1.06 0L4.5 6.99 2.78 5.27a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.06 0l5.25-5.25a.75.75 0 0 0 0-1.06Z" clipRule="evenodd"/>
                    </svg>
                    <p className="text-xs text-emerald-300 leading-relaxed">{forgotMsg}</p>
                  </div>
                  <button onClick={backToLogin} className={btnPrimary}>Back to Sign In</button>
                </div>

              ) : forgotStep === "send" ? (
                <>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Email</label>
                    <input
                      type="text"
                      value={forgotEmail}
                      onChange={e => { setForgotEmail(e.target.value); setForgotEmailErr("") }}
                      onKeyDown={e => e.key === "Enter" && handleSendCode()}
                      placeholder="you@example.com"
                      className={`${inputCls} ${forgotEmailErr ? "border-red-500/60" : ""}`}
                    />
                    {forgotEmailErr && <p className="text-xs text-red-400 mt-1">{forgotEmailErr}</p>}
                  </div>
                  <p className="text-xs text-gray-500 leading-relaxed">
                    We'll send a 6-digit code to this address.
                  </p>
                  {forgotErr && <p className="text-xs text-red-400">{forgotErr}</p>}
                  <button onClick={handleSendCode} disabled={forgotLoading} className={btnPrimary}>
                    {forgotLoading ? "Sending…" : "Send Code"}
                  </button>
                </>

              ) : (
                <>
                  <p className="text-xs text-gray-400 leading-relaxed">
                    Code sent to <span className="text-white font-medium">{forgotEmail}</span>
                  </p>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">6-digit code</label>
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
                      className={`${inputCls} tracking-widest text-center`}
                    />
                  </div>

                  {codeVerified ? (
                    <p className="text-xs text-emerald-400 flex items-center gap-1">
                      <svg className="w-3 h-3" viewBox="0 0 12 12" fill="currentColor">
                        <path fillRule="evenodd" d="M10.28 2.28a.75.75 0 0 0-1.06 0L4.5 6.99 2.78 5.27a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.06 0l5.25-5.25a.75.75 0 0 0 0-1.06Z" clipRule="evenodd"/>
                      </svg>
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
                        <label className="block text-xs text-gray-500 mb-1">New Password</label>
                        <PasswordInput
                          value={forgotNewPw}
                          onChange={e => { setForgotNewPw(e.target.value); setForgotErr("") }}
                          placeholder="At least 8 characters"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">Confirm Password</label>
                        <input
                          type="password"
                          value={forgotConfirm}
                          onChange={e => { setForgotConfirm(e.target.value); setForgotErr("") }}
                          onKeyDown={e => e.key === "Enter" && handleResetWithCode()}
                          placeholder="Repeat password"
                          className={inputCls}
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
                    className="w-full text-center text-xs text-gray-600 hover:text-gray-400 transition-colors pt-1"
                  >
                    Resend code
                  </button>
                </>
              )}
            </div>

          ) : (
            <>
              {/* ── Tab switcher ── */}
              <div className="flex rounded-lg bg-[#0f1117] p-1 mb-6">
                {["login", "signup"].map(m => (
                  <button
                    key={m}
                    onClick={() => switchMode(m)}
                    className={`flex-1 py-2 rounded-md text-sm font-medium transition-colors ${
                      mode === m
                        ? "bg-blue-600 text-white"
                        : "text-gray-400 hover:text-white"
                    }`}
                  >
                    {m === "login" ? "Sign In" : "Create Account"}
                  </button>
                ))}
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                {mode === "signup" && (
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Name</label>
                    <input
                      type="text"
                      required
                      value={name}
                      onChange={e => setName(e.target.value)}
                      placeholder="Your name"
                      className={inputCls}
                    />
                  </div>
                )}

                <div>
                  <label className="block text-sm text-gray-400 mb-1">Email</label>
                  <input
                    type="text"
                    value={email}
                    onChange={handleEmailChange}
                    onBlur={handleEmailChange}
                    placeholder="you@example.com"
                    required
                    className={`w-full bg-[#0f1117] border rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none text-sm transition-colors ${
                      emailError
                        ? "border-red-500/60 focus:border-red-500"
                        : "border-white/10 focus:border-blue-500"
                    }`}
                  />
                  {emailError && (
                    <p className="text-xs text-red-400 mt-1">{emailError}</p>
                  )}
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-sm text-gray-400">Password</label>
                    {mode === "login" && (
                      <button
                        type="button"
                        onClick={openForgot}
                        className="text-xs text-gray-500 hover:text-blue-400 transition-colors"
                      >
                        Forgot password?
                      </button>
                    )}
                  </div>
                  <PasswordInput
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder={mode === "signup" ? "At least 8 characters" : "Your password"}
                    required
                  />
                </div>

                {mode === "signup" && (
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Confirm Password</label>
                    <input
                      type="password"
                      value={confirm}
                      onChange={e => setConfirm(e.target.value)}
                      placeholder="Repeat password"
                      required
                      className={inputCls}
                    />
                  </div>
                )}

                {displayError && (
                  <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm">
                    {displayError}
                    {mode === "signup" && displayError.toLowerCase().includes("already exists") && (
                      <button
                        type="button"
                        onClick={() => switchMode("login")}
                        className="block mt-2 text-blue-400 hover:text-blue-300 text-xs font-medium transition-colors"
                      >
                        Sign in instead →
                      </button>
                    )}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className={`${btnPrimary} mt-2`}
                >
                  {loading
                    ? "Please wait…"
                    : mode === "login"
                    ? "Sign In"
                    : "Create Account"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
