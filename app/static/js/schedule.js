// Rotation drag-sort + calendar planning. Server data (routine list) arrives
// via the #schedule-data JSON block.
(function () {
    'use strict';

    const dataEl = document.getElementById('schedule-data');
    if (!dataEl) return;
    const routines = JSON.parse(dataEl.textContent).routines || [];
    const labelFor = (key) => (routines.find((r) => r.key === key) || {}).label || key;

    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const CSRF = csrfMeta ? csrfMeta.content : '';

    // ── Shared JSON fetch with error signalling ──
    async function fetchJSON(url, options) {
        try {
            const res = await fetch(url, options);
            const data = res.ok ? await res.json().catch(() => ({})) : null;
            return { ok: res.ok, data };
        } catch (_e) {
            return { ok: false, data: null };
        }
    }

    function toast(message) {
        const el = document.createElement('div');
        el.className = 'toast toast-error';
        el.textContent = message;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3000);
    }

    // ── Rotation drag-sort ──
    const list = document.getElementById('rotationList');
    let dragSrc = null;

    list.addEventListener('dragstart', (e) => {
        dragSrc = e.target.closest('.rotation-item');
        if (dragSrc) dragSrc.classList.add('dragging');
    });
    list.addEventListener('dragover', (e) => {
        e.preventDefault();
        const target = e.target.closest('.rotation-item');
        if (target && target !== dragSrc) {
            const rect = target.getBoundingClientRect();
            const after = e.clientY > rect.top + rect.height / 2;
            list.insertBefore(dragSrc, after ? target.nextSibling : target);
        }
    });
    list.addEventListener('dragend', () => {
        if (dragSrc) dragSrc.classList.remove('dragging');
        dragSrc = null;
    });

    list.addEventListener('click', (e) => {
        const btn = e.target.closest('.rotation-remove-btn');
        if (!btn) return;
        const item = btn.closest('.rotation-item');
        if (item) item.remove();
        if (!list.querySelector('.rotation-item')) {
            const empty = document.createElement('li');
            empty.className = 'rotation-empty';
            empty.id = 'rotationEmpty';
            empty.textContent = 'No rotation set — add routines below.';
            list.appendChild(empty);
        }
    });

    document.getElementById('rotationAddBtn').addEventListener('click', () => {
        const sel = document.getElementById('rotationAddSelect');
        const key = sel.value;
        const label = sel.options[sel.selectedIndex].text;
        if (!key) return;
        if (list.querySelector(`.rotation-item[data-routine="${key}"]`)) {
            sel.value = '';
            return;
        }
        const empty = document.getElementById('rotationEmpty');
        if (empty) empty.remove();

        const li = document.createElement('li');
        li.className = 'rotation-item';
        li.draggable = true;
        li.dataset.routine = key;
        li.innerHTML =
            `<span class="drag-handle" aria-hidden="true">⠿</span>` +
            `<span class="rotation-label">${label}</span>` +
            `<button type="button" class="rotation-remove-btn" data-routine="${key}" ` +
            `aria-label="Remove ${label} from rotation" title="Remove from rotation">×</button>`;
        list.appendChild(li);
        sel.value = '';
    });

    document.getElementById('saveRotationBtn').addEventListener('click', async () => {
        const items = [...list.querySelectorAll('.rotation-item')].map((el) => el.dataset.routine);
        const status = document.getElementById('rotationSaveStatus');
        status.textContent = 'Saving…';
        const { ok } = await fetchJSON('/schedule/rotation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({ rotation: items }),
        });
        status.textContent = ok ? 'Saved!' : 'Error saving.';
        if (!ok) toast('Could not save your rotation. Please try again.');
        setTimeout(() => { status.textContent = ''; }, 2500);
    });

    // ── Calendar popover ──
    const popover = document.getElementById('calPopover');
    let activeDayEl = null;

    function updateDayDisplay(dayEl, routineType, scheduleId) {
        dayEl.dataset.routine = routineType || '';
        dayEl.dataset.scheduleId = scheduleId || '';
        const span = dayEl.querySelector('.cal-day-routine');
        span.innerHTML = routineType
            ? `<span class="cal-routine-badge">${labelFor(routineType)}</span>`
            : '';
    }

    document.querySelectorAll('.cal-day').forEach((day) => {
        day.addEventListener('click', () => {
            if (activeDayEl === day && !popover.hidden) {
                popover.hidden = true;
                activeDayEl = null;
                return;
            }
            activeDayEl = day;
            document.getElementById('calPopoverDate').textContent = day.dataset.date;
            const rect = day.getBoundingClientRect();
            popover.hidden = false;
            popover.style.top = rect.bottom + window.scrollY + 6 + 'px';
            popover.style.left =
                Math.min(rect.left + window.scrollX, window.innerWidth - popover.offsetWidth - 12) + 'px';
        });
    });

    document.addEventListener('click', (e) => {
        if (!popover.hidden && !popover.contains(e.target) && !e.target.closest('.cal-day')) {
            popover.hidden = true;
            activeDayEl = null;
        }
    });

    document.getElementById('calPickerList').addEventListener('click', async (e) => {
        const btn = e.target.closest('.cal-picker-btn');
        if (!btn || !activeDayEl) return;
        const routineType = btn.dataset.routine;
        const dateStr = activeDayEl.dataset.date;
        const scheduleId = activeDayEl.dataset.scheduleId;

        if (!routineType) {
            if (scheduleId) {
                const { ok } = await fetchJSON(`/schedule/plan/${scheduleId}`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': CSRF },
                });
                if (ok) updateDayDisplay(activeDayEl, '', '');
                else toast('Could not clear that day. Please try again.');
            }
        } else {
            const { ok, data } = await fetchJSON('/schedule/plan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                body: JSON.stringify({ date: dateStr, routine_type: routineType }),
            });
            if (ok && data) updateDayDisplay(activeDayEl, routineType, data.id);
            else toast('Could not save that day. Please try again.');
        }
        popover.hidden = true;
        activeDayEl = null;
    });
})();

// ── Calendar feed: copy link ─────────────────────────────────────
document.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-copy-target]');
    if (!btn) return;
    const input = document.getElementById(btn.dataset.copyTarget);
    if (!input) return;
    input.select();
    const original = btn.textContent;
    const done = function () {
        btn.textContent = 'Copied ✓';
        setTimeout(function () { btn.textContent = original; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(done).catch(function () {});
    } else {
        try { document.execCommand('copy'); done(); } catch (err) {}
    }
});
