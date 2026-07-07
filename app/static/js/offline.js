// NoFluff offline logging: an IndexedDB outbox for sets logged without a
// connection, synced to POST /sync/workout when the network returns.
// Loaded before main.js, which calls into window.NoFluffOffline.
(function () {
    'use strict';

    const DB_NAME = 'nofluff-sync';
    const STORE = 'pending_logs';
    const OFFLINE_WORKOUT_KEY = 'nofluffOfflineWorkout';

    // ── IndexedDB micro-helpers ─────────────────────────────────────
    function openDb() {
        return new Promise(function (resolve, reject) {
            const req = indexedDB.open(DB_NAME, 1);
            req.onupgradeneeded = function () {
                req.result.createObjectStore(STORE, { keyPath: 'client_log_id' });
            };
            req.onsuccess = function () { resolve(req.result); };
            req.onerror = function () { reject(req.error); };
        });
    }

    function withStore(mode, fn) {
        return openDb().then(function (db) {
            return new Promise(function (resolve, reject) {
                const tx = db.transaction(STORE, mode);
                const out = fn(tx.objectStore(STORE));
                tx.oncomplete = function () { resolve(out && out.result !== undefined ? out.result : out); };
                tx.onerror = function () { reject(tx.error); };
            });
        });
    }

    function outboxAll() {
        return withStore('readonly', function (store) { return store.getAll(); });
    }

    function outboxPut(item) {
        return withStore('readwrite', function (store) { store.put(item); });
    }

    function outboxDelete(ids) {
        return withStore('readwrite', function (store) {
            ids.forEach(function (id) { store.delete(id); });
        });
    }

    // ── Offline-started workout (localStorage) ──────────────────────
    function getOfflineWorkout() {
        try { return JSON.parse(localStorage.getItem(OFFLINE_WORKOUT_KEY) || 'null'); }
        catch (e) { return null; }
    }
    function setOfflineWorkout(w) {
        try { localStorage.setItem(OFFLINE_WORKOUT_KEY, JSON.stringify(w)); } catch (e) {}
    }
    function clearOfflineWorkout() {
        try { localStorage.removeItem(OFFLINE_WORKOUT_KEY); } catch (e) {}
    }

    function uuid() {
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = (Math.random() * 16) | 0;
            return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
        });
    }

    function serverWorkoutId() {
        const el = document.querySelector('[data-active-workout]');
        return el && el.dataset.activeWorkout ? el.dataset.activeWorkout : null;
    }

    function startOfflineWorkout(routineType) {
        const workout = {
            client_uuid: uuid(),
            routine_type: routineType || 'gym',
            started_at: new Date().toISOString(),
            ended: false,
        };
        setOfflineWorkout(workout);
        showBanner();
        return workout;
    }

    function endOfflineWorkout() {
        const workout = getOfflineWorkout();
        if (!workout) return;
        workout.ended = true;
        setOfflineWorkout(workout);
        showBanner();
    }

    // ── Queueing a set from a log form ──────────────────────────────
    function fieldValues(form, prefix) {
        const out = [];
        for (let i = 1; i <= 10; i++) {
            const el = form.querySelector('[name="' + prefix + i + '"]');
            out.push(el ? el.value.trim() : '');
        }
        return out;
    }

    function queueLog(form) {
        const reps = fieldValues(form, 'reps_set_').filter(function (r) { return r !== ''; });
        if (!reps.length) return Promise.resolve(null);
        const allReps = fieldValues(form, 'reps_set_');
        const allWeights = fieldValues(form, 'weight_set_');
        // Keep weights aligned with the reps that were actually filled in.
        const weights = [];
        allReps.forEach(function (r, i) { if (r !== '') weights.push(allWeights[i] || '0'); });

        const action = form.getAttribute('action') || '';
        const exerciseName = decodeURIComponent(action.split('/').pop() || '');
        const levelEl = form.querySelector('[name=progression_level]');
        const notesEl = form.querySelector('[name=notes]');
        const unitEl = form.querySelector('[name=weight_unit]');
        const offlineWorkout = serverWorkoutId() ? null : getOfflineWorkout();

        const item = {
            client_log_id: uuid(),
            workout_id: serverWorkoutId() ? parseInt(serverWorkoutId(), 10) : null,
            client_uuid: offlineWorkout ? offlineWorkout.client_uuid : null,
            routine_type: form.querySelector('[name=routine]')
                ? form.querySelector('[name=routine]').value
                : 'gym',
            started_at: offlineWorkout ? offlineWorkout.started_at : null,
            exercise_name: exerciseName,
            section: form.querySelector('[name=section]')
                ? form.querySelector('[name=section]').value
                : '',
            reps: reps,
            weights: weights,
            weight_unit: unitEl ? unitEl.value : 'lbs',
            progression_level: levelEl ? parseInt(levelEl.value, 10) : null,
            notes: notesEl ? notesEl.value : '',
            logged_at: new Date().toISOString(),
        };
        if (!item.workout_id && !item.client_uuid) return Promise.resolve(null);
        return outboxPut(item).then(function () {
            updatePill();
            // Background Sync where supported — the page-side 'online' handler
            // is the baseline that works everywhere (including iOS).
            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.ready
                    .then(function (reg) { return reg.sync && reg.sync.register('nofluff-sync'); })
                    .catch(function () {});
            }
            // Connection may already be back (or never left, for an offline-started
            // workout being finished online) — flush right away.
            if (navigator.onLine) setTimeout(syncNow, 0);
            return item;
        });
    }

    // ── Sync ────────────────────────────────────────────────────────
    let syncing = false;

    function groupKey(item) {
        return item.workout_id ? 'w' + item.workout_id : 'c' + item.client_uuid;
    }

    async function syncNow() {
        if (syncing || !navigator.onLine) return;
        syncing = true;
        try {
            const items = await outboxAll();
            const groups = {};
            items.forEach(function (item) {
                (groups[groupKey(item)] = groups[groupKey(item)] || []).push(item);
            });
            for (const key of Object.keys(groups)) {
                const batch = groups[key];
                const first = batch[0];
                const body = {
                    workout_id: first.workout_id || undefined,
                    client_uuid: first.client_uuid || undefined,
                    routine_type: first.routine_type,
                    started_at: first.started_at || undefined,
                    logs: batch,
                };
                let resp;
                try {
                    resp = await fetch('/sync/workout', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        body: JSON.stringify(body),
                    });
                } catch (e) {
                    return; // still offline — try again on the next trigger
                }
                if (resp.status === 401) {
                    updatePill('Log in to sync');
                    return;
                }
                if (!resp.ok) continue;
                const data = await resp.json();
                await outboxDelete(data.accepted || []);
            }
            const workout = getOfflineWorkout();
            if (workout) {
                const left = await outboxAll();
                const stillPending = left.some(function (item) {
                    return item.client_uuid === workout.client_uuid;
                });
                // An ended offline workout whose sets all synced is done.
                if (workout.ended && !stillPending) clearOfflineWorkout();
            }
            updatePill();
            showBanner();
        } finally {
            syncing = false;
        }
    }

    // ── UI: offline banner + pending-sync pill ──────────────────────
    function ensureEl(id, className) {
        let el = document.getElementById(id);
        if (!el) {
            el = document.createElement('div');
            el.id = id;
            el.className = className;
            document.body.appendChild(el);
        }
        return el;
    }

    function showBanner() {
        const workout = getOfflineWorkout();
        const offline = !navigator.onLine;
        const banner = ensureEl('offline-banner', 'offline-banner');
        if (!offline && !workout) {
            banner.hidden = true;
            return;
        }
        banner.hidden = false;
        banner.textContent = '';
        let text;
        if (workout && !workout.ended) {
            text = 'Offline workout in progress — sets are saved on this phone.';
        } else if (workout && workout.ended) {
            text = offline
                ? 'Workout saved offline — it will sync when you’re back online.'
                : 'Syncing your offline workout…';
        } else {
            text = 'You’re offline — sets you log will be saved and synced later.';
        }
        banner.appendChild(document.createTextNode(text));
        if (workout && !workout.ended) {
            // The cached page's nav can't end a device-local workout — offer it here.
            const btn = document.createElement('button');
            btn.id = 'offline-end-btn';
            btn.className = 'offline-end-btn';
            btn.textContent = 'End workout';
            banner.appendChild(btn);
        }
    }

    function updatePill(label) {
        outboxAll().then(function (items) {
            const pill = ensureEl('sync-pill', 'sync-pill');
            if (!items.length) {
                pill.hidden = true;
                return;
            }
            pill.hidden = false;
            pill.textContent = label
                ? '⇪ ' + label + ' (' + items.length + ')'
                : '⇪ ' + items.length + (items.length === 1 ? ' set' : ' sets') + ' to sync';
        }).catch(function () {});
    }

    function pendingCount() {
        return outboxAll().then(function (items) { return items.length; });
    }

    // ── Wiring ──────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        showBanner();
        updatePill();
        if (navigator.onLine) syncNow();

        document.addEventListener('click', function (e) {
            if (e.target.closest('#sync-pill')) syncNow();
            if (e.target.closest('#offline-end-btn')) {
                endOfflineWorkout();
                if (navigator.onLine) syncNow();
            }
        });
    });
    window.addEventListener('online', function () {
        showBanner();
        syncNow();
    });
    window.addEventListener('offline', showBanner);
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.addEventListener('message', function (e) {
            if (e.data && e.data.type === 'do-sync') syncNow();
        });
    }

    window.NoFluffOffline = {
        queueLog: queueLog,
        syncNow: syncNow,
        getOfflineWorkout: getOfflineWorkout,
        startOfflineWorkout: startOfflineWorkout,
        endOfflineWorkout: endOfflineWorkout,
        serverWorkoutId: serverWorkoutId,
        pendingCount: pendingCount,
        clearAll: function () {
            clearOfflineWorkout();
            return withStore('readwrite', function (store) { store.clear(); });
        },
    };
})();
