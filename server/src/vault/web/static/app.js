"use strict";
// Bare Reaction Vault web UI. Plain DOM, no build step. Titles and tags can come from remote sites,
// so text is only ever set with textContent / createTextNode, never innerHTML.

const $ = (id) => document.getElementById(id);

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

async function api(path, opts = {}) {
  const init = { credentials: "same-origin", ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, init);
  if (r.status === 401) { showLogin(); throw new Error("unauthorised"); }
  if (r.status === 204) return null;
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
}

function qs(params) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, v);
  const s = u.toString();
  return s ? "?" + s : "";
}

function toast(msg, sticky) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), sticky ? 6000 : 2600);
}

const fmtBytes = (n) => n == null ? "" : n < 1024 ? n + " B" : n < 1048576 ? Math.round(n / 1024) + " KB" : (n / 1048576).toFixed(1) + " MB";
const fmtName = (mime) => ({ "image/webp": "WEBP", "image/gif": "GIF", "image/png": "PNG", "image/jpeg": "JPG", "image/avif": "AVIF", "video/mp4": "MP4", "video/webm": "WEBM" }[mime] || (mime || "").split("/").pop().toUpperCase());

const FILTERS = [
  { key: "all", label: "All", params: {} },
  { key: "animated", label: "Animated", params: { kind: "animated" } },
  { key: "static", label: "Static", params: { kind: "static" } },
  { key: "fav", label: "Favorites", params: { favorite: true } },
  { key: "unsorted", label: "Unsorted", params: { unsorted: true } },
  { key: "small", label: "Under 2 MB", params: { max_bytes: 2097152 } },
  { key: "alpha", label: "Transparent", params: { transparent: true } },
];

const state = {
  view: "vault", // vault | discover | server
  filter: "all",
  collection: null,
  q: "",
  items: [],
  cursor: null, // items cursor or search offset
  hasMore: false,
  collections: [],
  sources: [],
  activeSources: new Set(),
  discoverAnimated: false,
  page: 1,
  picks: JSON.parse(localStorage.getItem("picks") || "[]"),
};

/* ---------- boot / auth ---------- */

function showLogin() { $("app").hidden = true; $("login").hidden = false; }

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await fetch("/api/session", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: $("login-token").value.trim() }),
    }).then((r) => { if (!r.ok) throw new Error("That token was not accepted."); });
    location.reload();
  } catch (err) { $("login-error").textContent = err.message; }
});

async function boot() {
  try { await api("/api/server"); } catch { return; }
  $("login").hidden = true;
  $("app").hidden = false;
  state.sources = await api("/api/discover/sources").catch(() => []);
  state.activeSources = new Set(state.sources.map((s) => s.key));
  await refreshSide();
  renderChips();
  await load(true);
}

/* ---------- sidebar ---------- */

async function refreshSide() {
  const [info, collections] = await Promise.all([api("/api/server"), api("/api/collections")]);
  state.collections = collections;
  const navItem = (label, count, current, onclick, dot) =>
    h("button", { class: "nav-item", type: "button", "aria-current": current ? "true" : "false", onclick },
      dot ? h("span", { class: "dot", style: `background:${dot}` }) : null,
      h("span", { text: label }), count != null ? h("span", { class: "n", text: String(count) }) : null);

  $("nav").replaceChildren(
    navItem("All items", info.items, state.view === "vault" && !state.collection && state.filter === "all", () => go("vault", "all", null)),
    navItem("Favorites", info.favorites, state.view === "vault" && state.filter === "fav", () => go("vault", "fav", null)),
    navItem("Unsorted", info.unsorted, state.view === "vault" && state.filter === "unsorted", () => go("vault", "unsorted", null)),
    navItem("Discover", null, state.view === "discover", () => go("discover")),
    navItem("Server", null, state.view === "server", () => go("server")),
  );
  $("collections").replaceChildren(...collections.map((c) =>
    navItem(c.name, c.count, state.view === "vault" && state.collection === c.id, () => go("vault", "all", c.id), c.color || "#6e8b5a")));

  const emb = info.embeddings || {};
  $("server-card").replaceChildren(
    h("strong", {}, h("span", { class: "live" }), "Server online"),
    h("span", { text: `${info.items.toLocaleString()} items · ${fmtBytes(info.bytes)}` }),
    h("span", { text: `Search: ${emb.state === "ready" ? "by look + text" : emb.state === "loading" ? "model loading…" : "text only"}` }),
    info.jobs && info.jobs.queued ? h("span", { text: `${info.jobs.queued} queued jobs` }) : null,
  );
}

