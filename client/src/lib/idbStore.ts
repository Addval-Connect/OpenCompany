/**
 * Self-healing IndexedDB key-value store.
 *
 * Why this exists instead of `idb-keyval`'s default store: the library
 * opens the database WITHOUT a version (`indexedDB.open(dbName)`), so the
 * upgrade callback that creates the object store only runs when the
 * database does not exist yet. If a `keyval-store` database is left at
 * version 1 WITHOUT the `keyval` object store — an interrupted first
 * upgrade, a same-origin neighbour that created the name for different
 * stores, or a WebKit upgrade race — every transaction throws
 * `IDBDatabase.transaction: 'keyval' is not a known object store name`,
 * and because the library caches its connection promise forever, every
 * subsequent get/set keeps failing for the lifetime of the tab: the
 * warm-start cache is permanently dead and the console fills with
 * warnings (2026-10-20, workers.bluedoc-ai.com, "cuando creo un nuevo
 * workflow").
 *
 * This wrapper fixes both halves of that failure:
 *
 *   1. **Namespaced DB + store** (`opencompany-catalogue` / `catalogue`)
 *      so a poisoned shared `keyval-store` can never reach this code.
 *   2. **Self-healing**: the open verifies the object store actually
 *      exists; when it does not (or when a transaction hits the same
 *      missing-store signature mid-session), the stale connection is
 *      dropped, the database is deleted and the operation retried once —
 *      the fresh open runs the upgrade, recreates the store, and the
 *      cache resumes. `onversionchange → close()` on every connection
 *      keeps the delete from being blocked by our own handle (or another
 *      tab running this same bundle).
 *
 * Callers keep idb-keyval's contract: `get` resolves `undefined` on a
 * miss and any thrown error is the caller's cue to degrade gracefully.
 */

const DB_NAME = 'opencompany-catalogue';
const STORE_NAME = 'catalogue';
/** Upper bound on the deleteDatabase leg of a recovery — if another tab
 *  holds a connection that refuses to close, we would rather retry (and
 *  likely fail, degrading in the caller) than hang the write forever. */
const DELETE_TIMEOUT_MS = 1500;

let dbp: Promise<IDBDatabase> | null = null;

function isMissingStoreError(err: unknown): boolean {
  // Chrome: DOMException with that exact message; Firefox: NotFoundError
  // "One of the specified object stores was not found". Match both.
  const message = err instanceof Error ? err.message : String(err);
  const name = err instanceof DOMException ? err.name : '';
  return (
    /is not a known object store/i.test(message) ||
    (name === 'NotFoundError' && /object store/i.test(message))
  );
}

function rawOpen(): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') {
    // SSR / jsdom — the caller's try/catch degrades exactly like the
    // idb-keyval import did before.
    return Promise.reject(new TypeError('indexedDB is not available in this environment'));
  }
  return new Promise((resolve, reject) => {
    // No version argument — same semantics as idb-keyval: open at the
    // current version, upgrade only on create. The store-existence check
    // after open is what makes a poisoned database recoverable.
    const request = indexedDB.open(DB_NAME);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => {
      const db = request.result;
      // Unblock deleteDatabase / version upgrades issued by another tab
      // of this bundle: an open connection without this handler blocks
      // them until the tab closes.
      db.onversionchange = () => {
        db.close();
        if (dbp) {
          dbp = null;
        }
      };
      db.onclose = () => {
        dbp = null;
      };
      resolve(db);
    };
    request.onerror = () => reject(request.error ?? new Error(`indexedDB.open(${DB_NAME}) failed`));
    request.onblocked = () => reject(new Error(`indexedDB.open(${DB_NAME}) blocked by another connection`));
  });
}

/** Open and verify. A database that exists without the store is treated
 *  as corruption: delete + reopen once (the fresh create runs the
 *  upgrade). `recovered` guards against healing loops on a hostile
 *  environment where the delete itself is a no-op. */
async function openVerified(recovered = false): Promise<IDBDatabase> {
  const db = await rawOpen();
  if (db.objectStoreNames.contains(STORE_NAME)) {
    return db;
  }
  db.close();
  dbp = null;
  if (recovered) {
    throw new Error(`indexedDB ${DB_NAME} persists without the ${STORE_NAME} store after recovery`);
  }
  await deleteDatabase();
  return openVerified(true);
}

function openDb(): Promise<IDBDatabase> {
  if (!dbp) {
    dbp = openVerified().catch((err) => {
      dbp = null;
      throw err;
    });
  }
  return dbp;
}

function deleteDatabase(): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (!settled) {
        settled = true;
        resolve();
      }
    };
    // The delete is best-effort: a block we cannot clear (a tab running
    // a stale bundle without the onversionchange handler) must not hang
    // the recovery path — proceed to the retry after the timeout.
    const timer = setTimeout(done, DELETE_TIMEOUT_MS);
    try {
      const request = indexedDB.deleteDatabase(DB_NAME);
      request.onsuccess = () => {
        clearTimeout(timer);
        done();
      };
      request.onerror = () => {
        clearTimeout(timer);
        done();
      };
      request.onblocked = () => {
        // Another connection is still open; ours already closed itself
        // via onversionchange. Keep waiting up to the timeout, then go.
      };
    } catch {
      clearTimeout(timer);
      done();
    }
  });
}

async function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, mode);
  return promisifyRequest(run(tx.objectStore(STORE_NAME)));
}

function promisifyRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IDBRequest failed'));
  });
}

async function withRecovery<T>(op: () => Promise<T>): Promise<T> {
  try {
    return await op();
  } catch (err) {
    if (!isMissingStoreError(err)) {
      throw err;
    }
    // The store vanished under an open connection (environment cleaned
    // the object store but kept the shell, or a race we did not cover).
    // Drop the cached connection, delete the shell, retry once.
    dbp = null;
    await deleteDatabase();
    return op();
  }
}

/** Read a key. Resolves `undefined` when absent — identical to
 *  `idb-keyval`'s `get`. Recovers transparently from a missing store. */
export async function get<T = unknown>(key: string): Promise<T | undefined> {
  return withRecovery(() => withStore<T>('readonly', (store) => store.get(key) as IDBRequest<T>));
}

/** Write a key — identical to `idb-keyval`'s `set`. Recovers
 *  transparently from a missing store. */
export async function set(key: string, value: unknown): Promise<void> {
  await withRecovery(() => withStore('readwrite', (store) => store.put(value, key) as IDBRequest<unknown>));
}
