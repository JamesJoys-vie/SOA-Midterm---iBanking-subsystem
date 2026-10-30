# Frontend

React + Vite + Tailwind v4 web app for the tuition payment flow. The UI follows `docs/wireframes/wireframes.html`;
the API it calls is `docs/api/endpoints.md`.

```
npm install
npm run dev      # http://localhost:5173, proxies /api to the gateway on :8080
npm run build    # production build into dist/
```

Layout: `src/api` (fetch client), `src/context` (auth, hide / show amounts), `src/hooks` (React Query hooks),
`src/components` (AppLayout, ProtectedRoute, shared UI kit), `src/pages`, `src/utils`.
