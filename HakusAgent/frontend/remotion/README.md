# HakusAI Motion

Remotion compositions for exported HakusAI visuals. This package is kept
outside the Tauri runtime: the desktop app consumes rendered files from
`frontend/desktop-tauri/public/motion` and keeps live controls CSS-only.

```bash
npm install
npm run studio
npm run render:startup
npm run render:first-run
npm run render:long-run
```

The compositions share `frontend/hakus-design-tokens.json` with the desktop
frontend so color, typography, radius, and motion timing stay aligned.
