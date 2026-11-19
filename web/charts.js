// QPFL charts: SVG/HTML chart primitives and the chart registry.
//
// Loaded before app.js. Every primitive is a pure function that returns a
// markup string, so charts render the same in a view section, in QPFLTok and
// in node tests (tests/test_charts_js.py loads this file whole). Colors come
// from CSS classes in styles.css, never inline, so the theme stays in one place.
//
// Conventions shared by every primitive:
// - Empty input returns '' so callers can drop a chart with nothing to say.
// - `highlight` is a franchise code. Its series/row gets `is-highlight` and,
//   when one is set, every other series gets `is-muted`.
// - SVG charts carry role="img", an aria-label and a <title>; charts with
//   numbers behind them add a "Show as table" <details> fallback.
// - `data-tip` on any element shows a tooltip on hover or tap.
//
// See docs/PLAN_qpfltok_and_charts.md.

/* eslint-disable no-unused-vars */

function chartEsc(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function chartNum(value, digits = 1) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '–';
    return Number.isInteger(value) && digits <= 1 ? String(value) : value.toFixed(digits);
}

function chartRound(value) {
    return Math.round(value * 100) / 100;
}

// "Nice" axis ticks covering [min, max], about `count` of them.
function chartTicks(min, max, count = 4) {
    if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
    if (min === max) return [min];
    const raw = (max - min) / Math.max(1, count);
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(s => s >= raw) || raw;
    const ticks = [];
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(chartRound(v));
    return ticks;
}

function seriesClass(id, highlight) {
    if (!highlight) return '';
    return id === highlight ? ' is-highlight' : ' is-muted';
}

function chartTable({ caption, head, rows }) {
    if (!rows?.length) return '';
    return `
        <details class="chart-table">
            <summary>Show as table</summary>
            <table>
                ${caption ? `<caption class="visually-hidden">${chartEsc(caption)}</caption>` : ''}
                <thead><tr>${head.map(h => `<th scope="col">${chartEsc(h)}</th>`).join('')}</tr></thead>
                <tbody>${rows.map(row => `<tr>${row.map((cell, i) => i === 0
                    ? `<th scope="row">${chartEsc(cell)}</th>`
                    : `<td>${chartEsc(cell)}</td>`).join('')}</tr>`).join('')}</tbody>
            </table>
        </details>`;
}

function chartSvg({ className = '', width, height, label, body }) {
    return `<svg class="chart-svg ${chartEsc(className)}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${chartEsc(label)}"><title>${chartEsc(label)}</title>${body}</svg>`;
}

// ---- Line and bump charts ----

// Points of a series split into runs between nulls, so gaps stay gaps.
function linePaths(values, x, y) {
    const runs = [];
    let run = [];
    values.forEach((v, i) => {
        if (typeof v === 'number' && Number.isFinite(v)) {
            run.push(`${chartRound(x(i))},${chartRound(y(v))}`);
        } else if (run.length) {
            runs.push(run);
            run = [];
        }
    });
    if (run.length) runs.push(run);
    return runs.map(points => `M${points.join('L')}`).join('');
}

function lastIndex(values) {
    for (let i = values.length - 1; i >= 0; i -= 1) {
        if (typeof values[i] === 'number' && Number.isFinite(values[i])) return i;
    }
    return -1;
}

