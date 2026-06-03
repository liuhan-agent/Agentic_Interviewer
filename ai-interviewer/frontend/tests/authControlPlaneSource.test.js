const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("api client sends auth cookies for HttpOnly login sessions", () => {
  const client = read("src/lib/api/client.ts");

  assert.match(client, /credentials: "include"/);
});

test("api config keeps local browser auth calls same-origin for cookie stability", () => {
  const config = read("src/lib/config.ts");

  assert.match(config, /isLoopbackHost/);
  assert.match(config, /shouldUseSameOriginProxy/);
  assert.match(config, /window\.location\.hostname/);
  assert.match(config, /path\.startsWith\("\/ws\/"\)/);
});

test("api client formats FastAPI validation errors instead of object strings", () => {
  const client = read("src/lib/api/client.ts");

  assert.match(client, /formatFastApiValidationDetail/);
  assert.match(client, /Array\.isArray\(detail\)/);
  assert.match(client, /validationMessage/);
  assert.match(client, /registration_closed/);
  assert.match(client, /rate_limit_exceeded/);
});

test("frontend exposes account interview sessions api client", () => {
  const accountApi = read("src/lib/api/account.ts");
  const types = read("src/lib/api/types.ts");

  assert.match(types, /export interface AccountInterviewSession/);
  assert.match(types, /export interface AccountInterviewSessionsResponse/);
  assert.match(types, /export interface AccountCreditPolicy/);
  assert.match(types, /registration_mode:\s*"open" \| "closed"/);
  assert.match(types, /free_credits_require_email_verified:\s*boolean/);
  assert.match(types, /export interface AccountCreditsResponse/);
  assert.match(types, /export interface AccountCreditLedgerEntry/);
  assert.match(types, /export interface AccountCreditRequest/);
  assert.match(types, /export interface AccountCreditRequestsResponse/);
  assert.match(accountApi, /\/api\/v1\/account/);
  assert.match(accountApi, /export function getAccountInterviewSessions/);
  assert.match(accountApi, /export function getAccountCreditPolicy/);
  assert.match(accountApi, /export function getAccountCredits/);
  assert.match(accountApi, /export function getAccountCreditRequests/);
  assert.match(accountApi, /export function createAccountCreditRequest/);
  assert.match(accountApi, /\/credit-policy/);
  assert.match(accountApi, /\/credits/);
  assert.match(accountApi, /\/credit-requests/);
});

test("auth dialog keeps anti-abuse hooks backend-driven without invite UI", () => {
  const dialog = read("src/components/auth/AuthDialog.tsx");
  const types = read("src/lib/api/types.ts");

  assert.match(types, /registration_mode:\s*"open" \| "closed"/);
  assert.match(types, /free_credits_require_email_verified:\s*boolean/);
  assert.doesNotMatch(dialog, /invite_code/);
  assert.doesNotMatch(dialog, /邀请码/);
  assert.doesNotMatch(dialog, /emailVerificationToken/);
});

test("start session response exposes platform credit billing fields", () => {
  const types = read("src/lib/api/types.ts");

  assert.match(types, /billing_mode:\s*"platform_credits" \| "byok" \| "dev_unmetered"/);
  assert.match(types, /credit_delta:\s*number \| null/);
  assert.match(types, /credit_balance:\s*number \| null/);
});

test("frontend exposes auth api client for register login logout and me", () => {
  const authApi = read("src/lib/api/auth.ts");
  const types = read("src/lib/api/types.ts");

  assert.match(types, /export interface AuthUser/);
  assert.match(types, /export interface AuthState/);
  assert.match(authApi, /\/api\/v1\/auth/);
  assert.match(authApi, /export function register/);
  assert.match(authApi, /export function login/);
  assert.match(authApi, /export function logout/);
  assert.match(authApi, /export function getMe/);
});

test("auth dialog registration confirms password and can reveal password fields", () => {
  const dialog = read("src/components/auth/AuthDialog.tsx");

  assert.match(dialog, /confirmPassword/);
  assert.match(dialog, /showPassword/);
  assert.match(dialog, /showConfirmPassword/);
  assert.match(dialog, /MIN_AUTH_PASSWORD_LENGTH/);
  assert.match(dialog, /MAX_AUTH_PASSWORD_LENGTH/);
  assert.match(dialog, /password\.length < MIN_AUTH_PASSWORD_LENGTH/);
  assert.match(dialog, /catch \(err\)/);
  assert.match(dialog, /密码不一致/);
  assert.match(dialog, /auth\.register\(email,\s*password\)/);
  assert.match(dialog, /aria-label=.*显示密码/s);
  assert.match(dialog, /aria-label=.*显示确认密码/s);
  assert.match(dialog, /htmlFor="auth-confirm-password"/);
  assert.match(dialog, /autoComplete="new-password"/);
});

test("auth dialog becomes an account credits control plane after login", () => {
  const dialog = read("src/components/auth/AuthDialog.tsx");

  assert.match(dialog, /getAccountCredits/);
  assert.match(dialog, /getAccountInterviewSessions/);
  assert.match(dialog, /getHistory/);
  assert.match(dialog, /getSessionToken/);
  assert.match(dialog, /Promise\.all/);
  assert.match(dialog, /账号与额度/);
  assert.match(dialog, /剩余次数/);
  assert.match(dialog, /免费赠送/);
  assert.match(dialog, /平台托管模式每开始一场面试扣 1 次/);
  assert.match(dialog, /账号记录/);
  assert.match(dialog, /本机匿名记录/);
  assert.match(dialog, /去同步可认领记录/);
  assert.match(dialog, /查看本机匿名记录/);
  assert.doesNotMatch(dialog, /保存匿名记录到账号/);
  assert.match(dialog, /个人 API Key/);
  assert.match(dialog, /不扣平台次数/);
  assert.match(dialog, /自己的模型服务额度/);
  assert.match(dialog, /auth\.user\.role === "user"/);
});