$("new-collection").addEventListener("click", async () => {
  const name = prompt("Collection name");
  if (!name) return;
  try { await api("/api/collections", { json: { name } }); await refreshSide(); }
  catch (e) { toast(e.message); }
});

function go(view, filter = "all", collection = null) {
  state.view = view; state.filter = filter; state.collection = collection;
  state.q = ""; $("q").value = "";
  $("q").placeholder = view === "discover" ? "Search 7TV and more…" : "Search by vibe: smug frog, coping…";
  renderChips(); refreshSide(); load(true);
}

/* ---------- chips ---------- */

function renderChips() {
  if (state.view === "discover") {
    $("chips").replaceChildren(
      ...state.sources.map((s) => h("button", {
        class: "chip", type: "button", "aria-pressed": String(state.activeSources.has(s.key)),
        onclick: () => { state.activeSources.has(s.key) ? state.activeSources.delete(s.key) : state.activeSources.add(s.key); renderChips(); load(true); },
      }, s.label)),
      h("button", { class: "chip", type: "button", "aria-pressed": String(state.discoverAnimated),
        onclick: () => { state.discoverAnimated = !state.discoverAnimated; renderChips(); load(true); } }, "Animated"),
    );
    return;
  }
  $("chips").replaceChildren(...FILTERS.map((f) => h("button", {
    class: "chip", type: "button", "aria-pressed": String(state.filter === f.key),
    onclick: () => { state.filter = f.key; renderChips(); refreshSide(); load(true); },
  }, f.label)));
}

/* ---------- grid ---------- */

let loadSeq = 0;
async function load(reset) {
  const seq = ++loadSeq;
  document.querySelector(".server-view")?.remove();
  if (state.view === "server") { await renderServer(); return; }
  if (reset) { state.items = []; state.cursor = null; state.page = 1; $("grid").replaceChildren(); }
  $("more").hidden = true; $("empty").hidden = true;
  try {
    let data;
    if (state.view === "discover") {
      $("title").textContent = state.q ? "Results" : "Discover";
      if (!state.q) { renderPicks(); $("count").textContent = "Search the web, save what sticks"; $("empty").hidden = false; $("empty").textContent = "Type a search to browse 7TV."; return; }
      data = await api("/api/discover/search" + qs({
        q: state.q, sources: [...state.activeSources].join(","), animated: state.discoverAnimated ? true : undefined,
        similar_to: state.picks.join(","), page: state.page,
      }));
      if (seq !== loadSeq) return;
      state.items = state.items.concat(data.items);
      state.hasMore = data.has_more;
      $("count").textContent = Object.keys(data.errors || {}).length ? `Some sources are unavailable (${Object.keys(data.errors).join(", ")})` : (data.reranked ? "Closest to your picks first" : "Best match first");
    } else {
      const f = FILTERS.find((x) => x.key === state.filter) || FILTERS[0];
      const base = { ...f.params, collection: state.collection || undefined };
      if (state.q) {
        data = await api("/api/search" + qs({ ...base, q: state.q, offset: state.cursor || 0, limit: 60 }));
        state.cursor = (state.cursor || 0) + data.items.length;
        state.hasMore = data.items.length === 60;
        $("title").textContent = `Results for “${state.q}”`;
        $("count").textContent = data.semantic ? "Best match first" : "Text match only";
      } else {
        data = await api("/api/items" + qs({ ...base, cursor: state.cursor || undefined, limit: 60 }));
        state.cursor = data.next_cursor;
        state.hasMore = data.next_cursor != null;
        const col = state.collections.find((c) => c.id === state.collection);
        $("title").textContent = col ? col.name : "Recently saved";
        $("count").textContent = "Newest first";
      }
      if (seq !== loadSeq) return;
      state.items = state.items.concat(data.items);
    }
    renderGrid();
  } catch (e) { if (e.message !== "unauthorised") toast(e.message); }
}

