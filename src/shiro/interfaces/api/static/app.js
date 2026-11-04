// Painel da SHIRO. Só conversa com a API local (mesma origem, cookie da sessão).
// Tudo o que vem do banco entra na página como texto (textContent), nunca como HTML:
// respostas, memórias e resultados de ferramentas podem conter qualquer coisa.

const view = document.getElementById("view");
const statusBar = document.getElementById("status");
const live = document.getElementById("live");
const liveText = document.getElementById("live-text");

const TIERS = { T0: "regras", T1: "local", T2: "nuvem" };
const DECISIONS = { allow: "liberada", confirmed: "confirmada", denied: "negada", blocked: "bloqueada" };
const CHANNELS = { text: "texto", voice: "voz", api: "api", scheduler: "agenda" };
const EVENT_TYPES = { turn: "Turno", tool_call: "Ferramenta", claim_blocked: "Alegação barrada" };
const CATEGORIES = { preferencia: "preferência", pessoa: "pessoa", projeto: "projeto", outro: "outro" };

const clock = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const shortDay = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" });
const fullDate = new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" });
const oneDecimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat("pt-BR");
const dollars = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", maximumFractionDigits: 4 });

class LoggedOut extends Error {}

// ---------------------------------------------------------------- utilidades

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (response.status === 401) throw new LoggedOut();
  if (!response.ok) throw new Error(`A API respondeu ${response.status} em ${path}.`);
  return response.json();
}

const seconds = (ms) => `${oneDecimal.format((ms ?? 0) / 1000)} s`;

function when(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const today = date.toDateString() === new Date().toDateString();
  return today ? clock.format(date) : `${shortDay.format(date)} ${clock.format(date)}`;
}

function argsText(args) {
  const text = Object.entries(args ?? {})
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(", ");
  return text.length > 140 ? `${text.slice(0, 139)}…` : text;
}

function page(title, lede, ...content) {
  return h("section", {}, h("h1", {}, title), lede ? h("p", { class: "lede" }, lede) : null, content);
}

function empty(message, hint) {
  return h("div", { class: "empty" }, h("p", {}, message), hint ? h("p", { class: "hint" }, hint) : null);
}

// ---------------------------------------------------------------- turnos

function tierStats(stats) {
  const tiers = Object.entries(stats.tiers);
  if (!tiers.length) return null;
  const denied = (stats.decisions.denied ?? 0) + (stats.decisions.blocked ?? 0);
  return h(
    "dl",
    { class: "tiers" },
    tiers.map(([tier, s]) =>
      h(
        "div",
        { class: `t-${tier}` },
        h("dt", {}, `${tier}, ${TIERS[tier] ?? tier}`),
        h("dd", {}, h("span", {}, "p50 ", h("b", {}, seconds(s.p50_ms))), h("span", {}, "p95 ", h("b", {}, seconds(s.p95_ms))), h("span", {}, `${integer.format(s.turns)} turnos`)),
      ),
    ),
    h(
      "div",
      { class: denied ? "barred" : "" },
      h("dt", {}, "Ações barradas"),
      h("dd", {}, h("span", {}, h("b", {}, integer.format(denied)), " negadas ou bloqueadas")),
    ),
  );
}

function callItem(call) {
  return h(
    "li",
    {},
    h("span", { class: "tool" }, call.tool_name),
    h("span", { class: "args" }, argsText(call.args)),
    h("span", { class: `chip d-${call.decision}` }, DECISIONS[call.decision] ?? call.decision),
    call.status === "error" ? h("span", { class: "chip d-error" }, "falhou") : null,
  );
}

function turnItem(turn, scale) {
  const fill = h("span");
  fill.style.setProperty("--w", String(Math.min(1, (turn.latency_ms ?? 0) / scale)));
  return h(
    "li",
    { class: `turn t-${turn.tier ?? "x"}` },
    h("time", { class: "when", datetime: turn.created_at }, when(turn.created_at)),
    h(
      "div",
      {},
      h("p", { class: "ask" }, turn.request ?? "(pedido não registrado)"),
      turn.calls.length ? h("ul", { class: "calls" }, turn.calls.map(callItem)) : null,
      h("p", { class: "reply" }, turn.reply),
      h("div", { class: "bar", title: `Resposta em ${seconds(turn.latency_ms)}` }, fill),
    ),
    h(
      "div",
      { class: "meta" },
      h("span", { class: "lat" }, seconds(turn.latency_ms)),
      h("span", { class: "chip" }, `${turn.tier ?? "?"} ${TIERS[turn.tier] ?? ""}`.trim()),
      h("span", {}, CHANNELS[turn.channel] ?? turn.channel),
    ),
  );
}

