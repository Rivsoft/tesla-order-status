import { appendHistorySnapshot } from './history-store.js'

const DIGEST_META_KEY = 'teslaOrderDigestMeta'
const ACK_KEY = 'teslaOrderDigestAck'
const DEFAULT_POLL_INTERVAL = 300000 // 5 minutes
const MIN_POLL_INTERVAL = 60000
const POLL_ENDPOINT = '/api/orders'
const NOTIFICATION_PREF_KEY = 'teslaOrderNotificationPref'
const NOTIFICATION_DIGEST_KEY = 'teslaOrderNotificationDigest'
const NOTIFICATION_PREF = {
  ENABLED: 'enabled',
  DISABLED: 'disabled'
}
const NOTIFICATION_ICON = (() => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="18" ry="18" fill="#181818"/><path d="M48 18c-13.8 0-25 11.2-25 25v15.8l-6.8 11.6a3.2 3.2 0 0 0 2.7 4.8h58.2a3.2 3.2 0 0 0 2.7-4.8L73 58.8V43c0-13.8-11.2-25-25-25zm0 52.5a6 6 0 0 0 6-6H42a6 6 0 0 0 6 6z" fill="#e82127"/></svg>'
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
})()

let pollInFlight = null

function getStorage () {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const storage = window.localStorage
    const testKey = '__tesla_digest_test__'
    storage.setItem(testKey, '1')
    storage.removeItem(testKey)
    return storage
  } catch (error) {
    console.warn('localStorage unavailable', error)
    return null
  }
}

function readDigestMeta (storage) {
  if (!storage) {
    return null
  }
  try {
    return JSON.parse(storage.getItem(DIGEST_META_KEY)) || null
  } catch (error) {
    console.warn('Unable to parse digest metadata', error)
    return null
  }
}

function persistDigestMeta (storage, digest, capturedAt, { bootstrap = false } = {}) {
  if (!storage || !digest) {
    return { changed: false, meta: null }
  }
  const nextMeta = {
    digest,
    capturedAt: capturedAt || new Date().toISOString()
  }
  const current = readDigestMeta(storage)
  const changed = !current || current.digest !== digest
  try {
    storage.setItem(DIGEST_META_KEY, JSON.stringify(nextMeta))
    if (bootstrap && !storage.getItem(ACK_KEY)) {
      storage.setItem(ACK_KEY, digest)
    }
  } catch (error) {
    console.warn('Unable to persist digest metadata', error)
  }
  return { changed, meta: nextMeta }
}

function notificationsSupported () {
  return typeof window !== 'undefined' && typeof Notification !== 'undefined'
}

function readNotificationPreference (storage) {
  if (!storage) {
    return NOTIFICATION_PREF.DISABLED
  }
  try {
    return storage.getItem(NOTIFICATION_PREF_KEY) || NOTIFICATION_PREF.DISABLED
  } catch (error) {
    console.warn('Unable to read notification preference', error)
    return NOTIFICATION_PREF.DISABLED
  }
}

function persistNotificationPreference (storage, value) {
  if (!storage) {
    return
  }
  try {
    storage.setItem(NOTIFICATION_PREF_KEY, value)
  } catch (error) {
    console.warn('Unable to persist notification preference', error)
  }
}

function notificationsEnabled (storage) {
  return (
    notificationsSupported() &&
    Notification.permission === 'granted' &&
    readNotificationPreference(storage) === NOTIFICATION_PREF.ENABLED
  )
}

