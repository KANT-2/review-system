---
version: alpha
name: AX Evaluation Console
description: A calm, structured education evaluation dashboard built with Bootstrap 5.3. The system prioritizes clear hierarchy, predictable interaction, compact Korean-first typography, and reusable layout patterns.
colors:
  primary: "#1769E0"
  primary-hover: "#0F5AC4"
  primary-container: "#EAF2FF"
  navigation: "#082A4B"
  navigation-hover: "#103A62"
  background: "#F6F8FC"
  surface: "#FFFFFF"
  surface-subtle: "#FAFBFD"
  text: "#182230"
  text-muted: "#667085"
  outline: "#E2E8F0"
  success: "#168A50"
  warning: "#B7791F"
  error: "#C93C3C"
typography:
  display:
    fontFamily: "Pretendard, Noto Sans KR, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 28px
    fontWeight: 700
    lineHeight: 1.3
  heading:
    fontFamily: "Pretendard, Noto Sans KR, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 18px
    fontWeight: 700
    lineHeight: 1.4
  body:
    fontFamily: "Pretendard, Noto Sans KR, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Pretendard, Noto Sans KR, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: 13px
    fontWeight: 600
    lineHeight: 1.4
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
rounded:
  sm: 6px
  md: 10px
  lg: 14px
layout:
  sidebar-width: 240px
  topbar-height: 64px
  content-max-width: 1440px
---

# AX Evaluation Console

## Overview

AX Evaluation Console is an education-focused evaluation system for students and tutors.

The interface should feel **calm, trustworthy, structured, and easy to scan**. It should look like a practical SaaS admin product rather than a promotional website.

The design should help users quickly understand where they are, what they need to do, what information is most important, and what action should come next.

Bootstrap 5.3 is the implementation baseline. Custom CSS should extend Bootstrap rather than replace its interaction model.

## Colors

The visual system uses a small, controlled palette.

- **Primary Blue** is the main interaction color.
- **Navigation Navy** anchors the application shell.
- **Light Gray Background** separates the canvas from content surfaces.
- **White Surface** is used for cards, tables, forms, and major content containers.
- **Neutral Text Colors** create clear hierarchy between primary and secondary information.
- **Semantic Colors** such as success, warning, and error are reserved for meaning rather than decoration.

Avoid introducing additional accent colors unless they have a clear functional purpose.

## Typography

Use a Korean-first system font stack so the interface remains stable without depending on an external web font.

Typography should remain compact and functional.

- Page titles establish the highest hierarchy.
- Section headings divide major content areas.
- Body text is optimized for dense dashboard information.
- Labels and controls use slightly stronger weight for quick scanning.

Avoid decorative fonts, oversized headings, or unnecessary text weight variation.

## Layout

The application uses a consistent dashboard shell.

### Desktop

- Fixed navigation sidebar on the left.
- Compact top bar above the main content area.
- Main content arranged with Bootstrap containers, rows, and columns.
- Content width should remain readable on large monitors.
- Cards and tables should align to a consistent grid.

### Tablet and Mobile

- The sidebar becomes a collapsible or off-canvas navigation.
- Multi-column layouts collapse progressively.
- Tables remain horizontally scrollable when necessary.
- Primary actions remain easy to reach and tap.

Do not compress information so aggressively that hierarchy or readability is lost.

## Spacing

Use a consistent 4px-based spacing rhythm.

Recommended spacing progression:

- 4px for micro spacing
- 8px for related inline elements
- 16px for standard component spacing
- 24px for sections and card padding
- 32px or more for major page separation

Spacing should communicate grouping before borders or decorative elements are added.

## Elevation & Depth

Use minimal elevation.

- The page canvas uses a light gray background.
- Content surfaces are white.
- Cards use a subtle border and restrained shadow.
- The top bar is separated with a border rather than a heavy shadow.
- The sidebar relies on color contrast rather than elevation.

Avoid glassmorphism, strong blur, deep shadows, or decorative layering.

## Shapes

Use restrained rounded corners.

- Small controls: subtle rounding
- Buttons and inputs: medium rounding
- Cards and major panels: slightly larger rounding

Rounded corners should remain consistent across the system.

Avoid exaggerated pill shapes except where the content naturally requires a compact inline control.

## Components

Bootstrap components should be used as the structural foundation.

Prefer:

- `container`, `container-fluid`
- `row`, `col-*`
- `card`
- `table`, `table-responsive`
- `btn`
- `form-control`, `form-check`, `form-select`
- `nav`, `navbar`, `offcanvas`
- spacing and responsive utility classes

Custom styling should focus on brand colors, spacing, radius, typography, navigation appearance, and overall visual consistency.

Feature-specific rules should live in the corresponding page or component implementation rather than in this document.

## Interaction

Interaction should remain predictable.

- One primary action should be visually dominant within each local context.
- Secondary actions should remain visually quieter.
- Destructive actions should be clearly separated.
- Disabled controls must still communicate why they are unavailable.
- Hover, focus, active, and disabled states should follow Bootstrap conventions.
- Important information should never depend on color alone.

Avoid custom interaction patterns when a standard Bootstrap pattern already communicates the same behavior clearly.

## Responsive Behavior

Responsive behavior should preserve information hierarchy rather than reproduce the desktop layout at a smaller size.

- Sidebar → off-canvas navigation
- Multi-column cards → fewer columns
- Wide tables → horizontal scrolling
- Dense action groups → stacked or wrapped controls
- Main content padding → reduced on smaller screens

Mobile layouts should remain task-oriented and readable.

## Accessibility

The UI should follow practical accessibility principles.

- Maintain sufficient text and control contrast.
- Use semantic HTML.
- Associate labels with form controls.
- Preserve keyboard focus states.
- Provide readable text for important states and actions.
- Keep interactive targets large enough for touch input.

Accessibility should be treated as part of the base design rather than an optional enhancement.

## Do's and Don'ts

### Do

- Use Bootstrap 5.3 as the default UI framework.
- Reuse the same layout and component language across pages.
- Keep the interface calm and information-focused.
- Use whitespace and hierarchy before adding decoration.
- Keep Korean UI labels short and literal.
- Prefer reusable patterns over page-specific visual inventions.
- Keep static HTML previews visually stable when opened independently.

### Don't

- Don't use decorative gradients across content surfaces.
- Don't use glassmorphism or heavy visual effects.
- Don't add multiple competing accent colors.
- Don't create different visual systems for each page.
- Don't override Bootstrap behavior unnecessarily.
- Don't encode feature-specific business rules into the global design specification.
