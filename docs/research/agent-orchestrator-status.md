# Agent orchestrators: how each one exposes per-agent status to an external bridge

> Research spike for [issue #180](https://github.com/jonocodes/deckd/issues/180):
> show running AI coding agents on deckd as **view-only tiles**, one per agent,
> coloured by state.
> Compiled 2026-10-23. Sources:
>
> - The **local `paseo` 0.12.0 CLI and daemon**. Every Paseo command I ran was read-only, plus one read-only WebSocket subscription, described in §1.
> - **Source code**, pinned to the commits linked below:
>   - Paseo `v0.12.0` (`cafe4b01`)
>   - T3 Code `22dc1dab`
>   - opencode `v1.19.4` (`148842ef`)
>   - Claude Squad `ce1ffb43`
>   - Vibe Kanban `d5cbb538`
>   - Crystal `1e18e0bc`
>   - Nimbalyst `583ae024`
>   - tmux `3.8` (`7f2a35ad`)
>   - Effect `4.0.5` (`7f524e25`)
> - The **official Claude Code hooks, statusline and headless docs** (code.claude.com).
> - **Conductor's** public site and its OpenAPI spec.
>
> Agent names and prompts in CLI output are summarised generically. Credentials are never quoted.
>
> Scope: for each orchestrator, what per-agent states exist and how an outside program reads them: CLI, HTTP/WS, hooks, or files. Covers push vs poll, auth, local vs remote, Linux support, and how hard a ~50-line bridge would be. It ends with a status-entry model that every source maps onto, and a pick for the first bridge.

---

## Bottom line up front

**Build the first bridge against Paseo's daemon WebSocket, from inside deckd's Python daemon. Do not poll the `paseo` CLI.**

- **It works today with no Node.** A ~40-line `aiohttp` client authenticates with Paseo's same-user `local-credential` file. It sends `fetch_agents_request` with `subscribe: {}` and gets a full snapshot of every agent, then live `agent_update` pushes. I ran this read-only against the local daemon (§1.4).
- **Paseo already computes the state we want.** Its protocol package ships a five-bucket derivation (`needs_input > failed > running > attention > done`) that the app uses for its own sidebar ([`agent-state-bucket.ts#L22-L36`][p-bucket]). Our status model below is essentially that.
- **Polling the CLI is costly and incomplete.**
  - Each `paseo` call starts a fresh Node process: about 0.57 s wall and 0.4 s user CPU per call, measured locally.
  - `paseo ls --json` **drops** `pendingPermissions`, `requiresAttention` and `attentionReason` ([`ls.ts#L92-L104`][p-ls]).
  - So "waiting for permission" needs a second `paseo permit ls --json` call. At a 2 s tick, that is roughly 40% of a core spent on spawns.

**Second source: Claude Code's own hooks**, which cover raw `claude` sessions in terminals that Paseo doesn't manage. Hooks can POST JSON straight to an HTTP endpoint (`type: "http"`), so deckd only needs a route. **Third: opencode's `/global/event` SSE stream.** T3 Code has the richest model and is a strong fourth, but it isn't in the user's daily loop.

**Two gotchas apply to most sources:**
- "Idle" doesn't mean nothing is happening. A Paseo agent whose turn ended but whose background subagents are still working reports `idle`. I saw this live (§1.5).
- Most sources can't tell "finished, you haven't looked yet" from "idle". Only Paseo (`requiresAttention`) and Vibe Kanban (`has_unseen_turns`) can.

---

## Comparison

| Tool | Native states (summary) | "Needs input" visible? | Access | Push? | Auth | Local / remote | Linux | ~50-line bridge | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| **Paseo** | `initializing idle running error closed`, plus `pendingPermissions[]` and `requiresAttention` / `attentionReason ∈ finished,error,permission` | **Yes** | Daemon WS `/ws` (`fetch_agents_request` with `subscribe`); daemon plugins (`server.on`); CLI `ls` / `permit ls` / `inspect` | **Yes** (WS, plugin). CLI is poll | Optional password; same-user `local-credential` token; `Host` allowlist | Local by default; remote via TCP/relay/SSH | Yes | **Easy** (verified) | [lifecycle][p-life], [snapshot schema][p-snap], [bucket][p-bucket] |
| **T3 Code** | run: `preparing queued starting running waiting completed interrupted failed cancelled rolled_back`; thread adds `idle`; `pendingRuntimeRequest.kind` | **Yes** | HTTP `GET /api/orchestration/shell`; WS `orchestration.subscribeShell` (Effect RPC) | **Yes** (WS) | Bearer token from `t3 auth session issue` | Loopback by default | Yes (deb/AUR/AppImage) | Easy to poll; moderate to push (needs per-chunk `Ack`) | [run status][t3-run], [shell status][t3-shell] |
| **opencode** | `SessionStatus.type ∈ idle busy retry`; events `permission.asked`, `question.asked`, `session.error` | **Yes** | `opencode serve` HTTP + SSE `/global/event`; in-process plugin | **Yes** (SSE) | Optional HTTP Basic (`OPENCODE_SERVER_PASSWORD`) | `127.0.0.1` by default | Yes | **Easy** | [status][oc-status], [SSE][oc-global] |
| **Claude Code hooks** | Events, not states: `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `Notification`, `Stop`, `StopFailure`, `SessionEnd`, … | **Yes** (`PermissionRequest`, instant) | `command` / `http` hooks in `settings.json` | **Yes** | Whatever headers you configure | Hook runs locally, POSTs anywhere | Yes | **Very easy** | [hooks ref][cc-hooks] |
| **Vibe Kanban** | `ExecutionProcessStatus ∈ running completed failed killed`; summary has `has_pending_approval`, `has_unseen_turns` | Yes | HTTP + WS (JSON Patch) + SSE on a random port (port file) | Yes | None for local requests | Localhost | Yes | Easiest, but the project is **sunsetting** | [proc status][vk-proc], [summary][vk-sum] |
| **Nimbalyst** (Crystal successor) | `idle running waiting_for_input error` | Yes | Read-only SQLite / `nim session list --json` | No (poll) | File permissions | Local | Yes | Easy | [SessionStatus][nb-status] |
| **Claude Squad** | `Running Ready Loading Paused` (Go iota) | **No** | None. State file is not written on status change; you'd scrape tmux yourself | No | n/a | Local | Yes | Moderate, fragile | [enum][cs-enum], [scraper][cs-scrape] |
| **Conductor** | cloud session `idle working error` | No | Cloud REST API (beta) only; desktop app has no documented local API | No (poll) | API key | Cloud only | App is **macOS-only** | Cloud only | [site][cond-site], [API docs][cond-api] |
| **Crystal** | memory: `initializing ready running waiting stopped completed_unviewed error`; DB: `pending running stopped completed failed` | Lost on disk | SQLite only | No | n/a | Local | Yes | Not worth it (deprecated Feb 2026) | [types][cr-types] |
| **tmux** (fallback) | Per window/pane flags: activity, bell, silence, dead; OSC 133 command state | Only via bell heuristic | `alert-*` hooks, `set-hook -B`, control mode `refresh-client -B`, `list-windows -F` | Yes (hooks / control mode) | Unix socket permissions | Local (or SSH) | Yes | Easy, but states are heuristics | [tmux.1][tm-man] |

---

## 1. Paseo (`getpaseo/paseo`, local CLI 0.12.0): the user's daily driver

Pinned source: `P` = <https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b> (tag `v0.12.0`, matching the installed `paseo --version` → `0.12.0`). The Nix wrapper runs `node … @getpaseo/cli/bin/paseo`, so every CLI call is a full Node start.

### 1.1 Status model

- **Lifecycle enum:** `initializing`, `idle`, `running`, `error`, `closed` ([`packages/protocol/src/agent-lifecycle.ts#L1-L7`][p-life]).
  - `closed` means "persisted, resumable, no live provider runtime" ([`docs/agent-lifecycle.md#L5-L13`][p-lifedoc]).
  - The flow is `initializing → idle → running → idle (or error → closed)`.
- **Permission waits are not a lifecycle status.** An agent waiting for approval stays `running` and gains an entry in `pendingPermissions`.
  - `onStreamPermissionRequested` adds the request, sets attention `"permission"` on the first one, and re-emits state ([`agent-manager.ts#L4728-L4739`][p-perm]).
- **Attention (finished but not yet seen):** `requiresAttention` / `attentionReason ∈ "finished" | "error" | "permission"` / `attentionTimestamp` sit on the agent snapshot ([`messages.ts#L825-L839`][p-snap]).
  - `finished` is set on a `running → idle` transition. `error` is set on entering `error` ([`agent-manager.ts#L5000-L5020`][p-attn]).
  - Attention is cleared only by an explicit `clear_agent_attention` RPC, which the app sends when you view the agent ([`agent-manager.ts#L2223-L2230`][p-clear]).
  - **No other source evaluated has this distinction this cleanly.**
- **Paseo's own roll-up, the one to copy:** `deriveAgentStateBucket` maps the above to `needs_input | failed | running | attention | done` ([`agent-state-bucket.ts#L22-L36`][p-bucket]; enum at [`messages.ts#L1270-L1276`][p-bucketenum]). The rules, in order:
  1. Pending permission or `attentionReason=permission` → `needs_input`
  2. `status=error` or `attentionReason=error` → `failed`
  3. `running` → `running`
  4. `requiresAttention` → `attention`
  5. Anything else → `done`

### 1.2 Access paths

**a) CLI (poll).** All of these were run locally and are read-only.
- `paseo ls --json`
  - Default scope is active (non-archived, non-background) agents. `-g` lists all directories; `-a` adds archived and background agents ([`ls.ts#L138-L166`][p-lsopts]).
  - Output has exactly `id, shortId, name, provider, thinking, status, cwd, created` ([`ls.ts#L28-L37`][p-lsitem]). `created` is a relative string ("9 hours ago"), so it can't be used as a timestamp.
  - Locally, `ls` returned 21 agents (`idle` / `closed`). `ls -g -a` returned 282 (`closed` 257, `idle` 25).