function linePlot({
    series, x, yDomain, highlight, yFmt = v => chartNum(v), title, invert = false,
    width = 640, height = 280, refLine = null, endLabels = 'highlight', yTicks = null, className = '',
    xMarks = null,
}) {
    const live = (series || []).filter(s => (s.values || []).some(v => typeof v === 'number'));
    if (!live.length || !x?.length) return '';
    const all = live.flatMap(s => s.values.filter(v => typeof v === 'number' && Number.isFinite(v)));
    let [yMin, yMax] = yDomain || [Math.min(...all), Math.max(...all)];
    if (yMin === yMax) { yMin -= 1; yMax += 1; }
    const showEnd = s => endLabels === 'all' || (endLabels === 'highlight' && s.id === highlight);
    const longestEnd = Math.max(0, ...live.filter(showEnd).map(s => String(s.short || s.label).length));
    const pad = { left: 40, right: longestEnd ? Math.min(140, 14 + longestEnd * 7) : 12, top: 10, bottom: 26 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xs = i => pad.left + (x.length === 1 ? plotW / 2 : (i / (x.length - 1)) * plotW);
    const ys = v => {
        const t = (v - yMin) / (yMax - yMin);
        return pad.top + (invert ? t : 1 - t) * plotH;
    };
    const ticks = yTicks || chartTicks(yMin, yMax, 4);
    const xEvery = Math.max(1, Math.ceil(x.length / 8));
    const grid = ticks.map(v => `
        <line class="chart-gridline" x1="${pad.left}" y1="${chartRound(ys(v))}" x2="${pad.left + plotW}" y2="${chartRound(ys(v))}"/>
        <text class="chart-tick" x="${pad.left - 6}" y="${chartRound(ys(v) + 3)}" text-anchor="end">${chartEsc(yFmt(v))}</text>`).join('');
    // xMarks: [{ i, label }] replaces the even tick spacing with labeled
    // dividers (one per season on a multi-season chart).
    const xTicks = xMarks
        ? xMarks.map(({ i, label }) => `
            <line class="chart-gridline is-divider" x1="${chartRound(xs(i))}" y1="${pad.top}" x2="${chartRound(xs(i))}" y2="${pad.top + plotH}"/>
            <text class="chart-tick" x="${chartRound(xs(i) + 4)}" y="${height - 8}" text-anchor="start">${chartEsc(label)}</text>`).join('')
        : x.map((label, i) => (i % xEvery === 0 || i === x.length - 1)
            ? `<text class="chart-tick" x="${chartRound(xs(i))}" y="${height - 8}" text-anchor="middle">${chartEsc(label)}</text>`
            : '').join('');
    const ref = refLine != null && refLine >= Math.min(yMin, yMax) && refLine <= Math.max(yMin, yMax)
        ? `<line class="chart-refline" x1="${pad.left}" y1="${chartRound(ys(refLine))}" x2="${pad.left + plotW}" y2="${chartRound(ys(refLine))}"/>`
        : '';
    // End labels, nudged apart so lines that finish together stay readable.
    const labelY = {};
    const labelled = live.filter(showEnd)
        .map(s => ({ id: s.id, y: ys(s.values[lastIndex(s.values)]) }))
        .sort((a, b) => a.y - b.y);
    const gap = 11;
    labelled.forEach((l, i) => { l.at = i ? Math.max(l.y, labelled[i - 1].at + gap) : l.y; });
    const overflow = labelled.length ? labelled[labelled.length - 1].at - (pad.top + plotH) : 0;
    if (overflow > 0) {
        for (let i = labelled.length - 1; i >= 0; i -= 1) {
            const limit = i === labelled.length - 1 ? pad.top + plotH : labelled[i + 1].at - gap;
            labelled[i].at = Math.min(labelled[i].at, limit);
        }
    }
    labelled.forEach(l => { labelY[l.id] = l.at; });
    // The highlighted series draws last so it sits on top.
    const ordered = [...live].sort((a, b) => (a.id === highlight) - (b.id === highlight));
    const lines = ordered.map(s => {
        const end = lastIndex(s.values);
        const endX = xs(end);
        const endY = ys(s.values[end]);
        const tip = `${s.label}: ${yFmt(s.values[end])}`;
        const d = linePaths(s.values, xs, ys);
        return `
            <g class="chart-series${seriesClass(s.id, highlight)}" data-series="${chartEsc(s.id)}">
                <path class="chart-hit" d="${d}" data-tip="${chartEsc(tip)}"/>
                <path class="chart-line" d="${d}"/>
                <circle class="chart-dot" cx="${chartRound(endX)}" cy="${chartRound(endY)}" r="3" data-tip="${chartEsc(tip)}"/>
                ${showEnd(s) ? `<text class="chart-endlabel" x="${chartRound(endX + 6)}" y="${chartRound((labelY[s.id] ?? endY) + 4)}">${chartEsc(s.short || s.label)}</text>` : ''}
            </g>`;
    }).join('');
    const svg = chartSvg({
        className: `chart-line-chart ${className}`,
        width,
        height,
        label: title || `Line chart of ${live.length} series`,
        body: `${grid}${ref}${xTicks}${lines}`,
    });
    return svg;
}

// Values over time for several series (Elo, title odds, season arcs).
function lineChart(options) {
    const svg = linePlot(options);
    if (!svg) return '';
    const { series, x, yFmt = v => chartNum(v), title, table = true } = options;
    const rows = series.filter(s => (s.values || []).some(v => typeof v === 'number')).map(s => {
        const vals = s.values.filter(v => typeof v === 'number');
        return [s.label, yFmt(vals[0]), yFmt(vals[vals.length - 1]), yFmt(Math.min(...vals)), yFmt(Math.max(...vals))];
    });
    return `<figure class="chart-figure">${svg}${table ? chartTable({
        caption: title,
        head: ['', `First (${x[0]})`, `Latest (${x[x.length - 1]})`, 'Low', 'High'],
        rows,
    }) : ''}</figure>`;
}

// Rank over time, 1 at the top (power rankings, standings replay).
function bumpChart({ series, x, highlight, title, width = 640, height = 300, table = true }) {
    const live = (series || []).filter(s => (s.ranks || []).some(v => typeof v === 'number'));
    if (!live.length || !x?.length) return '';
    const n = Math.max(...live.flatMap(s => s.ranks.filter(v => typeof v === 'number')));
    const svg = linePlot({
        series: live.map(s => ({ ...s, values: s.ranks })),
        x,
        yDomain: [1, Math.max(2, n)],
        yTicks: Array.from({ length: n }, (_, i) => i + 1),
        invert: true,
        highlight,
        title,
        width,
        height,
        endLabels: 'all',
        yFmt: v => `${v}`,
        className: 'chart-bump',
    });
    return `<figure class="chart-figure">${svg}${table ? chartTable({
        caption: title,
        head: ['', ...x],
        rows: live.map(s => [s.label, ...s.ranks.map(r => (typeof r === 'number' ? r : '–'))]),
    }) : ''}</figure>`;
}

// ---- Ranked bars (HTML, so labels wrap and stay readable on phones) ----

// A row's label cell: the name, plus an optional short muted tag (the team a
// player played for). Detail (`sub`) never prints: it is the row's tooltip,
// so every row stays one line and the bars do the talking.
function barLabelHtml(r) {
    return `<span class="chart-bar-label">
                    <span class="chart-bar-name">${chartEsc(r.label)}</span>${r.tag ? ` <span class="chart-bar-tag">${chartEsc(r.tag)}</span>` : ''}
                </span>`;
}

function barTip(r) {
    return r.sub ? ` data-tip="${chartEsc(`${r.label}${r.tag ? ` (${r.tag})` : ''}: ${r.sub}`)}"` : '';
}

// rows: [{ id, label, tag?, sub?, value, display?, segments?: [{ value, cls, label }] }]
function barList({ rows, valueFmt = v => chartNum(v), highlight, max = null, title = '', className = '' }) {
    const live = (rows || []).filter(r => typeof r.value === 'number' && Number.isFinite(r.value));
    if (!live.length) return '';
    const top = max ?? Math.max(...live.map(r => Math.abs(r.value)), 0);
    const pct = v => (top > 0 ? Math.max(0, Math.min(100, (Math.abs(v) / top) * 100)) : 0);
    const items = live.map((r, i) => {
        const fill = r.segments?.length
            ? r.segments.map(s => `<span class="chart-bar-fill ${chartEsc(s.cls || '')}" style="width:${chartRound(pct(s.value))}%"></span>`).join('')
            : `<span class="chart-bar-fill" style="width:${chartRound(pct(r.value))}%"></span>`;
        return `
            <li class="chart-bar-row${seriesClass(r.id, highlight)}" data-series="${chartEsc(r.id ?? '')}"${barTip(r)}>
                <span class="chart-bar-rank">${i + 1}</span>
                ${barLabelHtml(r)}
                <span class="chart-bar-track">${fill}</span>
                <span class="chart-bar-value">${chartEsc(r.display ?? valueFmt(r.value))}</span>
            </li>`;
    }).join('');
    return `<ol class="chart-barlist ${chartEsc(className)}"${title ? ` aria-label="${chartEsc(title)}"` : ''}>${items}</ol>`;
}

// Bars growing left (negative) or right (positive) from a center line.
// Positive is good (green) unless `flip` says a bigger number is worse.
function divergingBars({ rows, valueFmt = v => `${v > 0 ? '+' : ''}${chartNum(v)}`, highlight, title = '', flip = false }) {
    const live = (rows || []).filter(r => typeof r.value === 'number' && Number.isFinite(r.value));
    if (!live.length) return '';
    const top = Math.max(...live.map(r => Math.abs(r.value))) || 1;
    const items = live.map(r => {
        const width = chartRound((Math.abs(r.value) / top) * 50);
        const side = (r.value < 0) !== flip ? 'neg' : 'pos';
        const style = r.value < 0 ? `right:50%;width:${width}%` : `left:50%;width:${width}%`;
        // Zero sits on the line, in neither color.
        const tone = r.value === 0 ? '' : side;
        return `
            <li class="chart-div-row${seriesClass(r.id, highlight)}" data-series="${chartEsc(r.id ?? '')}"${barTip(r)}>
                ${barLabelHtml(r)}
                <span class="chart-div-track"><span class="chart-div-fill ${tone}" style="${style}"></span></span>
                <span class="chart-bar-value ${tone}">${chartEsc(r.display ?? valueFmt(r.value))}</span>
            </li>`;
    }).join('');
    return `<ol class="chart-diverging"${title ? ` aria-label="${chartEsc(title)}"` : ''}>${items}</ol>`;
}

// ---- Scatter ----
//
// One dot per team on two measures of the same unit, with an optional y = x
// diagonal: above it got more than it earned, below it less (luck).
// points: [{ id, label, x, y, tip? }]
function scatterPlot({
    points, highlight, title, xLabel = '', yLabel = '', diagonal = false,
    width = 480, height = 360, fmt = v => chartNum(v), aboveLabel = '', belowLabel = '',
}) {
    const live = (points || []).filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
    if (!live.length) return '';
    const all = live.flatMap(p => [p.x, p.y]);
    const lo = Math.floor(Math.min(...all) - 0.5);
    const hi = Math.ceil(Math.max(...all) + 0.5);
    const [xMin, xMax] = diagonal ? [lo, hi] : [Math.floor(Math.min(...live.map(p => p.x))), Math.ceil(Math.max(...live.map(p => p.x)))];
    const [yMin, yMax] = diagonal ? [lo, hi] : [Math.floor(Math.min(...live.map(p => p.y))), Math.ceil(Math.max(...live.map(p => p.y)))];
    const pad = { left: 40, right: 16, top: 12, bottom: 38 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xs = v => pad.left + ((v - xMin) / (xMax - xMin || 1)) * plotW;
    const ys = v => pad.top + (1 - (v - yMin) / (yMax - yMin || 1)) * plotH;
    const grid = chartTicks(yMin, yMax, 4).map(v => `
        <line class="chart-gridline" x1="${pad.left}" y1="${chartRound(ys(v))}" x2="${pad.left + plotW}" y2="${chartRound(ys(v))}"/>
        <text class="chart-tick" x="${pad.left - 6}" y="${chartRound(ys(v) + 3)}" text-anchor="end">${chartEsc(fmt(v))}</text>`).join('')
        + chartTicks(xMin, xMax, 5).map(v => `
        <text class="chart-tick" x="${chartRound(xs(v))}" y="${pad.top + plotH + 14}" text-anchor="middle">${chartEsc(fmt(v))}</text>`).join('');
    // Above the diagonal is shaded good, below bad, so the dots read at a glance.
    const zones = diagonal ? `
        <path class="chart-zone-pos" d="M${xs(xMin)},${ys(yMin)}L${xs(xMin)},${ys(yMax)}L${xs(xMax)},${ys(yMax)}Z"/>
        <path class="chart-zone-neg" d="M${xs(xMin)},${ys(yMin)}L${xs(xMax)},${ys(yMin)}L${xs(xMax)},${ys(yMax)}Z"/>
        <line class="chart-refline" x1="${xs(xMin)}" y1="${ys(yMin)}" x2="${xs(xMax)}" y2="${ys(yMax)}"/>
        ${aboveLabel ? `<text class="chart-zone-label is-pos" x="${pad.left + 8}" y="${pad.top + 14}">${chartEsc(aboveLabel)}</text>` : ''}
        ${belowLabel ? `<text class="chart-zone-label is-neg" x="${pad.left + plotW - 8}" y="${pad.top + plotH - 8}" text-anchor="end">${chartEsc(belowLabel)}</text>` : ''}` : '';
    // Each label takes the first spot (right, left, above, below) that
    // clears every dot and every label already placed; the highlighted
    // team picks first.
    const dotsAt = live.map(p => ({ x: xs(p.x), y: ys(p.y) }));
    const boxes = [];
    const hits = (a, b) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;
    const spot = p => {
        const cx = xs(p.x);
        const cy = ys(p.y);
        const w = String(p.short || p.label).length * 6.4;
        const tries = [
            { x: cx + 9, y: cy + 4, anchor: 'start', box: { x1: cx + 8, x2: cx + 9 + w, y1: cy - 6, y2: cy + 6 } },
            { x: cx - 9, y: cy + 4, anchor: 'end', box: { x1: cx - 9 - w, x2: cx - 8, y1: cy - 6, y2: cy + 6 } },
            { x: cx, y: cy - 10, anchor: 'middle', box: { x1: cx - w / 2, x2: cx + w / 2, y1: cy - 20, y2: cy - 8 } },
            { x: cx, y: cy + 18, anchor: 'middle', box: { x1: cx - w / 2, x2: cx + w / 2, y1: cy + 8, y2: cy + 20 } },
        ];
        const clear = t => t.box.x1 >= pad.left && t.box.x2 <= pad.left + plotW + pad.right
            && !boxes.some(b => hits(b, t.box))
            && !dotsAt.some(d => (d.x !== cx || d.y !== cy) && hits(t.box, { x1: d.x - 6, x2: d.x + 6, y1: d.y - 6, y2: d.y + 6 }));
        const pick = tries.find(clear) || tries[0];
        boxes.push(pick.box);
        return pick;
    };
    const labelOf = new Map();
    [...live].sort((a, b) => (b.id === highlight) - (a.id === highlight)).forEach(p => labelOf.set(p, spot(p)));
    const ordered = [...live].sort((a, b) => (a.id === highlight) - (b.id === highlight));
    const dots = ordered.map(p => {
        const cx = xs(p.x);
        const at = labelOf.get(p);
        return `
            <g class="chart-scatter-point${seriesClass(p.id, highlight)}" data-series="${chartEsc(p.id)}" data-tip="${chartEsc(p.tip || `${p.label}: ${fmt(p.x)}, ${fmt(p.y)}`)}">
                <circle class="chart-scatter-hit" cx="${chartRound(cx)}" cy="${chartRound(ys(p.y))}" r="12"/>
                <circle class="chart-scatter-dot" cx="${chartRound(cx)}" cy="${chartRound(ys(p.y))}" r="5"/>
                <text class="chart-scatter-label" x="${chartRound(at.x)}" y="${chartRound(at.y)}" text-anchor="${at.anchor}">${chartEsc(p.short || p.label)}</text>
            </g>`;
    }).join('');
    const axes = `
        ${xLabel ? `<text class="chart-axis-label" x="${pad.left + plotW / 2}" y="${height - 4}" text-anchor="middle">${chartEsc(xLabel)}</text>` : ''}
        ${yLabel ? `<text class="chart-axis-label" x="12" y="${pad.top + plotH / 2}" text-anchor="middle" transform="rotate(-90 12 ${pad.top + plotH / 2})">${chartEsc(yLabel)}</text>` : ''}`;
    const svg = chartSvg({ className: 'chart-scatter', width, height, label: title || 'Scatter plot', body: `${zones}${grid}${axes}${dots}` });
    return `<figure class="chart-figure">${svg}${chartTable({
        caption: title,
        head: ['', xLabel || 'x', yLabel || 'y'],
        rows: live.map(p => [p.label, fmt(p.x), fmt(p.y)]),
    })}</figure>`;
}

// ---- Heat grid ----

// Cells on two axes. Each axis is numeric ({ min, max }, one cell per
// integer) or categorical (an array of labels, one cell each).
//
// cells: [{ x, y, cls?, attrs?, title?, text? }]
// prefix: the class prefix for gridlines/ticks/axis labels, so Scorigami
//   keeps its own sg-* styles.
// underlay / overlay: (scale) => svg markup drawn below or above the cells.
function heatGrid({
    cells, xDomain, yDomain, cellSize = 18, pad: padIn = null, step = null,
    xLabel = '', yLabel = '', label, className = 'chart-heatgrid', prefix = 'hg',
    yUp = false, underlay = null, overlay = null, table = null,
}) {
    if (!cells?.length) return '';
    const numericX = !Array.isArray(xDomain);
    const numericY = !Array.isArray(yDomain);
    const xCount = numericX ? xDomain.max - xDomain.min + 1 : xDomain.length;
    const yCount = numericY ? yDomain.max - yDomain.min + 1 : yDomain.length;
    const size = cellSize;
    const longest = list => Math.max(0, ...list.map(v => String(v).length));
    const pad = padIn || {
        left: numericY ? 40 : 12 + longest(yDomain) * 6.5,
        bottom: numericX ? 34 : 14,
        top: numericX ? 8 : 12 + Math.min(longest(xDomain), 6) * 6.5,
        right: 8,
    };
    const plotW = xCount * size;
    const plotH = yCount * size;
    const width = pad.left + plotW + pad.right;
    const height = pad.top + plotH + pad.bottom;
    const xIndex = v => (numericX ? v - xDomain.min : xDomain.indexOf(v));
    const yIndex = v => (numericY ? v - yDomain.min : yDomain.indexOf(v));
    const x = v => pad.left + xIndex(v) * size;
    const y = v => (yUp ? pad.top + plotH - (yIndex(v) + 1) * size : pad.top + yIndex(v) * size);
    const scale = { x, y, size, pad, plotW, plotH, width, height };

    let axes = '';
    if (numericX) {
        const s = step || 25;
        for (let v = xDomain.min; v <= xDomain.max; v += s) {
            axes += `
                <line class="${prefix}-gridline" x1="${x(v)}" y1="${pad.top}" x2="${x(v)}" y2="${pad.top + plotH}"/>
                <text class="${prefix}-tick" x="${x(v)}" y="${pad.top + plotH + 14}" text-anchor="middle">${v}</text>`;
        }
    } else {
        axes += xDomain.map(v => `<text class="${prefix}-tick ${prefix}-xcat" x="${x(v) + size / 2}" y="${pad.top - 6}" text-anchor="start" transform="rotate(-45 ${x(v) + size / 2} ${pad.top - 6})">${chartEsc(v)}</text>`).join('');
    }
    if (numericY) {
        const s = step || 25;
        for (let v = yDomain.min; v <= yDomain.max; v += s) {
            const edge = yUp ? y(v) + size : y(v);
            axes += `
                <line class="${prefix}-gridline" x1="${pad.left}" y1="${edge}" x2="${pad.left + plotW}" y2="${edge}"/>
                <text class="${prefix}-tick" x="${pad.left - 6}" y="${edge + 3}" text-anchor="end">${v}</text>`;
        }
    } else {
        axes += yDomain.map(v => `<text class="${prefix}-tick" x="${pad.left - 6}" y="${y(v) + size / 2 + 4}" text-anchor="end">${chartEsc(v)}</text>`).join('');
    }
    const rects = cells.filter(c => xIndex(c.x) >= 0 && yIndex(c.y) >= 0).map(c => {
        const attrs = Object.entries(c.attrs || {}).map(([k, v]) => ` ${k}="${chartEsc(v)}"`).join('');
        const tip = c.tip ? ` data-tip="${chartEsc(c.tip)}"` : '';
        const rect = `<rect class="${prefix}-cell${c.cls ? ` ${c.cls}` : ''}" x="${x(c.x)}" y="${y(c.y)}" width="${size}" height="${size}"${attrs}${tip}>${c.title ? `<title>${chartEsc(c.title)}</title>` : ''}</rect>`;
        const text = c.text != null
            ? `<text class="${prefix}-cell-text" x="${x(c.x) + size / 2}" y="${y(c.y) + size / 2 + 4}" text-anchor="middle">${chartEsc(c.text)}</text>`
            : '';
        return rect + text;
    }).join('');
    const axisLabels = `
        ${xLabel ? `<text class="${prefix}-axis" x="${pad.left + plotW / 2}" y="${height - 4}" text-anchor="middle">${chartEsc(xLabel)}</text>` : ''}
        ${yLabel ? `<text class="${prefix}-axis" x="12" y="${pad.top + plotH / 2}" text-anchor="middle" transform="rotate(-90 12 ${pad.top + plotH / 2})">${chartEsc(yLabel)}</text>` : ''}`;
    const svg = `
        <svg class="${chartEsc(className)}" viewBox="0 0 ${width} ${height}" role="img"
             aria-label="${chartEsc(label)}">
            ${underlay ? underlay(scale) : ''}
            ${axes}
            ${rects}
            ${overlay ? overlay(scale) : ''}
            ${axisLabels}
        </svg>`;
    return table ? `<figure class="chart-figure">${svg}${chartTable(table)}</figure>` : svg;
}

// ---- Ring (progress donut) ----

function ringStat({ pct, label = '', sub = '', center = null, size = 56, id = null, highlight = null, cls = '' }) {
    if (typeof pct !== 'number' || !Number.isFinite(pct)) return '';
    const p = Math.max(0, Math.min(1, pct));
    const r = size / 2 - 5;
    const c = 2 * Math.PI * r;
    // Short of the goal never reads 100%.
    const middle = center ?? `${p < 1 ? Math.min(99, Math.round(p * 100)) : 100}%`;
    const ring = `
        <svg class="chart-ring-svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true">
            <circle class="chart-ring-track" cx="${size / 2}" cy="${size / 2}" r="${chartRound(r)}"/>
            <circle class="chart-ring-fill" cx="${size / 2}" cy="${size / 2}" r="${chartRound(r)}"
                stroke-dasharray="${chartRound(c * p)} ${chartRound(c)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
            <text class="chart-ring-center" x="${size / 2}" y="${size / 2 + 4}" text-anchor="middle">${chartEsc(middle)}</text>
        </svg>`;
    return `
        <div class="chart-ring${seriesClass(id, highlight)}${cls ? ` ${chartEsc(cls)}` : ''}" role="img" aria-label="${chartEsc(`${label}: ${middle}${sub ? `, ${sub}` : ''}`)}">
            ${ring}
            ${label || sub ? `<div class="chart-ring-text">
                ${label ? `<span class="chart-ring-label">${chartEsc(label)}</span>` : ''}
                ${sub ? `<span class="chart-ring-sub">${chartEsc(sub)}</span>` : ''}
            </div>` : ''}
        </div>`;
}

// ---- Strip plot ----

function median(values) {
    const sorted = [...values].sort((a, b) => a - b);
    if (!sorted.length) return null;
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

// One row of dots per entry plus a median tick (score distributions,
// boom or bust). rows: [{ id, label, values: [number] }]
function stripPlot({ rows, domain = null, highlight, valueFmt = v => chartNum(v), title, width = 640, rowH = 26, table = true }) {
    const live = (rows || []).filter(r => (r.values || []).length);
    if (!live.length) return '';
    const all = live.flatMap(r => r.values);
    const [min, max] = domain || [Math.min(...all), Math.max(...all)];
    const span = max - min || 1;
    const labelW = 12 + Math.min(18, Math.max(...live.map(r => String(r.label).length))) * 6.5;
    const pad = { left: labelW, right: 16, top: 6, bottom: 24 };
    const plotW = width - pad.left - pad.right;
    const height = pad.top + live.length * rowH + pad.bottom;
    const xs = v => pad.left + ((v - min) / span) * plotW;
    const ticks = chartTicks(min, max, 5);
    const grid = ticks.map(v => `
        <line class="chart-gridline" x1="${chartRound(xs(v))}" y1="${pad.top}" x2="${chartRound(xs(v))}" y2="${pad.top + live.length * rowH}"/>
        <text class="chart-tick" x="${chartRound(xs(v))}" y="${height - 8}" text-anchor="middle">${chartEsc(valueFmt(v))}</text>`).join('');
    const body = live.map((r, i) => {
        const cy = pad.top + i * rowH + rowH / 2;
        const med = median(r.values);
        return `
            <g class="chart-strip-row${seriesClass(r.id, highlight)}" data-series="${chartEsc(r.id ?? '')}">
                <text class="chart-strip-label" x="${pad.left - 8}" y="${chartRound(cy + 4)}" text-anchor="end">${chartEsc(r.label)}</text>
                ${r.values.map(v => `<circle class="chart-strip-dot" cx="${chartRound(xs(v))}" cy="${chartRound(cy)}" r="3"/>`).join('')}
                <line class="chart-strip-median" x1="${chartRound(xs(med))}" y1="${chartRound(cy - rowH / 2 + 3)}" x2="${chartRound(xs(med))}" y2="${chartRound(cy + rowH / 2 - 3)}" data-tip="${chartEsc(`${r.label} median ${valueFmt(med)}`)}"/>
            </g>`;
    }).join('');
    const svg = chartSvg({ className: 'chart-strip', width, height, label: title || 'Strip plot', body: grid + body });
    return `<figure class="chart-figure">${svg}${table ? chartTable({
        caption: title,
        head: ['', 'Games', 'Median', 'Low', 'High'],
        rows: live.map(r => [r.label, r.values.length, valueFmt(median(r.values)), valueFmt(Math.min(...r.values)), valueFmt(Math.max(...r.values))]),
    }) : ''}</figure>`;
}

// ---- Registry ----
//
// One entry per chart (see the plan's "Registry" section):
//   { id, family, title, blurb, home: { view, subview, anchor },
//     compute(ctx) → model | null, render(model, { highlight }) → html,
//     tok?(model, { spotlight }) → card fields }
// compute returning null means the chart has nothing to say and renders
// nowhere, in its view or in QPFLTok.

const CHART_FAMILIES = {
    week: { label: 'This week', pill: 'THIS WEEK' },
    standings: { label: 'Standings & outlook', pill: 'STANDINGS' },
    luck: { label: 'Luck & what-if', pill: 'LUCK' },
    managers: { label: 'Managers & rivalries', pill: 'MANAGERS' },
    players: { label: 'Players, moves & awards', pill: 'PLAYERS' },
};

// Every chart says what span of games it covers, on its header and on its
// QPFLTok clip, so "this season" and "all-time" never get mixed up.
const CHART_SCOPES = {
    week: 'This week',
    season: 'This season',
    alltime: 'All-time',
};

const CHARTS = [];

function registerChart(entry) {
    if (!entry?.id || CHARTS.some(c => c.id === entry.id)) {
        throw new Error(`Chart ${entry?.id} is missing or registered twice`);
    }
    if (!CHART_FAMILIES[entry.family]) throw new Error(`Chart ${entry.id} has unknown family ${entry.family}`);
    if (!CHART_SCOPES[entry.scope]) throw new Error(`Chart ${entry.id} has unknown scope ${entry.scope}`);
    CHARTS.push(entry);
    return entry;
}

// { kind, text }: the chart's own scopeText(model) when it has one
// ("2020–2025 drafts"), else the season or week from the model, else the
// generic label.
function chartScope(entry, model) {
    const kind = entry?.scope;
    if (!CHART_SCOPES[kind]) return null;
    let text = null;
    try {
        text = entry.scopeText?.(model) || null;
    } catch {
        text = null;
    }
    if (!text) {
        const season = model?.input?.season ?? model?.season;
        const week = model?.week ?? model?.input?.week;
        if (kind === 'season' && season) text = `${season} season`;
        else if (kind === 'week' && week) text = `Week ${week}`;
        else text = CHART_SCOPES[kind];
    }
    return { kind, text };
}

function chartScopeBadge(scope) {
    if (!scope) return '';
    return `<span class="chart-scope is-${chartEsc(scope.kind)}">${chartEsc(scope.text)}</span>`;
}

function chartById(id) {
    return CHARTS.find(c => c.id === id) || null;
}

// A team's name in a QPFLTok caption: the owner's short name (Griff,
// Kaminska) when the feed has one, else the chart's own label.
function chartWho(opts, input, abbrev) {
    return opts?.ctx?.names?.[abbrev] || input.label(abbrev);
}

function chartAnchor(entry) {
    return entry.home?.anchor || `chart-${entry.id}`;
}

// compute() can throw on odd data; a broken chart must never break its view.
function computeChart(entry, ctx) {
    try {
        return entry.compute(ctx) ?? null;
    } catch (error) {
        if (typeof console !== 'undefined') console.warn(`Chart ${entry.id} failed`, error);
        return null;
    }
}

function chartSectionHtml(entry, model, { highlight = null, open = true } = {}) {
    if (!entry || model == null) return '';
    const body = entry.render(model, { highlight });
    if (!body) return '';
    return `
        <section class="chart-section" id="${chartEsc(chartAnchor(entry))}" data-chart="${chartEsc(entry.id)}">
            <details class="chart-details"${open ? ' open' : ''}>
                <summary class="chart-summary">
                    <h3 class="chart-title">${chartScopeBadge(chartScope(entry, model))}${chartEsc(entry.title)}</h3>
                    ${entry.blurb ? `<p class="chart-blurb">${chartEsc(entry.blurb)}</p>` : ''}
                </summary>
                <div class="chart-body">${body}</div>
            </details>
        </section>`;
}

// The markup for one registered chart, or '' when it has nothing to show.
function renderChartSection(id, ctx = {}, options = {}) {
    const entry = chartById(id);
    if (!entry) return '';
    return chartSectionHtml(entry, computeChart(entry, ctx), options);
}

// ---- Tooltips ----
//
// One floating tip for every [data-tip] element: hover on desktop, tap on
// touch. Installed once, from the browser only.

function installChartTooltips(doc) {
    if (!doc || doc.__chartTips) return;
    doc.__chartTips = true;
    const tip = doc.createElement('div');
    tip.className = 'chart-tip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    doc.body.appendChild(tip);
    const show = (target, event) => {
        tip.textContent = target.getAttribute('data-tip');
        tip.hidden = false;
        const { innerWidth } = doc.defaultView;
        const x = Math.min(innerWidth - tip.offsetWidth - 8, Math.max(8, event.clientX - tip.offsetWidth / 2));
        const y = Math.max(8, event.clientY - tip.offsetHeight - 12);
        tip.style.left = `${x}px`;
        tip.style.top = `${y}px`;
    };
    const hide = () => { tip.hidden = true; };
    doc.addEventListener('pointerover', event => {
        const target = event.target.closest?.('[data-tip]');
        if (target && event.pointerType === 'mouse') show(target, event);
    });
    doc.addEventListener('pointerout', event => {
        if (event.target.closest?.('[data-tip]') && event.pointerType === 'mouse') hide();
    });
    doc.addEventListener('click', event => {
        const target = event.target.closest?.('[data-tip]');
        if (target) show(target, event);
        else hide();
    });
    doc.addEventListener('scroll', hide, { capture: true, passive: true });
}

if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => installChartTooltips(document));
    } else {
        installChartTooltips(document);
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        chartEsc, chartNum, chartTicks, chartTable, lineChart, bumpChart, barList, divergingBars,
        heatGrid, ringStat, stripPlot, scatterPlot, median, CHART_FAMILIES, CHART_SCOPES, CHARTS,
        registerChart, chartById, chartScope, chartScopeBadge,
        chartAnchor, chartWho, computeChart, chartSectionHtml, renderChartSection, installChartTooltips,
    };
}
