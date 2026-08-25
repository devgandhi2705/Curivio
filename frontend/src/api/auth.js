const API_URL = import.meta.env.VITE_API_URL ?? ""

export const TOKEN_KEY = "ra_token"
const USER_KEY  = "ra_user"

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null")
  } catch {
    return null
  }
}

export function getAuthHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function storeSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

// ── Global 401 handler ────────────────────────────────────────────────────────
// AuthContext registers a handler here; any module that detects 401 calls
// signalUnauthorized() to clear state and redirect to login across the whole app.

let _unauthorizedHandler = null

export function onUnauthorized(fn) {
  _unauthorizedHandler = fn
}

export function signalUnauthorized() {
  clearSession()
  _unauthorizedHandler?.()
}

async function authPost(path, body) {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `Request failed: ${res.status}`)
    return data
  } catch (e) {
    if (e instanceof TypeError) throw new Error("Cannot reach the server. Please check your connection.")
    throw e
  }
}

async function authFetch(path, options = {}) {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      ...options,
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      if (res.status === 401) signalUnauthorized()
      throw new Error(data.detail || `Request failed: ${res.status}`)
    }
    return data
  } catch (e) {
    if (e instanceof TypeError) throw new Error("Cannot reach the server. Please check your connection.")
    throw e
  }
}

export async function register(email, name, password) {
  const data = await authPost("/auth/register", { email, name, password })
  storeSession(data.access_token, data.user)
  return data.user
}

export async function login(email, password) {
  const data = await authPost("/auth/login", { email, password })
  storeSession(data.access_token, data.user)
  return data.user
}

export async function getMe() {
  return authFetch("/auth/me")
}

export async function updateProfile(name, email) {
  const user = await authFetch("/auth/me", {
    method: "PUT",
    body: JSON.stringify({ name, email }),
  })
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  return user
}

export async function updateFeedVersion(feed_version) {
  const user = await authFetch("/auth/me/feed-version", {
    method: "PATCH",
    body: JSON.stringify({ feed_version }),
  })
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  return user
}

export async function changePassword(current_password, new_password) {
  return authFetch("/auth/me/password", {
    method: "PUT",
    body: JSON.stringify({ current_password, new_password }),
  })
}

export async function deleteAccount(password) {
  return authFetch("/auth/me/delete", {
    method: "POST",
    body: JSON.stringify({ password }),
  })
}

export async function verifyCurrentPassword(password) {
  return authFetch("/auth/verify-password", {
    method: "POST",
    body: JSON.stringify({ password }),
  })
}

export async function sendVerifyEmail(email, name, password) {
  return authPost("/auth/send-verify-email", { email, name, password })
}

export async function completeSignup(email, code) {
  const data = await authPost("/auth/complete-signup", { email, code })
  storeSession(data.access_token, data.user)
  return data.user
}

export async function forgotPassword(email) {
  return authPost("/auth/forgot-password", { email })
}

export async function verifyResetCode(email, code) {
  return authPost("/auth/verify-reset-code", { email, code })
}

export async function resetPassword(email, code, new_password) {
  return authPost("/auth/reset-password", { email, code, new_password })
}

export async function logoutRequest() {
  return authFetch("/auth/logout", { method: "POST" })
}