async function renderTurns() {
  const [turns, stats] = await Promise.all([api("/api/turns?limit=60"), api("/api/stats")]);
  const p95s = Object.values(stats.tiers).map((tier) => tier.p95_ms);
  const scale = Math.max(2000, ...p95s);
  return page(
    "Turnos",
    "O que ela ouviu, por qual camada decidiu, que ferramentas usou e quanto demorou. A barra vai até o p95 mais lento.",
    tierStats(stats),
    turns.length
      ? h("ol", { class: "turns", id: "turn-list" }, turns.map((turn) => turnItem(turn, scale)))
      : h("ol", { class: "turns", id: "turn-list" }, h("li", { class: "empty" }, "Nenhum turno ainda. Fale com ela pela voz ou rode shiro chat.")),
  );
}

// Turno em andamento, enquanto o resultado não chega pelo WebSocket.
function pendingTurn(event) {
  const list = document.getElementById("turn-list");
  if (!list) return;
  list.querySelector(".empty")?.remove();
  const item = h(
    "li",
    { class: "turn pending t-x", id: `pending-${event.trace_id}` },
    h("time", { class: "when" }, clock.format(new Date())),
    h("div", {}, h("p", { class: "ask" }, event.text), h("ul", { class: "calls" }), h("p", { class: "reply" }, "pensando…")),
    h("div", { class: "meta" }),
  );
  list.prepend(item);
}

function pendingCall(event) {
  const calls = document.querySelector(`#pending-${CSS.escape(event.trace_id)} .calls`);
  if (!calls) return;
  calls.append(callItem({ tool_name: event.tool, args: {}, decision: event.decision, status: event.ok ? "ok" : "error" }));
}

// ---------------------------------------------------------------- atividades

async function renderActivities() {
  const items = await api("/api/activities");
  if (!items.length) {
    return page("Atividades", null, empty("Nada pendente.", "Peça: “anota trabalho de física pra sexta às 10h”."));
  }
  const now = Date.now();
  const rows = items.map((item) => {
    const due = item.due_at ? new Date(item.due_at) : null;
    const late = due !== null && due.getTime() < now;
    return h(
      "tr",
      { class: late ? "late" : "" },
      h("td", {}, item.title),
      h("td", { class: "due" }, due ? fullDate.format(due) : item.due_text ?? "sem prazo", late ? ", atrasada" : ""),
      h("td", { class: "muted" }, item.context ?? ""),
    );
  });
  return page(
    "Atividades",
    `${integer.format(items.length)} pendentes, na ordem em que vencem.`,
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Atividade"), h("th", {}, "Prazo"), h("th", {}, "Contexto"))), h("tbody", {}, rows))),
  );
}

// ---------------------------------------------------------------- memória

function factItem(fact) {
  const button = h("button", { type: "button" }, "Esquecer");
  let disarm;
  button.addEventListener("click", async () => {
    if (!button.dataset.armed) {
      button.dataset.armed = "1";
      button.textContent = "Confirmar";
      disarm = setTimeout(() => {
        delete button.dataset.armed;
        button.textContent = "Esquecer";
      }, 4000);
      return;
    }
    clearTimeout(disarm);
    button.disabled = true;
    try {
      await api(`/api/memories/${encodeURIComponent(fact.id)}`, { method: "DELETE", headers: { "X-Shiro": "1" } });
      await show();
    } catch (error) {
      if (error instanceof LoggedOut) return showLoggedOut();
      delete button.dataset.armed;
      button.disabled = false;
      button.textContent = "Tentar de novo";
    }
  });
  const saved = new Date(fact.created_at);
  return h(
    "li",
    {},
    h("div", {}, h("p", {}, fact.content), h("p", { class: "sub" }, `${CATEGORIES[fact.category] ?? fact.category}, guardada em ${fullDate.format(saved)}`)),
    button,
  );
}

async function renderMemories() {
  const facts = await api("/api/memories");
  const lede = "Fatos que você pediu para ela lembrar. Ficam só neste PC e nunca vão para a nuvem.";
  if (!facts.length) return page("Memória", lede, empty("Nada guardado.", "Diga: “lembra que eu prefiro reuniões de manhã”."));
  return page("Memória", lede, h("ul", { class: "facts" }, facts.map(factItem)));
}