- `paseo inspect <id> --json` returns PascalCase fields, including `Status`, `PendingPermissions`, `UpdatedAt` and `LastUsage`.
  - It does **not** include `requiresAttention`. It is also one process per agent.
- `paseo permit ls --json` lists pending permissions across agents. It returned `[]` here.
- `paseo wait <id>` blocks until one agent is idle. `paseo attach <id>` streams one agent's output. `paseo logs -f --filter permissions <id>` follows one agent's timeline.
  - All three are per-agent, so they are no use for a fleet view.
- **Cost:** each call measured about 0.57 s wall and 0.39–0.41 s user CPU. Showing "needs input" takes two calls (`ls` + `permit ls`) per tick, and "finished but unseen" is not available from the CLI at all.

**b) Daemon WebSocket (push). This is the recommended path.**
- **Endpoint:** WS path `/ws` ([`websocket-server.ts#L823-L827`][p-wspath]). There is no HTTP agent-list endpoint: `/api/status` only returns server info ([`bootstrap.ts#L804-L812`][p-apistatus]), and `/api/health` is unauthenticated.
- **Handshake:**
  - Send `{"type":"hello","clientId":…,"clientType":"cli","protocolVersion":1,"auth":{…}}`.
  - `auth` is either `{"kind":"password",…}` or `{"kind":"localCredential","token":…}` ([`messages.ts#L7543-L7553`][p-hello]).
  - The server replies with a `session` / `status` message carrying `status:"server_info"` (including `version`), or with `hello.rejected` (`password_required` / `incorrect_password` / `incompatible_protocol`) ([`messages.ts#L7584-L7598`][p-env]).
