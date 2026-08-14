# LAYOUT.md

This document defines the **global layout structure and shared layout principles** for AX Evaluation Console.

It does not define page-specific screen compositions or feature-level UI details.

`LAYOUT.md` focuses on **where major interface regions are placed and how they behave**, not on how individual components are styled.

---

## 1. Layout Goals

The application should use one consistent two-region dashboard shell across all authenticated pages.

The layout should:

- Make the user's current location easy to understand.
- Keep the main content starting position consistent across pages.
- Preserve a predictable navigation and content structure.
- Allow student and admin screens to share the same base layout.
- Reflow naturally across desktop, tablet, and mobile.
- Use Bootstrap 5.3 Grid and responsive utilities as the default layout system.

---

## 2. Global Application Shell

All authenticated pages should use the same two-region application shell.

```text
┌───────────────┬──────────────────────────────────────┐
│               │                                      │
│               │                                      │
│   Sidebar     │            Main Content              │
│               │                                      │
│               │                                      │
└───────────────┴──────────────────────────────────────┘
```

The application shell consists of:

```text
App Shell
├── Sidebar
└── Main Content
```

There is no global top bar.

Page-level titles, descriptions, breadcrumbs, and actions belong inside the Main Content area.

---

## 3. Sidebar

On desktop, the sidebar is fixed to the left side of the viewport.

Base rules:

- Width: `240px`
- Full viewport height
- Contains service identity and primary navigation
- Shows the active navigation item
- Remains visually separated from the main content area
- May contain user-related utility actions near the bottom

The sidebar should not be used to display primary business content.

Navigation depth should remain shallow.

Recommended maximum depth:

```text
Navigation Group
└── Navigation Item
```

In general, keep navigation to two levels or fewer.

---

## 4. Main Content

The Main Content area contains all page-level content.

Base structure:

```html
<main>
  <div class="container-fluid">
    ...
  </div>
</main>
```

Guidelines:

- Maximum content width: `1440px`
- Desktop horizontal padding: approximately `24–32px`
- Tablet horizontal padding: approximately `20–24px`
- Mobile horizontal padding: approximately `16px`
- Prevent content from stretching excessively on very wide screens
- Keep the content start position consistent across pages
- Place page titles and page actions inside this area

---

## 5. Content Width

Content should not automatically consume the full viewport width.

Recommended hierarchy:

```text
Viewport
└── App Shell
    ├── Sidebar
    └── Main Content
        └── Content Container
            └── Page Content
```

On desktop, the Main Content area should generally stay within a maximum width of approximately `1440px`.

Even when a table or management screen requires more horizontal space, the overall application shell should remain unchanged.

---

## 6. Bootstrap Grid

Use Bootstrap 5.3's 12-column grid as the default layout system.

Example:

```html
<div class="row g-4">
  <div class="col-12 col-lg-8">
    ...
  </div>

  <div class="col-12 col-lg-4">
    ...
  </div>
</div>
```

Common layout ratios:

```text
12
8 + 4
6 + 6
4 + 4 + 4
3 + 3 + 3 + 3
```

Prefer Bootstrap Grid over page-specific fixed widths.

---

## 7. Vertical Structure

Most pages should follow this general vertical flow:

```text
Page Header
↓
Primary Content
↓
Secondary Content
```

Add a summary region only when it helps users understand the page.

```text
Page Header
↓
Summary
↓
Primary Content
↓
Secondary Content
```

Not every page needs every section.

Omit regions that do not support the page's primary purpose.

---

## 8. Page Header

The Main Content area should begin with a consistent page header structure.

Base layout:

```text
┌─────────────────────────────────────────────────┐
│ Page Title                     Primary Action    │
│ Short Description                               │
└─────────────────────────────────────────────────┘
```

Left side:

- Page title
- Short description or context
- Optional breadcrumb when needed

Right side:

- Primary page action

Rules:

- Keep page titles in the same position across the application.
- If no primary action exists, leave the right side empty.
- Avoid placing multiple competing primary actions in the same area.
- Do not create a separate global top bar just to hold page actions.

---

## 9. Section Spacing

Major page sections should follow a consistent vertical rhythm.

Recommended pattern:

```text
Page Header
    ↓ 24–32px

Section
    ↓ 24px

Section
    ↓ 24px

Section
```

Spacing between separate sections should be larger than spacing between related elements inside a section.

Detailed spacing tokens and visual rules belong in `DESIGN.md`.

---

## 10. Full-Width and Split Layouts

The Main Content area should primarily use two layout patterns.

### Full-Width

```text
┌──────────────────────────────────────┐
│                                      │
│             Main Content             │
│                                      │
└──────────────────────────────────────┘
```

Use this when the page is centered around one primary task.

