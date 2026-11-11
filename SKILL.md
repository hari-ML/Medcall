---
name: design-system-cozy
description: >
  Apply the Cozy design system when building or updating UI.
  Use when creating components, choosing colors or typography,
  or reviewing designs for marketing interfaces.
---

# Cozy — Design System Skill

## When to Use

- Building new UI components for Cozy.
- Reviewing or updating existing component styles.
- Choosing colors, typography, or spacing for marketing pages.
- Checking designs against the extracted token set.

## Context

- **Product:** Cozy — https://cozyjournal.app/#pricing
- **Surface:** marketing
- **Audience:** Business decision-makers and potential customers
- **Character:** Conversion-focused marketing presence with a minimal, restrained color palette and single-typeface typography.

## Tokens

### Colors

| Token | Value | Role |
|-------|-------|------|
| color-1 | `#FFFFFF` | Border |

### Typography

**Font stack:** Inter

| Level | Size | Usage |
|-------|------|-------|
| text-xs | 14px | Captions, metadata |
| text-sm | 16px | Labels, secondary text |
| text-base | 19px | Body text (default) |
| text-lg | 38px | Subheadings, emphasis |

**Weight scale:** 400 · 500
**Line heights:** 42.24px · 25.92px · 26.4px · 21.7px · 31px · 26px · 18.75px · 24px

### Spacing

**Base unit:** 8px

`space-1: 6px` · `space-2: 8px` · `space-3: 12px` · `space-4: 13px` · `space-5: 16px` · `space-6: 18px` · `space-7: 20px` · `space-8: 24px` · `space-9: 28px` · `space-10: 32px` · `space-11: 36px` · `space-12: 40px` · `space-13: 48px` · `space-14: 64px` · `space-15: 120px` · `space-16: 128px` · `space-17: 168px` · `space-18: 312px` · `space-19: 424px`

### Shapes

**Border radius:** `radius-sm: 4px` · `radius-md: 11px` · `radius-lg: 24px`

### Elevation

- **shadow-sm:** `rgba(255, 255, 255, 0.9) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.3) 0px 1px 2px 0px, rgba(0, 0, 0, 0.5) 0px 6px 14px -6px`
- **shadow-md:** `rgba(255, 255, 255, 0.06) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.3) 0px 1px 2px 0px`
- **shadow-lg:** `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, oklch(0.215 0.018 53 / 0.05) 0px 1px 3px -1px, oklch(0.215 0.018 53 / 0.16) 0px 12px 28px -18px`

### Motion

- **duration-fast:** `all`
- **duration-fast:** `none`
- **duration-fast:** `color 0.15s cubic-bezier(0.23, 1, 0.32, 1), background-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), outline-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), text-decoration-color 0.15s cubic-bezier(0.23, 1, 0.32, 1), fill 0.15s cubic-bezier(0.23, 1, 0.32, 1), stroke 0.15s cubic-bezier(0.23, 1, 0.32, 1), --tw-gradient-from 0.15s cubic-bezier(0.23, 1, 0.32, 1), --tw-gradient-via 0.15s cubic-bezier(0.23, 1, 0.32, 1), --tw-gradient-to 0.15s cubic-bezier(0.23, 1, 0.32, 1)`
- **duration-fast:** `color 0.15s ease-out, background 0.15s ease-out, border-color 0.15s ease-out, box-shadow 0.15s ease-out, opacity 0.15s ease-out, transform 0.15s ease-out`
- **duration-base:** `rotate 0.2s cubic-bezier(0.23, 1, 0.32, 1), color 0.2s cubic-bezier(0.23, 1, 0.32, 1)`

## Component Inventory

- **Buttons:** 268 detected
- **Links:** 81 detected
- **Inputs:** 2 detected
- **Navigation:** 2 elements
- **Lists:** 8 detected
- **Forms:** 1 detected
- **Images:** 227 detected

## Constraints

### Always

- Use tokens from the tables above — do not introduce new values.
- Include hover, focus-visible, and disabled states for interactive elements.
- Follow the 8px spacing grid.
- Meet WCAG 2.2 AA contrast minimums.

### Never

- Do not introduce colors outside the extracted palette.
- Do not use arbitrary spacing values — stick to the scale.
- Do not mix border-radius values. Pin to the detected set (4px, 11px, 24px).
- Do not use full-uppercase text for body or paragraph content.
- Do not nest interactive elements (e.g. buttons inside links).
- Do not ship components without defining hover, focus-visible, and disabled states.

## Tone

Concise, confident, implementation-focused. Avoid filler preambles.

## Authoring Workflow

When creating or documenting a component for this system:

1. State intent — one sentence on purpose.
2. Map tokens — list every token the component uses.
3. Define anatomy — named parts with token assignments.
4. Specify states — default, hover, focus-visible, active, disabled, loading, error, empty.
5. Describe interactions — keyboard, pointer, touch, edge cases.
6. Add a11y criteria — testable pass/fail checks.
7. List anti-patterns — concrete misuse examples.
8. Close with the Definition of Done checklist.

## Output Structure

Component guidelines must contain, in order:

1. Overview (purpose, when to use, when not to use)
2. Tokens and foundations
3. Anatomy, variants, responsive behavior
4. States and interactions
5. Accessibility (ARIA, contrast, focus, screen reader)
6. Content guidelines (copy rules, tone)
7. Anti-patterns with reasoning

## Component Requirements

- Reference only tokens from the tables above.
- Define all states: default, hover, focus-visible, active, disabled, loading, error.
- Handle edge cases: empty, overflow, truncation, max content.
- Include keyboard navigation behavior.
- Document ARIA roles and labels.

## Definition of Done

- Default state renders (smoke test).
- All states visually verified.
- Zero hardcoded visual values — tokens only.
- Keyboard navigation works without pointer.
- No critical a11y violations.
- Tested at min and max breakpoint.
- At least one anti-pattern documented.
- Purpose, usage, and limitations documented.
