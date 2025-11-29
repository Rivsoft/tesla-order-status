import { loadBundle, saveBundle, clearBundle } from './static/js/token-storage.js'

const TOKEN_HEADER = 'x-tesla-bundle'
const CLEAR_HEADER = 'x-tesla-clear'
const PUBLIC_PATHS = new Set(['/login', '/callback', '/logout'])
const CACHE_NAME = 'tesla-order-status-v2'

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('fetch', event => {
  const { request } = event
  const url = new URL(request.url)

  if (url.origin !== self.location.origin) {
    return
  }

  event.respondWith(handleFetch(request, url))
})

async function handleFetch (request, url) {
  const requiresTokens = shouldAttachTokens(url.pathname)
  let proxiedRequest = request

  if (requiresTokens) {
    const bundle = await loadBundle()
    if (!bundle) {
      const response = await fetch(request)
      await processResponseHeaders(response)
      return response
    }
    const encoded = btoa(JSON.stringify(bundle))
    proxiedRequest = await cloneRequestWithHeader(request, encoded)
  }

  // Caching Logic for Dashboard
  if (url.pathname === '/') {
    const forceRefresh = url.searchParams.get('refreshed') === '1'
    const cacheKey = new Request(url.origin + '/') // Normalize key to root

    if (!forceRefresh) {
      const cachedResponse = await caches.match(cacheKey)
      if (cachedResponse) {
        return cachedResponse
      }
    }

    try {
      const response = await fetch(proxiedRequest)
      await processResponseHeaders(response)

      if (response.status === 200) {
        const cache = await caches.open(CACHE_NAME)
        await cache.put(cacheKey, response.clone())
      }
      return response
    } catch (err) {
      // Fallback to cache if network fails
      const cachedResponse = await caches.match(cacheKey)
      if (cachedResponse) {
        return cachedResponse
      }
      throw err
    }
  }

  const response = await fetch(proxiedRequest)
  await processResponseHeaders(response)
  return response
}

function shouldAttachTokens (pathname) {
  if (pathname.startsWith('/static/')) {
    return false
  }
  if (PUBLIC_PATHS.has(pathname)) {
    return false
  }
  return true
}

async function cloneRequestWithHeader (request, headerValue) {
  const headers = new Headers(request.headers)
  headers.set(TOKEN_HEADER, headerValue)
  return new Request(request, { headers })
}

async function processResponseHeaders (response) {
  const updatedBundle = response.headers.get(TOKEN_HEADER)
  if (updatedBundle) {
    try {
      const parsed = JSON.parse(atob(updatedBundle))
      await saveBundle(parsed)
    } catch (error) {
      console.warn('Unable to persist updated tokens', error)
    }
  }

  if (response.headers.get(CLEAR_HEADER)) {
    await clearBundle()
  }
}
