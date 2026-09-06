# Authentication — Quizzer + QUE (A → Z)

Interview-ready map of **every auth plane** in Exambook (Quizzer) and how **QUE-Agent** plugs in.

> **Rule #1:** Never mix creator-workspace cookies with exam-attempt tokens on the same request.  
> **Rule #2:** Never put `QUE_SERVICE_KEY` in the browser.  
> **Rule #3:** Que chat JWT (if used) is **not** the same secret as Quizzer login JWT.

---

## 1. Big picture — three auth planes

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         EXAMBOOK (QUIZZER)                              │
│                                                                         │
│  Plane A — Creator workspace                                            │
│  Who: teachers / creators                                               │
│  Proof: HttpOnly cookies  access_token + refresh_token                  │
│  Client: frontend/src/lib/api/client.ts                                 │
│                                                                         │
│  Plane B — Exam attempt runtime                                         │
│  Who: exam takers (often no Quizzer account)                            │
│  Proof: header X-Attempt-Token                                          │
│  Client: frontend/src/api/examApi.ts (+ axiosClient)                    │
│                                                                         │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                │  Plane C — QUE assistant microservice
                                │  Who: logged-in workspace users chatting
                                │  Proof: see §5 (BFF today / Que JWT target)
                                ▼
                     ┌──────────────────────┐
                     │     QUE-Agent        │
                     │  /v1/chat[/stream]   │
                     └──────────────────────┘
```

| Plane | Proves | Stored where | Talks to |
|---|---|---|---|
| A Workspace | “This browser is user X’s active session” | Cookies + `AuthSession` row | Quizzer Backend |
| B Attempt | “This browser holds attempt Y” | Memory (`attemptToken`) | Quizzer attempt APIs |
| C QUE | “This caller may use the assistant” | BFF: never leaves Quizzer server · or Que JWT in browser memory | QUE-Agent |

---

## 2. Token & expiry cheat sheet (memorize this)

| Token | Secret / store | Default lifetime | What happens when it expires | Must user log in again? |
|---|---|---|---|---|
| Quizzer **access** JWT (cookie) | `JWT_SECRET_KEY` | **60 minutes** (`JWT_EXPIRE_MINUTES`) | Frontend calls `POST /auth/refresh` | **No** — if refresh cookie still valid |
| Quizzer **refresh** JWT (cookie) | `JWT_SECRET_KEY` | **7 days** (`REFRESH_TOKEN_EXPIRE_DAYS`) | Refresh fails → clear client → `/login` | **Yes** |
| DB **AuthSession** | Postgres | Aligned with refresh (~7 days); can be revoked | Context lookup fails → 401 | **Yes** (or re-auth after logout-all) |
| **Attempt** token | DB `Attempt.attempt_token` | Life of the attempt (no refresh) | Attempt APIs fail; UI sends user back to start | N/A (not a Quizzer login) |
| **Que access** JWT (`typ=que_access`) | `QUE_JWT_SECRET` (≠ login secret) | Short (~**15 min** when mint path is used) | Re-call Quizzer mint (`/que/session`) with cookies | **No** — only if workspace cookies still good |
| **QUE service key** | `QUE_SERVICE_KEY` shared env | Until rotated | 401/502 from QUE | N/A (server secret) |

**Interview one-liner:**  
*“Users don’t re-login every hour — the 60-minute access cookie silently refreshes for up to 7 days. They only see login again when the refresh cookie/session is dead, revoked, or logout happened.”*

---

## 3. Plane A — Creator workspace (Quizzer login) A → Z

### 3.1 How a user gets in (login paths)

All successful paths end the same way: **create `AuthSession` → set `access_token` + `refresh_token` cookies**.

| Path | Flow (short) |
|---|---|
| Email + password | Frontend encrypts password (RSA transport) → Quizzer `/auth/login` → **Supabase Auth** verifies credentials → Quizzer issues cookies |
| Google Sign-In | `/login/google` → Google OIDC → `/auth/google/callback` → get/create user → cookies (does **not** connect Classroom) |
| Microsoft | Supabase Azure OAuth in browser → `POST /auth/supabase-oauth` → cookies |

Password hashing locally (where used): **Argon2**.  
Email/password source of truth for verify/login/reset: **Supabase Auth**.

### 3.2 What the cookies contain

Implemented in `backend/core/security.py` + set in `backend/api/auth.py`.

**Access JWT** (`typ: "access"`)

| Claim | Meaning |
|---|---|
| `sub` | User UUID |
| `sid` | AuthSession UUID |
| `typ` | `"access"` |
| `role` | User role string |
| `exp` | Expiry (default **60m**) |

**Refresh JWT** (`typ: "refresh"`)

| Claim | Meaning |
|---|---|
| `sub` | User UUID |
| `sid` | Same session id |
| `typ` | `"refresh"` |
| `exp` | Expiry (default **7d**) |

Cookie flags: `HttpOnly`, `Secure` (forced in non-local), `SameSite` (default `lax`), optional `Domain`, `Path=/`.

Optional fallback: `Authorization: Bearer <access>` if cookie missing (`deps.py`).

### 3.3 Every authenticated workspace request

```text
Browser
  → cookie access_token
  → Quizzer Backend
       1. Read cookie (or Bearer)
       2. decode_token(..., expected_type="access")
       3. Load AuthSession by sid + user by sub
       4. Reject if session revoked/expired or user inactive
       5. Attach user to handler