- **Subscription:**
  - Send `{"type":"session","message":{"type":"fetch_agents_request","requestId":"r1","subscribe":{}}}`.
  - Optional `filter` fields: `statuses`, `includeArchived`, `requiresAttention`, `labels`, `includeBackground` ([`messages.ts#L908-L918`][p-filter]). Optional `page.limit` (max 200) ([`messages.ts#L1241-L1268`][p-fetch]).
  - The reply `fetch_agents_response` carries `entries[].agent` (a full `AgentSnapshotPayload`) and a `subscriptionId` ([`messages.ts#L4178-L4187`][p-fetchresp]).
  - After that, `agent_update` arrives as `{kind:"upsert", agent}` or `{kind:"remove", agentId}` ([`messages.ts#L4096-L4115`][p-update]).
  - `agent_permission_request` and `agent_permission_resolved` also exist ([`messages.ts#L5150-L5167`][p-permmsg]).
- **Liveness:** the client may send top-level `ping`. A raw socket that never pings is never put under the idle lease, so it isn't dropped for that ([`docs/architecture.md`][p-arch], "WebSocket protocol").

**c) Daemon plugin (push, in-process).**
- An `index.server.ts` can call `server.on(…)` for `agent.created`, `agent.turn_started`, `agent.turn_ended` (outcome `completed | failed | canceled`), `agent.permission_requested`, `agent.permission_resolved`, `agent.closed` and `agent.archived` ([`packages/plugin/src/server/lifecycle.ts#L42-L66`][p-plughooks]).
- These hooks "run on the daemon while the plugin is enabled, even with no app connected" ([`public-docs/plugins/reference.md#L539-L560`][p-plugref]).
- The callback context includes a `PaseoApi`, so a plugin could also list agents for an initial snapshot.
- Plugins are trusted, unsandboxed TypeScript, and installed plugins need `pluginsEnabled: true` ([`docs/plugins.md#L7`][p-plugtrust]).
- This is viable, but it splits the bridge across two languages and two repos. The WS client gives the same data from Python.

**d) Files on disk (inotify-able, not recommended).**
- Agent records are JSON at `$PASEO_HOME/agents/<project>/<id>.json`, with `lastStatus`, `requiresAttention`, `attentionReason` and `updatedAt` (checked locally).
- **Pending permissions are not persisted.**
- The schema is internal ([`agent-storage.ts`][p-storage]), and docs say transitions "persist to disk" ([`docs/agent-lifecycle.md#L13`][p-lifedoc]).
- Usable as a fallback, but it cannot show `needs_input`.

**e) Paseo already consumes Claude hooks for terminals.**
- Paseo terminals get `PASEO_TERMINAL_ACTIVITY_URL` and a token. `paseo hooks <agent> <event>` maps Claude's `UserPromptSubmit → running`, `Stop`/`StopFailure`/`SessionEnd → idle` and `Notification(idle_prompt) → needs-input`, then posts the result to the daemon ([`docs/terminal-activity.md#L39-L54`][p-termact]).
- Terminal activity states are `idle | working | attention` with reasons `finished | needs_input` ([`terminal-activity.ts#L3-L4`][p-termstates]).
- This is internal plumbing (the `paseo hooks` help text is "Record agent hook activity"), not an external API. It does confirm the hooks-to-state mapping in §4.

### 1.3 Auth model

- **Binding and password.** The daemon binds `127.0.0.1` by default. A password is optional (`auth.password` or `PASEO_PASSWORD`, stored bcrypt-hashed) and is sent in `hello`. HTTP routes use a bearer header ([`SECURITY.md#L49-L53`][p-sec]).
- **Same-user credential.** The daemon writes a fresh `$PASEO_HOME/local-credential` (mode 0600, a 43-char base64url token) on every run and deletes it on shutdown ([`local-credential.ts#L10-L40`][p-cred]). Any same-user process can use it, which is what makes a deckd bridge possible without asking the user for the password.
  - **The bridge must re-read the file on every reconnect**, because a daemon restart rotates it.
- **Host and Origin checks.** `Host` header allowlist: `localhost`, `*.localhost` and literal IPs by default ([`SECURITY.md#L73`][p-sec73]). Origin is checked only when present; a non-browser client sends none ([`websocket-server.ts#L895-L912`][p-origin]).
- **Local daemon here.** `paseo status` reports a live `listen` that differs from the configured listen because env vars override it, and the daemon has a password set. Unauthenticated `GET /api/status` returns **401**; `/api/health` returns 200. The `local-credential` path works regardless.

### 1.4 Live verification (read-only)

A throwaway script ran with deckd's own venv Python and `aiohttp` (not committed). It:
1. Read `~/.paseo/local-credential`.
2. Connected to `ws://127.0.0.1:6767/ws` and sent `hello` with `localCredential`.
3. Waited for `server_info`, then sent `fetch_agents_request{subscribe:{}}`.

Result: `fetch_agents_response` with 23 agent snapshots and a `subscriptionId`. Each snapshot had `status`, `pendingPermissions`, `requiresAttention` and `attentionReason` (two agents showed `attentionReason: finished`).

I left the socket open for a few minutes. It received live pushes when another agent ran a turn:
- `agent_update upsert … status=running` (three times)
- then `agent_update upsert … status=idle attentionReason=finished`

So push is confirmed end to end. The same socket also carried about 300 `agent_stream` timeline frames in that window. A bridge should drop them.
- **Unverified:** whether a `hello` capability (`explicitEventSubscriptions` / `selectiveAgentTimeline`, [`messages.ts#L7555-L7568`][p-hello]) suppresses them at the source.

**Gotcha found:** if the `session` message is sent before the server has processed `hello`, the server closes the socket with **code 4002, "Session message before hello"**. The bridge must wait for the first `server_info` frame before subscribing. The first naive run worked only by luck of timing.

### 1.5 Caveats

- **`idle` is not "nothing happening".** The Paseo agent that commissioned this research showed `idle` (and `requiresAttention: false`) for the whole time this background research subagent was working.
  - Paseo's docs describe a related failure: if the provider runtime dies between turns, "nothing is watching, so the agent sits at `idle` looking healthy while its background work is gone" ([`docs/agent-lifecycle.md#L30-L37`][p-lifedoc35]). Background work that is still alive is likewise not reflected in `status`. That second point is my observation; the docs don't say it.
  - Claude Code's `Stop` hook does expose `background_tasks[]`, so the Claude-hooks source could fill this gap (§4).
