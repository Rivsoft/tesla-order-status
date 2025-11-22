import { registerServiceWorker } from './sw-register.js'
import { initChangeWatcher } from './change-watcher.js'

registerServiceWorker()
initChangeWatcher()
