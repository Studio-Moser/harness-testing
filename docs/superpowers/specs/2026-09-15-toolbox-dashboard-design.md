# Harness Test Toolbox Dashboard Design

## Outcome

Replace the existing dashboard presentation with a simple, readable Harness Test Toolbox. The first and initially only page explains the coding tasks used to compare harnesses. It contains no run results, rankings, recommendations, or winner claims.

The Toolbox answers:

- What kinds and sizes of work do we test?
- Which Type × Level combinations have coverage?
- What does each test ask an agent to do?
- What repository, fixture, tests, and verifier support each test?
- What agent and harness behavior should the test exercise?
- What should the test teach us when results are evaluated elsewhere?

## Scope

The Toolbox contains 15 coding benchmarks:

- Nine controlled first-party tests under `tasks/workflow/`.
- Six pinned real-repository tasks from DeepSWE.

The following are deliberately excluded:

- All eight `tasks/contract/` scenarios. They are internal Harness protocol checks, not work-profile benchmarks.
- `react-bulk-dashboard-updates`. It duplicates the grouped React fixture while explicitly requiring the Harness `bulk` route, making it a routing diagnostic rather than an independent work-profile test.
- All run results, scores, costs, timings, recommendations, and comparative conclusions.

All included items are presented as **Harness Tests**. `Studio Moser` and `DeepSWE` appear only as source or provenance metadata.

This project does not change the testing apparatus. The current Harbor-compatible prompt, frozen repository, isolated environment, separate verifier, artifact, and report pipeline remains intact.

## Work Taxonomy

Each Harness Test has one work type and one scope level.

### Work types

- **Polish** — presentation work such as copy, color, spacing, or semantic markup without a material behavior change.
- **Bug fix** — investigation and correction of incorrect behavior, normally requiring reproduction, regression coverage, QA, and review.
- **Feature** — new behavior that normally requires requirements interpretation, design, implementation, and verification.

### Scope levels

- **L1 — Atomic** — one obvious, tightly constrained edit.
- **L2 — Focused** — one behavior within a component or module, with targeted verification.
- **L3 — Coordinated** — multiple related changes across files, packages, or outputs, with a clear specification.
- **L4 — Complex** — cross-module real-repository work involving ambiguity, design judgment, or substantial investigation and verification.

Type and level are independent. This permits both a focused bug and a complex real-repository bug instead of treating all bugs as small.

### Initial coverage

| Type | L1 | L2 | L3 | L4 | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Polish | 2 | 0 | 2 | 0 | 4 |
| Bug fix | 0 | 3 | 0 | 1 | 4 |
| Feature | 0 | 0 | 2 | 5 | 7 |
| **Total** | **2** | **3** | **4** | **6** | **15** |

The initial assignments are:

- L1 Polish: React accent polish; static pricing-card copy and spacing.
- L2 Bug fix: React active badge count; Rust quoted-value parser; accessible static disclosure.
- L3 Polish: grouped React UI updates; grouped static-page updates.
- L3 Feature: persisted React saved views; Rust workspace warning summary.
- L4 Bug fix: Happy DOM interrupted-body shutdown behavior.
- L4 Feature: Quill shared toolbar; Yjs map conflict detection; KaTeX multicolumn spans; wasmi trap coredumps; pest character-class coalescing.

Empty combinations remain visible in the interface because they reveal missing test coverage.

## Architecture

Keep Observable Framework as the existing static build and data-loader layer. Replace the visible dashboard rather than replacing the experiment evidence pipeline.

- The Toolbox becomes the home page and the only initial navigation destination.
- Load pinned Tabler 1.5.1 CSS from jsDelivr through Observable's supported global stylesheet or head configuration.
- Do not load Tabler JavaScript until an interaction requires it. Native buttons and `<details>` provide the initial behavior.
- Use one plain JavaScript component for navigation, filters, grouping, and cards.
- Use one small local stylesheet for layout and Studio Moser-specific refinements.
- Use one build-time catalog loader to combine explicit editorial metadata with technical facts from task sources.
- Remove the existing results-oriented dashboard pages, navigation, presentation components, and styles.
- Do not alter experiment evidence, retained reports, schemas, task fixtures, or the CLI.

The exact CDN version must be pinned. Do not use `@latest`.

## Catalog Data

Maintain an explicit allowlist of the 15 included Harness Test IDs. Do not discover every directory automatically because internal protocol diagnostics must remain excluded by design.

The catalog supplies editorial fields that task files do not currently encode:

- Human-readable title
- Work type
- Scope level
- Purpose
- Prompt summary
- Expected agent process
- Expected harness behavior
- Learning goal

Derive technical facts from the real task sources wherever practical:

- Technical task ID
- Language and framework
- Controlled fixture or real repository
- Source and provenance
- Base repository and pinned commit
- Existing project tests
- Agent and verifier environments
- Network restrictions
- Time and resource limits
- Protected files
- Verification structure
- Local setup state