- **The protocol is first-party but not a documented public API.** `protocolVersion: 1` and many `COMPAT(...)` markers mean the bridge should log `server_info.version` and fail soft on schema drift. The published TS SDK `@getpaseo/client` 0.12.0 (npm `latest`; `0.13.0-beta.2` on `beta`) is the supported surface, but it is Node.
- `closed` agents are numerous (257 here), so use the default scope or `filter.includeArchived: false`. Treat `closed` as "hide" or `offline`, not as a tile.

---

## 2. T3 Code (`pingdotgg/t3code`)

Pinned: `T3` = <https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc>

### States

| Status set | Values | Source |
|---|---|---|
| Run status | `preparing, queued, starting, running, waiting, completed, interrupted, failed, cancelled, rolled_back` | [`orchestrationV2.ts#L453-L464`][t3-run] |
| Thread shell status | `idle` plus the run statuses | [`#L1789-L1792`][t3-shell] |
| Provider session status | `starting, ready, running, waiting, stopped, error` | [`#L757-L768`][t3-sess] |

- **Pending input** is `pendingRuntimeRequest: {id, kind, createdAt, blocking?} | null` ([`#L1795-L1802`][t3-shell]).
  - `kind` covers `command, file-read, file-change, mcp-elicitation, permission` ([`providerPolicy.ts#L38-L44`][t3-kind]) plus `dynamic_tool_call, user_input, auth_refresh`.
- **Trap:** `waiting` on its own is ambiguous. A finished provider turn is first stored as `waiting` and becomes `completed` only after checkpoint capture ([`RunExecutionService.ts#L695-L696`][t3-wait1], [`CheckpointCaptureService.ts#L209-L216`][t3-wait2]).
  - The official UI decides "pending approval" or "awaiting input" from `pendingRuntimeRequest`, not from `status` ([`client-runtime/src/state/models.ts#L305-L311`][t3-ui]).
  - Its sidebar priority is Pending Approval > Awaiting Input > Failed > Working > Waiting > Plan Ready > Completed ([`Sidebar.logic.ts#L579-L603`][t3-side]).

### Access

- **Server location.** It binds `127.0.0.1:3773` by default ([`apps/server/src/config.ts#L17`][t3-port]). The real origin is written to `~/.t3/userdata/server-runtime.json`.
- **Auth.** Mint a token with `t3 auth session issue --scope orchestration:read --token-only` (default TTL 30 days) ([`cli/auth.ts#L159-L190`][t3-auth]). There is no Origin allowlist on `/ws`; auth alone gates it.
- **Poll:** `GET /api/orchestration/shell` with `Authorization: Bearer …` and `x-t3-orchestration-protocol: 2` returns `{snapshotSequence, threads[], archivedThreads[], projects[]}` ([`environmentHttp.ts#L680-L684`][t3-http]).
- **Push:**
  - Connect to `ws://…/ws?orchestrationProtocol=2` (without it you get 426) and send the Effect-RPC request `{"_tag":"Request","id":"1","tag":"orchestration.subscribeShell","payload":{},"headers":[]}`.
  - Stream items are `snapshot`, `thread.updated` (a full ThreadShell), `thread.removed`, and so on ([`orchestrationV2.ts#L1906-L1937`][t3-stream]).
  - **You must send `{"_tag":"Ack","requestId":"1"}` after every `Chunk`**, or the server stalls the stream ([Effect `RpcServer.ts#L443-L450`][ef-ack]).
- **Linux:** first-class (deb, AUR, AppImage, plus a `t3 service install` systemd unit).
- **Unverified:** I didn't run a live T3 server, so the exact JSON encoding of fields such as `DateTimeUtc` was not observed.

---

## 3. opencode (`anomalyco/opencode`, formerly `sst/opencode`)

Pinned: `OC` = <https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801> (v1.19.4)

### States and events

- **SessionStatus** is a union keyed by `type`: `"idle"`, `"busy"`, `"retry"`. `retry` carries `attempt`, `message`, `next` and an optional `action` ([`packages/schema/src/session-status-event.ts#L9-L32`][oc-status]).
- **Status events:**
  - `session.status {sessionID, status}`.
  - `session.idle {sessionID}`, which is marked deprecated ([`#L35-L49`][oc-status]).
  - An unknown session is treated as idle, and idle sessions are dropped from the in-memory map ([`session/status.ts#L30-L48`][oc-statusimpl]).
- **Waiting-for-user events:**
  - `permission.asked {id, sessionID, permission, patterns, …}` and `permission.replied {…, reply: once|always|reject}` ([`v1/permission.ts#L27-L66`][oc-perm]).
  - `question.asked`, `question.replied` and `question.rejected` ([`v1/question.ts#L58-L60`][oc-q]).
- **Errors:** `session.error {sessionID?, error}` ([`v1/session.ts#L651-L657`][oc-err]).

### Access

- **SSE endpoint.** `GET /global/event` streams every project. Each frame is `data: {"directory","project","workspace","payload":{"id","type","properties"}}`, with a 10 s `server.heartbeat` ([`httpapi/handlers/global.ts#L25-L58`][oc-global]). The per-project form is `GET /event?directory=…`.
- **Snapshot endpoints.** `GET /session/status` returns non-idle sessions. `GET /permission` and `GET /question` list pending requests.
- **Host and port.** Default host is `127.0.0.1`. Port `0` means "try 4096, else any free port" ([`cli/network.ts#L6-L16`][oc-net], [`server/server.ts#L117-L122`][oc-port]).
- **Auth.** HTTP Basic, only when `OPENCODE_SERVER_PASSWORD` is set; the username defaults to `opencode` ([`server/auth.ts#L17-L42`][oc-auth]). A `?auth_token=` query parameter works for SSE clients.
  - **Unverified:** whether `/global/*` sits behind the same Basic auth.
