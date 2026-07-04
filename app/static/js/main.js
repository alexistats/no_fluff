document.addEventListener('DOMContentLoaded', function () {
    'use strict';

    // ── Shared helpers ─────────────────────────────────────────────
    function mkEl(tag, cls) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        return e;
    }
    function fmtW(w) { return (Math.round(w * 100) / 100).toString(); }
    function pad2(n) { return String(n).padStart(2, '0'); }

    // ── Constants ──────────────────────────────────────────────────
    const LBS_PER_KG = 2.20462;
    const PLATE_LBS  = [45, 35, 25, 10, 5, 2.5];
    const PLATE_KG   = [20, 15, 10, 5, 2.5, 1.25];
    const BAR_LBS    = [45, 35, 25];   // standard / women's / technique
    const BAR_KG     = [20, 15, 10];
    const DB_LBS = [5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80];
    const DB_KG  = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 35, 37.5, 40];
    const PLATE_COLORS = ['#c0392b', '#2962a8', '#f1c40f', '#27ae60', '#7f8c8d', '#bdc3c7'];
    // Equipment icons come from the Jinja equipment_icon macro (single source),
    // emitted as a JSON block in base.html.
    const eqIconsEl = document.getElementById('eq-icons');
    const EQ_ICONS = eqIconsEl ? JSON.parse(eqIconsEl.textContent) : {};

    // ── Theme toggle ───────────────────────────────────────────────
    // The current theme is applied to <html> before first paint (see base.html)
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', function () {
            const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        });
    }

    // ── Service worker (PWA) ───────────────────────────────────────
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function () {
            navigator.serviceWorker.register('/sw.js').catch(function () {});
        });
    }

    // ── Log-form drafts (survive a dropped connection / reload) ─────
    function draftKey(form) {
        return 'draft:' + form.getAttribute('action');
    }
    function saveDraft(form) {
        const data = {};
        form.querySelectorAll('input, textarea, select').forEach(function (el) {
            if (!el.name || el.name === 'csrf_token' || el.type === 'submit') return;
            data[el.name] = el.value;
        });
        try { localStorage.setItem(draftKey(form), JSON.stringify(data)); } catch (e) {}
    }
    function restoreDraft(form) {
        let data;
        try { data = JSON.parse(localStorage.getItem(draftKey(form)) || 'null'); } catch (e) { return; }
        if (!data) return;
        // A draft only exists because the user typed and didn't submit, so it
        // reflects their latest intent — restore it over any prefilled default.
        Object.keys(data).forEach(function (name) {
            const el = form.querySelector('[name="' + (window.CSS ? CSS.escape(name) : name) + '"]');
            if (el && data[name] !== '') el.value = data[name];
        });
    }
    function clearDraft(form) {
        try { localStorage.removeItem(draftKey(form)); } catch (e) {}
    }
    document.querySelectorAll('.exercise-log-form').forEach(restoreDraft);
    document.addEventListener('input', function (e) {
        const form = e.target.closest('.exercise-log-form');
        if (form) saveDraft(form);
    });

    // ── Unit state ─────────────────────────────────────────────────
    let currentUnit = localStorage.getItem('weightUnit') || 'lbs';

    function curPlates()  { return currentUnit === 'kg' ? PLATE_KG  : PLATE_LBS; }
    function curBarOpts() { return currentUnit === 'kg' ? BAR_KG    : BAR_LBS;   }
    function curDbSteps() { return currentUnit === 'kg' ? DB_KG     : DB_LBS;    }

    // ── Card accordion ─────────────────────────────────────────────
    let openCardId = null;

    document.addEventListener('click', function (e) {
        if (e.target.closest('.remove-exercise-form')) return;
        const header = e.target.closest('.exercise-card-header');
        if (!header) return;
        if (header.dataset.card) toggleCard(header.dataset.card);
        else if (header.dataset.href) window.location.href = header.dataset.href;
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const header = e.target.closest('.exercise-card-header');
        if (!header) return;
        e.preventDefault();
        if (header.dataset.card) toggleCard(header.dataset.card);
        else if (header.dataset.href) window.location.href = header.dataset.href;
    });

    function toggleCard(cardId) {
        const panel = document.getElementById('panel-' + cardId);
        if (!panel) return;
        if (openCardId && openCardId !== cardId) collapseCard(openCardId);
        panel.hidden ? expandCard(cardId) : collapseCard(cardId);
    }

    function expandCard(cardId) {
        const panel = document.getElementById('panel-' + cardId);
        if (!panel) return;
        panel.hidden = false;
        openCardId = cardId;
        setExpandIcon(cardId, true);
        syncUnitInPanel(panel);
    }

    function collapseCard(cardId) {
        const panel = document.getElementById('panel-' + cardId);
        if (panel) panel.hidden = true;
        if (openCardId === cardId) openCardId = null;
        setExpandIcon(cardId, false);
    }

    function setExpandIcon(cardId, open) {
        const h = document.querySelector('.exercise-card-header[data-card="' + cardId + '"]');
        if (!h) return;
        h.setAttribute('aria-expanded', open ? 'true' : 'false');
        const icon = h.querySelector('.expand-icon');
        if (icon) icon.classList.toggle('open', open);
    }

    // ── Routine edit mode ──────────────────────────────────────────
    const editToggle = document.getElementById('edit-routine-toggle');
    if (editToggle) {
        editToggle.addEventListener('click', function () {
            const container = document.querySelector('.routine-container');
            const on = container.classList.toggle('edit-mode');
            editToggle.classList.toggle('active', on);
            editToggle.textContent = on ? '✓ Done' : '✎ Edit';
        });
    }

    document.addEventListener('click', function (e) {
        const t = e.target.closest('.add-exercise-toggle');
        if (!t) return;
        const box = t.parentElement.querySelector('.add-exercise-box');
        if (box) box.hidden = !box.hidden;
    });

    // ── Add / remove sets ──────────────────────────────────────────
    document.addEventListener('click', function (e) {
        const addBtn = e.target.closest('[data-add-set]');
        const remBtn = e.target.closest('[data-remove-set]');
        if (!addBtn && !remBtn) return;

        const form = e.target.closest('form');
        const rows = form && form.querySelector('.set-rows');
        if (!rows) return;
        const count = rows.children.length;

        if (remBtn) {
            if (count > 1) rows.lastElementChild.remove();
        } else {
            if (count >= 10) return;
            const i = count + 1;
            const weighted = rows.dataset.weighted === '1';
            const defaultReps = rows.dataset.defaultReps || '';
            const row = mkEl('div', 'set-row');
            let html = '<span class="set-label">Set ' + i + '</span><div class="set-inputs">';
            if (weighted) {
                html += '<div class="form-group"><label>Weight (<span class="unit-display">' + currentUnit + '</span>)</label>' +
                        '<input type="number" class="weight-input" name="weight_set_' + i + '" step="0.5" min="0"></div>';
            }
            html += '<div class="form-group"><label>Reps</label>' +
                    '<input type="number" name="reps_set_' + i + '" min="1" max="100" value="' + defaultReps + '"></div></div>';
            row.innerHTML = html;
            rows.appendChild(row);
        }

        // Rebuild the picker so Fill/Load buttons match the new set count
        const panel = form.closest('.exercise-panel');
        const picker = panel && panel.querySelector('.weight-picker');
        if (picker) buildPicker(picker);
    });

    // ── AJAX form submit ───────────────────────────────────────────
    document.addEventListener('submit', function (e) {
        const form = e.target;
        if (!form.classList.contains('exercise-log-form')) return;
        e.preventDefault();
        const btn = form.querySelector('[type="submit"]');
        let btnLabel = '';
        if (btn) {
            btn.disabled = true;
            btnLabel = btn.textContent;
            btn.textContent = 'Logging…';
        }
        const errDiv = form.querySelector('.form-error');
        if (errDiv) errDiv.textContent = '';

        function restoreBtn() {
            if (btn) { btn.disabled = false; btn.textContent = btnLabel; }
        }

        fetch(form.action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: new FormData(form),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                restoreBtn();
                if (data.status === 'ok') {
                    clearDraft(form);
                    markCardDone(form.dataset.cardId, data.sets_completed);
                    collapseCard(form.dataset.cardId);
                    startTimer(data.rest_period, data.exercise_name);
                    if (data.advanced && data.new_progression) showAdvancementBanner(data.new_progression);
                } else {
                    if (errDiv) errDiv.textContent = data.message || 'Error logging exercise.';
                }
            })
            .catch(function () { restoreBtn(); form.submit(); });
    });

    function markCardDone(cardId, n) {
        const h = document.querySelector('.exercise-card-header[data-card="' + cardId + '"]');
        if (!h) return;
        let badge = h.querySelector('.logged-badge');
        if (!badge) { badge = mkEl('span', 'logged-badge'); h.appendChild(badge); }
        badge.textContent = '✓ ' + n + (n === 1 ? ' set' : ' sets');
    }

    function showAdvancementBanner(name) {
        const b = mkEl('div', 'advancement-banner');
        b.textContent = 'Advanced to: ' + name;
        const m = document.querySelector('main');
        if (m) m.insertAdjacentElement('afterbegin', b);
        setTimeout(function () { b.remove(); }, 5000);
    }

    // ── Timer ──────────────────────────────────────────────────────
    let timerSeconds = 0;
    let timerInterval = null;
    let timerRunning = false;
    let timerRestPeriod = 90;

    function startTimer(restPeriod, exerciseName) {
        timerRestPeriod = restPeriod || 90;
        timerSeconds = timerRestPeriod;
        clearInterval(timerInterval);
        timerRunning = true;
        const bar = document.getElementById('timer-bar');
        if (bar) bar.hidden = false;
        document.body.classList.add('timer-visible');
        const label = document.getElementById('timer-exercise');
        if (label) label.textContent = exerciseName || '';
        const btn = document.getElementById('timer-bar-toggle');
        if (btn) btn.textContent = '⏸';
        updateTimerDisplay();
        timerInterval = setInterval(timerTick, 1000);
    }

    function timerTick() {
        if (timerSeconds > 0) { timerSeconds--; updateTimerDisplay(); return; }
        clearInterval(timerInterval);
        timerRunning = false;
        const d = document.getElementById('timer-bar-display');
        if (d) d.textContent = 'REST ✓';
        const b = document.getElementById('timer-bar-toggle');
        if (b) b.textContent = '▶';
        if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
    }

    function updateTimerDisplay() {
        const d = document.getElementById('timer-bar-display');
        if (d) d.textContent = pad2(Math.floor(timerSeconds / 60)) + ':' + pad2(timerSeconds % 60);
    }

    window.timerToggle = function () {
        if (timerRunning) {
            clearInterval(timerInterval); timerRunning = false;
            const b = document.getElementById('timer-bar-toggle'); if (b) b.textContent = '▶';
        } else {
            timerRunning = true;
            const b = document.getElementById('timer-bar-toggle'); if (b) b.textContent = '⏸';
            timerInterval = setInterval(timerTick, 1000);
        }
    };
    window.timerAdjust = function (d) { timerSeconds = Math.max(0, timerSeconds + d); updateTimerDisplay(); };
    window.timerReset  = function () {
        clearInterval(timerInterval); timerRunning = false; timerSeconds = timerRestPeriod;
        updateTimerDisplay();
        const b = document.getElementById('timer-bar-toggle'); if (b) b.textContent = '▶';
    };

    // ── Weight picker ──────────────────────────────────────────────
    function getExPref(name) {
        try { return JSON.parse(localStorage.getItem('gymPref_' + name) || '{}'); }
        catch (e) { return {}; }
    }
    function setExPref(name, patch) {
        localStorage.setItem('gymPref_' + name, JSON.stringify(Object.assign({}, getExPref(name), patch)));
    }
    function pickerEquipment(p) {
        return getExPref(p.dataset.exercise).equipment || p.dataset.defaultEquipment || 'machine';
    }
    function pickerBarWeight(p) {
        const pref = getExPref(p.dataset.exercise);
        return (currentUnit === 'kg' ? pref.barWeightKg : pref.barWeightLbs) || curBarOpts()[0];
    }
    function getSetInputs(p) {
        const panel = p.closest('.exercise-panel');
        return panel ? Array.from(panel.querySelectorAll('input[name^="weight_set_"]')) : [];
    }

    function buildPicker(p) {
        const eq = pickerEquipment(p);
        if (p._lastEq && p._lastEq !== eq) p._plates = [];
        p._lastEq = eq;
        p._plates = p._plates || [];
        p.innerHTML = '';

        // Header row
        const hdr = mkEl('div', 'picker-header');
        const title = mkEl('span', 'picker-title');
        const titleText = eq === 'barbell' ? 'Plate calculator'
                        : eq === 'dumbbell' ? 'Dumbbell rack'
                        : 'Weight stack';
        title.innerHTML = (EQ_ICONS[eq] || '') + ' ' + titleText;
        hdr.appendChild(title);
        const tot = mkEl('span', 'picker-total');
        tot.innerHTML = '<span class="picker-total-value"></span> <span class="unit-display picker-unit"></span>';
        hdr.appendChild(tot);
        const settingsBtn = mkEl('button', 'picker-settings-btn');
        settingsBtn.type = 'button';
        settingsBtn.textContent = '⚙';
        settingsBtn.title = 'Equipment settings';
        hdr.appendChild(settingsBtn);
        p.appendChild(hdr);

        // Settings panel (hidden until ⚙ tapped)
        const sp = mkEl('div', 'picker-settings-panel');
        sp.hidden = true;
        const eqRow = mkEl('div', 'settings-row');
        const eqLabel = mkEl('span', 'settings-label');
        eqLabel.textContent = 'Equipment:';
        eqRow.appendChild(eqLabel);
        ['barbell', 'dumbbell', 'machine'].forEach(function (t) {
            const b = mkEl('button', 'settings-opt-btn' + (t === eq ? ' active' : ''));
            b.type = 'button';
            b.dataset.setEquipment = t;
            b.innerHTML = (EQ_ICONS[t] || '') + ' ' + t.charAt(0).toUpperCase() + t.slice(1);
            eqRow.appendChild(b);
        });
        sp.appendChild(eqRow);
        if (eq === 'barbell') {
            const bwRow = mkEl('div', 'settings-row');
            const bwLabel = mkEl('span', 'settings-label');
            bwLabel.textContent = 'Bar:';
            bwRow.appendChild(bwLabel);
            const curBW = pickerBarWeight(p);
            curBarOpts().forEach(function (w) {
                const b = mkEl('button', 'settings-opt-btn' + (w === curBW ? ' active' : ''));
                b.type = 'button';
                b.dataset.setBarWeight = w;
                b.textContent = fmtW(w) + ' ' + currentUnit;
                bwRow.appendChild(b);
            });
            sp.appendChild(bwRow);
        }
        if (eq === 'machine') {
            const ssRow = mkEl('div', 'settings-row');
            const ssLabel = mkEl('span', 'settings-label');
            ssLabel.textContent = 'Per plate:';
            ssRow.appendChild(ssLabel);
            const curStep = stackStep(p);
            (currentUnit === 'kg' ? [2.5, 5, 7.5, 10] : [5, 10, 15, 20]).forEach(function (w) {
                const b = mkEl('button', 'settings-opt-btn' + (w === curStep ? ' active' : ''));
                b.type = 'button';
                b.dataset.setStackStep = w;
                b.textContent = fmtW(w) + ' ' + currentUnit;
                ssRow.appendChild(b);
            });
            sp.appendChild(ssRow);
        }
        p.appendChild(sp);

        // Main content
        if (eq === 'barbell')      buildBarbellContent(p);
        else if (eq === 'dumbbell') buildDumbbellContent(p);
        else                        buildMachineContent(p);
    }

    function buildBarbellContent(p) {
        p.appendChild(mkEl('div', 'barbell-visual'));

        const btns = mkEl('div', 'plate-buttons');
        curPlates().forEach(function (w, i) {
            const b = mkEl('button', 'plate-add-btn');
            b.type = 'button';
            b.dataset.addPlate = w;
            b.textContent = fmtW(w);
            b.style.borderColor = PLATE_COLORS[i];
            btns.appendChild(b);
        });
        p.appendChild(btns);

        const acts = mkEl('div', 'picker-actions');
        const setInputs = getSetInputs(p);
        if (setInputs.length) {
            const fromLabel = mkEl('span', 'action-label');
            fromLabel.textContent = 'Load from:';
            acts.appendChild(fromLabel);
            setInputs.forEach(function (_, i) {
                const b = mkEl('button', 'action-btn ghost');
                b.type = 'button';
                b.dataset.loadFrom = i + 1;
                b.textContent = 'Set ' + (i + 1);
                acts.appendChild(b);
            });
            acts.appendChild(mkEl('span', 'action-sep'));
            const fillLabel = mkEl('span', 'action-label');
            fillLabel.textContent = 'Fill:';
            acts.appendChild(fillLabel);
            setInputs.forEach(function (_, i) {
                const b = mkEl('button', 'action-btn blue');
                b.type = 'button';
                b.dataset.fillSet = i + 1;
                b.textContent = 'Set ' + (i + 1);
                acts.appendChild(b);
            });
        }
        const clrBtn = mkEl('button', 'action-btn muted');
        clrBtn.type = 'button';
        clrBtn.dataset.clearPlates = '1';
        clrBtn.textContent = '↺';
        acts.appendChild(clrBtn);
        p.appendChild(acts);

        drawBarbell(p);
    }

    function firstSetWeight(p) {
        const inp = getSetInputs(p)[0];
        const v = inp ? parseFloat(inp.value) : NaN;
        return isNaN(v) || v <= 0 ? null : v;
    }

    function fillAllSets(p, w) {
        getSetInputs(p).forEach(function (inp) {
            inp.value = fmtW(w);
            inp.classList.add('just-filled');
            setTimeout(function () { inp.classList.remove('just-filled'); }, 500);
        });
    }

    function nearestIndex(arr, value) {
        let best = 0;
        arr.forEach(function (w, i) {
            if (Math.abs(w - value) < Math.abs(arr[best] - value)) best = i;
        });
        return best;
    }

    // ── Dumbbell: visual rack stepper ──
    function buildDumbbellContent(p) {
        const steps = curDbSteps();
        const w0 = firstSetWeight(p);
        p._dbIndex = w0 != null ? nearestIndex(steps, w0) : Math.floor(steps.length / 3);

        const vis = mkEl('div', 'dumbbell-visual');
        const prev = mkEl('button', 'db-arrow');
        prev.type = 'button';
        prev.dataset.dbPrev = '1';
        prev.textContent = '−';
        const draw = mkEl('div', 'db-draw');
        const next = mkEl('button', 'db-arrow');
        next.type = 'button';
        next.dataset.dbNext = '1';
        next.textContent = '+';
        vis.appendChild(prev);
        vis.appendChild(draw);
        vis.appendChild(next);
        p.appendChild(vis);

        const chips = mkEl('div', 'db-steps');
        steps.forEach(function (w) {
            const b = mkEl('button', 'db-step-btn');
            b.type = 'button';
            b.dataset.dbWeight = w;
            b.textContent = fmtW(w);
            chips.appendChild(b);
        });
        p.appendChild(chips);

        const hint = mkEl('p', 'picker-hint');
        hint.textContent = 'Step through the rack — fills all sets';
        p.appendChild(hint);

        renderDumbbell(p);
    }

    function renderDumbbell(p) {
        const steps = curDbSteps();
        p._dbIndex = Math.max(0, Math.min(p._dbIndex || 0, steps.length - 1));
        const w = steps[p._dbIndex];
        const ratio = (p._dbIndex + 1) / steps.length;

        const draw = p.querySelector('.db-draw');
        if (!draw) return;
        draw.innerHTML = '';

        const discs = 1 + Math.floor(ratio * 2.4); // 1–3 discs per side
        const baseH = Math.round(26 + 34 * ratio);

        function mkSide(reverse) {
            const side = mkEl('div', 'db-side');
            // Biggest disc closest to the handle
            for (let i = 0; i < discs; i++) {
                const d = mkEl('div', 'db-disc');
                d.style.height = Math.max(16, baseH - i * 7) + 'px';
                side.appendChild(d);
            }
            if (!reverse) {
                // Mirror so the big disc faces the handle on both sides
                Array.from(side.children).reverse().forEach(function (c) { side.appendChild(c); });
            }
            return side;
        }

        draw.appendChild(mkSide(false));
        draw.appendChild(mkEl('div', 'db-handle'));
        draw.appendChild(mkSide(true));

        const lbl = mkEl('div', 'db-weight-label');
        lbl.textContent = fmtW(w);
        draw.appendChild(lbl);

        p.querySelectorAll('.db-step-btn').forEach(function (b) {
            b.classList.toggle('selected', parseFloat(b.dataset.dbWeight) === w);
        });
        const sel = p.querySelector('.db-step-btn.selected');
        if (sel) {
            const row = sel.parentElement;
            row.scrollLeft = sel.offsetLeft - row.clientWidth / 2 + sel.clientWidth / 2;
        }

        const tv = p.querySelector('.picker-total-value');
        if (tv) tv.textContent = fmtW(w);
        p.querySelectorAll('.picker-unit').forEach(function (el) { el.textContent = currentUnit; });
        return w;
    }

    // ── Machine: tap-the-pin weight stack ──
    const STACK_PLATES = 15;

    function stackStep(p) {
        const pref = getExPref(p.dataset.exercise);
        const saved = currentUnit === 'kg' ? pref.stackStepKg : pref.stackStepLbs;
        return saved || (currentUnit === 'kg' ? 5 : 10);
    }

    function buildMachineContent(p) {
        const step = stackStep(p);
        const w0 = firstSetWeight(p);
        p._pin = w0 != null
            ? Math.max(1, Math.min(STACK_PLATES, Math.round(w0 / step)))
            : 5;

        const wrap = mkEl('div', 'machine-visual');
        const stack = mkEl('div', 'machine-stack');
        for (let i = 1; i <= STACK_PLATES; i++) {
            const plate = mkEl('button', 'stack-plate');
            plate.type = 'button';
            plate.dataset.pin = i;
            const num = mkEl('span', 'stack-plate-num');
            num.textContent = fmtW(i * step);
            plate.appendChild(num);
            stack.appendChild(plate);
        }
        wrap.appendChild(stack);
        p.appendChild(wrap);

        const hint = mkEl('p', 'picker-hint');
        hint.textContent = 'Tap the stack to set the pin — fills all sets';
        p.appendChild(hint);

        renderStack(p);
    }

    function renderStack(p) {
        const step = stackStep(p);
        p.querySelectorAll('.stack-plate').forEach(function (plate) {
            const i = parseInt(plate.dataset.pin, 10);
            plate.classList.toggle('selected', i <= p._pin);
            plate.classList.toggle('pinned', i === p._pin);
        });
        const total = p._pin * step;
        const tv = p.querySelector('.picker-total-value');
        if (tv) tv.textContent = fmtW(total);
        p.querySelectorAll('.picker-unit').forEach(function (el) { el.textContent = currentUnit; });
        return total;
    }

    function drawBarbell(p) {
        const v = p.querySelector('.barbell-visual');
        if (!v) return;
        v.innerHTML = '';

        const plates  = p._plates || [];
        const barW    = pickerBarWeight(p);
        const denoms  = curPlates();
        const maxW    = denoms[0];
        const sorted  = plates
            .map(function (w, i) { return { w: w, i: i }; })
            .sort(function (a, b) { return b.w - a.w; });

        function mkPlate(entry) {
            const btn = mkEl('button', 'bv-plate');
            btn.type = 'button';
            btn.dataset.removePlate = entry.i;
            btn.title = 'Remove ' + fmtW(entry.w) + ' ' + currentUnit;
            const ratio = entry.w / maxW;
            btn.style.height = Math.round(26 + 44 * ratio) + 'px';
            btn.style.width  = Math.max(7, Math.round(14 * ratio)) + 'px';
            const ci = denoms.indexOf(entry.w);
            btn.style.backgroundColor = PLATE_COLORS[ci >= 0 ? ci : denoms.length - 1];
            return btn;
        }

        const L = mkEl('div', 'bv-side bv-left');
        const R = mkEl('div', 'bv-side bv-right');
        sorted.slice().reverse().forEach(function (e) { L.appendChild(mkPlate(e)); });
        sorted.forEach(function (e) { R.appendChild(mkPlate(e)); });

        v.appendChild(L);
        v.appendChild(mkEl('div', 'bv-bar'));
        v.appendChild(R);

        if (!plates.length) {
            const hint = mkEl('div', 'bv-hint');
            hint.textContent = 'Tap a plate to load it';
            v.appendChild(hint);
        }

        const total = barW + 2 * plates.reduce(function (s, w) { return s + w; }, 0);
        const tv = p.querySelector('.picker-total-value');
        if (tv) tv.textContent = fmtW(total);
        p.querySelectorAll('.picker-unit').forEach(function (el) { el.textContent = currentUnit; });
        return total;
    }

    // Greedy reverse calc: find closest plate arrangement ≤ target weight
    function reverseCalc(p, targetWeight) {
        const barW = pickerBarWeight(p);
        let perSide = (targetWeight - barW) / 2;
        const plates = [];
        if (perSide > 0) {
            curPlates().forEach(function (d) {
                while (perSide >= d - 0.001) { plates.push(d); perSide -= d; }
            });
        }
        p._plates = plates;
        drawBarbell(p);
    }

    // Picker delegated click handler
    document.addEventListener('click', function (e) {
        const p = e.target.closest('.weight-picker');
        if (!p) return;

        // ⚙ toggle settings
        if (e.target.closest('.picker-settings-btn')) {
            const sp = p.querySelector('.picker-settings-panel');
            if (sp) sp.hidden = !sp.hidden;
            return;
        }
        // Change equipment type
        const eqEl = e.target.closest('[data-set-equipment]');
        if (eqEl) {
            setExPref(p.dataset.exercise, { equipment: eqEl.dataset.setEquipment });
            buildPicker(p);
            return;
        }
        // Change bar weight
        const bwEl = e.target.closest('[data-set-bar-weight]');
        if (bwEl) {
            const key = currentUnit === 'kg' ? 'barWeightKg' : 'barWeightLbs';
            const patch = {};
            patch[key] = parseFloat(bwEl.dataset.setBarWeight);
            setExPref(p.dataset.exercise, patch);
            buildPicker(p);
            return;
        }
        // Add plate
        const addEl = e.target.closest('[data-add-plate]');
        if (addEl) {
            (p._plates = p._plates || []).push(parseFloat(addEl.dataset.addPlate));
            drawBarbell(p);
            return;
        }
        // Remove plate (tap on barbell visual)
        const remEl = e.target.closest('[data-remove-plate]');
        if (remEl) {
            if (p._plates) p._plates.splice(parseInt(remEl.dataset.removePlate, 10), 1);
            drawBarbell(p);
            return;
        }
        // Clear all plates
        if (e.target.closest('[data-clear-plates]')) {
            p._plates = [];
            drawBarbell(p);
            return;
        }
        // Load from set input → reverse-calc plates
        const fromEl = e.target.closest('[data-load-from]');
        if (fromEl) {
            const inp = getSetInputs(p)[parseInt(fromEl.dataset.loadFrom, 10) - 1];
            if (inp) {
                const v = parseFloat(inp.value);
                if (!isNaN(v) && v > 0) reverseCalc(p, v);
            }
            return;
        }
        // Fill set input ← barbell total
        const fillEl = e.target.closest('[data-fill-set]');
        if (fillEl) {
            const total = drawBarbell(p);
            const inp = getSetInputs(p)[parseInt(fillEl.dataset.fillSet, 10) - 1];
            if (inp && total != null) {
                inp.value = fmtW(total);
                fillEl.classList.add('applied');
                setTimeout(function () { fillEl.classList.remove('applied'); }, 600);
            }
            return;
        }
        // Machine stack-step setting
        const ssEl = e.target.closest('[data-set-stack-step]');
        if (ssEl) {
            const key = currentUnit === 'kg' ? 'stackStepKg' : 'stackStepLbs';
            const patch = {};
            patch[key] = parseFloat(ssEl.dataset.setStackStep);
            setExPref(p.dataset.exercise, patch);
            buildPicker(p);
            return;
        }
        // Machine: tap a plate to set the pin
        const pinEl = e.target.closest('[data-pin]');
        if (pinEl) {
            p._pin = parseInt(pinEl.dataset.pin, 10);
            fillAllSets(p, renderStack(p));
            return;
        }
        // Dumbbell: step through the rack
        if (e.target.closest('[data-db-prev]') || e.target.closest('[data-db-next]')) {
            p._dbIndex = (p._dbIndex || 0) + (e.target.closest('[data-db-next]') ? 1 : -1);
            fillAllSets(p, renderDumbbell(p));
            return;
        }
        // Dumbbell: jump straight to a rack weight
        const dbEl = e.target.closest('[data-db-weight]');
        if (dbEl) {
            p._dbIndex = curDbSteps().indexOf(parseFloat(dbEl.dataset.dbWeight));
            fillAllSets(p, renderDumbbell(p));
        }
    });

    function initPickers() {
        document.querySelectorAll('.weight-picker').forEach(function (p) {
            p._plates = [];
            buildPicker(p);
        });
    }
    function refreshPickers() {
        document.querySelectorAll('.weight-picker').forEach(function (p) {
            p._plates = [];
            buildPicker(p);
        });
    }

    initPickers();

    // ── Unit conversion ────────────────────────────────────────────
    function convertWeight(value, from, to) {
        if (from === to) return value;
        return from === 'lbs' ? value / LBS_PER_KG : value * LBS_PER_KG;
    }
    function roundWeight(v) { return Math.round(v * 2) / 2; }

    window.setUnit = function (unit) {
        if (unit === currentUnit) return;
        document.querySelectorAll('.weight-input').forEach(function (input) {
            const v = parseFloat(input.value);
            if (!isNaN(v) && v > 0) input.value = roundWeight(convertWeight(v, currentUnit, unit));
        });
        currentUnit = unit;
        localStorage.setItem('weightUnit', currentUnit);
        applyUnitUI(document);
        refreshPickers(); // denominations are physical — swap, don't convert
    };

    function applyUnitUI(root) {
        root = root || document;
        root.querySelectorAll('.weight-unit-input').forEach(function (el) { el.value = currentUnit; });
        root.querySelectorAll('.unit-display').forEach(function (el) { el.textContent = currentUnit; });
        document.querySelectorAll('.unit-toggle-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.unit === currentUnit);
        });
        root.querySelectorAll('.last-set-badge').forEach(function (badge) {
            const wd = badge.querySelector('.last-weight-display');
            const ul = badge.querySelector('.last-unit-label');
            if (!wd || !ul) return;
            const raw = parseFloat(badge.dataset.lbsValue);
            if (isNaN(raw)) return;
            wd.textContent = roundWeight(convertWeight(raw, badge.dataset.storedUnit || 'lbs', currentUnit));
            ul.textContent = currentUnit;
        });
    }

    function syncUnitInPanel(panel) {
        panel.querySelectorAll('.weight-unit-input').forEach(function (el) { el.value = currentUnit; });
        panel.querySelectorAll('.unit-display').forEach(function (el) { el.textContent = currentUnit; });
    }

    // Convert pre-filled weight inputs to saved unit preference on load
    document.querySelectorAll('.weight-input').forEach(function (input) {
        const sv = parseFloat(input.dataset.storedValue);
        const su = input.dataset.storedUnit || 'lbs';
        if (!isNaN(sv) && sv > 0) input.value = roundWeight(convertWeight(sv, su, currentUnit));
    });

    applyUnitUI(document);
});