// ---------------------------------------------------------------- rotinas

function routineCard(routine) {
  return h(
    "article",
    { class: "routine" },
    h("h2", {}, routine.name),
    routine.description ? h("p", { class: "sub" }, routine.description) : null,
    routine.aliases.length ? h("p", { class: "aliases" }, "Diga ", routine.aliases.map((alias, i) => [i ? " ou " : "", h("q", {}, alias)])) : null,
    h("ol", { class: "steps" }, routine.steps.map((step) => h("li", {}, h("span", { class: "tool" }, step.tool), " ", h("span", { class: "args" }, argsText(step.args))))),
  );
}

async function renderRoutines() {
  const routines = await api("/api/routines");
  const lede = "Sequências de ações que rodam com uma frase só, sem passar pelo modelo.";
  if (!routines.length) {
    return page("Rotinas", lede, empty("Nenhuma rotina configurada.", "Crie em [routines] no shiro.toml. O exemplo está em config/shiro.example.toml."));
  }
  return page("Rotinas", lede, h("div", { class: "routines" }, routines.map(routineCard)));
}

// ---------------------------------------------------------------- auditoria

function auditSummary(event) {
  const p = event.payload ?? {};
  if (event.event_type === "tool_call") {
    const failed = p.ok === false ? ", falhou" : "";
    return `${p.tool} ${DECISIONS[p.outcome] ?? p.outcome ?? ""}${failed}`;
  }
  if (event.event_type === "turn") {
    const tools = p.calls?.length ? `, ${p.calls.join(", ")}` : "";
    return `${p.tier} ${TIERS[p.tier] ?? ""} em ${seconds(p.latency_ms)}${tools}`;
  }
  if (event.event_type === "claim_blocked") return "resposta dizia ter feito algo que não fez";
  return "";
}

function isBarred(event) {
  const outcome = event.payload?.outcome;
  return event.event_type === "claim_blocked" || outcome === "denied" || outcome === "blocked";
}

async function renderAudit() {
  const audit = await api("/api/audit?limit=150");
  const banner = audit.intact
    ? h("p", { class: "integrity" }, "Cadeia íntegra. Cada evento carrega o hash do anterior, e nenhum foi alterado.")
    : h("p", { class: "integrity broken" }, `Cadeia quebrada no evento ${audit.broken_at}. O banco foi alterado por fora da SHIRO.`);
  const events = audit.events.map((event) =>
    h(
      "li",
      {},
      h(
        "details",
        {},
        h(
          "summary",
          {},
          h("span", { class: "seq" }, `#${event.seq}`),
          h("time", { datetime: event.ts }, when(event.ts)),
          h("span", { class: "kind" }, EVENT_TYPES[event.event_type] ?? event.event_type),
          h("span", { class: isBarred(event) ? "what barred" : "what" }, auditSummary(event)),
        ),
        h("pre", {}, JSON.stringify(event.payload, null, 2)),
      ),
    ),
  );
  return page(
    "Auditoria",
    "Registro encadeado de tudo o que ela decidiu e executou. Clique num evento para ver os detalhes.",
    banner,
    events.length ? h("ul", { class: "events" }, events) : empty("Nenhum evento registrado ainda."),
  );
}

// ---------------------------------------------------------------- custos

async function renderUsage() {
  const rows = await api("/api/usage?days=30");
  const lede = "Uso da nuvem nos últimos 30 dias. O que roda no seu PC não custa nada e não aparece aqui.";
  if (!rows.length) return page("Custos", lede, empty("Nenhum uso de nuvem registrado.", "Sem chave do Gemini, tudo roda localmente."));
  const sum = (key) => rows.reduce((total, row) => total + (row[key] ?? 0), 0);
  const numeric = (value) => h("td", { class: "num" }, integer.format(value ?? 0));
  return page(
    "Custos",
    lede,
    h(
      "div",
      { class: "totals" },
      h("span", {}, h("b", {}, integer.format(sum("requests"))), "pedidos"),
      h("span", {}, h("b", {}, integer.format(sum("tokens_in") + sum("tokens_out"))), "tokens"),
      h("span", {}, h("b", {}, dollars.format(sum("est_cost_usd"))), "custo estimado"),
    ),
    h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, h("th", {}, "Dia"), h("th", {}, "Modelo"), h("th", { class: "num" }, "Pedidos"), h("th", { class: "num" }, "Tokens de entrada"), h("th", { class: "num" }, "Tokens de saída"), h("th", { class: "num" }, "Custo"))),
        h(
          "tbody",
          {},
          rows.map((row) =>
            h("tr", {}, h("td", {}, row.day), h("td", {}, `${row.provider}/${row.model}`), numeric(row.requests), numeric(row.tokens_in), numeric(row.tokens_out), h("td", { class: "num" }, dollars.format(row.est_cost_usd ?? 0))),
          ),
        ),
      ),
    ),
  );
}