- **Gotcha: the plain TUI has no port.** `opencode` talks to its worker in-process. It only listens when `--port`, `--hostname` or `--mdns` is passed on the command line ([`cli/cmd/tui.ts#L271-L288`][oc-tui]). The docs saying the TUI "randomly assigns a port" contradict the code.
  - So bridging needs either `opencode --port 4096`, or `opencode serve` plus `opencode attach`, or a `~/.config/opencode/plugins/*` plugin exporting `event: async ({event}) => …`.
  - Paseo-managed opencode agents are already visible through Paseo, which avoids this.
- **Churn ahead:** the unreleased 2.x `dev` branch reshapes `permission.asked`.

---

## 4. Claude Code hooks (official reference: <https://code.claude.com/docs/en/hooks>)

### Handler types

- There are five: `command`, `http`, `mcp_tool`, `prompt`, `agent`.
- **`type: "http"` POSTs the event's JSON input to a URL.** Headers support `$VAR` interpolation (allow-listed via `allowedEnvVars`).
- Non-2xx responses and connection failures are non-blocking, so a down deckd never stalls Claude.
- **Exception:** `SessionStart` supports only `command` / `mcp_tool`, so use `curl` from a command hook there ([hooks ref][cc-hooks]).

### Fields

- Common input: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode`, plus `agent_id` / `agent_type` inside subagents.

### Events that matter for a status tile

| Event | Fires when | Status meaning |
|---|---|---|
| `SessionStart` | Session begins or resumes. `source ∈ startup, resume, clear, compact, fork` | Tile appears (idle) |
| `UserPromptSubmit` | A prompt is submitted | working |
| `PreToolUse` / `PostToolUse` | Around each tool call | working (and clears needs_input) |
| `PermissionRequest` | **Immediately** when a permission dialog is about to show | needs_input |
| `Notification` | `notification_type ∈ permission_prompt, idle_prompt, elicitation_dialog, agent_needs_input, agent_completed, …` | needs_input or done. **Delayed**, see below |
| `Stop` | The main agent finishes responding. Not fired on user interrupt. Carries `background_tasks[]` | done (or still working if `background_tasks` is non-empty) |
| `StopFailure` | Turn ends on an API error. `error ∈ rate_limit, overloaded, authentication_failed, billing_error, server_error, …` | error |
| `SubagentStart` / `SubagentStop` | Subagent lifecycle | optional child tiles |
| `SessionEnd` | `reason ∈ clear, resume, logout, prompt_input_exit, other`. Budget is about 1.5 s | Tile removed / offline |

### Timing and gaps

- **Notification timing is a trap.** `permission_prompt` fires only after the prompt has waited **about 6 s**, and `idle_prompt` about **60 s** after Claude finishes. Use `PermissionRequest` for instant "needs input" and `Stop` for "done".
- Paseo's own terminal mapping uses the slower `idle_prompt` (§1.2e).
- There is no "permission answered" hook. Infer it from the next `PostToolUse`, or from `PermissionDenied` (auto-mode denials only). This inference is mine; the docs don't state it.

### Other surfaces

- The **statusline** command receives JSON, but it has no busy/idle/waiting field and is hidden during permission prompts ([statusline docs][cc-status]).
- `claude -p --output-format stream-json` covers headless runs only ([headless docs][cc-headless]).
- OpenTelemetry events exist but need a collector ([monitoring docs][cc-otel]).
- `preferredNotifChannel: "terminal_bell"` rings the terminal bell, which pairs with tmux `monitor-bell` ([terminal config][cc-term]).
- Local version: `claude --version` → 2.1.303.

---

## 5. Others

### Vibe Kanban (`BloopAI/vibe-kanban`, `d5cbb538`)

- **Sunsetting** ([announcement 2026-04-10][vk-shut]). It continues as community open source; local workspaces still work.
- **States:**
  - `ExecutionProcessStatus ∈ running, completed, failed, killed` ([`execution_process.rs#L39-L48`][vk-proc]).
  - `ApprovalStatus ∈ pending, approved, denied, timed_out` ([`utils/src/approvals.rs#L30-L41`][vk-appr]).
  - `POST /api/workspaces/summaries` returns `has_pending_approval`, `latest_process_status` and `has_unseen_turns` ([`workspace_summary.rs#L25-L54`][vk-sum]).
- **Push:** `GET /api/workspaces/streams/ws` and `/api/approvals/stream/ws` send JSON Patch; `GET /api/events` is SSE.
- **Port and auth:** binds `127.0.0.1` on a random port, recorded in `$TMPDIR/vibe-kanban/vibe-kanban.port` ([`port_file.rs#L13-L29`][vk-port]). No auth for local requests; Origin is checked only if present ([`middleware/origin.rs#L41-L81`][vk-origin]).

### Nimbalyst (`Nimbalyst/nimbalyst`, `583ae024`), Crystal's successor

- **States:** `SessionStatus ∈ idle, running, waiting_for_input, error` ([`SessionState.ts#L10-L14`][nb-status]). Tool-permission and plan-exit requests set `waiting_for_input` ([`MessageStreamingHandler.ts#L926-L940`][nb-wait]).
- **Persistence:** status is written straight to SQLite `ai_sessions.status` ([`SessionStateManager.ts#L458-L469`][nb-sql]). On Linux the DB is `~/.config/@nimbalyst/electron/sqlite-db/nimbalyst.sqlite`, in WAL mode, so a read-only connection is safe.
- **Official CLI:** `nim session list --json` does the same query ([`sessionDoc.ts#L25-L49`][nb-cli]).
- **Poll only.** In-process events are not exposed.
- **Unverified:** whether its loopback MCP-HTTP server has a status tool.

### Crystal (`stravu/crystal`, `1e18e0bc`)

- Deprecated in February 2026 in favour of Nimbalyst.
- **States:** in memory, `initializing, ready, running, waiting, stopped, completed_unviewed, error` ([`main/src/types/session.ts#L6`][cr-types]). The DB stores only `pending, running, stopped, completed, failed`, and `waiting` is persisted as `running` ([`sessionManager.ts#L241-L273`][cr-persist]).
- Not worth bridging.

### Claude Squad (`smtg-ai/claude-squad`, `ce1ffb43`)