async function renderServer() {
  $("grid").replaceChildren(); $("more").hidden = true; $("empty").hidden = true;
  $("chips").replaceChildren();
  $("title").textContent = "Server"; $("count").textContent = "";
  let info, health;
  try { [info, health] = await Promise.all([api("/api/server"), api("/api/health")]); } catch (e) { toast(e.message); return; }
  const emb = info.embeddings || {};
  const jobs = Object.entries(info.jobs || {});
  const row = (k, v) => h("div", { class: "kv" }, h("span", { class: "muted", text: k }), h("span", { text: String(v) }));
  $("grid").before(h("div", { class: "server-view" },
    row("Status", health.status), row("Version", health.version), row("Schema", health.schema), row("Change rev", info.rev),
    row("Items", info.items.toLocaleString()), row("Stored", fmtBytes(info.bytes)), row("Disk free", fmtBytes(info.disk_free)),
    row("Embedding model", `${emb.model || "none"} (${emb.state || "off"})${emb.error ? " · " + emb.error : ""}`),
    row("Jobs", jobs.length ? jobs.map(([k, v]) => `${k}: ${v}`).join(" · ") : "idle"),
    row("Discover sources", state.sources.map((s) => s.label).join(", ") || "none"),
    h("p", { class: "muted", text: "Create or revoke device tokens on the server: vault token create|list|revoke." })));
}

function renderPicks() {
  const old = document.querySelector(".picks");
  if (old) old.remove();
  if (state.view !== "discover" || !state.picks.length) return;
  $("chips").after(h("div", { class: "picks" },
    h("div", { class: "t" }, h("strong", { text: `Similar to ${state.picks.length} pick${state.picks.length > 1 ? "s" : ""}` }),
      h("div", { class: "muted", text: "Ranks by look, not just tags" })),
    h("button", { class: "btn small", type: "button", onclick: () => { state.picks = []; savePicks(); renderPicks(); load(true); } }, "Clear")));
}
const savePicks = () => localStorage.setItem("picks", JSON.stringify(state.picks));

function renderGrid() {
  const grid = $("grid");
  grid.replaceChildren(...state.items.map(state.view === "discover" ? discoverTile : vaultTile));
  $("more").hidden = !state.hasMore;
  $("empty").hidden = state.items.length > 0;
  if (!state.items.length) $("empty").textContent = state.q ? "Nothing matched." : "Nothing here yet. Add an image, or find some in Discover.";
  renderPicks();
}

function vaultTile(it) {
  const thumb = it.urls.thumb || it.urls.original;
  const img = h("img", { src: thumb, alt: it.title || "reaction", loading: "lazy" });
  const tile = h("button", { class: "tile", type: "button", "aria-label": it.title || "Open item", onclick: () => openDetail(it.id) },
    img, h("span", { class: "badge", text: fmtName(it.mime) }));
  if (it.urls.preview) {
    tile.addEventListener("mouseenter", () => { img.src = it.urls.preview; });
    tile.addEventListener("mouseleave", () => { img.src = thumb; });
  }
  return tile;
}

