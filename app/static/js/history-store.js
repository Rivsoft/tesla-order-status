const HISTORY_KEY = 'teslaOrderHistory'
const MAX_HISTORY_ENTRIES = 40

function getStorage () {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const storage = window.localStorage
    const testKey = '__tesla_history_test__'
    storage.setItem(testKey, '1')
    storage.removeItem(testKey)
    return storage
  } catch (error) {
    console.warn('LocalStorage unavailable', error)
    return null
  }
}

export function readHistoryEntries () {
  const storage = getStorage()
  if (!storage) {
    return []
  }
  try {
    return JSON.parse(storage.getItem(HISTORY_KEY)) || []
  } catch (error) {
    console.warn('Unable to parse stored history snapshot', error)
    return []
  }
}

export function writeHistoryEntries (entries) {
  const storage = getStorage()
  if (!storage) {
    return
  }
  try {
    storage.setItem(HISTORY_KEY, JSON.stringify(entries))
  } catch (error) {
    console.warn('Unable to persist history snapshot', error)
  }
}

export function clearHistoryEntries () {
  const storage = getStorage()
  if (!storage) {
    return
  }
  storage.removeItem(HISTORY_KEY)
}

export function appendHistorySnapshot (orders, timestamp = new Date().toISOString()) {
  if (!Array.isArray(orders) || !orders.length) {
    return false
  }
  const history = readHistoryEntries().filter(Boolean)
  const normalizedOrders = JSON.parse(JSON.stringify(orders))
  const lastEntry = history[history.length - 1]
  const lastOrdersJson = lastEntry ? JSON.stringify(lastEntry.orders) : null
  const currentOrdersJson = JSON.stringify(normalizedOrders)

  if (lastOrdersJson === currentOrdersJson) {
    return false
  }

  history.push({ timestamp, orders: normalizedOrders })
  if (history.length > MAX_HISTORY_ENTRIES) {
    history.splice(0, history.length - MAX_HISTORY_ENTRIES)
  }
  writeHistoryEntries(history)
  return true
}

export { HISTORY_KEY, MAX_HISTORY_ENTRIES }