- **States:** `Running, Ready, Loading, Paused` ([`session/instance.go#L18-L29`][cs-enum]).
- **Status is inferred** by hashing `tmux capture-pane` output every 500 ms: changed → `Running`, unchanged → `Ready` ([`app/app.go#L238-L252`][cs-scrape]). Prompt detection is a string match ([`tmux.go#L246-L267`][cs-prompt]).
- **No needs-input state, no API.** `~/.claude-squad/state.json` is not rewritten on status change ([`instance.go#L193-L195`][cs-set]).
- A bridge would re-implement the scrape (sessions are named `claudesquad_<title>`). That is doable, but brittle across CLI UI changes.

### Conductor (conductor.build)

- **The desktop app is macOS-only** ("Run parallel coding agents on your Mac", [site][cond-site]). It has no documented local API, CLI or hook.
- **Cloud API (beta) for cloud workspaces only:** `GET https://api.conductor.build/v0/sessions/{id}/status` returns `status ∈ idle, working, error` plus `lastError`. Poll only, bearer API key ([API docs][cond-api], `openapi.json`). It has no waiting-for-permission state.
- **Not relevant for a Linux desk.**

### tmux 3.8 (fallback for anything in a terminal)

- **Options and hooks.** Window options are `monitor-activity`, `monitor-bell` and `monitor-silence <secs>`. The matching hooks are `alert-activity`, `alert-bell` and `alert-silence`.
  - The hooks fire only when the matching `*-action` applies. The default `other` skips the current window. They fire once until the flag clears ([`tmux.1#L6476-L6487`][tm-hooks], [`alerts.c#L220-L285`][tm-alerts]).
  - 3.8 adds per-pane `pane-activity`, `pane-bell` and the OSC 133 hooks `pane-command-started` / `pane-command-finished`.
- **Push options.**
  - `set-hook -B name:what:format` re-evaluates a format once a second ([`tmux.1#L6599-L6640`][tm-sethook]).
  - Control mode is cleaner: `tmux -C attach`, then `refresh-client -B agent:%*:#{window_bell_flag}|#{window_silence_flag}|#{pane_title}`. Changes arrive as `%subscription-changed …`, at most once a second ([`tmux.1#L1444`][tm-refresh]).
- **Poll:** `tmux list-windows -a -F '#{session_name}:#{window_index} #{window_activity_flag}#{window_bell_flag}#{window_silence_flag}'`.
- **Limits.** Agent TUIs redraw constantly (spinners), so "activity" is nearly always on. Silence works as an idle proxy and bell as a needs-input proxy, the latter only with Claude's `terminal_bell`. tmux can't tell waiting from idle on its own.
- **Unverified:** whether Claude Code and opencode set `pane_title` or emit OSC 133.
- Local version: `tmux -V` → 3.8.

---

## 6. Recommended source-agnostic status entry

One entry per agent, keyed by `(source, id)`. The bridge for each source only translates into this shape; deckd's tile renderer never sees native states.

| Field | Type | Notes |
|---|---|---|
| `source` | `str` | `"paseo"`, `"claude-code"`, `"opencode"`, `"t3code"`, `"tmux"`, … |
| `id` | `str` | Source-scoped stable id (Paseo agent id, Claude `session_id`, opencode `sessionID`, T3 thread id, tmux `%pane`) |
| `title` | `str \| None` | Human label (Paseo `title`, T3 thread title, Claude `session_title`). Fall back to `basename(cwd)` |
| `cwd` | `str \| None` | For a short project label and grouping |
| `state` | `AgentState` | See the enum below |
| `detail` | `str \| None` | Short reason: tool awaiting approval, error code (`rate_limit`), retry attempt. Truncate, and never put prompts here |
| `since` | `datetime` | When `state` was entered (drives a "waiting 3m" subtitle and pulse) |
| `seen_at` | `datetime` | Last time the source confirmed this entry. Older than a per-source TTL means the bridge marks it `offline` |
| `parent_id` | `str \| None` | Optional, for subagents (Paseo `paseo.parent-agent-id`, Claude `agent_id`). The POC can ignore it |

**`AgentState` enum (6 values, listed in tile-priority order for any roll-up):**

| Value | Meaning | Suggested colour |
|---|---|---|
| `needs_input` | Blocked on the human: permission, question, elicitation | amber, pulsing |
| `error` | Last turn failed or the runtime died | red |
| `working` | A turn is in progress (includes starting, queued, retrying) | blue |
| `done` | Turn finished and not yet acknowledged ("your move") | green |
| `idle` | Alive, nothing pending | grey |
| `offline` | Closed, ended, stale or unreachable | dim / hidden |

This is Paseo's `deriveAgentStateBucket` order (`needs_input > failed > running > attention > done`) with `done` / `idle` renamed for clarity and `offline` added for liveness. Sources that cannot track "seen" emit `done` on turn completion. deckd can decay `done → idle` when the tile is tapped, or after a timeout. That is a deckd-side policy, not a bridge concern, and it keeps tiles view-only toward the source.

### Native → enum mapping

