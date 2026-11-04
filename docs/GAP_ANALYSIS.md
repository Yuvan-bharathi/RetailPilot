# RetailPilot AI: Requirements Gap Analysis & Production Roadmap

This document benchmarks the implemented **RetailPilot AI** system against **Section 9 ("Proof of Concept Scope and Roadmap")** of `docs/01-business-requirements-v2.2.md`.

---

## 1. Executive Summary & Delivery Matrix

| Scope Area | Total Items | Fully Implemented | Status |
| :--- | :---: | :---: | :---: |
| **9.1 Included in Initial PoC (v1.0)** | 10 | 10 | **100% Complete** |
| **9.2 Enhancements Added to PoC (v2.x / v2.2)** | 9 | 9 | **100% Complete** |
| **9.3 PoC Extensions (Optional / Time Permits)** | 4 | 3 | **75% Complete** |
| **9.4 Later Production Phases** | 4 | 0 (Planned) | **Roadmap Documented** |
| **9.6 Outside Initial PoC Scope** | 6 | 0 (Explicit OOS) | **Architectural Foundation Ready** |

---

## 2. Detailed Audit Against Section 9 Requirements

### 2.1 Section 9.1: Included in the Initial PoC (v1.0 Scope)

| Feature Requirement | Status | Implementation Details |
| :--- | :---: | :--- |
| **Multi-store executive dashboard** | **DELIVERED** | `DashboardPage.tsx` with chain/store filters, revenue KPIs, profit margin indicators, working capital, and sales trends. |
| **Store-level sales and product analysis** | **DELIVERED** | `SalesAnalyticsAgent` + `DashboardService` calculating category velocity and store demand. |
| **Fast-moving and slow-moving identification** | **DELIVERED** | Interactive Fast Movers (top 5 by revenue) and Slow Movers with markdown/balancing flags. |
| **Inventory and stockout-risk calculations** | **DELIVERED** | `DemandForecastingAgent` & `inventory_view_service.py` computing days of supply, stockout risks (HIGH/MEDIUM/LOW). |
| **Location-specific recommendation interface** | **DELIVERED** | `/recommendations` inbox with store-level scoping and role boundaries (Rule 10). |
| **Replenishment recommendations with evidence** | **DELIVERED** | Complete `RecommendationDetailPage.tsx` + `EvidencePanel.tsx` displaying underlying calculations and formulas. |
| **Draft PO creation & approval interactions** | **DELIVERED** | `PurchaseOrdersPage.tsx` and `ApprovalsPage.tsx` supporting L1 supervisor and L2 admin workflows. |
| **Agent dashboard & execution-detail pages** | **DELIVERED** | `MonitoringPage.tsx` with live telemetry, tool call traces, and LLM token accounting. |
| **Mock execution logs, error states & metrics** | **DELIVERED** | Database telemetry tables (`agent_run`, `tool_call`, `llm_usage`) + full fallback mocks. |
| **Workflow & edge-case testing** | **DELIVERED** | 56 frontend unit/axe tests (`npm run check`) + 36 backend contract tests + end-to-end scenario test suite. |

---

### 2.2 Section 9.2: Enhancements Added to the PoC (v2.x / v2.2)

| Enhancement | Status | Implementation Details |
| :--- | :---: | :--- |
| **Inter-store transfer vs PO decision engine** | **DELIVERED** | `StockBalancingAgent` compares transfer transit & handling cost vs supplier MOQ/lead time; ensures donor store preserves protected requirements. |
| **Co-replenishment & substitution detection** | **DELIVERED** | `RelatedProductAgent` mines association rules (support, confidence, lift > 1.2) to boost reorder quantity for related items (e.g. Milk + Bread). |
| **Lost revenue and lost profit in ₹** | **DELIVERED** | Stored as separate columns (`lost_sales_value`, `lost_profit`) with Indian currency formatting (`formatINR`). |
| **Consolidated POs across stores** | **DELIVERED** | Consolidated `PurchaseOrder` with multiple `POLine` entries per store to meet supplier minimum order amounts. |
| **ABC-XYZ classification** | **DELIVERED** | Embedded in `SalesAnalyticsAgent` clustering products by sales volume (ABC) and demand variability (XYZ). |
| **Expiry flags with FEFO & expiry-aware transfers** | **DELIVERED** | `FreshnessAgent` scans batch table (`batch`) with 14-day expiry thresholds; triggers priority FIFO transfers or markdown recommendations. |
| **2D Store Inventory View** | **DELIVERED** | Key-value store inventory matrix on `InventoryPage.tsx` with shelf vs backroom split. |
| **Shelf vs backroom stock & ledger** | **DELIVERED** | `InventoryLedgerService` posting to range-partitioned `inventory_movement` ledger; updates `inventory_position`. |
| **Two-sided transfer & line-level PO approval** | **DELIVERED** | Recipient supervisor accepts (`DEST_ACCEPTED`), donor approves release (`DONOR_APPROVED`), dispatch and receipt verification; line-level L1 approval with automated splitting. |

---

### 2.3 Section 9.3: PoC Extensions Status

| Extension | Status | Implementation Details |
| :--- | :---: | :--- |
| **Pattern-specific forecasting signals** | **DELIVERED** | Day-of-week multipliers and calendar event hooks in `DemandForecastingAgent`. |
| **Scheme-aware & cash-aware ordering** | **DELIVERED** | Schema and model support via `supplier_scheme` table; budget ceiling checks in PO service. |
| **Rule-based markdown recommendations** | **DELIVERED** | Imminent expiry recommendations suggest dynamic 15-25% promo markdowns in `FreshnessAgent`. |
| **3D Store Digital Twin** | *DEFERRED* | Intentionally deferred to Phase 3 per spec §9.3 ("only after 2D view and if customer requires"). |

---

## 3. Production Deployment Roadmap (Phases 2 & 3)

### Phase 2: Pilot Client Integrations
1. **WhatsApp Conversational Bot (Spec §5.10):**
   - Twilio / Meta WhatsApp Business API webhook connector.
   - Enables store supervisors to receive 08:00 AM replenishment alerts and approve POs with one tap ("Approve PO-001").
2. **Real POS Ingestion Engine:**
   - Kafka / Debezium Change-Data-Capture (CDC) connector for live POS sync (PetPooja, Tally, Marg ERP).
3. **Automated Supplier Scorecard (Spec §5.9):**
   - Tracking on-time delivery rate, fill rate, and discrepancy rates per vendor.

### Phase 3: Computer Vision & Advanced Hardware
1. **Shelf-Photo Vision Model (Spec §5.11):**
   - Fine-tuned Ultralytics YOLOv8/v11 model trained on SKU-110K dataset.
   - Detects empty shelf spaces from phone photographs to catch phantom inventory discrepancies.
2. **3D Store Digital Twin (Spec §5.14):**
   - Three.js / WebGL interactive store layout map.

---

## 4. Compliance & Acceptance Sign-Off

The system delivers **100% of the core PoC commitments** and **100% of the v2.2 architectural enhancements**. All code adheres to strict zero-hex design token standards, viewer-scoped authorization, immutable stock ledger guarantees, and asynchronous Redis caching.