// ---------------------------------------------------------------- estado e navegação

const SECTIONS = {
  turnos: { title: "Turnos", render: renderTurns },
  atividades: { title: "Atividades", render: renderActivities },
  memoria: { title: "Memória", render: renderMemories },
  rotinas: { title: "Rotinas", render: renderRoutines },
  auditoria: { title: "Auditoria", render: renderAudit },
  custos: { title: "Custos", render: renderUsage },
};

let current = "turnos";
let generation = 0;
let loggedOut = false;

async function loadStatus() {
  const s = await api("/api/status");
  const items = [
    h("span", {}, "Modelo local ", h("b", {}, s.local_model)),
    h("span", {}, s.cloud),
    h("span", {}, "Memória ", h("b", {}, s.memory ?? "desligada")),
    h("span", {}, h("b", {}, integer.format(s.tools.length)), " ferramentas"),
    s.read_only ? h("span", { class: "flag" }, "Modo só leitura: ações pedem confirmação") : null,
    s.problems.map((problem) => h("span", { class: "warn" }, problem)),
    h("span", { class: "version" }, `v${s.version}`),
  ];
  statusBar.replaceChildren(...items.flat().filter(Boolean));
}

async function show() {
  const key = location.hash.slice(1);
  current = key in SECTIONS ? key : "turnos";
  for (const link of document.querySelectorAll(".rail ul a")) {
    if (link.hash === `#${current}`) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = `${SECTIONS[current].title} – Painel da SHIRO`;
  const mine = ++generation;
  try {
    const content = await SECTIONS[current].render();
    if (mine === generation) view.replaceChildren(content);
  } catch (error) {
    if (error instanceof LoggedOut) return showLoggedOut();
    if (mine === generation) view.replaceChildren(h("p", { class: "error" }, `Não deu para carregar: ${error.message}`));
  }
}

function showLoggedOut() {
  loggedOut = true;
  setLive("off", "Sem sessão");
  statusBar.replaceChildren();
  view.replaceChildren(
    h(
      "section",
      { class: "locked" },
      h("h1", {}, "Abra pelo link da SHIRO"),
      h(
        "p",
        { class: "lede" },
        "O painel só entra com o link de uso único que ela gera a cada abertura. Use “Abrir painel” no ícone da bandeja ou rode shiro dashboard no terminal.",
      ),
    ),
  );
}

function setLive(state, text) {
  live.dataset.state = state;
  liveText.textContent = text;
}

// ---------------------------------------------------------------- ao vivo

let refreshTimer;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(show, 400);
}

function onEvent(event) {
  if (event.type === "turn_started") {
    setLive("busy", "Pensando…");
    if (current === "turnos") pendingTurn(event);
  } else if (event.type === "tool_call") {
    if (current === "turnos") pendingCall(event);
  } else if (event.type === "turn_finished") {
    setLive("on", "Ao vivo");
    if (current !== "rotinas") refreshSoon();
  }
}

let retry = 1000;
function connect() {
  if (loggedOut) return;
  const socket = new WebSocket(`ws://${location.host}/api/events`);
  socket.addEventListener("open", () => {
    retry = 1000;
    setLive("on", "Ao vivo");
  });
  socket.addEventListener("message", (message) => onEvent(JSON.parse(message.data)));
  socket.addEventListener("close", () => {
    if (loggedOut) return;
    setLive("off", "Reconectando…");
    setTimeout(connect, retry);
    retry = Math.min(retry * 2, 30000);
  });
}

async function start() {
  window.addEventListener("hashchange", () => {
    show();
    view.focus({ preventScroll: true });
  });
  try {
    await loadStatus();
  } catch (error) {
    if (error instanceof LoggedOut) return showLoggedOut();
    statusBar.replaceChildren(h("span", { class: "warn" }, `Estado indisponível: ${error.message}`));
  }
  await show();
  connect();
}

start();
