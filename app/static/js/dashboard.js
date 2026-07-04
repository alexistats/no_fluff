// Dashboard charts. Server data arrives via the #dashboard-data JSON block so
// this file is static and cacheable.
(function () {
    'use strict';

    const dataEl = document.getElementById('dashboard-data');
    if (!dataEl || typeof Chart === 'undefined') return;
    const data = JSON.parse(dataEl.textContent);

    const PALETTE = ['#e67e22', '#27ae60', '#8e44ad', '#e74c3c'];
    let charts = [];

    Chart.defaults.font = {
        family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        size: 12,
    };

    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function buildCharts() {
        // Rebuild from our own registry — no reliance on Chart.instances.
        charts.forEach((c) => c.destroy());
        charts = [];

        const text2 = cssVar('--text-2');
        const border = cssVar('--border');
        const accent = cssVar('--accent');
        const gridOpts = { color: border, drawBorder: false };
        const tickOpts = { color: text2 };
        const palette = [accent, ...PALETTE];

        const freqCtx = document.getElementById('freqChart');
        if (freqCtx) {
            charts.push(new Chart(freqCtx, {
                type: 'bar',
                data: {
                    labels: data.freq_labels,
                    datasets: [{
                        label: 'Workouts',
                        data: data.freq_values,
                        backgroundColor: accent,
                        borderRadius: 6,
                        borderSkipped: false,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: gridOpts, ticks: tickOpts },
                        y: { grid: gridOpts, ticks: { ...tickOpts, stepSize: 1 }, beginAtZero: true },
                    },
                },
            }));
        }

        const routineCtx = document.getElementById('routineChart');
        if (routineCtx) {
            const routineData = data.routine_breakdown;
            charts.push(new Chart(routineCtx, {
                type: 'bar',
                data: {
                    labels: routineData.map((r) => r.label),
                    datasets: [{
                        label: 'Sessions',
                        data: routineData.map((r) => r.count),
                        backgroundColor: routineData.map((_, i) => palette[i % palette.length]),
                        borderRadius: 6,
                        borderSkipped: false,
                    }],
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: gridOpts, ticks: { ...tickOpts, stepSize: 1 }, beginAtZero: true },
                        y: { grid: { display: false }, ticks: tickOpts },
                    },
                },
            }));
        }

        const exCtx = document.getElementById('exerciseChart');
        if (exCtx) {
            const exData = data.top_exercises;
            charts.push(new Chart(exCtx, {
                type: 'bar',
                data: {
                    labels: exData.map((e) => e.name),
                    datasets: [{
                        label: 'Sessions',
                        data: exData.map((e) => e.count),
                        backgroundColor: accent,
                        borderRadius: 6,
                        borderSkipped: false,
                    }],
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: gridOpts, ticks: { ...tickOpts, stepSize: 1 }, beginAtZero: true },
                        y: { grid: { display: false }, ticks: { color: text2, font: { size: 11 } } },
                    },
                },
            }));
        }

        const weightCtx = document.getElementById('weightChart');
        if (weightCtx) {
            const trends = data.weight_trends;
            const exercises = Object.keys(trends);
            if (exercises.length === 0) {
                weightCtx.closest('.dash-chart-wrap').innerHTML =
                    '<p class="dash-empty">Log weighted exercises to see strength trends.</p>';
                return;
            }
            const allDates = [...new Set(exercises.flatMap((ex) => trends[ex].map((p) => p.date)))].sort();
            const datasets = exercises.map((ex, i) => {
                const byDate = Object.fromEntries(trends[ex].map((p) => [p.date, p.weight]));
                return {
                    label: ex,
                    data: allDates.map((d) => byDate[d] ?? null),
                    borderColor: palette[i % palette.length],
                    backgroundColor: palette[i % palette.length] + '22',
                    tension: 0.3,
                    spanGaps: true,
                    pointRadius: 3,
                };
            });
            charts.push(new Chart(weightCtx, {
                type: 'line',
                data: { labels: allDates, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: text2, boxWidth: 12, padding: 16 } },
                        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y} kg` } },
                    },
                    scales: {
                        x: { grid: gridOpts, ticks: { color: text2, maxTicksLimit: 8 } },
                        y: {
                            grid: gridOpts,
                            ticks: { color: text2 },
                            beginAtZero: false,
                            title: { display: true, text: 'kg (normalised)', color: text2 },
                        },
                    },
                },
            }));
        }
    }

    document.addEventListener('DOMContentLoaded', buildCharts);
    document.addEventListener('themechange', buildCharts);
})();