| Source | `needs_input` | `error` | `working` | `done` | `idle` | `offline` |
|---|---|---|---|---|---|---|
| **Paseo** (snapshot) | `pendingPermissions.length>0` or `attentionReason=="permission"` | `status=="error"` or `attentionReason=="error"` | `status ∈ {running, initializing}` | `status=="idle"` and `requiresAttention` (`finished`) | `status=="idle"` | `status=="closed"`, `archivedAt` set, or `agent_update{kind:"remove"}` |
| **T3 Code** (ThreadShell) | `pendingRuntimeRequest != null` (any kind except `auth_refresh`; `user_input` only if `blocking !== false`) | `status=="failed"` or `lastError` | `status ∈ {preparing, queued, starting, running}`, or `waiting` with no pending request | `status=="completed"` | `status ∈ {idle, interrupted, cancelled, rolled_back}` | `thread.removed`, archived |
| **opencode** (events) | `permission.asked` / `question.asked` until `*.replied` / `rejected` | `session.error` | `session.status` `busy` / `retry` (detail is the attempt) | `session.status` `idle` after `busy` | `idle` with no prior busy (startup) | server disconnect / `server.instance.disposed` |
| **Claude Code hooks** | `PermissionRequest`; `Notification` with `permission_prompt` / `elicitation_dialog` / `agent_needs_input` | `StopFailure` | `UserPromptSubmit`, `PreToolUse`, `PostToolUse`; `Stop` with non-empty `background_tasks` | `Stop` | `SessionStart` | `SessionEnd` |
| **Vibe Kanban** | `has_pending_approval` | `latest_process_status=="failed"` | `latest_process_status=="running"` | `completed` and `has_unseen_turns` | `completed` (seen), `killed` | workspace archived / removed |
| **Nimbalyst** | `waiting_for_input` | `error` | `running` | `running → idle` transition (bridge-inferred) | `idle` | row gone |
| **Claude Squad** (scraped) | own prompt-string match (not native) | none | `Running`, `Loading` | `Running → Ready` transition | `Ready` | `Paused`, tmux session gone |
| **Conductor** (cloud) | none | `error` | `working` | `working → idle` transition | `idle` | workspace `sleeping` / `archived` |
| **Crystal** | `waiting` (memory only) | `error` / DB `failed` | `initializing`, `running` | `completed_unviewed` / DB `completed` | `ready`, `stopped` | row gone |
| **tmux** (heuristic) | `window_bell_flag` (with Claude `terminal_bell`) | `pane_dead` with non-zero `pane_dead_status` | activity / OSC 133 command running | silence after activity | silence | pane / session gone |

Every evaluated source maps onto the six values without leftovers. Native states that don't map cleanly are either transient (T3's ambiguous `waiting`) or derived by the bridge (`done` from a transition, for sources without "unseen").

---

## 7. Which to bridge first: Paseo, over its WebSocket, from Python

1. **It's the daily driver, and it aggregates.** Paseo-managed Claude **and** opencode agents (both providers are enabled locally per `paseo status`) arrive through one subscription. That covers two of the other candidates for free.
2. **Push costs almost nothing; CLI polling does not.**

   | | CLI poll (`ls --json` + `permit ls --json`) | WS subscribe (`aiohttp`, in-daemon) |
   |---|---|---|
   | Cost per update | 2 Node spawns, about 0.8 s CPU per tick | 0 spawns; one idle socket |
   | Latency | Tick interval | Immediate (`agent_update`) |
   | `needs_input` | Needs the second call | In the snapshot (`pendingPermissions`) |
   | `done` (unseen) | **Not available** (`requiresAttention` is dropped by `ls`) | In the snapshot |
   | Dependency | `paseo` on PATH | `aiohttp`, already a deckd dependency (`pyproject.toml`) |
   | Fragility | CLI output contract | Internal WS protocol: pin on `server_info.version` and fail soft |

