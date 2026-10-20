/**
 * Tests for the self-healing IDB store backing the credentials catalogue
 * warm-start cache (client/src/lib/idbStore.ts).
 *
 * The production incident (2026-10-20): idb-keyval's default store opens
 * its database without a version, so the upgrade that creates the `keyval`
 * object store never runs when a `keyval-store` database already exists
 * without it — every transaction then throws
 * `IDBDatabase.transaction: 'keyval' is not a known object store name`
 * forever (the connection promise is cached). The fake IDB here recreates
 * that poisoned state and asserts the wrapper heals it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The wrapper caches its connection at module scope (`dbp`), so every test
// gets a fresh module instance via resetModules + dynamic import.
type Store = typeof import('../idbStore');
let store: Store;

const DB_NAME = 'opencompany-catalogue';

// ---------------------------------------------------------------------------
// Minimal fake IndexedDB: just enough surface (open without version,
// deleteDatabase, transactions on a single object store) to exercise the
// wrapper's happy path and both recovery paths. Handlers are dispatched
// asynchronously (setTimeout 0) because the real IDBRequest fires events
// after the caller attaches them.
// ---------------------------------------------------------------------------

interface FakeDb {
  version: number;
  stores: Map<string, Map<string, unknown>>;
  connections: FakeIDBDatabase[];
}

class FakeIDBDatabase {
  objectStoreNames: { contains: (name: string) => boolean };
  /** Public so transactions can re-check store existence mid-session. */
  stores: Map<string, Map<string, unknown>>;
  onversionchange: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(private database: FakeDb) {
    this.stores = database.stores;
    this.objectStoreNames = {
      contains: (name: string) => database.stores.has(name),
    };
  }

  createObjectStore(name: string): void {
    this.database.stores.set(name, new Map());
  }

  transaction(name: string, _mode: IDBTransactionMode): FakeIDBTransaction {
    if (this.closed || !this.database.stores.has(name)) {
      throw new DOMException(`IDBDatabase.transaction: '${name}' is not a known object store name`, 'NotFoundError');
    }
    return new FakeIDBTransaction(this.database.stores.get(name)!, this);
  }

  close(): void {
    this.closed = true;
    const index = this.database.connections.indexOf(this);
    if (index >= 0) this.database.connections.splice(index, 1);
    this.onclose?.();
  }
}

class FakeIDBTransaction {
  constructor(private store: Map<string, unknown>, private db: FakeIDBDatabase) {}

  objectStore(name: string): FakeIDBObjectStore {
    if (!this.db.stores.has(name)) {
      throw new DOMException(`IDBDatabase.transaction: '${name}' is not a known object store name`, 'NotFoundError');
    }
    return new FakeIDBObjectStore(this.store);
  }
}

class FakeIDBObjectStore {
  constructor(private store: Map<string, unknown>) {}

  get(key: string): FakeIDBRequest {
    return makeRequest(() => this.store.get(key));
  }

  put(value: unknown, key: string): FakeIDBRequest {
    return makeRequest(() => {
      this.store.set(key, value);
      return undefined;
    });
  }
}

class FakeIDBRequest {
  onsuccess: (() => void) | null = null;
  onerror: (() => void) | null = null;
  error: DOMException | null = null;
  result: unknown = undefined;

  constructor(compute: () => unknown) {
    setTimeout(() => {
      try {
        this.result = compute();
        this.onsuccess?.();
      } catch (err) {
        this.error = err as DOMException;
        this.onerror?.();
      }
    }, 0);
  }
}

function makeRequest(compute: () => unknown): FakeIDBRequest {
  return new FakeIDBRequest(compute);
}

/** Open without a version — same semantics that make idb-keyval fragile:
 *  an existing database opens at its current version with NO upgrade. */
function fakeOpen(name: string): FakeIDBOpenRequest {
  return new FakeIDBOpenRequest(name);
}

class FakeIDBOpenRequest {
  onupgradeneeded: (() => void) | null = null;
  onsuccess: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onblocked: (() => void) | null = null;
  error: DOMException | null = null;
  result: FakeIDBDatabase | null = null;

