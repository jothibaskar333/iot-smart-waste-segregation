/* Smart Waste Segregation dashboard - vanilla JS, no build step.
 * Polls the Flask REST API and refreshes immediately after every action. */
(function () {
  "use strict";

  const POLL_MS = 3000;
  const BINS = ["wet", "dry", "metal"];
  const STATUS_ICON = { LOW: "○", NORMAL: "●", HIGH: "▲" };

  const $ = (sel) => document.querySelector(sel);
  let charts = { category: null, fill: null };
  let refreshing = false;
  let lastEventId = null;
  let settingsLoaded = false;

  // ------------------------------------------------------------ helpers
  async function api(path, options = {}) {
    const opts = { headers: { "Content-Type": "application/json" }, ...options };
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON response */ }
    if (!res.ok) {
      const detail = data && data.details ? ": " + data.details.join("; ") : "";
      throw new Error(((data && data.error) || "Request failed (" + res.status + ")") + detail);
    }
    return data;
  }

  function fmtTime(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function fmtDateTime(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "className") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of children) node.append(c);
    return node;
  }

  function categoryBadge(category) {
    const lower = String(category).toLowerCase();
    const span = el("span", { className: "cat" });
    if (BINS.includes(lower)) span.append(el("i", { className: "swatch swatch-" + lower }));
    span.append(document.createTextNode(category));
    return span;
  }

  let toastTimer = null;
  function toast(message, isError = false) {
    const t = $("#toast");
    t.textContent = message;
    t.classList.toggle("is-error", isError);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, isError ? 6000 : 3000);
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // ------------------------------------------------------------- charts
  function chartColors() {
    return {
      wet: cssVar("--wet"), dry: cssVar("--dry"), metal: cssVar("--metal"),
      critical: cssVar("--critical"), text: cssVar("--text-2"), grid: cssVar("--grid"),
      surface: cssVar("--surface"),
    };
  }

  function initCharts() {
    if (typeof Chart === "undefined") {
      $("#chart-fallback").hidden = false;
      return;
    }
    const c = chartColors();
    Chart.defaults.color = c.text;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.borderColor = c.grid;

    charts.category = new Chart($("#category-chart"), {
      type: "bar",
      data: {
        labels: ["Wet", "Dry", "Metal"],
        datasets: [{
          label: "Items sorted",
          data: [0, 0, 0],
          backgroundColor: [c.wet, c.dry, c.metal],
          borderRadius: 4,
          borderSkipped: "start",
          maxBarThickness: 48,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${ctx.parsed.y} item(s)` } } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: c.grid } },
          x: { grid: { display: false } },
        },
      },
    });

    const line = (label, color) => ({
      label, data: [], borderColor: color, backgroundColor: color,
      borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 10, tension: 0, stepped: false,
    });
    charts.fill = new Chart($("#fill-chart"), {
      type: "line",
      data: {
        labels: [],
        datasets: [
          line("Wet", c.wet), line("Dry", c.dry), line("Metal", c.metal),
          { ...line("High threshold", c.critical), borderDash: [6, 4], borderWidth: 1.5, pointHoverRadius: 0 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y}%` } },
        },
        scales: {
          y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" }, grid: { color: c.grid } },
          x: { ticks: { maxTicksLimit: 8, autoSkip: true, maxRotation: 0 }, grid: { display: false } },
        },
      },
    });
  }

  function updateCategoryChart(counts) {
    if (!charts.category) return;
    charts.category.data.datasets[0].data = [counts.WET, counts.DRY, counts.METAL];
    charts.category.update();
  }

  function updateFillChart(fill) {
    if (!charts.fill) return;
    const h = fill.history;
    charts.fill.data.labels = h.map((r) => fmtTime(r.timestamp));
    charts.fill.data.datasets[0].data = h.map((r) => r.wet);
    charts.fill.data.datasets[1].data = h.map((r) => r.dry);
    charts.fill.data.datasets[2].data = h.map((r) => r.metal);
    charts.fill.data.datasets[3].data = h.map(() => fill.thresholds.high);
    charts.fill.update();
  }

  // ---------------------------------------------------------- renderers
  function renderStatus(s) {
    $("#kpi-total").textContent = s.total_sorted;
    $("#kpi-wet").textContent = s.counts.WET;
    $("#kpi-dry").textContent = s.counts.DRY;
    $("#kpi-metal").textContent = s.counts.METAL;
    $("#kpi-none").textContent = s.no_item_readings;
    $("#kpi-alerts").textContent = s.active_alerts;
    $("#fill-inc").textContent = s.settings.fill_increment;

    renderBins(s.fill_levels, s.settings);
    renderSensor(s.latest_reading, s.settings, s.servo);
    renderMqtt(s.mqtt);
    updateCategoryChart(s.counts);

    if (!settingsLoaded) { fillSettingsForm(s.settings); settingsLoaded = true; }
  }

  function renderBins(levels, settings) {
    for (const name of BINS) {
      const box = document.querySelector(`.bin[data-bin="${name}"]`);
      const info = levels[name];
      box.querySelector('[data-role="fill"]').style.height = info.level + "%";
      box.querySelector('[data-role="threshold"]').style.bottom = settings.fill_high_threshold + "%";
      box.querySelector('[data-role="level"]').textContent = info.level + "%";
      box.querySelector(".bin-track").setAttribute("aria-valuenow", info.level);
      const st = box.querySelector('[data-role="status"]');
      st.textContent = `${STATUS_ICON[info.status]} ${info.status}`;
      st.className = "status status-" + info.status;
    }
  }

  function renderSensor(r, settings, servo) {
    const threshold = settings.moisture_threshold;
    $("#s-moisture-mark").style.left = threshold + "%";
    if (!r) {
      $("#s-moisture-note").textContent = `WET threshold: > ${threshold}%`;
      return;
    }
    $("#s-ir").textContent = r.ir_detected ? "Item detected" : "No item";
    $("#s-metal").textContent = r.metal_detected ? "Metal detected" : "No metal";
    $("#s-moisture").textContent = r.moisture + "%";
    $("#s-moisture-bar").style.width = r.moisture + "%";
    $("#s-moisture-note").textContent = `WET threshold: > ${threshold}%`;
    const cls = $("#s-class");
    cls.replaceChildren(r.classification === "NONE" ? document.createTextNode("No sorting (no item)") : categoryBadge(r.classification));
    $("#s-servo").textContent = `${servo.current_angle}° (idle ${servo.idle_angle}°)`;
    $("#s-source").textContent = r.source === "mqtt" ? `MQTT (${r.device_id || "unknown device"})` : "Simulator";
    $("#s-time").textContent = fmtDateTime(r.timestamp);
  }

  function renderMqtt(m) {
    const badge = $("#mqtt-badge");
    const labels = {
      disabled: "MQTT: disabled", not_started: "MQTT: not started", connecting: "MQTT: connecting",
      connected: "MQTT: connected", disconnected: "MQTT: disconnected", error: "MQTT: error",
    };
    badge.replaceChildren(el("span", { className: "dot", "aria-hidden": "true" }), document.createTextNode(labels[m.state] || "MQTT: " + m.state));
    badge.classList.toggle("is-connected", m.state === "connected");
    badge.classList.toggle("is-error", m.state === "error" || m.state === "disconnected");
    badge.classList.toggle("is-pending", m.state === "connecting");

    $("#m-state").textContent = m.enabled ? m.state : "disabled (optional)";
    $("#m-broker").textContent = m.broker || "–";
    $("#m-topic").textContent = m.topic || "–";
    $("#m-count").textContent = `${m.messages_received} received, ${m.messages_rejected} rejected`;
    $("#m-last").textContent = fmtDateTime(m.last_message_at);
    $("#m-error").textContent = m.last_error || "none";
  }

  function renderEvents(events) {
    const body = $("#events-body");
    if (!events.length) {
      body.replaceChildren(el("tr", {}, [el("td", { colspan: "9", className: "muted", text: "No items sorted yet." })]));
      lastEventId = null;
      return;
    }
    const newestPrev = lastEventId;
    body.replaceChildren(...events.map((e) => {
      const tr = el("tr", {}, [
        el("td", { text: e.id }),
        el("td", { text: fmtDateTime(e.timestamp) }),
        el("td", {}, [categoryBadge(e.category)]),
        el("td", { text: e.ir_detected ? "yes" : "no" }),
        el("td", { text: e.moisture + "%" }),
        el("td", { text: e.metal_detected ? "yes" : "no" }),
        el("td", { text: e.servo_action }),
        el("td", { text: e.servo_angle + "°" }),
        el("td", { text: e.source === "mqtt" ? "MQTT" + (e.device_id ? " · " + e.device_id : "") : "Simulator" }),
      ]);
      if (newestPrev !== null && e.id > newestPrev) tr.classList.add("is-new");
      return tr;
    }));
    lastEventId = events[0].id;
  }

  function alertItem(a) {
    const resolved = !a.active;
    const meta = resolved ? `Raised ${fmtDateTime(a.timestamp)} · resolved ${fmtDateTime(a.resolved_at)}` : `Raised ${fmtDateTime(a.timestamp)}`;
    return el("li", { className: "alert-item " + (resolved ? "is-resolved" : "is-active") }, [
      el("span", { className: "alert-icon", "aria-hidden": "true", text: resolved ? "✓" : "▲" }),
      el("div", {}, [
        el("div", { text: (resolved ? "Resolved: " : "HIGH: ") + a.message }),
        el("div", { className: "alert-meta", text: meta }),
      ]),
    ]);
  }

  function renderAlerts(data) {
    const active = $("#active-alerts");
    active.replaceChildren(...(data.active.length ? data.active.map(alertItem) : [el("li", { className: "muted", text: "No active alerts." })]));
    const hist = $("#alert-history");
    hist.replaceChildren(...(data.history.length ? data.history.map(alertItem) : [el("li", { className: "muted", text: "No alerts yet." })]));
  }

  function renderResult(r) {
    const box = $("#last-result");
    if (!r.sorted) {
      box.replaceChildren(
        el("strong", { text: "No item detected" }),
        el("div", { className: "tiny muted", text: `IR = false · moisture ${r.reading.moisture}% · ${r.servo.description}` }),
      );
      return;
    }
    box.replaceChildren(
      el("strong", {}, [document.createTextNode("Classified as "), categoryBadge(r.classification)]),
      el("div", { className: "tiny muted", text: `IR = true · moisture ${r.reading.moisture}% · metal ${r.reading.metal_detected ? "yes" : "no"}` }),
      el("div", { className: "tiny", text: `Simulated servo: ${r.servo.description}` }),
    );
  }

  function fillSettingsForm(s) {
    const f = $("#settings-form");
    for (const key of Object.keys(s)) {
      if (f.elements[key]) f.elements[key].value = s[key];
    }
  }

  // ------------------------------------------------------------ refresh
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const [status, events, fill, alerts] = await Promise.all([
        api("/api/status"), api("/api/events?limit=15"), api("/api/fill-levels?limit=60"), api("/api/alerts?limit=30"),
      ]);
      renderStatus(status);
      renderEvents(events.events);
      updateFillChart(fill);
      renderAlerts(alerts);
      $("#last-updated").textContent = "Updated " + fmtTime(new Date().toISOString());
    } catch (err) {
      $("#last-updated").textContent = "Server unreachable – retrying";
      console.warn("Refresh failed:", err.message);
    } finally {
      refreshing = false;
    }
  }

  // ------------------------------------------------------------ actions
  async function withButton(btn, fn) {
    if (btn) btn.disabled = true;
    try { await fn(); } catch (err) { toast(err.message, true); } finally { if (btn) btn.disabled = false; }
  }

  function announceAlerts(result) {
    if (result.new_alerts && result.new_alerts.length) {
      toast(result.new_alerts.map((a) => a.message).join(" "), true);
    }
  }

  function bindActions() {
    document.querySelectorAll("[data-sim]").forEach((btn) => {
      btn.addEventListener("click", () => withButton(btn, async () => {
        const result = await api("/api/simulate", { method: "POST", body: JSON.stringify({ type: btn.dataset.sim }) });
        renderResult(result);
        announceAlerts(result);
        await refresh();
      }));
    });

    $("#custom-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = ev.target;
      const moistureInput = f.elements.moisture;
      const moisture = Number(moistureInput.value);
      const valid = moistureInput.value !== "" && moisture >= 0 && moisture <= 100;
      moistureInput.classList.toggle("invalid", !valid);
      if (!valid) { toast("Moisture must be a number between 0 and 100.", true); return; }
      const btn = f.querySelector("button[type=submit]");
      withButton(btn, async () => {
        const reading = { ir: f.elements.ir.checked, metal: f.elements.metal.checked, moisture };
        const result = await api("/api/simulate", { method: "POST", body: JSON.stringify({ reading }) });
        renderResult(result);
        announceAlerts(result);
        await refresh();
      });
    });

    $("#reset-all").addEventListener("click", (ev) => withButton(ev.currentTarget, async () => {
      const r = await api("/api/reset", { method: "POST", body: "{}" });
      toast(`All bins reset to 0%${r.alerts_resolved ? ` · ${r.alerts_resolved} alert(s) resolved` : ""}.`);
      await refresh();
    }));

    document.querySelectorAll("[data-reset]").forEach((btn) => {
      btn.addEventListener("click", () => withButton(btn, async () => {
        await api("/api/reset", { method: "POST", body: JSON.stringify({ bin: btn.dataset.reset }) });
        toast(`${btn.dataset.reset} bin reset to 0%.`);
        await refresh();
      }));
    });

    $("#settings-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = ev.target;
      const payload = {};
      let ok = true;
      for (const input of f.querySelectorAll("input[type=number]")) {
        const v = Number(input.value);
        const valid = input.value !== "" && v >= 0 && v <= 100;
        input.classList.toggle("invalid", !valid);
        ok = ok && valid;
        payload[input.name] = v;
      }
      if (!ok) { toast("All thresholds must be numbers between 0 and 100.", true); return; }
      if (payload.fill_low_threshold >= payload.fill_high_threshold) {
        f.elements.fill_low_threshold.classList.add("invalid");
        f.elements.fill_high_threshold.classList.add("invalid");
        toast("Low-fill threshold must be lower than the high-fill threshold.", true);
        return;
      }
      if (payload.fill_increment <= 0) {
        f.elements.fill_increment.classList.add("invalid");
        toast("Simulated fill per item must be greater than 0.", true);
        return;
      }
      withButton(f.querySelector("button[type=submit]"), async () => {
        const r = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
        fillSettingsForm(r.settings);
        toast("Thresholds saved.");
        announceAlerts(r);
        await refresh();
      });
    });
  }

  // --------------------------------------------------------------- boot
  function start() {
    initCharts();
    bindActions();
    refresh();
    setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });

    // Re-colour charts if the OS switches between light and dark.
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const recolor = () => {
      if (!charts.fill) return;
      charts.category.destroy(); charts.fill.destroy();
      initCharts(); refresh();
    };
    if (mq.addEventListener) mq.addEventListener("change", recolor);
  }

  start();
})();