function updateNotificationControls (storage, statusEl, toggleEl) {
  if (!statusEl || !toggleEl) {
    return
  }
  if (!notificationsSupported()) {
    statusEl.textContent = 'Desktop alerts are not supported in this browser.'
    toggleEl.disabled = true
    toggleEl.classList.add('opacity-40', 'cursor-not-allowed')
    return
  }
  toggleEl.disabled = false
  toggleEl.classList.remove('opacity-40', 'cursor-not-allowed')

  const permission = Notification.permission
  const pref = readNotificationPreference(storage)

  if (permission === 'denied') {
    statusEl.textContent = 'Notifications are blocked in browser settings.'
    toggleEl.textContent = 'Enable desktop alerts'
    return
  }

  if (pref === NOTIFICATION_PREF.ENABLED && permission === 'granted') {
    statusEl.textContent = 'Desktop alerts enabled.'
    toggleEl.textContent = 'Disable desktop alerts'
  } else {
    statusEl.textContent = 'Desktop alerts off.'
    toggleEl.textContent = 'Enable desktop alerts'
  }
}

function bindNotificationControls (storage) {
  const statusEl = document.querySelector('[data-notification-status]')
  const toggleEl = document.querySelector('[data-notification-toggle]')
  if (!statusEl || !toggleEl) {
    return () => {}
  }

  const refreshUi = () => updateNotificationControls(storage, statusEl, toggleEl)
  refreshUi()

  toggleEl.addEventListener('click', async () => {
    if (!notificationsSupported()) {
      return
    }

    const pref = readNotificationPreference(storage)
    if (pref === NOTIFICATION_PREF.ENABLED && Notification.permission === 'granted') {
      persistNotificationPreference(storage, NOTIFICATION_PREF.DISABLED)
      refreshUi()
      return
    }

    if (Notification.permission === 'denied') {
      statusEl.textContent = 'Notifications are blocked. Allow them in browser settings to re-enable.'
      return
    }

    if (Notification.permission === 'granted') {
      persistNotificationPreference(storage, NOTIFICATION_PREF.ENABLED)
      refreshUi()
      return
    }

    try {
      const result = await Notification.requestPermission()
      if (result === 'granted') {
        persistNotificationPreference(storage, NOTIFICATION_PREF.ENABLED)
      } else {
        persistNotificationPreference(storage, NOTIFICATION_PREF.DISABLED)
      }
    } catch (error) {
      console.warn('Notification permission request failed', error)
    }

    refreshUi()
  })

  return refreshUi
}

function buildNotificationPayload (orders, capturedAt) {
  const timestampValue = capturedAt ? Date.parse(capturedAt) || Date.now() : Date.now()
  if (!Array.isArray(orders) || orders.length === 0) {
    return {
      title: 'Tesla orders updated',
      body: 'View the history tab for the latest details.',
      timestamp: timestampValue
    }
  }
  if (orders.length > 1) {
    return {
      title: `${orders.length} Tesla orders updated`,
      body: 'Open the history view to review each change.',
      timestamp: timestampValue
    }
  }
  const order = orders[0]
  const parts = []
  if (order.status) {
    parts.push(`Status ${order.status}`)
  }
  if (order.delivery_window) {
    parts.push(order.delivery_window)
  } else if (order.delivery_date) {
    parts.push(order.delivery_date)
  }
  if (order.location) {
    parts.push(order.location)
  }
  return {
    title: `${order.model || 'Order'} - ${order.rn || 'Tesla'}`,
    body: parts.join(' - ') || 'Open the history view for full details.',
    timestamp: timestampValue
  }
}

function maybeSendDesktopNotification (storage, payload, digestMeta) {
  if (!notificationsEnabled(storage)) {
    return
  }
  const digest = digestMeta?.digest || payload?.digest
  if (!digest || storage.getItem(NOTIFICATION_DIGEST_KEY) === digest) {
    return
  }
  try {
    const notificationData = buildNotificationPayload(payload.orders, digestMeta?.capturedAt)
    new Notification(notificationData.title, {
      body: notificationData.body,
      tag: digest,
      timestamp: notificationData.timestamp,
      icon: NOTIFICATION_ICON,
      badge: NOTIFICATION_ICON
    })
    storage.setItem(NOTIFICATION_DIGEST_KEY, digest)
  } catch (error) {
    console.warn('Unable to deliver desktop notification', error)
  }
}

