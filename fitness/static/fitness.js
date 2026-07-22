// progressive enhancement for the fitness site; every page works without it.
// layers: theme toggle, chart tooltips + crosshair, time-range toggles,
// relative "generated" date. no dependencies.
"use strict";
(() => {
    const store = {
        get(key) {
            try {
                return localStorage.getItem(key) || "";
            } catch {
                return "";
            }
        },
        set(key, val) {
            try {
                val ? localStorage.setItem(key, val) : localStorage.removeItem(key);
            } catch {}
        },
    };

    // ---- theme toggle (light ⇄ dark) ----------------------------------------
    // same html class + localStorage key as the parent site's poxy.js, so one
    // toggle switches the whole site, blog included
    const nav = document.querySelector("nav");
    if (nav) {
        const btn = document.createElement("button");
        btn.className = "theme-btn";
        btn.type = "button";
        const current = () =>
            document.documentElement.className.includes("dark") ? "dark" : "light";
        const label = () => {
            const t = current();
            btn.textContent = t === "dark" ? "☾ dark" : "☀ light";
            btn.setAttribute("aria-label", `colour theme: ${t} (click to switch)`);
        };
        btn.addEventListener("click", () => {
            const next = current() === "dark" ? "light" : "dark";
            document.documentElement.className = "poxy-theme-" + next;
            store.set("poxy-theme", next);
            label();
        });
        label();
        nav.appendChild(btn);
    }

    // ---- relative "generated" date -----------------------------------------
    const gen = document.querySelector("[data-generated]");
    if (gen) {
        const [y, m, d] = gen.dataset.generated.split("-").map(Number);
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const days = Math.round((today - new Date(y, m - 1, d)) / 864e5);
        if (days >= 0)
            gen.textContent +=
                days === 0 ? " (today)" : days === 1 ? " (yesterday)" : ` (${days} days ago)`;
    }

    // ---- shared tooltip state (used by both sections below) ----------------
    const tip = document.createElement("div");
    tip.className = "tip";
    tip.hidden = true;
    document.body.appendChild(tip);
    let hot = null;
    const hideTip = () => {
        tip.hidden = true;
        if (hot) hot.classList.remove("hot");
        hot = null;
        for (const line of document.querySelectorAll(".xhair")) line.remove();
    };

    // ---- time-range toggles on charts with pre-rendered variants -----------
    // one choice drives every chart, so what you see always matches what reloads
    const rangeCharts = [];
    const applyRange = (label) => {
        for (const { variants, buttons } of rangeCharts) {
            const idx = Math.max(0, variants.findIndex((v) => v.dataset.range === label));
            variants.forEach((v, i) => v.classList.toggle("active", i === idx));
            buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(i === idx)));
        }
        hideTip();
    };
    for (const chart of document.querySelectorAll(".chart")) {
        const variants = [...chart.querySelectorAll(":scope > .variant")];
        if (variants.length < 2) continue;
        const group = document.createElement("div");
        group.className = "ranges";
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", "time range");
        const buttons = variants.map((variant) => {
            const b = document.createElement("button");
            b.type = "button";
            b.textContent = variant.dataset.range;
            b.addEventListener("click", () => {
                applyRange(variant.dataset.range);
                store.set("fitness-range", variant.dataset.range);
            });
            group.appendChild(b);
            return b;
        });
        rangeCharts.push({ variants, buttons });
        const h3 = chart.querySelector("h3");
        h3 ? h3.after(group) : chart.prepend(group);
    }
    if (rangeCharts.length) applyRange(store.get("fitness-range"));

    // ---- chart tooltips + crosshair ----------------------------------------
    for (const svg of document.querySelectorAll(".chart svg")) {
        const targets = [];
        for (const el of svg.querySelectorAll("circle, path.bar")) {
            const title = el.querySelector("title");
            if (!title) continue;
            targets.push([el, title.textContent]);
            el.setAttribute("aria-label", title.textContent);
            title.remove(); // native tooltip would fight ours
        }
        if (!targets.length) continue;
        const axis = svg.querySelector("line.axis");

        const show = (e) => {
            let best = null,
                bestD = 26 * 26;
            for (const [el, label] of targets) {
                const r = el.getBoundingClientRect();
                const dx = Math.max(r.left - e.clientX, 0, e.clientX - r.right);
                const dy = Math.max(r.top - e.clientY, 0, e.clientY - r.bottom);
                const d = dx * dx + dy * dy;
                if (d < bestD) [bestD, best] = [d, [el, label]];
            }
            if (!best) return hideTip();
            const [el, label] = best;
            if (hot !== el) {
                if (hot) hot.classList.remove("hot");
                hot = el;
                hot.classList.add("hot");
                for (const line of svg.querySelectorAll(".xhair")) line.remove();
                if (axis && el.tagName === "circle") {
                    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
                    line.setAttribute("class", "xhair");
                    line.setAttribute("x1", el.getAttribute("cx"));
                    line.setAttribute("x2", el.getAttribute("cx"));
                    line.setAttribute("y1", el.getAttribute("cy"));
                    line.setAttribute("y2", axis.getAttribute("y1"));
                    svg.insertBefore(line, svg.firstChild.nextSibling);
                }
            }
            tip.textContent = label;
            tip.hidden = false;
            const vw = document.documentElement.clientWidth;
            tip.style.left = `${Math.min(e.clientX + 14, vw - tip.offsetWidth - 8)}px`;
            tip.style.top = `${Math.max(e.clientY - 34, 8)}px`;
        };
        svg.addEventListener("pointermove", show);
        svg.addEventListener("pointerdown", show);
        // touch fires pointerleave on finger lift; keep the tip up until the
        // next tap outside (handled on document below)
        svg.addEventListener("pointerleave", (e) => {
            if (e.pointerType !== "touch") hideTip();
        });
        svg.addEventListener("pointercancel", hideTip);
    }
    document.addEventListener("pointerdown", (e) => {
        if (!e.target.closest(".chart svg")) hideTip();
    });
})();
