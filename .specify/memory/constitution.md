<!--
SYNC IMPACT REPORT
==================
Version change: (initial template) → 1.0.0
Bump rationale: MAJOR — initial ratification of the project constitution; all
prior content was placeholder text from the template.

Modified principles:
- (template) [PRINCIPLE_1_NAME] → I. Deterministic Core, LLM at the Edges
- (template) [PRINCIPLE_2_NAME] → II. Single Source of Assumptions
- (template) [PRINCIPLE_3_NAME] → III. Tag Every Assumption by Origin
- (template) [PRINCIPLE_4_NAME] → IV. Layered Separation
- (template) [PRINCIPLE_5_NAME] → V. Scope Discipline
- (added)                       → VI. Auditability Over Cleverness

Added sections:
- Engineering Constraints (replaces template [SECTION_2_NAME])
- Development Workflow & Quality Gates (replaces template [SECTION_3_NAME])
- Governance

Removed sections: none (all template placeholders resolved)

Templates requiring updates:
- ✅ .specify/templates/plan-template.md — Constitution Check section already
  references "constitution file" abstractly; no edits required. Plans MUST
  evaluate each /speckit-plan against principles I–VI explicitly.
- ✅ .specify/templates/spec-template.md — no edits required; specs MUST tag
  assumptions per Principle III and defer non-essential scope per Principle V.
- ✅ .specify/templates/tasks-template.md — no edits required; tasks MUST
  preserve the data → logic → presentation boundary from Principle IV.
- ⚠ README.md / docs/quickstart.md — not present in repo; create when project
  documentation is authored, and reference this constitution.

Follow-up TODOs: none.
-->

# HTS SEE Finance Engine Constitution

## Core Principles

### I. Deterministic Core, LLM at the Edges

All financial math MUST be computed in code and MUST be reproducible and
auditable. The same inputs MUST always yield the same outputs.

LLMs are permitted ONLY at the edges of the system: generating narrative
summaries of computed results and translating natural language into
structured inputs that the deterministic core then validates. LLMs MUST
NEVER compute, derive, round, infer, or alter a number that appears in
an output.

**Rationale**: Finance work is judged on whether the numbers can be
defended. A non-deterministic core would make every output unfalsifiable
and every audit impossible.

### II. Single Source of Assumptions

Every model input MUST live in exactly one config location (a named
assumption registry — typically YAML/JSON/TOML at a known path). No
input value may be hardcoded in logic, duplicated across files, or
silently overridden at call sites.

Derived values (e.g., `payout = coverage_pct × fare`) MUST be computed
at use time from their constituent inputs. Derived values MUST NEVER be
stored alongside the inputs they depend on, because storage of a
derivation breaks the link between assumption and result.

**Rationale**: When the same number appears in two places, they will
drift. The only way to make assumption changes safe is to make them
edit exactly one cell.

### III. Tag Every Assumption by Origin

Every input MUST carry an origin label drawn from this closed set:

- `measured-from-data` — computed from a dataset the project owns or
  ingests, with the computation reproducible from raw data.
- `disclosed` — published by an authoritative external party (regulator,
  counterparty, official filing). The source MUST be cited.
- `observed` — recorded from real-world activity that the project did
  not generate (e.g., market prices, traffic counts).
- `assumed` — chosen by the modeller in the absence of measurement.

The origin label MUST remain visible in every output that depends on the
input — in tables, exports, narratives, and dashboards. Outputs MUST NOT
present `assumed` values in the same visual register as
`measured-from-data` values without distinguishing them.

**Rationale**: A model's credibility comes from being honest about what
is known versus estimated. Hiding the distinction is the difference
between analysis and storytelling.

### IV. Layered Separation

The system MUST be organised as three strictly ordered layers:

1. **Data layer** — facts: raw inputs, the assumption registry, ingested
   datasets. Knows nothing about computation or display.
2. **Logic layer (the engine)** — pure computation over the data layer.
   Produces results as data. MUST NOT import, depend on, or know about
   the presentation layer.
3. **Presentation layer** — UI, reports, narratives, exports. Reads
   results from the engine. MUST NOT perform calculations of its own,
   including aggregations, unit conversions, or sign flips.

Dependencies flow downward only: presentation → engine → data.

**Rationale**: When presentation calculates, the same number computed
two ways will eventually disagree. When the engine knows about the UI,
it becomes impossible to swap or audit either independently.