### Split Layout

```text
┌────────────────────────┬─────────────┐
│                        │             │
│      Main Area         │ Side Area   │
│                        │             │
└────────────────────────┴─────────────┘
```

Recommended ratios:

```text
8 + 4
```

or:

```text
9 + 3
```

The side area should contain supporting information only.

Do not place the page's primary workflow in the side area.

---

## 11. Card Grid

When multiple equal information units are displayed together, use a Bootstrap Grid-based card layout.

Desktop:

```text
4 columns
or
3 columns
```

Tablet:

```text
2 columns
```

Mobile:

```text
1 column
```

Before introducing custom CSS Grid layouts, check whether Bootstrap `row` and `col-*` classes can solve the layout cleanly.

---

## 12. Table Layout

Tables may be wider than the available content area, so they should be wrapped in a responsive container.

Recommended structure:

```html
<div class="table-responsive">
  <table class="table">
    ...
  </table>
</div>
```

Do not force table columns to become unreadably narrow on mobile.

Allow horizontal scrolling when necessary.

---

## 13. Form Layout

Forms should generally flow vertically.

```text
Label
Input

Label
Input

Label
Input
```

Closely related short fields may share a row.

Example:

```text
Start Date | End Date
```

On smaller screens, these fields should collapse naturally into a single column.

---

## 14. Responsive Layout

Use Bootstrap's default breakpoints.

### Large (`lg`) and above

```text
Sidebar: Fixed
Main Content: Multi-column allowed
```

### Medium (`md`)

```text
Sidebar: Offcanvas when needed
Main Content: One or two columns
Supporting areas may move below primary content
```

### Small (`sm`) and below

```text
Sidebar: Offcanvas
Main Content: Single column
Table: Horizontal scroll
Actions: Wrapped or full-width when needed
```

Do not simply shrink the desktop layout for mobile.

Reflow the interface while preserving information priority.

---

## 15. Mobile Navigation

Do not keep the desktop sidebar fixed on small screens.

Use this structure:

```text
Main Content
└── Mobile Menu Trigger
    └── Bootstrap Offcanvas
        └── Navigation
```

The mobile menu trigger should be placed near the top of the Main Content area or integrated into the page header.

Desktop Sidebar and Mobile Offcanvas should use the same navigation source.

Do not maintain separate navigation definitions for desktop and mobile.

---

## 16. Height and Scrolling

Use the browser's main vertical scroll by default.

Avoid creating nested vertical scroll regions unless there is a strong reason.

Avoid structures such as:

```text
Browser Scroll
└── Main Scroll
    └── Card Scroll
```

Nested scrolling reduces usability.

Use secondary scrolling only where necessary, such as horizontal scrolling for wide tables.

---

## 17. Fixed and Sticky Elements

Keep fixed and sticky elements to a minimum.

Commonly acceptable:

- Desktop Sidebar
- Mobile Navigation Trigger when necessary

Do not make page-specific cards, form actions, or table headers fixed by default.

If sticky positioning is introduced, verify that it does not cover content or consume too much space on mobile.

---

## 18. Common Template Structure

Django should reuse the shared layout through common templates.

Recommended structure:

```text
templates/
├── base.html
└── includes/
    ├── sidebar.html
    └── messages.html
```

Each page template should extend `base.html`.

```django
{% extends "base.html" %}

{% block content %}
  ...
{% endblock %}
```

Do not duplicate the sidebar inside individual app templates.

Page headers should remain part of each page's content block because titles and actions are page-specific.

---

## 19. Layout Responsibility

`LAYOUT.md` defines:

- Application shell
- Sidebar placement
- Main Content area
- Maximum content width
- Grid usage
- Shared page header structure
- Section arrangement
- Full-width and split layouts
- Responsive reflow behavior
- Scrolling principles
- Shared template structure

`LAYOUT.md` does not define:

- Page-specific screen composition
- Feature-specific UI flows
- Colors
- Font sizes
- Button styles
- Badge styles
- Status presentation
- Data models
- Business logic

Page-specific details belong in the actual templates, while visual rules belong in `DESIGN.md`.

---

## 20. Layout Checklist

Before creating a new page or template, verify:

- Does it use the shared Sidebar + Main Content application shell?
- Is the page header positioned consistently inside Main Content?
- Does the main content begin at the same horizontal position as other pages?
- Does it use Bootstrap Grid before custom layout CSS?
- Is the content width appropriately constrained?
- Does it avoid unnecessary nested scrolling?
- Does the sidebar become Offcanvas on mobile?
- Do multi-column sections collapse naturally on smaller screens?
- Is the shared Sidebar reused instead of duplicated?
- Has a global top bar been avoided?
- Does the document remain separate in responsibility from `DESIGN.md`?