function discoverTile(c) {
  const saved = c.saved_item_id != null;
  const btn = h("button", {
    class: "saved-btn" + (saved ? " done" : ""), type: "button",
    "aria-label": saved ? "Saved" : "Save to Vault", text: saved ? "✓" : "+",
    onclick: async (e) => {
      e.stopPropagation();
      if (saved || btn.disabled) return;
      btn.disabled = true;
      try {
        const r = await api("/api/discover/save", { json: { source: c.source, source_id: c.source_id } });
        c.saved_item_id = r.item.id;
        toast(r.duplicate ? "Already in your vault" : "Saved to Vault");
        renderGrid(); refreshSide();
      } catch (err) { toast(err.message); btn.disabled = false; }
    },
  });
  return h("div", { class: "tile", title: c.title },
    h("img", { src: c.preview_url, alt: c.title, loading: "lazy", referrerpolicy: "no-referrer" }),
    h("span", { class: "badge left", text: fmtName(c.mime) }),
    h("span", { class: "src", text: `${c.source.toUpperCase()} · ${c.title}` }), btn);
}

$("more").addEventListener("click", () => { if (state.view === "discover") state.page += 1; load(false); });

let searchTimer;
$("q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); load(true); }, 250);
});

/* ---------- detail ---------- */

function closeOnBackdrop(dlg) {
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
}
closeOnBackdrop($("detail")); closeOnBackdrop($("save"));

function tagChip(name, { auto, onremove } = {}) {
  return h("span", { class: "tag" + (auto ? " auto" : "") }, name,
    onremove ? h("button", { type: "button", "aria-label": `Remove tag ${name}`, onclick: onremove }, "×") : null);
}

function tagInput(onadd) {
  const input = h("input", { class: "tag-input", placeholder: "+ tag", "aria-label": "Add tag" });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && input.value.trim()) { e.preventDefault(); onadd(input.value.trim()); input.value = ""; }
  });
  return input;
}

function mediaEl(it) {
  if (it.kind === "video") return h("video", { src: it.urls.original, controls: true, loop: true, muted: true, autoplay: true, playsinline: true });
  return h("img", { src: it.urls.original, alt: it.title || "reaction" });
}

