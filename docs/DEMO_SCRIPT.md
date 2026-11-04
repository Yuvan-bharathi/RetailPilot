# RetailPilot AI: Demonstration Walkthrough & Evaluation Script

This guide outlines the complete operational walkthrough of **RetailPilot AI** across all 5 core demonstration scenarios. It provides exact test credentials, step-by-step UI actions, API interactions, and autonomous agent decisions.

---

## 1. Setup & Demonstration Personas

### Rapid Seed & Reset Commands
From `backend/`:
```bash
# Reset database to clean baseline and purge cache:
uv run python -m scripts.reset_demo

# Seed master catalog and all 5 demo scenarios:
uv run python -m scripts.seed_demo
```

### User Roles & Logins

| Persona | Username | Password | Role | Scope |
| :--- | :--- | :--- | :--- | :--- |
| **Priya Sharma** | `admin` | `demo` | Super Admin | Chain-wide (Stores A, B, C) |
| **Karthik Nair** | `sup.a` | `demo` | Store Supervisor | Koramangala Store (BLR-KOR) |
| **Sneha Rao** | `sup.b` | `demo` | Store Supervisor | Indiranagar Store (BLR-IND) |
| **Vikram Reddy** | `sup.c` | `demo` | Store Supervisor | HSR Layout Store (BLR-HSR) |

---

## 2. Walkthrough: The 5 Core Demonstration Scenarios

### Scenario 1: Urgent Stockout Replenishment (Koramangala Store A)
- **Problem:** High-velocity fresh milk (`DAI-MILK-TONED-1L`) has only 6 units on hand at Koramangala Store A. Daily consumption is 38 units, leading to guaranteed stockout within 4 hours.
- **Agent Decision:** `DemandForecastingAgent` & `PurchaseOrderAgent` calculate a replenishment deficit of 19 units below safety stock, recommending an urgent reorder of 36 units.
- **Walkthrough Steps:**
  1. Login as `sup.a` (Store Supervisor, Koramangala).
  2. Navigate to **AI Recommendations** (`/recommendations`).
  3. Observe the high-priority pill: **"Fresh Toned Milk 1L - Critical Stockout Imminent"**.
  4. Click the row to open the **Evidence Panel**:
     - Daily velocity: 38 units/day.
     - Days of supply: 0.2 days.
     - Est. lost sales prevented: ₹1,728.
  5. Click **Accept Recommendation**. The line is queued into today's consolidated supplier order.

---

### Scenario 2: PO Approval Workflow & Threshold Escalation (L1 / L2)
- **Problem:** High-value consolidated purchase order exceeds the ₹50,000 operational budget ceiling (Total: ₹56,400.00). Under governance rules, this requires L2 Super Admin sign-off before electronic transmission to the supplier.
- **Agent Decision:** `PurchaseOrderAgent` automatically flags the PO for L2 review with a hard approval deadline of 11:30 AM IST.
- **Walkthrough Steps:**
  1. Login as `admin` (Super Admin).
  2. Observe the notification badge in the header: **"PO exceeds ₹50,000 threshold (₹56,400.00). Pending L2 Super Admin sign-off."**
  3. Click the bell or navigate to **Approvals** (`/approvals`).
  4. In the Approval Centre:
     - Review the order breakdown: Milk (Store A: ₹20,160), Paneer (Store B: ₹26,250), Bread (Store C: ₹9,990).
     - Notice the countdown timer to the 11:30 AM supplier transmission cutoff.
  5. Click **Approve Order**. The order transitions to `APPROVED` and is scheduled for dispatch.

---

### Scenario 3: Expiry-Aware Inter-Store Balancing (Store B -> Store C)
- **Problem:** HSR Store C is facing a stockout of Paneer (`DAI-PANEER-MALAI-200G`) with 2 units left. Meanwhile, Indiranagar Store B holds 75 units (48 units of surplus) with 10 days of shelf life.
- **Agent Decision:** `StockBalancingAgent` proposes an inter-store transfer of 20 units from Store B to Store C. This satisfies Store C's deficit while preserving Store B's protected safety stock and saving procurement lead time.
- **Walkthrough Steps:**
  1. Login as `sup.c` (Recipient Supervisor, HSR Layout).
  2. Navigate to **Stock Transfers** (`/transfers`) -> **Inbound** tab.
  3. Locate the proposed transfer from `BLR-IND` -> `BLR-HSR` (20 units, Transit: 1 day).
  4. Click **Accept Transfer**. Status transitions to `DEST_ACCEPTED`.
  5. Switch persona to `sup.b` (Donor Supervisor, Indiranagar).
  6. Go to **Stock Transfers** -> **Outbound** tab.
  7. Verify the numberless assurance: *"Donor keeps full protected requirement"*.
  8. Click **Approve Release**, then **Dispatch Stock**.
  9. Switch back to `sup.c` and click **Receive Transfer** (enter 20 units). Stock ledger posts arrival immediately.

---

### Scenario 4: Basket Association Rule Co-Replenishment (Milk + Bread)
- **Problem:** Market basket mining shows that 42% of customer transactions containing Fresh Toned Milk also include Premium White Bread (`Lift: 2.4`). A surge in milk sales will trigger unexpected bread stockouts if bread is only ordered based on historical isolated sales.
- **Agent Decision:** `RelatedProductAgent` intercepts the replenishment pipeline, detecting the joint association rule, and boosts bread reorder quantity by +18%.
- **Walkthrough Steps:**
  1. Login as `sup.a` or `admin`.
  2. Navigate to **AI Recommendations** (`/recommendations`).
  3. View the recommendation for **Premium White Bread 400g**.
  4. Inspect the **Evidence Drawer**:
     - Rule: `Milk_Bread_CoPurchase` (Confidence: 42%, Lift: 2.4).
     - Adjusted Demand Lift: +18%.
  5. The store supervisor accepts the co-replenishment recommendation with confidence.

---

### Scenario 5: Imminent Expiry Alert & Markdown Protection (Paneer Batch)
- **Problem:** Indiranagar Store B holds batch `LOT-PNR-202611-01` (18 units of Malai Paneer) expiring in 2 days. Store B's local run rate cannot clear these units before expiration, risking ₹1,980 in total write-offs.
- **Agent Decision:** `FreshnessAgent` identifies the batch during the nightly sweep, prioritizing FIFO liquidation and generating a transfer/markdown action before spoilage occurs.
- **Walkthrough Steps:**
  1. Login as `sup.b` (Indiranagar Store Supervisor).
  2. Navigate to **Inventory** (`/inventory`) -> **Expiring Soon** tab.
  3. Review the high-risk batch: `LOT-PNR-202611-01` (Expires in 2 days, 18 units remaining).
  4. Check **AI Recommendations**:
     - System recommendation proposes immediate priority FIFO dispatch or a 25% promo markdown.
  5. Click **Accept**, ensuring 0% inventory wastage.

---

## 3. System Observability & Telemetry (Super Admin)

1. Login as `admin`.
2. Navigate to **System Monitoring** (`/monitoring`).
3. View the live telemetry dashboard:
   - Total recorded runs, success rate, executed tool invocations, and LLM token usage.
4. Click **View Trace** on any agent execution:
   - View parent/child execution hierarchy.
   - Inspect tool calls (e.g. `query_velocity_metrics` with duration in ms).
   - Inspect LLM token consumption by model (`claude-3-7-sonnet`).
5. Click **Trigger Nightly Pipeline** to execute an on-demand replenishment cycle.
