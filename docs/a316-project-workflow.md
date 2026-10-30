# A3.16 — Project workflow

The main workspace now has three steps: **Metraj → Pozları incele → Maliyet**.
The project is selected once. Project summary and source administration remain
available under a secondary disclosure. Legacy deep links remain usable.

1. Create/select a project, upload an Excel, inspect columns, preview and save.
   Saving remembers the returned import ID. No import is created by navigation.
2. Open Pozları incele. The existing review workbench is embedded with a fixed
   project scope, with no second project selector. The remembered import is
   revalidated; when none is available the newest server-listed import is loaded.
   Candidate assignment and comparison remain explicit and limited to 20 rows.
   Source evidence, saved reviews, assessments and the read-only candidate bridge
   use their existing endpoints. Returning from another step preserves edits and
   the current preview during this mounted session. Project changes unmount it;
   parent metraj revisions/imports invalidate the old preview. Session expiry in
   the workbench logs the whole project workspace out.
3. Open Maliyet. The existing cost endpoint rechecks engineering decisions,
   current metraj and source gates. It uses the latest import in the engineering
   workflow, not an older import selected for historical PDF review. A blocked
   request shows its reason and a return action. Only eligible candidates with
   explicit prices and provenance can create an immutable draft. A partial draft
   is not represented as the complete project cost.

## Scope

This is navigation and state integration, not an expansion of technical coverage.
The real PDF pilot still supports 15.275.1111; the owned synthetic fixture is
separate and has no official price. No engineering approval, source usage status,
PDF price, calculation rule, or database schema is changed. A matching A3 preview
is not automatically an M4 approval. Existing multi-layer blocks remain active.
The legacy page /batch-technical-review remains available using the same component.

## Validation

- TypeScript: `cd apps/web` then `npm run typecheck`.
- Production compilation, TypeScript and static generation passed with
  `npm run build -- --webpack`. The default Turbopack build in the review
  container failed opening its persistence database (invalid digit); the project
  build script and bundler configuration are unchanged.
- Simulated DOM checks exercised embedded scope, comparison retention across all
  three steps, blocked cost eligibility, no automatic mutation, project switching,
  late response isolation and whole-workspace logout on nested session expiry.
- Previous saved-review, assessment and source separation DOM checks passed after
  the workbench extraction. These checks are not a live Windows browser test.
- Existing backend regression selection: 121 passed, one dependency warning.

## Local acceptance

Run the API and frontend as usual; no migration or PDF upload is needed for this
UI update. In the browser select the owned synthetic project, enter Pozları incele,
compare explicitly and visit Maliyet. A blocked cost result must stay blocked.
Return to Pozları incele and verify the candidate input and preview remain. Switch
projects and verify the old preview disappears. For an existing project with
eligible engineering decisions, use the normal explicit-price draft workflow.
