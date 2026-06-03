# Auth Control Plane Phase 1

## Intent

This phase treats login/register as an ownership and control-plane layer for
the interview workflow, not as a standalone login page. Anonymous session
capability is preserved for tryout/debug paths, while account identity controls
owned interview sessions for later history, quota, billing, and admin
operations.

## Boundary

- `users` is the durable ownership anchor for product accounts.
- `auth_sessions` stores hashed, opaque browser login sessions carried by an
  HttpOnly cookie.
- `interview_sessions.owner_user_id` records who owns an interview session.
- `X-Session-Token` only grants capability access to unowned anonymous
  sessions.
- Owned sessions require account owner auth: the current `auth_sessions` cookie
  must resolve to `interview_sessions.owner_user_id`.
- Recovery tokens only recover unowned anonymous sessions by themselves. Owned
  session recovery also requires the logged-in owner.
- WebSocket voice auth follows the same ownership boundary. A voice ticket is a
  short-lived channel ticket, not a replacement for owner auth on owned
  sessions.
- BYOK remains a browser-side advanced route and does not become an account
  credential store in this phase.
- Admin remains gated by the existing `API_TOKEN`/`allow_open_admin` control;
  role-based admin login is deferred.

## Permission Boundaries

- Anonymous users can start and continue unowned sessions with valid local
  session/recovery credentials. They cannot access owned sessions, admin
  surfaces, or account-owned history.
- Logged-in users can start owned sessions, claim unowned sessions with a valid
  `X-Session-Token`, and access only sessions owned by their account.
- Administrators can use the existing admin-token-gated observability and
  maintenance surfaces. Admin access is not inferred from normal account login
  in this phase.

## Phase 1 Decisions

- Registration is open.
- Anonymous interview start remains supported for compatibility and early
  adoption.
- Production anonymous start is configurable through
  `anonymous_session_start_rate_limit_per_minute`; setting it to `0` requires
  login before starting a new anonymous session. The default is `10`.
- Logged-in interview start automatically sets `owner_user_id`.
- Anonymous sessions can be claimed by a logged-in user only with a valid
  `X-Session-Token`.
- Claiming rotates both session and recovery tokens so browser-local anonymous
  credentials do not become stale long-lived account credentials.
- API Settings stays visible as an advanced BYOK/debug path during Phase 1.

## Deferred

- Email verification.
- Credit ledger and free quota accounting.
- Payment, membership, refunds, and invoices.
- Admin role login replacing `API_TOKEN`.
- Account-level persistent BYOK storage.