The loader must reject duplicate IDs, missing referenced tasks, unsupported type or level values, and missing required card content. All displayed counts are calculated from validated catalog data.

Setup state describes only whether a test is defined, locally materialized, or queued. It must not imply that any harness passed the test.

## DeepSWE Boundary

DeepSWE is a third-party task collection that supplies the six L4 real-repository tests. It is not a separate testing platform; these tasks ultimately use the same Harbor-compatible comparison pipeline.

The pinned DeepSWE tree has no license that permits copying its task contents into the published dashboard. Therefore:

- Store only Studio Moser-authored summaries and permitted provenance metadata in the catalog.
- Link to each exact pinned upstream prompt.
- Do not copy DeepSWE prompt or verifier contents into tracked dashboard assets.
- Local first-party Harness Tests may display their exact tracked prompts inline.

## Page Structure

Use a compact top navigation rather than a sidebar while Toolbox is the only page.

The page contains, in order:

1. A short title and explanation of the Toolbox.
2. Type navigation with counts.
3. Level navigation with counts.
4. The current Type × Level intersection count and a clear-filters action.
5. Harness Test cards grouped by ascending level.

On initial load, Type and Level are both `All`, and all 15 tests appear in L1, L2, L3, then L4 sections. Within each level, cards sort alphabetically.

## Filtering

Type and Level are independent single-select dimensions. Each includes an `All` option.

- Type counts reflect the currently selected Level.
- Level counts reflect the currently selected Type.
- The intersection count reports the number of matching tests.
- Zero-count options remain visible and selectable.
- A zero-result combination displays a neutral coverage-gap explanation.
- The clear action restores `All × All`.
- The selected Type and Level are encoded in URL query parameters so filtered views are bookmarkable and shareable.

Do not add text search initially. Fifteen tests, two filter dimensions, and level grouping are sufficient.

## Harness Test Cards

Cards use a consistent summary area followed by independently expandable structured sections.

### Always visible

- Human-readable title
- Work type and level
- One-sentence purpose
- Language and stack
- Controlled or real-repository badge
- Source and setup state
- Technical task ID in secondary text

### Expandable sections

1. **What it tests** — the behavior and harness qualities being exercised.
2. **Task brief** — prompt summary followed by the exact local prompt or pinned DeepSWE link.
3. **Test setup** — base repository, commit, existing tests, isolation, network, and protected-file boundaries.
4. **Expected agent process** — appropriate investigation, brainstorming, design, implementation, tool or skill use, delegation, QA, and review.
5. **Verification** — visible tests, hidden verifier, first-party five-case QA where applicable, and success criteria.
6. **What we learn** — the question this test will help answer once results are evaluated elsewhere.

Cards contain no run results or conclusions.

## Visual Direction

- Use Tabler's light, neutral admin foundation with one restrained blue accent.
- Keep the page wide and information-dense without resembling a spreadsheet.
- Use typography and spacing rather than decoration to establish hierarchy.
- Use icons only when they clarify meaning.
- Keep card summaries visually consistent even when expanded content lengths differ.
- Treat zero coverage as neutral information rather than an error.
- Use a responsive three-column, two-column, then one-column card grid.
- Treat the approved Toolbox navigation wireframe as structural guidance; the implementation design pass may refine typography, color, spacing, and responsive details without changing the information hierarchy.

## Accessibility

- Use semantic headings and landmarks.
- Implement filters as keyboard-accessible buttons with an exposed selected state.
- Use native `<details>` and `<summary>` elements for disclosure.
- Preserve visible focus, sufficient contrast, and sensible tab order.
- Respect reduced-motion preferences.
- Do not rely on color alone to convey filter selection, work type, level, or empty coverage.

## Failure and Empty States

- A catalog validation failure stops the dashboard build with the affected task ID and field.
- A valid zero-result filter combination renders a coverage-gap message and keeps the filters available.
- A DeepSWE prompt link remains an external pinned-source link; the dashboard does not silently replace inaccessible upstream content.
- Missing local materialization is shown as setup state and does not prevent the task definition from appearing.

## Verification

Verification must cover:

- The catalog contains exactly the 15 explicitly included Harness Tests.
- Internal contract scenarios and `react-bulk-dashboard-updates` do not appear.
- Type, Level, and intersection counts are correct.
- Type and Level filtering work independently and together.
- URL parameters restore the selected filters.
- Default results are grouped L1 through L4 and alphabetized within each group.
- Zero-count options and zero-result states remain visible.
- Every card has all required summary and expandable fields.
- Local prompts render from tracked sources and DeepSWE tasks link to pinned upstream prompts.
- Keyboard navigation, selected-state semantics, focus visibility, and native disclosures work.
- The responsive layout works at wide, medium, and narrow widths.
- The dashboard's existing test command and production build pass.

## Implementation Boundary

This design authorizes a Toolbox-first dashboard rebuild only after an implementation plan is separately reviewed. It does not authorize changes to task fixtures, Harbor execution, comparison policy, retained evidence, or model-backed experiment runs.
