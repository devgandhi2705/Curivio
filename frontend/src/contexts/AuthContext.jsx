import { createContext, useContext, useState, useEffect, useCallback } from "react"
import {
  login as apiLogin,
  register as apiRegister,
  completeSignup as apiCompleteSignup,
  updateProfile as apiUpdateProfile,
  updateFeedVersion as apiUpdateFeedVersion,
  changePassword as apiChangePassword,
  deleteAccount as apiDeleteAccount,
  verifyCurrentPassword as apiVerifyPassword,
  logoutRequest,
  getMe,
  getStoredUser,
  getToken,
  clearSession,
  onUnauthorized,
  TOKEN_KEY,
} from "../api/auth"

const AuthContext = createContext(null)

// AUTH_CHECK_TIMEOUT_MS: if the backend doesn't respond within this window
// (e.g. HF Spaces cold start), we optimistically allow the stored session through
// so the user isn't stuck on a loading screen forever.
const AUTH_CHECK_TIMEOUT_MS = 10_000

export function AuthProvider({ children }) {
  const [user,        setUser]        = useState(() => getStoredUser())
  // Start checked immediately when there's no token — no need to verify
  const [authChecked, setAuthChecked] = useState(() => !getToken())
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState(null)

  // On mount: register global 401 handler, then verify the stored token.
  useEffect(() => {
    // 1. Register the global 401 handler BEFORE making any requests, so it's in
    //    place if getMe() itself comes back with 401.
    onUnauthorized(() => setUser(null))

    const token = getToken()
    if (!token) {
      // No token → already marked as checked in the useState initializer
      return
    }

    // 2. Verify the token is still accepted by the server.
    //    - Success  → refresh stored user with server-fresh data
    //    - 401      → authFetch already called signalUnauthorized (clears session +
    //                 calls the handler above which sets user to null)
    //    - Network  → keep existing stored session; don't log out on connectivity issues
    let settled = false
    const timeoutId = setTimeout(() => {
      if (!settled) { settled = true; setAuthChecked(true) }
    }, AUTH_CHECK_TIMEOUT_MS)

    getMe()
      .then(freshUser => {
        if (!settled) {
          settled = true
          clearTimeout(timeoutId)
          setUser(freshUser)
          setAuthChecked(true)
        }
      })
      .catch(() => {
        if (!settled) {
          settled = true
          clearTimeout(timeoutId)
          // 401 path: signalUnauthorized already set user to null + cleared session
          // Network error path: keep user logged in (optimistic)
          setAuthChecked(true)
        }
      })

    return () => { settled = true; clearTimeout(timeoutId) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Multi-tab logout: if token is removed in another tab, mirror the logout here.
  useEffect(() => {
    function onStorage(e) {
      if (e.key === TOKEN_KEY && !e.newValue) setUser(null)
    }
    window.addEventListener("storage", onStorage)
    return () => window.removeEventListener("storage", onStorage)
  }, [])

  const clearError = useCallback(() => setError(null), [])

  const login = useCallback(async (email, password) => {
    setLoading(true)
    setError(null)
    try {
      const u = await apiLogin(email, password)
      setUser(u)
      return u
    } catch (e) {
      setError(e.message)
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  const register = useCallback(async (email, name, password) => {
    setLoading(true)
    setError(null)
    try {
      const u = await apiRegister(email, name, password)
      setUser(u)
      return u
    } catch (e) {
      setError(e.message)
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  const finalizeSignup = useCallback(async (email, code) => {
    const u = await apiCompleteSignup(email, code)
    setUser(u)
    return u
  }, [])

  const logout = useCallback(async () => {
    // Best-effort server-side revocation: the token is blocklisted by jti so
    // it can't be replayed after logout. Local session is cleared regardless
    // of whether the request succeeds — a network failure here must never
    // trap the user in a logged-in UI.
    try {
      await logoutRequest()
    } catch {
      // ignore — clearing local state below is what actually logs the user out client-side
    }
    clearSession()
    setUser(null)
  }, [])

  const updateProfile = useCallback(async (name, email) => {
    const u = await apiUpdateProfile(name, email)
    setUser(u)
    return u
  }, [])

  const updateFeedVersion = useCallback(async (feedVersion) => {
    const u = await apiUpdateFeedVersion(feedVersion)
    setUser(u)
    return u
  }, [])

  const changePassword = useCallback(async (current, next) => {
    return apiChangePassword(current, next)
  }, [])

  const deleteAccount = useCallback(async (password) => {
    await apiDeleteAccount(password)
    clearSession()
    setUser(null)
  }, [])

  const verifyPassword = useCallback(async (password) => {
    return apiVerifyPassword(password)
  }, [])

  return (
    <AuthContext.Provider value={{
      user,
      authChecked,
      loading,
      error,
      clearError,
      login,
      register,
      finalizeSignup,
      logout,
      updateProfile,
      updateFeedVersion,
      changePassword,
      deleteAccount,
      verifyPassword,
      isAuthenticated: !!user,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