function acknowledgeLatest (storage, updateIndicator) {
  if (!storage) {
    return
  }
  const meta = readDigestMeta(storage)
  if (meta?.digest) {
    storage.setItem(ACK_KEY, meta.digest)
    if (typeof updateIndicator === 'function') {
      updateIndicator()
    }
  }
}

function formatTimestamp (value) {
  if (!value) {
    return 'just now'
  }
  try {
    const date = new Date(value)
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(date)
  } catch (error) {
    return value
  }
}

function updateIndicatorDisplay (indicator, storage) {
  if (!indicator || !storage) {
    return
  }
  const meta = readDigestMeta(storage)
  const ackDigest = storage.getItem(ACK_KEY)
  if (meta?.digest && meta.digest !== ackDigest) {
    indicator.classList.remove('hidden')
    const timeEl = indicator.querySelector('[data-change-time]')
    if (timeEl) {
      timeEl.textContent = formatTimestamp(meta.capturedAt)
    }
  } else {
    indicator.classList.add('hidden')
  }
}

async function pollForUpdates (storage, updateIndicator) {
  if (!storage || pollInFlight) {
    return pollInFlight
  }
  pollInFlight = fetch(POLL_ENDPOINT, {
    headers: {
      Accept: 'application/json'
    },
    cache: 'no-store',
    credentials: 'same-origin'
  })
    .then(async (response) => {
      if (!response.ok) {
        if (response.status === 401) {
          acknowledgeLatest(storage, updateIndicator)
        }
        return
      }
      const payload = await response.json()
      if (!payload?.digest) {
        return
      }
      const result = persistDigestMeta(storage, payload.digest, payload.captured_at)
      if (result.changed && Array.isArray(payload.orders)) {
        appendHistorySnapshot(payload.orders, payload.captured_at)
        maybeSendDesktopNotification(storage, payload, result.meta)
      }
      updateIndicator()
    })
    .catch((error) => {
      console.warn('Order refresh poll failed', error)
    })
    .finally(() => {
      pollInFlight = null
    })

  return pollInFlight
}

export function initChangeWatcher () {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return
  }
  const storage = getStorage()
  if (!storage) {
    return
  }
  const indicator = document.querySelector('[data-change-indicator]')
  if (!indicator) {
    return
  }

  const refreshNotificationControls = bindNotificationControls(storage)

  const dataset = document.body?.dataset || {}
  if (dataset.orderDigest) {
    persistDigestMeta(storage, dataset.orderDigest, dataset.ordersCaptured, { bootstrap: true })
  }

  const indicatorButton = indicator.querySelector('[data-change-link]') || indicator
  const navigateToHistory = () => {
    acknowledgeLatest(storage, () => updateIndicatorDisplay(indicator, storage))
    window.location.href = '/history'
  }
  indicatorButton.addEventListener('click', navigateToHistory)
  indicatorButton.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      navigateToHistory()
    }
  })

  const updateIndicator = () => updateIndicatorDisplay(indicator, storage)
  updateIndicator()

  window.addEventListener('storage', (event) => {
    if (event.key === DIGEST_META_KEY || event.key === ACK_KEY) {
      updateIndicator()
    }
  })

  if (window.location.pathname === '/history') {
    acknowledgeLatest(storage, updateIndicator)
  }

  const intervalAttr = Number(dataset.refreshInterval || DEFAULT_POLL_INTERVAL)
  const interval = Number.isFinite(intervalAttr)
    ? Math.max(intervalAttr, MIN_POLL_INTERVAL)
    : DEFAULT_POLL_INTERVAL

  const schedulePoll = () => {
    pollForUpdates(storage, updateIndicator).finally(() => {
      window.setTimeout(schedulePoll, interval)
    })
  }

  schedulePoll()

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      pollForUpdates(storage, updateIndicator)
      refreshNotificationControls()
    }
  })

  window.addEventListener('focus', refreshNotificationControls)
}