async function openDetail(id) {
  const dlg = $("detail");
  let it;
  try { it = await api(`/api/items/${id}`); } catch (e) { toast(e.message); return; }
  let format = "original";
  let similar = [];
  try { similar = (await api(`/api/items/${id}/similar?limit=12`)).items; } catch { /* optional */ }

  const patch = async (body) => {
    it = await api(`/api/items/${id}`, { method: "PATCH", json: body });
    draw(); load(true); refreshSide();
  };
  const urlFor = (f) => f === "original" ? it.urls.original : it.urls[f];

  async function copy() {
    const url = urlFor(format);
    try {
      const blob = await (await fetch(url)).blob();
      await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
      toast("Copied");
    } catch {
      try { await navigator.clipboard.writeText(new URL(url, location.href).href); toast("Copied link (this browser can't copy this format)"); }
      catch { toast("Copy isn't available here. Use Download."); }
    }
  }

  function draw() {
    const animated = it.kind !== "image";
    const options = [{ key: "original", label: "Original", ext: fmtName(it.mime), size: it.bytes }];
    if (animated) {
      if (it.mime !== "video/mp4") options.push({ key: "mp4", label: "MP4", size: it.renditions.mp4 && it.renditions.mp4.bytes });
      if (it.mime !== "image/gif") options.push({ key: "gif", label: "GIF", size: it.renditions.gif && it.renditions.gif.bytes });
    }
    const picked = state.picks.includes(it.id);
    dlg.replaceChildren(h("div", { class: "sheet-body" },
      h("div", { class: "preview" }, mediaEl(it)),
      h("div", {},
        h("h1", { text: it.title || "Untitled" }),
        h("div", { class: "muted", text: `${it.width}×${it.height} · ${fmtBytes(it.bytes)} · ${fmtName(it.mime)}${it.source !== "upload" ? " · from " + it.source : ""}` })),
      h("div", {}, h("div", { class: "label", text: "Tags" }),
        h("div", { class: "tags" },
          it.tags.map((t) => tagChip(t.name, { auto: t.origin === "auto", onremove: () => patch({ tags: it.tags.filter((x) => x.name !== t.name).map((x) => x.name) }) })),
          tagInput((name) => patch({ tags: [...it.tags.map((x) => x.name), name] })))),
      h("div", {}, h("div", { class: "label", text: "Send as" }),
        h("div", { class: "formats" }, options.map((o) => h("button", {
          class: "format", type: "button", "aria-pressed": String(format === o.key),
          onclick: () => { format = o.key; draw(); },
        }, h("span", { text: o.label }), h("small", { text: o.size ? fmtBytes(o.size) : (o.key === "original" ? "" : "converts on first use") }))))),
      h("div", { class: "row" },
        h("button", { class: "btn primary", type: "button", onclick: copy }, "Copy"),
        h("a", { class: "btn", style: "display:grid;place-items:center;text-decoration:none", href: urlFor(format), download: (it.title || "reaction") + "." + (format === "original" ? fmtName(it.mime).toLowerCase() : format) }, "Download"),
        h("button", { class: "btn", type: "button", "aria-pressed": String(it.favorite), onclick: () => patch({ favorite: !it.favorite }) }, it.favorite ? "★ Favorite" : "☆ Favorite")),
      state.collections.length ? h("div", {}, h("div", { class: "label", text: "Collections" }),
        h("div", { class: "tags" }, state.collections.map((c) => {
          const on = it.collection_ids.includes(c.id);
          return h("button", { class: "chip", type: "button", "aria-pressed": String(on),
            onclick: () => patch({ collection_ids: on ? it.collection_ids.filter((x) => x !== c.id) : [...it.collection_ids, c.id] }) }, c.name);
        }))) : null,
      similar.length ? h("div", {}, h("div", { class: "label", text: "More like this" }),
        h("div", { class: "strip" }, similar.map((s) => h("button", { type: "button", "aria-label": s.title || "similar item", onclick: () => openDetail(s.id) },
          h("img", { src: s.urls.thumb || s.urls.original, alt: "" }))))) : null,
      h("div", { class: "row" },
        h("button", { class: "btn small", type: "button", onclick: () => { state.picks = picked ? state.picks.filter((x) => x !== it.id) : [...state.picks, it.id].slice(-10); savePicks(); draw(); } },
          picked ? "Remove from Discover picks" : "Use as Discover pick"),
        h("button", { class: "btn small danger", type: "button", onclick: async () => {
          if (!confirm("Delete this item?")) return;
          await api(`/api/items/${id}`, { method: "DELETE" }); dlg.close(); toast("Deleted"); load(true); refreshSide();
        } }, "Delete"),
        h("button", { class: "btn small", type: "button", onclick: () => dlg.close() }, "Close"))));
  }
  draw();
  if (!dlg.open) dlg.showModal();
}

/* ---------- save sheet (stage, review, commit) ---------- */

function uploadWithProgress(file) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file, file.name || "pasted.png");
    const xhr = new XMLHttpRequest();
    const name = file.name || "pasted image";
    xhr.open("POST", "/api/ingest");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) toast(`Uploading ${name} · ${Math.round((e.loaded / e.total) * 100)}%`, true);
    };
    xhr.onerror = () => reject(new Error("Upload failed"));
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* not json */ }
      if (xhr.status === 401) { showLogin(); reject(new Error("unauthorised")); }
      else if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body.detail || `${xhr.status} ${xhr.statusText}`));
    };
    xhr.send(fd);
  });
}

async function stageFile(file) {
  return handleStage(await uploadWithProgress(file));
}

async function stageUrl(url) {
  const fd = new FormData();
  fd.append("url", url);
  return handleStage(await api("/api/ingest", { method: "POST", body: fd }));
}

function handleStage(r) {
  if (r.duplicate === "exact") { toast("Already in your vault"); openDetail(r.item.id); return Promise.resolve(); }
  return new Promise((resolve) => openSaveSheet(r, resolve));
}

