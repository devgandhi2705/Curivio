/**
 * Registers the service worker for offline article reading.
 * @returns {Promise<ServiceWorkerRegistration|null>}
 */
export function registerSW() {
  if (!('serviceWorker' in navigator)) return Promise.resolve(null)

  return new Promise((resolve) => {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js')
        .then((registration) => {
          console.log('[SW] registered:', registration.scope)
          resolve(registration)
        })
        .catch((err) => {
          console.error('[SW] registration failed:', err)
          resolve(null)
        })
    })
  })
}
