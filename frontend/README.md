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

## Canonical Type Contract

`src/types/canonical.ts` is a **TypeScript transport / compile-time mirror** of the frozen Python canonical models defined in the repository-root `contracts/` package (`contracts/transaction.py`, `contracts/case.py`, `contracts/evidence.py`, `contracts/account.py`, `contracts/enums.py`).

**Key rules:**

- **`contracts/` is the single authoritative source of truth.** The TypeScript file is a dependent reflection, not an independent schema.
- Changes to data shapes **must originate in the Python contract package first** and then be reflected (manually or via future codegen) in `src/types/canonical.ts`.
- The frontend types must not add, remove, or rename fields relative to the canonical schema. They exist solely so that TypeScript can enforce shape-correctness at compile time and so that IDE tooling can provide autocompletion for API payloads.
- **No fraud logic, business rules, taint propagation, ML scores, risk assessments, or recovery estimates** may be embedded in these types. Such concerns are computed exclusively by backend services and, when needed in the UI, are carried by separate downstream response types — never grafted onto the canonical models.
- If a future schema version adds fields, the `schema_version` constant and corresponding interfaces in `canonical.ts` must be updated to match `contracts/` exactly.

