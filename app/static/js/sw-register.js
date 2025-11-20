let registrationPromise;
const WORKER_URL = '/sw.js';

export async function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) {
        return null;
    }
    if (registrationPromise) {
        return registrationPromise;
    }

    registrationPromise = navigator.serviceWorker
        .register(WORKER_URL, { type: 'module' })
        .then(async (registration) => {
            await navigator.serviceWorker.ready;
            return registration;
        })
        .catch((error) => {
            console.warn('Service worker registration failed', error);
            return null;
        });

    return registrationPromise;
}
