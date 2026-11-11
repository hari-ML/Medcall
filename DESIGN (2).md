# Cozy

## Overview

**Product:** Cozy
**URL:** https://cozyjournal.app/#pricing
**Surface type:** marketing
**Audience:** Business decision-makers and potential customers
**Brand character:** Conversion-focused marketing presence with a minimal, restrained color palette and single-typeface typography.

### Design Principles

- Consistency over novelty — reuse existing patterns before inventing new ones.
- Token-driven — every visual decision references a token, not a magic number.
- Accessible by default — compliance is a baseline, not a feature.

## Colors

| Token | Value | Role |
|-------|-------|------|
| color-1 | `#FFFFFF` | Border |

## Typography

**Font stack:** Inter

| Level | Size | Usage |
|-------|------|-------|
| text-xs | 14px | Captions, metadata |
| text-sm | 16px | Labels, secondary text |
| text-base | 19px | Body text (default) |
| text-lg | 38px | Subheadings, emphasis |

**Weight scale:** 400 · 500
**Line heights:** 42.24px · 25.92px · 26.4px · 21.7px · 31px · 26px · 18.75px · 24px

## Spacing

**Base unit:** 8px

`space-1: 6px` · `space-2: 8px` · `space-3: 12px` · `space-4: 13px` · `space-5: 16px` · `space-6: 18px` · `space-7: 20px` · `space-8: 24px` · `space-9: 28px` · `space-10: 32px` · `space-11: 36px` · `space-12: 40px` · `space-13: 48px` · `space-14: 64px` · `space-15: 120px` · `space-16: 128px` · `space-17: 168px` · `space-18: 312px` · `space-19: 424px`

## Shapes

**Border radius:** `radius-sm: 4px` · `radius-md: 11px` · `radius-lg: 24px`

## Elevation

- **shadow-sm:** `rgba(255, 255, 255, 0.9) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.3) 0px 1px 2px 0px, rgba(0, 0, 0, 0.5) 0px 6px 14px -6px`
- **shadow-md:** `rgba(255, 255, 255, 0.06) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.3) 0px 1px 2px 0px`
- **shadow-lg:** `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, oklch(0.215 0.018 53 / 0.05) 0px 1px 3px -1px, oklch(0.215 0.018 53 / 0.16) 0px 12px 28px -18px`

## Motion

- **duration-fast:** `all`
- **duration-fast:** `none`
- **duration-fast:** `color 0.15s cubic-bezier(0.23, 1, 0.32, 1), background-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), outline-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), text-decoration-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), fill 0.15s cubic-bezier(0.23, 1, 0.32, 1), stroke 0.15s cubic-bezier(0.23, 1, 0.32, 1), --tw-gradient-from 0.15s cubic-bezier(0.23, 1, 0.32, 1), --tw-gradient-via 0.15s cubic-bezier(0.23, 1, 0.32, 1), --tw-gradient-to 0.15s cubic-bezier(0.23, 1, 0.32, 1)`
- **duration-fast:** `color 0.15s ease-out, background 0.15s ease-out, border-color 0.15s ease-out, box-shadow 0.15s ease-out, opacity 0.15s ease-out, transform 0.15s ease-out`
- **duration-base:** `rotate 0.2s cubic-bezier(0.23, 1, 0.32, 1), color 0.2s cubic-bezier(0.23, 1, 0.32, 1)`

## Components

- **Buttons:** 268 detected
- **Links:** 81 detected
- **Inputs:** 2 detected
- **Navigation:** 2 elements
- **Lists:** 8 detected
- **Forms:** 1 detected
- **Images:** 227 detected

## Do's and Don'ts

### Do

- Reference tokens by name, not raw values — agents and developers should use `color.text.primary`, not `#171717`.
- Define all interactive states: default, hover, focus-visible, active, disabled.
- Use the spacing scale for all padding, margin, and gap values.
- Write content in sentence case. Reserve ALL CAPS for acronyms only.
- Test every component at the smallest and largest breakpoint before shipping.

### Don't

- Do not introduce colors outside the extracted palette.
- Do not use arbitrary spacing values — stick to the scale.
- Do not mix border-radius values. Pin to the detected set (4px, 11px, 24px).
- Do not use full-uppercase text for body or paragraph content.
- Do not nest interactive elements (e.g. buttons inside links).
- Do not ship components without defining hover, focus-visible, and disabled states.

## Writing Tone

Concise, confident, implementation-focused. Avoid filler preambles.

## Authoring Workflow

When creating or updating a component guideline for this system, follow this sequence:

1. **State the intent** — one sentence on what the component does and why it exists.
2. **Map tokens** — list every color, spacing, typography, and radius token the component uses. No raw values.
3. **Define anatomy** — break the component into named parts (container, label, icon, etc.) with their token assignments.
4. **Specify states** — document every state: default, hover, focus-visible, active, disabled, loading, error, empty.
5. **Describe interactions** — keyboard, pointer, and touch behavior, including edge cases (long content, overflow, truncation).
6. **Add accessibility criteria** — write testable pass/fail checks (e.g. "focus ring must be visible at 3:1 contrast").
7. **List anti-patterns** — concrete examples of misuse with a brief explanation of why each is wrong.
8. **Close with a QA checklist** — a mechanical list of verifiable items (see Definition of Done below).

## Required Output Structure

Every component guideline produced from this system must contain these sections, in order:

1. Overview — purpose, when to use, when not to use.
2. Tokens and foundations — all referenced tokens from the tables above.
3. Anatomy and variants — named parts, variant matrix, responsive behavior.
4. States and interactions — full state table, keyboard/pointer/touch behavior.
5. Accessibility — ARIA attributes, contrast requirements, focus management, screen reader behavior.
6. Content guidelines — copy length, tone, capitalisation, placeholder text rules.
7. Anti-patterns — explicit examples of what not to build, with reasoning.

## Component Requirements

Every component built against this system must:

- Reference only tokens defined in the tables above — no hardcoded hex, px, or font values.
- Define all interactive states: default, hover, focus-visible, active, disabled, loading, error.
- Specify responsive behavior at the smallest and largest supported breakpoint.
- Handle edge cases: empty state, overflow / truncation, maximum content length.
- Include keyboard navigation (Tab, Enter, Escape, Arrow keys where applicable).
- Document ARIA roles, labels, and live-region behavior where relevant.
- Include known page component density: - **Buttons:** 268 detected
- **Links:** 81 detected
- **Inputs:** 2 detected
- **Navigation:** 2 elements
- **Lists:** 8 detected
- **Forms:** 1 detected
- **Images:** 227 detected

## Definition of Done

A component is not complete until every item below is checked:

- Renders correctly in its default state (smoke test).
- All states documented and visually verified (hover, focus, disabled, loading, error, empty).
- All visual values use design tokens — zero hardcoded values.
- Keyboard navigation works without a pointer.
- No critical accessibility violations (contrast, ARIA, focus order).
- Tested at smallest and largest breakpoint.
- Anti-patterns section lists at least one concrete misuse example.
- Documentation covers purpose, usage, props/API, and limitations.
