# LAYOUT.md

This document defines the **global layout structure and shared layout principles** for AX Evaluation Console.

It does not define page-specific screen compositions or feature-level UI details.

`LAYOUT.md` focuses on **where major interface regions are placed and how they behave**, not on how individual components are styled.

---

## 1. Layout Goals

The application should use one consistent dashboard shell across all authenticated pages.

The layout should:

- Make the user's current location easy to understand.
- Keep navigation and utility functions in predictable positions.
- Keep the main content starting position consistent across pages.
- Allow student and admin screens to share the same base layout.
- Reflow naturally across desktop, tablet, and mobile.
- Use Bootstrap 5.3 Grid and responsive utilities as the default layout system.

---

## 2. Global Application Shell

All authenticated pages should use the same three-region application shell.

```text
┌───────────────┬──────────────────────────────────────┐
│               │ Top Bar                              │
│               ├──────────────────────────────────────┤
│   Sidebar     │                                      │
│               │            Main Content              │
│               │                                      │
└───────────────┴──────────────────────────────────────┘
```

The application shell consists of:

```text
App Shell
├── Sidebar
├── Top Bar
└── Main Content
```

Page templates should inherit this shared structure instead of recreating it.

---

## 3. Sidebar

On desktop, the sidebar is fixed to the left side of the viewport.

Base rules:

- Expanded width: `240px`
- Full viewport height
- Contains service identity and primary navigation
- Shows the active navigation item
- Remains visually separated from the main content area
- Includes a hamburger button near the top of the sidebar
- May contain low-priority utility links near the bottom

The hamburger button controls the sidebar itself.

Recommended desktop behavior:

```text
Expanded Sidebar
┌──────────────────────┐
│ Logo / Brand     ☰   │
│                      │
│ Navigation           │
│ Navigation           │
│ Navigation           │
└──────────────────────┘
```

When collapsed, the sidebar may reduce to an icon-only navigation rail.

```text
Collapsed Sidebar
┌──────┐
│  ☰   │
│  ◇   │
│  ◇   │
│  ◇   │
└──────┘
```

The collapsed width should remain consistent across the application. A width of approximately `72–80px` is recommended.

When the sidebar is collapsed:

- Keep navigation icons visible.
- Hide or visually collapse text labels.
- Preserve the active navigation state.
- Keep the hamburger control accessible.
- Do not remove navigation items from the DOM only for visual collapse.
- The Main Content area should expand into the released horizontal space.

The sidebar should not be used to display primary business content.

Navigation depth should remain shallow.

Recommended maximum depth:

```text
Navigation Group
└── Navigation Item
```

In general, keep navigation to two levels or fewer.

---

## 4. Top Bar

The Top Bar is a shared utility region placed above the Main Content area.

Base rules:

- Height: `64px`
- Spans the full width of the content area to the right of the Sidebar
- Remains visually lightweight
- Contains global or cross-page utilities
- Should not replace the page-level header inside Main Content
- Does not need a desktop hamburger button because the primary sidebar control lives inside the Sidebar

Recommended structure:

```text
┌────────────────────────────────────────────────────┐
│ Left / Context                         Utilities   │
└────────────────────────────────────────────────────┘
```

### Left Side

Keep the left side minimal.

It may contain:

- A lightweight breadcrumb
- A short current-location label
- A mobile menu trigger when needed

On desktop, the sidebar hamburger remains inside the Sidebar rather than the Top Bar.

Do not duplicate the full page title here if the same title already appears in the Page Header.

### Right Side

The right side is reserved for global functions.

Typical examples:

- Notifications
- User profile / account menu
- Logout
- Help or support entry point
- Global quick action
- Role switch or admin shortcut when the product requires it

These actions should be useful across multiple pages.

Page-specific actions such as `Create Round`, `Submit Evaluation`, or `Save Changes` should remain in the Page Header or page content.

---

## 5. Main Content

The Main Content area contains the actual working content for each page.

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
- Place page-specific titles and actions inside this area

---

## 6. Content Width

Content should not automatically consume the full viewport width.

Recommended hierarchy:

```text
Viewport
└── App Shell
    ├── Sidebar
    └── Content Area
        ├── Top Bar
        └── Main Content
            └── Content Container
                └── Page Content
```

On desktop, the Main Content area should generally stay within a maximum width of approximately `1440px`.

Even when a table or management screen requires more horizontal space, the overall application shell should remain unchanged.

---

## 7. Bootstrap Grid

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

## 8. Vertical Structure

Most pages should follow this general vertical flow:

```text
Top Bar
↓
Page Header
↓
Primary Content
↓
Secondary Content
```

Add a summary region only when it helps users understand the page.