function openSaveSheet(r, done) {
  const dlg = $("save");
  const meta = r.meta;
  const tags = new Map(r.auto_tags.map((t) => [t.name, true])); // name -> suggested by server
  const collections = new Set();
  let title = meta.suggested_title || "";

  function draw() {
    const near = r.near[0];
    dlg.replaceChildren(h("div", { class: "sheet-body" },
      h("h1", { text: "Save to Vault" }),
      h("div", { class: "preview" }, meta.kind === "video"
        ? h("video", { src: r.file_url, controls: true, loop: true, muted: true, autoplay: true, playsinline: true })
        : h("img", { src: r.file_url, alt: "Preview" })),
      h("div", { class: "muted", text: `${fmtName(meta.mime)} · ${meta.width}×${meta.height} · ${fmtBytes(meta.bytes)}${meta.duration_ms ? " · " + (meta.duration_ms / 1000).toFixed(1) + " s" : ""}` }),
      h("label", {}, h("div", { class: "label", text: "Title" }),
        h("input", { class: "field", value: title, oninput: (e) => { title = e.target.value; } })),
      h("div", {}, h("div", { class: "label", text: r.auto_tags.length ? "Tags from your server" : "Tags" }),
        h("div", { class: "tags" },
          [...tags].map(([name, auto]) => tagChip(name, { auto, onremove: () => { tags.delete(name); draw(); } })),
          tagInput((name) => { tags.set(name.toLowerCase(), false); draw(); }))),
      state.collections.length ? h("div", {}, h("div", { class: "label", text: "Collection" }),
        h("div", { class: "tags" }, state.collections.map((c) => h("button", {
          class: "chip", type: "button", "aria-pressed": String(collections.has(c.id)),
          onclick: () => { collections.has(c.id) ? collections.delete(c.id) : collections.add(c.id); draw(); },
        }, c.name)))) : null,
      near ? h("div", { class: "notice" },
        h("img", { src: near.item.urls.thumb || near.item.urls.original, alt: "" }),
        h("div", { class: "grow" }, h("strong", { text: "Looks a lot like one you have" }),
          h("div", { class: "muted", text: `${near.item.title || "Untitled"} · ${Math.round(near.similarity * 100)}% match` })),
        h("button", { class: "btn small", type: "button", onclick: () => openDetail(near.item.id) }, "View")) : null,
      h("div", { class: "row" },
        h("button", { class: "btn primary", type: "button", onclick: save }, "Save to Vault"),
        h("button", { class: "btn", type: "button", onclick: cancel }, "Cancel"))));
  }

  async function save() {
    try {
      const res = await api(`/api/ingest/${r.staged_id}/commit`, { json: { title, tags: [...tags.keys()], collection_ids: [...collections] } });
      dlg.close("saved");
      toast(res.duplicate ? "Already in your vault" : "Saved to Vault");
      load(true); refreshSide();
    } catch (e) { toast(e.message); }
  }
  async function cancel() {
    dlg.close("cancel");
    api(`/api/ingest/${r.staged_id}`, { method: "DELETE" }).catch(() => {});
  }
  dlg.addEventListener("close", () => done(), { once: true });
  draw();
  dlg.showModal();
}

async function ingestMany(files) {
  for (const f of files) {
    try { await stageFile(f); } catch (e) { if (e.message !== "unauthorised") toast(`${f.name || "file"}: ${e.message}`); }
  }
}

$("add").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => { const files = [...e.target.files]; e.target.value = ""; ingestMany(files); });
$("add-url").addEventListener("click", async () => {
  const url = prompt("Image or video URL");
  if (!url) return;
  try { await stageUrl(url.trim()); } catch (e) { toast(e.message); }
});

let dragDepth = 0;
addEventListener("dragenter", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { dragDepth++; $("drop").hidden = false; } });
addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("drop").hidden = true; });
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", (e) => {
  e.preventDefault(); dragDepth = 0; $("drop").hidden = true;
  if (e.dataTransfer?.files?.length) ingestMany([...e.dataTransfer.files]);
});
addEventListener("paste", (e) => {
  if (e.target instanceof HTMLInputElement) return;
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) ingestMany(files);
});
addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("q").focus(); }
});

boot();