```

Code: `backend/api/deps.py` → `get_current_auth_context` / `get_current_user`.

### 3.4 Silent refresh (no login page)

```text
API returns 401
  → frontend client interceptor (lib/api/client.ts)
  → POST /auth/refresh  (sends refresh_token cookie)
  → Backend:
       decode refresh JWT
       validate AuthSession still active
       touch session
       issue NEW access + refresh cookies (same sid)
  → retry original request once
  → if refresh fails → clear client auth → redirect /login
```

Refresh is **coalesced** (one in-flight refresh shared across parallel 401s) so concurrent requests don’t revoke the session via refresh-token reuse.

### 3.5 Logout

| Action | Effect |
|---|---|
| Logout | Expire session for this `sid`; clear cookies |
| Logout others / all | Expire other or all sessions for the user |

After logout, access+refresh are useless even if not yet past `exp`, because **DB session check fails**.

### 3.6 When the user must log in again

| Situation | Re-login? |
|---|---|
| Access cookie expired, refresh still valid | No — auto refresh |
| Refresh expired (≈7 days idle) | **Yes** |
| Logout / logout-all | **Yes** |
| Session revoked / user deactivated | **Yes** |
| Hard clear cookies | **Yes** |

---

## 4. Plane B — Exam attempt (`X-Attempt-Token`)

Completely separate from Plane A.

```text
Taker opens exam link
  → POST /attempts/.../start
  → Backend creates Attempt row + unique attempt_token
  → Frontend keeps attemptToken in memory (Zustand; NOT persisted)
  → Every attempt API / WS sends header: X-Attempt-Token: <token>
  → Backend looks up Attempt by token (no User cookie required)
```

| Property | Detail |
|---|---|
| Tied to User account? | **No** — enrollment identity + token |
| Refresh? | **No** |
| Survives hard reload? | **No** (token is memory-only) → back to `/start` |
| Mix with workspace cookies? | **Never** on attempt writes |

**Interview line:** *“Taking an exam is anonymous-to-Quizzer-account by design; the attempt token is the only credential for that runtime.”*

---

## 5. Plane C — QUE assistant

QUE is a **separate process** (default `:8100`). It has **no Quizzer DB**.

QUE accepts **either**:

1. `Authorization: Bearer <que_access JWT>` — browser → QUE (token-exchange design)  
2. `X-Que-Service-Key` — server → QUE only  

### 5.1 What ships today on Quizzer branch `feat/que-agent-wip` (BFF)

This is the **current WIP integration** in Quizzer:

```text
Browser (QueChatWidget)
  │  cookie access_token (Plane A)
  ▼
Quizzer Backend  /que/identity | /que/chat | /que/chat/stream
  │  get_current_user (cookie)
  │  rate limit que_chat_user
  │  outbound X-Que-Service-Key
  ▼
QUE-Agent  /v1/identity | /v1/chat | /v1/chat/stream
  │
  ▼
LLM
```

| Hop | Auth |
|---|---|
| Browser → Quizzer | Workspace cookies (Plane A) |
| Quizzer → QUE | Shared `QUE_SERVICE_KEY` |
| Browser → QUE | **Does not happen** (browser never gets the service key) |

Env (must match):

```env
# Quizzer
QUE_ENABLED=true
QUE_BASE_URL=http://127.0.0.1:8100
QUE_SERVICE_KEY=<long secret>

