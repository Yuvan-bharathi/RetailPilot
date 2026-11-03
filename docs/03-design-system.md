# RetailPilot AI — Design System v1.0 (frozen) + UI rules

Light mode only · Burgundy & Neutral · Premium SaaS · Information-dense · Font: Inter.
Burgundy is the identity colour for primary actions, active navigation and key emphasis — not applied everywhere.
Reference inspiration: Heirloom dashboard (Dribbble) for overview screens; Odoo inventory for operational tables.

## 1. Tokens — single source of truth (`frontend/src/styles/tokens.css`)
```css
:root {
  /* Brand */
  --brand-primary: #873F52; --brand-hover: #6F3042; --brand-soft: #F3E9EC; --brand-muted: #D8BFC5;
  /* Neutral */
  --app-bg: #F7F6F5; --surface: #FFFFFF; --sidebar-bg: #F1EFEE; --surface-elevated: #FCFBFA;
  --border: #E8E3E2; --divider: #EEEAE9;
  /* Text */
  --text-primary: #332D30; --text-secondary: #746A6D; --text-muted: #958B8D; --text-disabled: #C8C1C2;
  /* Supporting accents */
  --accent-blue: #7892A6; --accent-lavender: #A096B5; --accent-sand: #C5A779;
  --accent-sage: #8DAE9A; --accent-stone: #A5A0A0;
  /* Semantic status */
  --success-bg: #E8F2EC; --success-text: #397653;
  --warning-bg: #FBF1DF; --warning-text: #986F28;
  --attention-bg: #F8EDE5; --attention-text: #A7653D;
  --danger-bg: #F7E8E8; --danger-text: #A64F52;
  --info-bg: #EAF0F5; --info-text: #56758F;
  --neutral-bg: #EFEEED; --neutral-text: #706A6A;
  /* Typography */
  --font-family: "Inter", sans-serif;
  /* Layout */
  --sidebar-width: 248px; --sidebar-collapsed-width: 72px; --header-height: 64px;
  --page-padding: 24px; --content-gap: 20px;
  /* Components */
  --radius-card: 10px; --radius-input: 7px; --radius-button: 7px; --radius-modal: 12px;
  /* Shadows */
  --shadow-card: 0 1px 3px rgba(51, 45, 48, 0.04);
  --shadow-dropdown: 0 8px 24px rgba(51, 45, 48, 0.10);
}
```
Map these into Tailwind v4 with an `@theme` block in CSS (e.g. `@theme { --color-brand: var(--brand-primary); … }`,
giving utilities such as `bg-brand`), not a `tailwind.config` file (decision D-11). No other hex values anywhere.

## 2. Typography
Page title 28/600 · Section title 18/600 · Card title 14/600 · Body 14/400 · Labels 500 · Metadata 12/400 ·
KPI numbers 600 with `font-variant-numeric: tabular-nums`. Sentence case; no all-caps headings.

## 3. Layout and components
- Spacing base 4px (4, 8, 12, 16, 20, 24, 32, 40). Table rows 44–48px. Inputs 40px. Buttons 38–40px.
- Sidebar: pale neutral, burgundy icon+text for active item, collapsible to 72px. Never a dark sidebar.
- Header (64px): page title, store switcher + period selector (Super Admin), "Data as of last run: <time>", user menu.
- Cards: white, 1px border, 10px radius, no heavy shadows; KPI value + optional trend chip + metadata.
- Buttons: Primary (burgundy fill) · Secondary (white, border) · Tertiary (text) · Destructive · Disabled.
- Tables: sticky header, search, filters, group-by, sort, pagination, row selection, status badges,
  right-aligned numbers, row action menu, configurable columns, loading/empty/error states.
- Forms/modals: labels above inputs, required markers, inline validation, confirmation before high-impact
  actions showing reason, consequences and approver.
- Status badges: semantic colours + text label + icon (never colour alone).

## 4. Charts
Inventory #873F52 · Sales #7892A6 · Forecast #A096B5 · Transfers #C5A779 · Stock availability #8DAE9A ·
Historical #A5A0A0 · Secondary brand #D8BFC5. Burgundy only for the primary series. Soft gridlines, compact
legends, no 3D. Alerts use semantic colours, not the analytics palette.

## 5. Navigation map (one map, visibility by role)
| Item | Super Admin | Store Supervisor |
|---|---|---|
| Overview | Business overview | Store overview |
| Stores | ✓ | – |
| Inventory (2D Store Inventory View) | all stores (switcher) | own store |
| Replenishment / AI Recommendations | ✓ | ✓ (own store) |
| Stock Transfers | ✓ (view) | ✓ (accept / approve release / dispatch / receive) |
| Purchase Orders | ✓ | ✓ (own lines) |
| Approvals | L2 + escalations | L1 (own lines) |
| Goods Receipt | – | ✓ |
| Analytics / Reports | business-wide | store reports |
| System Monitoring (agent runs, jobs) | ✓ | – |
| Settings | ✓ | profile only |
Hide items a role cannot access (do not show disabled items).

## 6. Critical workflow UI requirements
| Workflow | Required behaviour |
|---|---|
| Own-stock-first | Show donor's protected requirement before any surplus transfer |
| Stock balancing | Compare short stores with surplus stores |
| Transfer acceptance | Destination explicitly accepts before dispatch |
| Transfer execution | Stepper: Proposed → Destination accepted → Donor approved → Dispatched → Received (+ discrepancy) |
| Purchase order | Transfer quantity and PO remainder shown separately |
| Approval timeout | Deadline countdown, overdue state, escalated state |
| Rejected PO lines | Approved lines preserved (split PO shown); rejected lines clearly marked with reason |
| Shelf/backroom | Distinguish shelf availability from backroom quantity; "refill from backroom" flag |
| Freshness | Batch, expiry date, FEFO priority |
| Lost sales | Lost revenue and lost profit as two separate values |
Recommendation detail must show: destination shortage, donor surplus, donor protected requirement, proposed
transfer qty, PO remainder, transfer vs PO incremental cost, expected delivery, impact on days of cover,
explanation text, acceptance/approval status.
Scoping: a Store Supervisor sees another store only as name + offered/requested quantity.

## 7. Non-negotiable design rules
Light only · burgundy primary · neutrals dominate · no dark sidebar · no neon/gradients · no per-module colours ·
status colours keep their meaning · tables optimised for readability · one component system for both roles ·
actions follow permissions and approval guardrails · responsive for desktop, laptop, tablet ·
visible focus, keyboard navigation, readable contrast.

## 8. Review notes to confirm (do not change tokens without approval — flag only)
- Estimated contrast below WCAG AA 4.5:1 for 12px text: `--text-muted` on white (~3.3:1), warning text on
  warning bg (~4:1), attention text on attention bg (~4:1). Use `--text-secondary` for essential small text and
  verify with a contrast checker; propose darker values for approval.
- Brand burgundy and danger text are close in hue: destructive buttons should be outlined with danger text,
  and critical badges must carry an icon.
- Muted Rose and Soft Rose share #D8BFC5 — treat as one token (`--brand-muted`).