```text
Top Bar
↓
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

## 9. Page Header

The Main Content area should begin with a consistent Page Header structure.

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

Right side:

- Primary page action

Rules:

- Keep page titles in the same position across the application.
- If no primary action exists, leave the right side empty.
- Avoid placing multiple competing primary actions in the same area.
- Do not move page-specific primary actions into the Top Bar.

---

## 10. Top Bar vs. Page Header

The two regions have different responsibilities.

### Top Bar

Use for:

- Global navigation support
- Notifications
- User account controls
- Help
- Cross-page utilities

### Page Header

Use for:

- Current page title
- Current page description
- Current page primary action

Example:

```text
Top Bar
┌──────────────────────────────────────────────┐
│ Breadcrumb        Notification   User Menu   │
└──────────────────────────────────────────────┘

Page Header
┌──────────────────────────────────────────────┐
│ Evaluation Rounds              [Create Round]│
│ Manage evaluation schedules and settings     │
└──────────────────────────────────────────────┘
```

Avoid placing the same information or action in both regions.

---

## 11. Section Spacing

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

## 12. Full-Width and Split Layouts

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

## 13. Card Grid

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

## 14. Table Layout

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

## 15. Form Layout

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

## 16. Responsive Layout

Use Bootstrap's default breakpoints.

### Large (`lg`) and above

```text
Sidebar: Fixed
Top Bar: Full-width utility region within content area
Main Content: Multi-column allowed
```

### Medium (`md`)

```text
Sidebar: Offcanvas when needed
Top Bar: Keeps essential utilities only
Main Content: One or two columns
Supporting areas may move below primary content
```

### Small (`sm`) and below

```text
Sidebar: Offcanvas
Top Bar: Compact
Main Content: Single column
Table: Horizontal scroll
Actions: Wrapped or full-width when needed
```

Do not simply shrink the desktop layout for mobile.

Reflow the interface while preserving information priority.

---

## 17. Mobile Navigation

Do not keep the desktop sidebar fixed on small screens.

On mobile, the same navigation concept should open as a Bootstrap Offcanvas.

Recommended structure:

```text
Top Bar
├── Mobile Menu Trigger
└── Global Utilities

Mobile Menu Trigger
└── Bootstrap Offcanvas
    ├── Hamburger / Close Control
    ├── Service Identity
    └── Navigation
```

On desktop, the hamburger button belongs inside the Sidebar.

On mobile, a compact menu trigger may appear in the Top Bar because the Sidebar itself is not visible.

Desktop Sidebar and Mobile Offcanvas should use the same navigation source.

Do not maintain separate navigation definitions for desktop and mobile.

On small screens, low-priority Top Bar utilities may move into the user menu or Offcanvas.

---

## 18. Height and Scrolling

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

## 19. Fixed and Sticky Elements

Keep fixed and sticky elements to a minimum.

Commonly acceptable:

- Desktop Sidebar
- Top Bar
- Mobile Navigation Trigger

Do not make page-specific cards, form actions, or table headers fixed by default.

If sticky positioning is introduced, verify that it does not cover content or consume too much space on mobile.

---

## 20. Common Template Structure

Django should reuse the shared layout through common templates.

Recommended structure:

```text
templates/
├── base.html
└── includes/
    ├── sidebar.html
    ├── topbar.html
    └── messages.html
```

Each page template should extend `base.html`.

```django
{% extends "base.html" %}

{% block content %}
  ...
{% endblock %}
```

Do not duplicate the Sidebar or Top Bar inside individual app templates.

Page Headers remain part of each page's content block because titles and primary actions are page-specific.

---

## 21. Layout Responsibility

`LAYOUT.md` defines:

- Application shell
- Sidebar placement, expansion, and collapse behavior
- Sidebar hamburger control
- Top Bar placement and responsibility
- Main Content area
- Maximum content width
- Grid usage
- Shared Page Header structure
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

## 22. Layout Checklist

Before creating a new page or template, verify:

- Does it use the shared Sidebar + Top Bar + Main Content application shell?
- Is the desktop hamburger control placed inside the Sidebar?
- Does collapsing the Sidebar expand the Main Content area correctly?
- Are global utilities placed in the Top Bar?
- Are page-specific actions kept in the Page Header?
- Is the Page Header positioned consistently inside Main Content?
- Does the main content begin at the same horizontal position as other pages?
- Does it use Bootstrap Grid before custom layout CSS?
- Is the content width appropriately constrained?
- Does it avoid unnecessary nested scrolling?
- Does the Sidebar become Offcanvas on mobile?
- Does the Top Bar remain usable on smaller screens?
- Do multi-column sections collapse naturally on smaller screens?
- Are the shared Sidebar and Top Bar reused instead of duplicated?
- Does the document remain separate in responsibility from `DESIGN.md`?