3. **About 50 lines, and verified.** Read `local-credential`, then `hello`, wait for `server_info`, send `fetch_agents_request{subscribe:{}}`, and fold `agent_update` upserts and removes into a `{id: StatusEntry}` map using the mapping row above. Reconnect with backoff, re-reading the credential each time.
4. **Then add Claude Code `http` hooks.** They cover un-managed terminal sessions (and Paseo's blind spot of background work via `Stop.background_tasks`) with zero polling. Add opencode SSE only for opencode run outside Paseo.

**Open questions for the POC:**
- Dedupe. A Paseo-managed Claude agent would also fire Claude hooks if the user's global hooks are configured. Key on `cwd` + provider session id, or let Paseo win for agents it manages.
- Whether `done` should decay to `idle` on tile tap, or on a timer.
- Whether to use the Paseo plugin path instead, if the WS protocol churns across 0.13.

[p-life]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/agent-lifecycle.ts#L1-L7
[p-lifedoc]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/docs/agent-lifecycle.md#L5-L13
[p-lifedoc35]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/docs/agent-lifecycle.md#L30-L37
[p-bucket]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/agent-state-bucket.ts#L22-L36
[p-bucketenum]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L1270-L1276
[p-snap]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L825-L839
[p-filter]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L908-L918
[p-fetch]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L1241-L1268
[p-fetchresp]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L4178-L4187
[p-update]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L4096-L4115
[p-permmsg]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L5150-L5167
[p-hello]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L7543-L7553
[p-env]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/messages.ts#L7584-L7598
[p-perm]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/agent/agent-manager.ts#L4728-L4739
[p-attn]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/agent/agent-manager.ts#L5000-L5020
[p-clear]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/agent/agent-manager.ts#L2223-L2230
[p-storage]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/agent/agent-storage.ts#L56
[p-wspath]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/websocket-server.ts#L823-L827
[p-origin]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/websocket-server.ts#L895-L912
[p-apistatus]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/bootstrap.ts#L800-L812
[p-cred]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/local-credential.ts#L10-L40
[p-sec]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/SECURITY.md#L49-L59
[p-sec73]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/SECURITY.md#L73
[p-ls]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/cli/src/commands/agent/ls.ts#L92-L104
[p-lsitem]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/cli/src/commands/agent/ls.ts#L28-L37
[p-lsopts]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/cli/src/commands/agent/ls.ts#L138-L166
[p-plughooks]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/plugin/src/server/lifecycle.ts#L42-L66
[p-plugref]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/public-docs/plugins/reference.md#L539-L560
[p-plugtrust]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/docs/plugins.md#L7
[p-termact]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/docs/terminal-activity.md#L39-L54
[p-termstates]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/protocol/src/terminal-activity.ts#L3-L4
[p-arch]: https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/docs/architecture.md

[t3-run]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/packages/contracts/src/orchestrationV2.ts#L453-L464
[t3-shell]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/packages/contracts/src/orchestrationV2.ts#L1789-L1802
[t3-sess]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/packages/contracts/src/orchestrationV2.ts#L757-L768
[t3-kind]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/packages/contracts/src/providerPolicy.ts#L38-L44
[t3-wait1]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/apps/server/src/orchestration-v2/RunExecutionService.ts#L695-L696
[t3-wait2]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/apps/server/src/orchestration-v2/CheckpointCaptureService.ts#L209-L216
[t3-ui]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/packages/client-runtime/src/state/models.ts#L305-L311
[t3-side]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/apps/web/src/components/Sidebar.logic.ts#L579-L603
[t3-port]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/apps/server/src/config.ts#L17
[t3-auth]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/apps/server/src/cli/auth.ts#L159-L190
[t3-http]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/packages/contracts/src/environmentHttp.ts#L680-L684
[t3-stream]: https://github.com/pingdotgg/t3code/blob/22dc1dabc6d3b1616d0fa5017268c086a77887bc/packages/contracts/src/orchestrationV2.ts#L1906-L1937
[ef-ack]: https://github.com/Effect-TS/effect/blob/7f524e25cfb49a71ac39b0f44278d08d40dda5de/packages/effect/src/rpc/RpcServer.ts#L443-L450

[oc-status]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/schema/src/session-status-event.ts#L9-L49
[oc-statusimpl]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/opencode/src/session/status.ts#L30-L48
[oc-perm]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/schema/src/v1/permission.ts#L27-L66
[oc-q]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/schema/src/v1/question.ts#L58-L60
[oc-err]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/schema/src/v1/session.ts#L651-L657
[oc-global]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/opencode/src/server/routes/instance/httpapi/handlers/global.ts#L25-L58
[oc-net]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/opencode/src/cli/network.ts#L6-L16
[oc-port]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/opencode/src/server/server.ts#L117-L122
[oc-auth]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/opencode/src/server/auth.ts#L17-L42
[oc-tui]: https://github.com/anomalyco/opencode/blob/148842ef7cb1bc34192b3fff57d0f9721ab9c801/packages/opencode/src/cli/cmd/tui.ts#L271-L288

[cc-hooks]: https://code.claude.com/docs/en/hooks
[cc-status]: https://code.claude.com/docs/en/statusline
[cc-headless]: https://code.claude.com/docs/en/headless
[cc-otel]: https://code.claude.com/docs/en/monitoring-usage
[cc-term]: https://code.claude.com/docs/en/terminal-config

[vk-proc]: https://github.com/BloopAI/vibe-kanban/blob/d5cbb5380fa0b32e98ef9b8d987f63decce4be3a/crates/db/src/models/execution_process.rs#L39-L48
[vk-appr]: https://github.com/BloopAI/vibe-kanban/blob/d5cbb5380fa0b32e98ef9b8d987f63decce4be3a/crates/utils/src/approvals.rs#L30-L41
[vk-sum]: https://github.com/BloopAI/vibe-kanban/blob/d5cbb5380fa0b32e98ef9b8d987f63decce4be3a/crates/server/src/routes/workspaces/workspace_summary.rs#L25-L54
[vk-port]: https://github.com/BloopAI/vibe-kanban/blob/d5cbb5380fa0b32e98ef9b8d987f63decce4be3a/crates/utils/src/port_file.rs#L13-L29
[vk-origin]: https://github.com/BloopAI/vibe-kanban/blob/d5cbb5380fa0b32e98ef9b8d987f63decce4be3a/crates/server/src/middleware/origin.rs#L41-L81
[vk-shut]: https://www.vibekanban.com/blog/shutdown

[nb-status]: https://github.com/Nimbalyst/nimbalyst/blob/583ae0244dae266667be579733d6c571fd74e037/packages/runtime/src/ai/server/types/SessionState.ts#L10-L14
[nb-wait]: https://github.com/Nimbalyst/nimbalyst/blob/583ae0244dae266667be579733d6c571fd74e037/packages/electron/src/main/services/ai/MessageStreamingHandler.ts#L926-L940
[nb-sql]: https://github.com/Nimbalyst/nimbalyst/blob/583ae0244dae266667be579733d6c571fd74e037/packages/runtime/src/ai/server/SessionStateManager.ts#L458-L469
[nb-cli]: https://github.com/Nimbalyst/nimbalyst/blob/583ae0244dae266667be579733d6c571fd74e037/packages/cli/src/commands/sessionDoc.ts#L25-L49

[cr-types]: https://github.com/stravu/crystal/blob/1e18e0bc981225f75b5226f82a300fa741970c6f/main/src/types/session.ts#L6
[cr-persist]: https://github.com/stravu/crystal/blob/1e18e0bc981225f75b5226f82a300fa741970c6f/main/src/services/sessionManager.ts#L241-L273

[cs-enum]: https://github.com/smtg-ai/claude-squad/blob/ce1ffb4392b01f38e2c4599c7c84d2a93973b138/session/instance.go#L18-L29
[cs-set]: https://github.com/smtg-ai/claude-squad/blob/ce1ffb4392b01f38e2c4599c7c84d2a93973b138/session/instance.go#L193-L195
[cs-scrape]: https://github.com/smtg-ai/claude-squad/blob/ce1ffb4392b01f38e2c4599c7c84d2a93973b138/app/app.go#L238-L252
[cs-prompt]: https://github.com/smtg-ai/claude-squad/blob/ce1ffb4392b01f38e2c4599c7c84d2a93973b138/session/tmux/tmux.go#L246-L267

[cond-site]: https://www.conductor.build/
[cond-api]: https://www.conductor.build/docs/api

[tm-man]: https://github.com/tmux/tmux/blob/7f2a35ad3321f9ba57a1062ca73b1f3ff26aca53/tmux.1
[tm-hooks]: https://github.com/tmux/tmux/blob/7f2a35ad3321f9ba57a1062ca73b1f3ff26aca53/tmux.1#L6476-L6487
[tm-sethook]: https://github.com/tmux/tmux/blob/7f2a35ad3321f9ba57a1062ca73b1f3ff26aca53/tmux.1#L6599-L6640
[tm-refresh]: https://github.com/tmux/tmux/blob/7f2a35ad3321f9ba57a1062ca73b1f3ff26aca53/tmux.1#L1444
[tm-alerts]: https://github.com/tmux/tmux/blob/7f2a35ad3321f9ba57a1062ca73b1f3ff26aca53/alerts.c#L220-L285
