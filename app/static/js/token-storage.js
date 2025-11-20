const DB_NAME = 'tesla-order-status';
const STORE_NAME = 'secrets';
const TOKEN_KEY = 'bundle';

function openDatabase() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = () => {
            request.result.createObjectStore(STORE_NAME);
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

function transactionDone(tx) {
    return new Promise((resolve, reject) => {
        tx.oncomplete = () => resolve();
        tx.onabort = () => reject(tx.error);
        tx.onerror = () => reject(tx.error);
    });
}

export async function saveBundle(bundle) {
    const db = await openDatabase();
    try {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).put(bundle, TOKEN_KEY);
        await transactionDone(tx);
    } finally {
        db.close();
    }
}

export async function loadBundle() {
    const db = await openDatabase();
    try {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const request = tx.objectStore(STORE_NAME).get(TOKEN_KEY);
        const result = await new Promise((resolve, reject) => {
            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => reject(request.error);
        });
        await transactionDone(tx);
        return result;
    } finally {
        db.close();
    }
}

export async function clearBundle() {
    const db = await openDatabase();
    try {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).delete(TOKEN_KEY);
        await transactionDone(tx);
    } finally {
        db.close();
    }
}