test("account credits UI formats ledger entries for human-readable history", () => {
  const helperPath = path.join(root, "src", "lib", "credits.ts");
  assert.equal(fs.existsSync(helperPath), true);

  const helper = fs.readFileSync(helperPath, "utf8");
  const dialog = read("src/components/auth/AuthDialog.tsx");

  assert.match(helper, /export function formatCreditLedgerEntry/);
  assert.match(helper, /free_grant/);
  assert.match(helper, /session_debit/);
  assert.match(helper, /session_refund/);
  assert.match(helper, /admin_adjustment/);
  assert.match(helper, /免费赠送/);
  assert.match(helper, /开始平台托管面试/);
  assert.match(helper, /管理员调整/);
  assert.match(dialog, /recent_entries/);
  assert.match(dialog, /最近额度流水/);
  assert.match(dialog, /formatCreditLedgerEntry/);
});

test("auth dialog exposes lightweight credit request workflow", () => {
  const dialog = read("src/components/auth/AuthDialog.tsx");

  assert.match(dialog, /getAccountCreditRequests/);
  assert.match(dialog, /createAccountCreditRequest/);
  assert.match(dialog, /creditRequestAmount/);
  assert.match(dialog, /creditRequestReason/);
  assert.match(dialog, /showCreditRequestForm/);
  assert.match(dialog, /handleCreditRequestSubmit/);
  assert.match(dialog, /申请补充次数/);
  assert.match(dialog, /再次申请补充次数/);
  assert.match(dialog, /提交申请/);
  assert.match(dialog, /待处理申请/);
  assert.match(dialog, /最近申请记录/);
  assert.match(dialog, /pendingCreditRequest \|\| showCreditRequestForm/);
  assert.match(dialog, /每个账号同时只能有 1 个待处理申请/);
});

test("account dialog keeps long account content inside the viewport", () => {
  const dialog = read("src/components/auth/AuthDialog.tsx");

  assert.match(dialog, /max-h-\[calc\(100dvh-2rem\)\]/);
  assert.match(dialog, /grid-rows-\[auto_minmax\(0,1fr\)_auto\]/);
  assert.match(dialog, /overflow-y-auto/);
  assert.match(dialog, /border-t bg-background\/95/);
  assert.match(dialog, /<details/);
  assert.match(dialog, /<summary/);
  assert.match(dialog, /最近一条/);
});

test("auth dialog waits for verified auth before loading account-only data", () => {
  const dialog = read("src/components/auth/AuthDialog.tsx");

  assert.match(dialog, /auth\.loading/);
  assert.match(dialog, /if \(!open\)/);
  assert.match(dialog, /if \(auth\.loading\) return/);
});

test("root layout provides shared auth state", () => {
  const layout = read("src/app/layout.tsx");
  const useAuth = read("src/lib/auth/useAuth.ts");

  assert.match(layout, /AuthProvider/);
  assert.match(useAuth, /createContext/);
  assert.match(useAuth, /useContext/);
  assert.match(useAuth, /export function AuthProvider/);
});

test("auth provider caches non-sensitive account state across reloads", () => {
  const useAuth = read("src/lib/auth/useAuth.ts");

  assert.match(useAuth, /AUTH_STATE_CACHE_KEY/);
  assert.match(useAuth, /readCachedAuthState/);
  assert.match(useAuth, /writeCachedAuthState/);
  assert.match(useAuth, /clearCachedAuthState/);
  assert.match(useAuth, /useState<AuthState>\(ANON_STATE\)/);
  assert.match(useAuth, /const cached = readCachedAuthState\(\)/);
  assert.match(useAuth, /if \(cached\) setState\(cached\)/);
  assert.match(useAuth, /writeCachedAuthState\(next\)/);
  assert.match(useAuth, /clearCachedAuthState\(\)/);
});

test("app shell keeps api settings advanced and adds account entry", () => {
  const shell = read("src/components/layout/AppShell.tsx");

  assert.match(shell, /AuthDialog/);
  assert.match(shell, /UserRound/);
  assert.match(shell, /auth\.authenticated/);
  assert.match(shell, /API 设置/);
});

test("setup page keeps anonymous flow but nudges account ownership", () => {
  const page = read("src/app/interview/setup/page.tsx");

  assert.match(page, /登录后/);
  assert.match(page, /保存到账号/);
});

test("claim session persists rotated recovery token", () => {
  const interviewApi = read("src/lib/api/interview.ts");

  assert.match(interviewApi, /upsertEntry/);
  assert.match(interviewApi, /ownerUserId:\s*claimed\.owner_user_id/);
  assert.match(interviewApi, /recoveryToken:\s*claimed\.recovery_token/);
  assert.match(
    interviewApi,
    /recoveryTokenExpiresAt:\s*claimed\.recovery_token_expires_at/,
  );
});
