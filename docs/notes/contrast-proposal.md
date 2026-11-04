# Contrast proposal — for approval (tokens NOT changed)

Design system v1.0 §8 flagged possible contrast problems. Measured with the WCAG 2.x relative-luminance formula
(AA requires **4.5:1** for normal text, 3:1 for text ≥ 18.66 px bold / 24 px). Status badges and metadata are
12–13 px, so 4.5:1 applies. The tokens in `frontend/src/styles/tokens.css` are unchanged until you approve.

## Measured (current tokens)
| Pair | Ratio | AA (4.5) |
|---|---|---|
| white on `--brand-primary` (primary button) | 7.33 | pass |
| `--text-primary` on surface / app bg | 13.47 / 12.48 | pass |
| `--text-secondary` on surface / app bg / sidebar | 5.22 / 4.83 / 4.55 | pass (sidebar is close) |
| **`--text-muted` on surface / app bg** | **3.30 / 3.06** | **fail** |
| `--brand-primary` on surface / on `--brand-soft` (active nav) | 7.33 / 6.17 | pass |
| `--success-text` on `--success-bg` | 4.72 | pass |
| **`--warning-text` on `--warning-bg`** | **4.04** | **fail** |
| **`--attention-text` on `--attention-bg`** | **3.99** | **fail** |
| `--danger-text` on `--danger-bg` / surface | 4.57 / 5.44 | pass (badge is close) |
| **`--info-text` on `--info-bg`** | **4.22** | **fail** — not flagged in §8; used by "Pending" and "Due in" badges |
| `--neutral-text` on `--neutral-bg` | 4.58 | pass |

## Proposed values (same hue and saturation, lightness lowered to just pass with margin)
| Token | Current | Proposed | New ratio (on its background) |
|---|---|---|---|
| `--text-muted` | #958B8D | #786D6F | 4.62 on app bg |
| `--warning-text` | #986F28 | #8C6625 | 4.64 on `--warning-bg` |
| `--attention-text` | #A7653D | #995C38 | 4.63 on `--attention-bg` |
| `--info-text` | #56758F | #516F87 | 4.60 on `--info-bg` |

Notes
- `--text-muted` at #786D6F is almost identical to `--text-secondary` (#746A6D). Alternative: keep #958B8D but
  restrict it to non-text use (placeholders are already `--text-secondary`, dividers, large text). Phase 7 code does
  not use `--text-muted` for any text today; essential small text uses `--text-secondary` as agreed.
- Brand and danger remain close in hue (§8); destructive buttons are outlined with danger text and critical badges
  carry an icon, as implemented.
- jsdom cannot evaluate colour contrast, so the axe checks in the frontend tests cover structure, names, roles and
  labels but not contrast; this measurement covers contrast.

**Decision needed:** approve the four values (or the `--text-muted` alternative), and I will update `tokens.css`,
design doc §1 and record it in the decision log.