# QUE-Agent
QUE_SERVICE_KEY=<same secret>
LLM_API_KEY=...
```

**Expiry here:** there is **no Que JWT**. Chat works as long as the user’s **Quizzer access cookie** is valid (refresh keeps them in). If Quizzer session dies → `/que/*` returns 401 → user must log into Quizzer again; then chat works.

### 5.2 Target / recommended production design (token exchange)

Avoids proxying SSE through Quizzer:

```text
1) Browser ──cookie──► Quizzer POST /que/session
                       └─ mints short Que JWT with QUE_JWT_SECRET
                       └─ returns { access_token, que_base_url, expires_in_seconds }

2) Browser ──Bearer Que JWT──► QUE /v1/chat/stream
                               └─ verifies aud=que-agent, iss=quizzer, typ=que_access
                               └─ SSE stays on QUE (Quizzer not in hot path)
```

| Piece | Value |
|---|---|
| Secret | `QUE_JWT_SECRET` on **both** Quizzer and QUE (**not** `JWT_SECRET_KEY`) |
| Claims | `sub`, optional `sid`, `typ=que_access`, `aud=que-agent`, `iss=quizzer`, `exp` |
| Typical TTL | **~15 minutes** (`QUE_ACCESS_TOKEN_EXPIRE_MINUTES`) |
| On Que JWT expiry | Frontend calls `/que/session` again **using cookies** — **no full login** if Plane A still valid |
| On Quizzer session expiry | Mint fails with 401 → **login again** |

QUE also keeps `QUE_SERVICE_KEY` for ops / future QUE→Quizzer tools — still never in the browser.

### 5.3 QUE verification (code)

`Que-Agent/app/core/security.py` → `require_chat_auth`:

1. Optional local insecure bypass (local only)  
2. Else Bearer → `decode_que_access_token` (`app/core/tokens.py`)  
3. Else `X-Que-Service-Key` constant-time compare  

---

## 6. Secrets map (don’t confuse these in an interview)

| Secret | Used for | Who holds it |
|---|---|---|
| `JWT_SECRET_KEY` | Sign/verify Quizzer access + refresh cookies | Quizzer Backend only |
| `QUE_JWT_SECRET` | Sign/verify `que_access` JWTs | Quizzer Backend **and** QUE |
| `QUE_SERVICE_KEY` | Server→QUE calls | Quizzer Backend **and** QUE (never FE) |
| Supabase keys | Email/password + Microsoft OAuth | Quizzer + frontend anon key |
| Google login OAuth client | Sign-in only | Quizzer |
| Google integration OAuth client | Classroom/Drive/Calendar | Quizzer (separate from login) |

---

## 7. End-to-end stories (say these out loud)

### Story 1 — Teacher uses Dashboard all day

1. Logs in Monday 9:00 → cookies set (access 60m, refresh 7d).  
2. At 10:05 access expired → interceptor refreshes → still working.  
3. Returns next Monday → refresh expired → login page.

### Story 2 — Teacher opens QUE (BFF WIP)

1. Already logged into Quizzer.  
2. QueChatWidget calls `/backend/que/chat/stream` with cookies.  
3. Quizzer checks Plane A, then calls QUE with service key.  
4. If Quizzer cookies die → Que UI gets 401 → login; service key never involved for the human.

### Story 3 — Teacher opens QUE (token-exchange design)

1. Logged into Quizzer.  
2. `POST /que/session` → Que JWT (~15m).  
3. Browser streams to QUE with Bearer token.  
4. After 15m → mint again (still logged in).  
5. After 7d idle → mint fails → full login.

### Story 4 — Student takes exam

1. Opens public/share link — **no** Quizzer account cookies required.  
2. Starts attempt → `attempt_token` in memory.  
3. Answers/violations use `X-Attempt-Token` only.  
4. Reload page → token gone → start again (by design).

---

## 8. Common interview Q&A

**Q: Why two JWTs for Quizzer (access + refresh)?**  
A: Short-lived access limits stolen-cookie damage; refresh enables UX without hourly login; DB `sid` lets us revoke.

**Q: Why isn’t QUE using the same `JWT_SECRET_KEY`?**  
A: Blast-radius separation. Compromising QUE’s mint secret shouldn’t forge Quizzer workspace sessions (and vice versa).

**Q: Does chatting with QUE require logging in again every 15 minutes?**  
A: No. Only the **Que access token** is short. Re-mint uses existing Quizzer cookies. Full login only when Plane A is dead.

**Q: Can the exam runtime call QUE?**  
A: Product intent is workspace assistant (Plane A). Attempt plane is separate; don’t wire Que chat to `X-Attempt-Token` unless you explicitly design that.

**Q: Where is the password checked?**  
A: For email users, **Supabase Auth**. Quizzer then issues its own cookies. Google/Microsoft have their own bridges, then same cookie model.

**Q: What’s HttpOnly buying you?**  
A: JS on the page cannot read access/refresh cookies → reduces XSS token theft (still need CSRF/SameSite discipline).

---

## 9. File index (go deeper)

| Topic | Where |
|---|---|
| Cookie JWT create/decode | `Quizzer/backend/core/security.py` |
| Login / refresh / logout | `Quizzer/backend/api/auth.py` |
| Request user resolution | `Quizzer/backend/api/deps.py` |
| AuthSession lifecycle | `Quizzer/backend/services/auth_sessions.py` |
| Frontend refresh interceptor | `Quizzer/frontend/src/lib/api/client.ts` |
| Attempt token client | `Quizzer/frontend/src/api/examApi.ts` |
| QUE BFF (WIP) | `Quizzer/backend/api/que.py`, `services/que_client.py` |
| QUE local integration notes | `Quizzer/docs/que-local-integration.md` |
| QUE auth gate | `Que-Agent/app/core/security.py` |
| Que JWT verify | `Que-Agent/app/core/tokens.py` |
| Quizzer AI memory (auth) | `Quizzer/.ai-memory/authentication.md` |

---

## 10. Thirty-second closing pitch

> “Quizzer has two product runtimes: a cookie-JWT workspace for creators, and an attempt-token runtime for exam takers — never mixed. Sessions use a 60-minute access cookie and a 7-day refresh cookie backed by a revocable DB session, so users rarely re-login. QUE is a separate assistant microservice: today the WIP path is Quizzer BFF with a service key; the production-oriented path mints a short Que JWT so chat/SSE hit QUE directly. Expiring the Que token only means re-minting while Quizzer cookies are still valid — not a full login.”
