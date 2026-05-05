# Frontend E2E Tests

Playwright covers browser-level flows that source tests cannot prove.

## Commands

```powershell
npm run e2e
npm run e2e:ui
```

The config starts the Next.js dev server on `127.0.0.1:3000` unless one is already running.

## Scope

- Keep tests focused on user-visible flows.
- Mock backend APIs unless the test explicitly needs the full backend stack.
- Prefer a few stable smoke tests over many brittle selectors.
