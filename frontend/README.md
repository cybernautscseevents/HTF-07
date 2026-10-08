# AEGIS-Flow - Frontend

This directory houses the frontend application for **AEGIS-Flow** (Temporal Fraud-Flow Intervention Engine).

## Tech Stack

- **Next.js**: 16.4.0 (App Router, Turbopack)
- **TypeScript**: 5.9.3
- **Tailwind CSS**: 4.3.3
- **React**: 19.3.0

## Getting Started

Run the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to view the application.

## Build and Verification

- **Type Check**: `npx tsc --noEmit`
- **Lint**: `npm run lint`
- **Production Build**: `npm run build`
- **Production Start**: `npm run start`

## Architecture Principles

1. The frontend is strictly a visualization and interaction layer.
2. Financial provenance, taint propagation, fraud decisions, and legal logic are computed exclusively by the backend.
3. Keep dependency footprint minimal and avoid unnecessary state management or API frameworks.