  constructor(name: string) {
    setTimeout(() => {
      const existing = fakeIDB.databases.get(name);
      if (!existing) {
        const fresh: FakeDb = { version: 1, stores: new Map(), connections: [] };
        fakeIDB.databases.set(name, fresh);
        const db = new FakeIDBDatabase(fresh);
        fresh.connections.push(db);
        this.result = db;
        this.onupgradeneeded?.();
        this.onsuccess?.();
        return;
      }
      // Existing database: open at the current version, no upgrade event.
      const db = new FakeIDBDatabase(existing);
      existing.connections.push(db);
      this.result = db;
      this.onsuccess?.();
    }, 0);
  }
}

const fakeIDB = {
  databases: new Map<string, FakeDb>(),
  open(name: string): FakeIDBOpenRequest {
    return fakeOpen(name);
  },
  deleteDatabase(name: string): FakeIDBDeleteRequest {
    return new FakeIDBDeleteRequest(name);
  },
};

class FakeIDBDeleteRequest {
  onsuccess: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onblocked: (() => void) | null = null;
  error: DOMException | null = null;

  constructor(name: string) {
    setTimeout(() => {
      const existing = fakeIDB.databases.get(name);
      if (existing) {
        // Connections with an onversionchange handler close (that is the
        // real spec behaviour); a delete blocked by a handlerless
        // connection is NOT modelled — the wrapper always installs one.
        for (const conn of [...existing.connections]) {
          conn.onversionchange?.();
        }
        fakeIDB.databases.delete(name);
      }
      this.onsuccess?.();
    }, 0);
  }
}

// ---------------------------------------------------------------------------
// The tests
// ---------------------------------------------------------------------------

beforeEach(async () => {
  fakeIDB.databases.clear();
  vi.stubGlobal('indexedDB', fakeIDB as unknown as IDBFactory);
  vi.resetModules();
  store = await import('../idbStore');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('idbStore', () => {
  it('round-trips a value on a healthy database', async () => {
    await store.set('k', { a: 1 });
    await expect(store.get('k')).resolves.toEqual({ a: 1 });
    await expect(store.get('missing')).resolves.toBeUndefined();
  });

  it('heals a database that exists WITHOUT the object store (the production incident)', async () => {
    // Poison: the shell exists at version 1 with no `catalogue` store —
    // exactly the state that made idb-keyval fail forever.
    fakeIDB.databases.set(DB_NAME, { version: 1, stores: new Map(), connections: [] });

    // First read triggers recovery: delete + reopen (upgrade recreates
    // the store) — and resolves to a miss, not an error.
    await expect(store.get('k')).resolves.toBeUndefined();

    // The database now has the store and accepts writes.
    await store.set('k', 'v1');
    await expect(store.get('k')).resolves.toBe('v1');
  });

  it('heals mid-session when the store vanishes under an open connection', async () => {
    await store.set('k', 'v1');
    await expect(store.get('k')).resolves.toBe('v1');

    // Simulate the environment dropping the object store but keeping the
    // shell: wipe the store registration itself, while the wrapper still
    // holds its cached connection.
    const db = fakeIDB.databases.get(DB_NAME)!;
    db.stores.clear();

    await expect(store.get('k')).resolves.toBeUndefined(); // healed, empty
    await store.set('k', 'v2');
    await expect(store.get('k')).resolves.toBe('v2');
  });

  it('surfaces non-recoverable errors to the caller (graceful degradation)', async () => {
    // Fresh module AFTER stubbing indexedDB away, so no cached connection
    // from a previous test can serve the request.
    vi.resetModules();
    store = await import('../idbStore');
    vi.stubGlobal('indexedDB', undefined);
    // The caller (useCatalogueQuery) catches and warns — the contract is
    // a throw, not a hang and not a silent swallow.
    await expect(store.get('k')).rejects.toThrow(/indexedDB is not available/);
    await expect(store.set('k', 1)).rejects.toThrow(/indexedDB is not available/);
  });
});