### V. Scope Discipline

Every feature MUST be built as the smallest version that tells the
complete story end-to-end. "Complete story" means data in → computation →
output that a finance reader can interpret.

Anything not essential to the complete story MUST be moved to an
explicit `Future` section (in the spec, plan, or README), not quietly
included "while we're here." Speculative abstractions, optional
parameters with no current caller, and infrastructure for features that
aren't being built MUST be rejected at review.

**Rationale**: A minimal end-to-end build exposes the real questions.
Anything beyond it is a guess that will need to be torn out, and quiet
additions evade the scrutiny that explicit deferrals receive.

### VI. Auditability Over Cleverness

Outputs MUST be interrogable by a finance person who does not read code.
This means:

- Every number on screen MUST be traceable to its assumption inputs and
  the formula that combined them.
- Exports (e.g., Excel/CSV) MUST preserve live formulas where the target
  format supports them, not pre-evaluated constants, so the reader can
  alter an assumption and watch the dependent cells recompute.
- Code structure MUST favour the obvious, named, single-pass calculation
  over the compact or generic one. A clever one-liner that hides the
  formula is worse than a six-line block that names it.

**Rationale**: The audience for this engine is a controller, not a
compiler. If the controller cannot defend the number, the model has
failed regardless of how elegant the code is.

## Engineering Constraints

These constraints derive from the principles above and apply to every
spec, plan, and task:

- **Assumption registry path**: a single, project-defined config
  location is the authoritative source of inputs (Principle II). Any PR
  that introduces a numeric literal in logic code MUST be rejected
  unless the literal is a pure mathematical constant (e.g., 0, 1, π).
- **Origin metadata is mandatory** (Principle III): each entry in the
  assumption registry MUST carry an `origin` field and, where
  applicable, a `source` field (citation or dataset reference).
- **No engine → presentation imports** (Principle IV): linting or
  directory layout MUST make cross-layer imports visible at review.
- **No stored derivations** (Principle II): persisted artefacts (caches,
  snapshots, exports) MAY contain computed values, but the assumption
  registry itself MUST contain only primitive inputs.
- **LLM I/O is typed** (Principle I): every LLM call MUST have a typed
  output schema. Free-form LLM text MUST NOT be parsed into numbers
  downstream.

## Development Workflow & Quality Gates

- **Spec → Plan → Tasks → Implement** is the required order. Each stage
  MUST verify compliance with Principles I–VI before proceeding.
- **Constitution Check gate** in every `/speckit-plan` MUST evaluate the
  plan against each principle by name. Violations MUST be either fixed
  or recorded in the plan's Complexity Tracking table with an explicit
  justification of why no simpler alternative works.
- **Scope deferral discipline** (Principle V): every spec MUST contain a
  `Future` (or equivalently labelled) section listing what was
  considered and explicitly deferred. An empty section is acceptable;
  silent omission is not.
- **Review focus**: code review MUST verify (a) no hardcoded inputs,
  (b) every assumption carries an origin, (c) layer boundaries are
  intact, and (d) outputs remain interrogable by a non-coder.
- **Audit artefact**: significant releases SHOULD ship with a reviewer
  worksheet (the assumption registry plus a sample of outputs showing
  origin tags) so a finance reader can reproduce key numbers without
  reading source code.

## Governance

This constitution supersedes all other practices, style guides, and
informal conventions in this repository. When a guideline elsewhere
conflicts with a principle here, this document wins.

**Amendment procedure**: Amendments MUST be proposed as a change to
this file accompanied by (a) the Sync Impact Report at the top of the
file, (b) updates to any dependent templates flagged in the report, and
(c) a one-line entry in the commit message explaining the bump.

**Versioning policy** (semantic):

- **MAJOR**: a principle is removed, renamed in substance, or has its
  meaning materially redefined; or a governance rule changes in a way
  that invalidates prior decisions.
- **MINOR**: a new principle or section is added, or existing guidance
  is materially expanded.
- **PATCH**: clarifications, wording, typos, non-semantic refinements.

**Compliance review**: every PR description MUST state whether the
change affects any principle and, if so, which. The Constitution Check
gate in `/speckit-plan` is the primary enforcement point; reviewers are
the backstop.

**Version**: 1.0.0 | **Ratified**: 2026-05-23 | **Last Amended**: 2026-05-23
