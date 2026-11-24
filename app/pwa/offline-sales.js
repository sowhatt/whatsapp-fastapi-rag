(() => {
  'use strict';

  const DB_NAME = 'whatzabi-offline';
  const DB_VERSION = 1;
  const STORE = 'pending_sales';

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(
        DB_NAME,
        DB_VERSION
      );

      request.onupgradeneeded = () => {
        const db = request.result;

        if (!db.objectStoreNames.contains(STORE)) {
          const store = db.createObjectStore(
            STORE,
            {
              keyPath: 'offline_sale_id',
            }
          );

          store.createIndex(
            'status',
            'status',
            { unique: false }
          );

          store.createIndex(
            'merchant_id',
            'merchant_id',
            { unique: false }
          );

          store.createIndex(
            'shop_id',
            'shop_id',
            { unique: false }
          );
        }
      };

      request.onsuccess = () => {
        resolve(request.result);
      };

      request.onerror = () => {
        reject(request.error);
      };
    });
  }


  function uuid() {
    if (
      window.crypto &&
      typeof window.crypto.randomUUID === 'function'
    ) {
      return window.crypto.randomUUID();
    }

    const bytes = new Uint8Array(16);

    if (
      window.crypto &&
      typeof window.crypto.getRandomValues === 'function'
    ) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (let index = 0; index < bytes.length; index += 1) {
        bytes[index] =
          Math.floor(Math.random() * 256);
      }
    }

    bytes[6] =
      (bytes[6] & 0x0f) | 0x40;

    bytes[8] =
      (bytes[8] & 0x3f) | 0x80;

    const hex = [...bytes]
      .map((value) =>
        value.toString(16).padStart(2, '0')
      );

    return (
      hex.slice(0, 4).join('') +
      '-' +
      hex.slice(4, 6).join('') +
      '-' +
      hex.slice(6, 8).join('') +
      '-' +
      hex.slice(8, 10).join('') +
      '-' +
      hex.slice(10, 16).join('')
    );
  }


  async function put(record) {
    const db = await openDb();

    return new Promise((resolve, reject) => {
      const transaction = db.transaction(
        STORE,
        'readwrite'
      );

      transaction.objectStore(STORE).put(
        record
      );

      transaction.oncomplete = () => {
        db.close();
        resolve(record);
      };

      transaction.onerror = () => {
        const error = transaction.error;
        db.close();
        reject(error);
      };

      transaction.onabort = () => {
        const error = transaction.error;
        db.close();
        reject(error);
      };
    });
  }


  async function remove(offlineSaleId) {
    const db = await openDb();

    return new Promise((resolve, reject) => {
      const transaction = db.transaction(
        STORE,
        'readwrite'
      );

      transaction.objectStore(STORE).delete(
        offlineSaleId
      );

      transaction.oncomplete = () => {
        db.close();
        resolve();
      };

      transaction.onerror = () => {
        const error = transaction.error;
        db.close();
        reject(error);
      };
    });
  }


  async function all() {
    const db = await openDb();

    return new Promise((resolve, reject) => {
      const transaction = db.transaction(
        STORE,
        'readonly'
      );

      const request =
        transaction.objectStore(STORE).getAll();

      request.onsuccess = () => {
        resolve(request.result || []);
      };

      request.onerror = () => {
        reject(request.error);
      };

      transaction.oncomplete = () => {
        db.close();
      };
    });
  }


  function notify(type, detail = {}) {
    window.dispatchEvent(
      new CustomEvent(
        'whatzabi:offline-sales-changed',
        {
          detail: {
            type,
            ...detail,
          },
        }
      )
    );
  }


  async function summary(merchantId = null) {
    const rows = await all();

    const merchantRows = merchantId
      ? rows.filter(
          (row) =>
            Number(row.merchant_id) ===
            Number(merchantId)
        )
      : rows;

    return {
      total: merchantRows.length,
      pending: merchantRows.filter(
        (row) => row.status === 'pending'
      ).length,
      conflict: merchantRows.filter(
        (row) => row.status === 'conflict'
      ).length,
      blocked: merchantRows.filter(
        (row) => row.status === 'blocked'
      ).length,
    };
  }


  async function enqueue({
    offline_sale_id,
    merchant_id,
    shop_id,
    payload,
  }) {
    if (!offline_sale_id) {
      throw new Error(
        'offline_sale_id requis'
      );
    }

    if (!merchant_id) {
      throw new Error(
        'merchant_id requis pour une vente hors ligne'
      );
    }

    if (!shop_id) {
      throw new Error(
        'shop_id requis pour une vente hors ligne'
      );
    }

    const now = new Date().toISOString();

    const record = {
      offline_sale_id,
      merchant_id: Number(merchant_id),
      shop_id: Number(shop_id),
      payload,
      status: 'pending',
      retry_count: 0,
      last_error: null,
      created_at: now,
      updated_at: now,
    };

    await put(record);

    notify('queued', {
      offline_sale_id,
      merchant_id: Number(merchant_id),
      shop_id: Number(shop_id),
    });

    return record;
  }


  function errorMessage(error) {
    if (!error) return 'Erreur inconnue';

    if (typeof error.message === 'string') {
      return error.message;
    }

    return String(error);
  }


  async function mark(
    record,
    status,
    error = null
  ) {
    const updated = {
      ...record,
      status,
      retry_count:
        Number(record.retry_count || 0) + 1,
      last_error:
        error ? errorMessage(error) : null,
      updated_at:
        new Date().toISOString(),
    };

    await put(updated);

    notify('status-changed', {
      offline_sale_id:
        record.offline_sale_id,
      status,
    });

    return updated;
  }


  async function syncRecord(record) {
    const currentMerchantId =
      Number(state?.merchant?.id || 0);

    if (
      !currentMerchantId ||
      currentMerchantId !==
        Number(record.merchant_id)
    ) {
      return {
        status: 'skipped',
        reason: 'merchant_mismatch',
      };
    }

    try {
      const sale = await api(
        '/pwa/sales/offline-sync',
        {
          method: 'POST',
          body: JSON.stringify({
            shop_id: record.shop_id,
            sale: record.payload,
          }),
        }
      );

      await remove(
        record.offline_sale_id
      );

      return {
        status: 'synced',
        sale,
      };
    } catch (error) {
      const status =
        Number(error?.status || 0);

      if (
        status === 400 ||
        status === 409 ||
        status === 422
      ) {
        await mark(
          record,
          'conflict',
          error
        );

        return {
          status: 'conflict',
          error,
        };
      }

      if (status === 403) {
        await mark(
          record,
          'blocked',
          error
        );

        return {
          status: 'blocked',
          error,
        };
      }

      if (status === 401) {
        await mark(
          record,
          'pending',
          error
        );

        return {
          status: 'auth_required',
          error,
        };
      }

      /*
       * 5xx ou nouvelle panne réseau :
       * la vente reste dans la file.
       */
      await mark(
        record,
        'pending',
        error
      );

      return {
        status: 'pending',
        error,
      };
    }
  }


  let syncRunning = false;


  async function sync() {
    if (syncRunning) {
      return {
        running: true,
      };
    }

    if (!navigator.onLine) {
      return {
        offline: true,
      };
    }

    if (!token) {
      return {
        authenticated: false,
      };
    }

    syncRunning = true;

    const result = {
      synced: 0,
      conflicts: 0,
      blocked: 0,
      pending: 0,
      skipped: 0,
    };

    try {
      const rows = await all();

      const pendingRows = rows.filter(
        (row) =>
          row.status === 'pending' ||
          row.status === 'conflict' ||
          row.status === 'blocked'
      );

      for (const row of pendingRows) {
        /*
         * Les conflits et blocages ne sont pas
         * rejoués automatiquement à l'infini.
         */
        if (
          row.status === 'conflict' ||
          row.status === 'blocked'
        ) {
          continue;
        }

        const response =
          await syncRecord(row);

        if (response.status === 'synced') {
          result.synced += 1;
        } else if (
          response.status === 'conflict'
        ) {
          result.conflicts += 1;
        } else if (
          response.status === 'blocked'
        ) {
          result.blocked += 1;
        } else if (
          response.status === 'skipped'
        ) {
          result.skipped += 1;
        } else {
          result.pending += 1;
        }

        if (
          response.status ===
          'auth_required'
        ) {
          break;
        }
      }

      notify('sync-complete', {
        result,
      });

      return result;
    } finally {
      syncRunning = false;
    }
  }


  async function pendingCount() {
    const rows = await all();

    return rows.filter(
      (row) =>
        row.status === 'pending'
    ).length;
  }


  window.WhatzabiOfflineSales = {
    uuid,
    enqueue,
    sync,
    all,
    summary,
    pendingCount,
  };
})();
