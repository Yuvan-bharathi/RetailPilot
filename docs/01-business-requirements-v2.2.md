**RetailPilot AI**

Retail Intelligence & AI-Powered Replenishment Platform

for FMCG Retail

Problem Understanding and Proposed Solution – with Enhancements

**Prepared by:** Yuvanbharathi N (original v1.0)

**Enhancements:** GWC Development Team (v2.0 / v2.1 / v2.2)

**Original date:** 27 October 2026     **This version:** v2.2, 3 November 2026

**Project Type:** Business Process Optimization using Data Analytics and AI Agents

**Industry:** FMCG Retail (Fast-Moving Consumer Goods / Consumer Packaged Goods sold through supermarkets)

*How to read this version: all content from the original v1.0 document is retained. Additions from v2.0/v2.1 are marked [NEW in v2.x]. Corrections and additions from the v2.2 technical review are marked [UPDATED in v2.2] or [NEW in v2.2] and listed in Appendix C. Appendix A maps each original section to its place in this document, and Appendix B lists every enhancement, so the project stays on the original track.*

# 1. Executive Summary

Retail businesses operating supermarkets across multiple locations face challenges in maintaining the right product assortment, managing inventory, understanding local demand, and making timely purchasing decisions. A product that sells quickly in one location may have low demand in another because of differences in customer demographics, surrounding establishments, purchasing behaviour, and local market conditions.

My proposed solution is a Retail Intelligence and AI-Powered Replenishment Platform that consolidates sales, inventory, product, supplier, and store-level information into a single application.

The platform will analyse historical sales, identify fast-moving and slow-moving products, estimate replenishment requirements, recommend location-specific product assortments, and prepare purchase orders for human review and approval. It will also provide an Agent Observability Dashboard to monitor agent executions, tool usage, decision evidence, errors, latency, and token consumption.

As a Junior FDE, my initial focus will be to understand the business workflow, translate the problem into clear requirements, build a customer-facing proof of concept (PoC), and validate whether the proposed solution can deliver measurable operational value.

**[NEW in v2.x]** The platform is positioned for FMCG retail. Because it restocks fast-moving products and also restocks related products that sell together, v2.x adds the following enhancements on the same track:

- **Related-product engine** (market basket analysis): co-replenishment, substitution detection, assortment-gap suggestions.

- **Better forecasting:** ABC-XYZ classification, models suited to each demand pattern, festival, salary-week and weather signals.

- **Inter-store transfer before purchase:** move only genuine surplus between own stores; raise a PO when every store needs the stock.

- **Lost revenue and lost profit in ₹** as separate KPIs.

- **Scheme-aware and cash-aware ordering,** and consolidated POs.

- **Expiry (FEFO) and markdown management.**

- **WhatsApp interface, supplier scorecard and shelf-photo vision** in later phases.

**[NEW in v2.2]** The v2.2 technical review refined the transfer cost comparison, per-store delivery windows, transfer and consolidated-PO approval, basket data quality and inventory accuracy (shelf vs backroom stock and a movement ledger). It also fixed the technology stack and added a 2D store inventory view to the PoC, with the 3D digital twin kept as a later extension (Sections 5, 16 and 17).

# 2. Business Problem Statement

Supermarket owners operating across multiple locations must make frequent decisions about which products to stock, how much inventory to maintain, when to reorder, and which suppliers to use.

These decisions are often based on the owner’s experience, manual analysis, or separate reports maintained for individual stores. Although experience is valuable, it may not provide a complete picture of changing demand, related-product opportunities, profitability, stockout risks, and differences between locations.

For example, a supermarket near a college or hostel may have different demand patterns from a supermarket in a residential neighbourhood or near a school and temple. Applying the same stocking strategy to all these stores may lead to missed sales opportunities in some locations and excess inventory in others.

Additionally, sales analysis, inventory monitoring, supplier coordination, purchase order creation, and approval may involve multiple manual steps and disconnected systems. This can make it difficult for owners to obtain a consolidated and timely view of their business.

*Problem statement: How might we help multi-location supermarket owners make data-driven, location-specific product assortment and replenishment decisions, improve inventory availability and profitability, and streamline purchasing workflows through a unified, explainable, and human-supervised intelligent application?*

**[NEW in v2.x]** FMCG context: these products sell in high volumes, at low margins and on short replenishment cycles; many are perishable, and demand shifts sharply around festivals, month-end salary dates and seasons. The problem statement above is unchanged; v2.x strengthens how the platform answers it.

## 2.1 Industry Positioning

**[NEW in v2.x]** In industry usage, “FMCG/CPG” usually refers to brands and manufacturers (for example HUL, ITC, Nestlé). A supermarket that restocks fast-moving goods is more precisely described as FMCG retail or grocery retail replenishment, so this platform is positioned as “AI replenishment for FMCG retail”.

**[NEW in v2.x]** Differentiation: standard replenishment tools reorder each store in isolation. This platform also restocks related products together, uses stock already held in the business’s own stores before buying, and quantifies lost sales in rupees.

**[NEW in v2.x]** Market note (future opportunity, not current scope): in India, kirana stores handle nearly 90% of FMCG sales, through the chain Brand → Super Stockist → Distributor → Retailer (Kirana) → Consumer. A distributor serving many kiranas faces a similar replenishment problem, so the same engine could later serve that audience (see Section 9.5).

# 3. My Understanding of the Root Causes

The problem can be divided into six key areas.

### 3.1 Location-Specific Demand

Different stores serve different customer groups and operate in different surroundings. A uniform product assortment may not satisfy the needs of every location.

### 3.2 Limited Sales and Profitability Insights

Owners need to understand not only which products sell the most, but also which products generate higher gross profit, which categories are growing, and which products are underperforming.

### 3.3 Inventory and Stockout Management

Without systematic replenishment calculations, stores may reorder too late, maintain excessive inventory, or miss sales because popular products are unavailable.

### 3.4 Related-Product Opportunities

Historical sales can reveal products frequently purchased together or complementary products that may be worth testing in specific stores. These opportunities may be missed when analysis is performed manually.

### 3.5 Manual Purchasing Workflows

Reorder calculations, supplier selection, purchase order preparation, budget checks, and approvals can require significant coordination and may lack a consistent audit trail.

### 3.6 Limited Visibility into Automated Decisions

When an AI agent recommends an action, business users need to understand the evidence behind the recommendation, which tools were used, whether the execution succeeded, what it cost, and whether human approval is required.

### 3.7 Stock Imbalance Across Own Stores

**[NEW in v2.x]** One store may be overstocked on an item while another store runs out, leading to unnecessary purchase orders and lost sales at the same time.

### 3.8 Perishability and Expiry

**[NEW in v2.x]** Perishable FMCG items that do not sell before expiry become write-offs, eroding already thin margins.

### 3.9 Festivals, Promotions and Distributor Schemes

**[NEW in v2.x]** Demand spikes around festivals and salary dates, and distributor slab offers (for example, buy 10 cases get 1 free) are not reflected in order quantities when ordering is manual.

# 4. Gaps Addressed in This Version

**[NEW in v2.x]** A review of v1.0 found it strong on governance (approvals, observability, human-in-the-loop control) and lighter on the intelligence behind recommendations. v2.x fills these gaps without changing the original direction:

| **Area in v1.0** |** Gap** |** Enhancement (section)** |
| --- | --- | --- |
| Forecasting | Based on average daily sales only | ABC-XYZ and pattern-specific forecasting (5.3) |
| Related products | Mentioned, but no method defined | Market basket engine (5.4) |
| Perishables / expiry | Only “when data is available” | FEFO and markdowns (5.8) |
| Promotions, schemes, festivals | Not covered | Calendar signals (5.3), scheme-aware PO (5.7) |
| Multi-store stock | Each store reordered independently | Inter-store transfer vs PO engine (5.6) |
| Business value | Stockout rate only | Lost revenue and lost profit in ₹ (5.1) |

# 5. Proposed Solution

I propose a centralized retail intelligence application that combines business analytics, inventory decision support, purchasing workflows, and agent observability.

The system will transform raw operational data into actionable recommendations while retaining human control over financially significant decisions.

## 5.1 Unified Business Dashboard

Provide a consolidated view of business performance across all stores. Key capabilities:

- Revenue, gross profit, and sales trends.

- Store and product category comparisons.

- Inventory value and stockout risk.

- Fast-moving and slow-moving products.

- Pending replenishment recommendations and purchase orders.

- **[NEW in v2.x]** ABC-XYZ class, days of cover and near-expiry stock value.

- **[NEW in v2.x]** Pending inter-store transfers.

- **[UPDATED in v2.2]** Lost revenue and lost profit, by store and product, as two separate KPIs. Demand is estimated from the days the product was in stock, so stockout days do not pull the estimate down. This turns “stockout rate” into rupees and is the most persuasive number in a client demo.

*Lost units = demand rate on in-stock days × stockout days     Lost revenue = lost units × selling price     Lost profit = lost units × unit gross margin*

## 5.2 Location-Specific Product Intelligence

Analyse each store independently using its sales history, inventory position, product assortment, and available location context. The system will:

- Identify products with strong or declining demand.

- Compare category performance across locations.

- Highlight potential assortment gaps.

- Identify complementary products from observed purchasing patterns (method defined in 5.4).

- Consider relevant local events, seasonality, and surrounding establishments when reliable data is available.

Location-based assumptions will be treated as hypotheses and validated against actual demand wherever possible.

## 5.3 Demand Forecasting

v1.0 estimates average daily sales and stock cover; this remains the baseline method for the PoC.

**[NEW in v2.x]** Enhanced forecasting, evaluated against the baseline:

- **ABC-XYZ classification:** ABC ranks SKUs by value contribution; XYZ ranks them by demand volatility. Each class gets an appropriate model and safety-stock policy.

- **Pattern-specific models:** many supermarket SKUs sell irregularly (many zero-sale days). The open-source Nixtla statsforecast library provides models built for intermittent demand, such as Croston, IMAPA and TSB, alongside standard models for smooth sellers.

- **External signals:** Indian festival calendar, salary-week effects and weather as external inputs.

- **Accuracy tracking:** back-testing (historical replay) and accuracy by class (WMAPE and bias); a model replaces the baseline only where it is measurably better.

**[UPDATED in v2.2]** Delivery window per store and SKU: the demand that matters is the demand until the next delivery, which differs by store because supplier lead time and review period differ. The requirement for each store-SKU uses its own window (lead time of the supplier serving that store + review period + safety days), and the forecast horizon is set to at least the longest window in the run, instead of applying a fixed 14 days everywhere.

| **Store** |** Supplier lead time** |** Review period** |** Demand window (before safety days)** |
| --- | --- | --- | --- |
| Store A | 3 days | 2 days | 5 days |
| Store B | 7 days | 2 days | 9 days |
| Store C | 5 days | 3 days | 8 days |

## 5.4 Related-Product Intelligence (Market Basket Analysis)

**[NEW in v2.x]** Market basket analysis uses association rule mining (Apriori or FP-Growth) to identify products frequently bought together. Rules are kept when lift is greater than 1, backed by high confidence and adequate support. Rules are calculated per store, because baskets differ by location. The rules power these features:

- **Co-replenishment:** when the agent reorders a product (for example bread), it checks stock cover for its associated products (butter, jam) and includes them if they will run short before the next delivery.

- **Substitution detection:** when Brand A stocks out and Brand B’s sales jump, the pair is flagged as substitutes so both are not over-ordered in the next cycle.

- **Assortment-gap suggestions:** items that sell together in one store but are missing from another are suggested as trial listings.

- **Placement suggestions:** high-lift pairs can be recommended for adjacent shelf placement or bundle offers.

Data note: this requires transaction-level (bill-level) sales data, which must be confirmed with the client (see Section 10).

**[UPDATED in v2.2]** Complements and substitutes are separate analyses: complements come from basket rules (bought together); substitutes come from stockout days (sales of one product rise when another is unavailable). They use different data and methods and are stored and shown separately.

- **[NEW in v2.2]** **Data-quality controls:** before mining, bills are cleaned – returns and voided lines removed, bulk or wholesale bills above a quantity limit excluded, and promotion days optionally excluded so offers do not create false associations. Stores with too few bills are skipped and logged.

- **[NEW in v2.2]** **Configurable thresholds:** minimum bills, support, confidence and lift are business settings (defaults in the technical document), not hard-coded values, and can be tuned per store.

## 5.5 Inventory Analysis and Replenishment

Calculate inventory requirements using historical demand, current stock, incoming stock, supplier lead times, safety stock, and ordering constraints. The system will:

- Estimate average daily sales and stock cover.

- Identify products approaching their reorder points.

- Recommend replenishment quantities.

- Flag excess inventory and potential expiry risks when the required data is available.

- Explain the evidence and calculations behind each recommendation.

- **[NEW in v2.2]** **Shelf vs backroom stock:** stock is held as shelf quantity and backroom quantity (on-hand = shelf + backroom). A product can be short on the shelf while the backroom has stock – that needs a shelf refill task, not a purchase order.

- **[NEW in v2.2]** **Inventory movement ledger:** every change to stock is recorded as a movement – sale, purchase receipt, transfer out, transfer in, adjustment, expiry write-off, shelf refill – with quantity, reason, user and time. Stock levels are derived from the ledger and reconciled daily against the POS snapshot; differences are posted as adjustments and flagged. This makes discrepancies and audits traceable.

## 5.6 Inter-Store Transfer vs Purchase Order Decision Engine

**[NEW in v2.x]** Before buying, the system checks whether the business already holds the needed stock in one of its own stores that does not need it. Transfers happen only when necessary: a product is routed from a store where it is surplus to a store whose forecast shows a need. If a product sells high in every store, each store needs its stock for sales and display, so the product is not routed elsewhere and a purchase order is raised.

### Step 1 – Each store’s own requirement

*Own requirement = forecast demand until the next delivery (lead time + review period) + safety stock + minimum display stock (shelf facings)*

The display minimum ensures that even a slow-selling store keeps enough units to keep the shelf looking full.

**[UPDATED in v2.2]** Lead time is the lead time of the supplier that serves that store, so each store-SKU has its own demand window (see 5.3).

### Step 2 – Transferable surplus

*Surplus = on-hand stock − own requirement*

**[UPDATED in v2.2]** Available stock = shelf + backroom + incoming − reserved (stock already promised to transfers or orders). Surplus is calculated from available stock.

If a product sells fast in both Store A and Store B, the surplus comes out zero or negative, so the system automatically does not transfer it. Only stock above a store’s own requirement is transferable – not whatever happens to be in its storeroom.

### Step 3 – Decide per product, per short store

| **Situation** |** Action** |
| --- | --- |
| Product sells fast everywhere; no store has surplus | Raise a PO |
| One store has enough surplus to cover Store C’s forecast shortfall | Transfer to Store C |
| Some surplus exists, but not enough for Store C | Transfer the surplus; raise a PO for the remainder |
| Surplus exists, but transfer cost or time is worse than a PO | Raise a PO |
| Surplus batch will expire before the donor can sell it, but Store C can sell it in time | Transfer that batch first (expiry-aware) |

### Cost comparison (refined in v2.2)

**[UPDATED in v2.2]** v2.1 compared the transfer cost with the full purchase price of the units. That comparison almost always favours a transfer, because units bought through a PO are paid for either way. v2.2 compares only the incremental cost of each option:

*Transfer incremental cost = fixed trip cost + per-unit transport cost × qty + handling cost at both stores × qty*

*PO incremental cost = order fixed cost + supplier delivery charge + holding cost of the donor’s surplus left unsold (qty × unit cost × holding rate per day × days the donor needs to sell it) + expected expiry loss on that surplus*

A transfer is chosen when its incremental cost is lower than the PO’s incremental cost and it arrives no later than a supplier delivery would. The order fixed cost and delivery charge are shared when the PO is consolidated, so the engine uses the share attributable to this line.

### Decision logic

for store in short_stores (most urgent first):

    need = own_requirement(store) - available(store)

    donors = [s for s in stores if surplus(s, product) > 0]

    for d in sorted(donors, key=lambda s: transfer_cost(s, store)):

        qty = min(surplus(d, product), need)

        if transfer_incremental_cost(d, store, qty) < po_incremental_cost(d, qty) \

           and transit_days(d, store) <= supplier_lead_time(store):

            propose_transfer(d, store, qty); need -= qty

    if need > 0:

        add_to_po(store, product, need)

### Refinements

- **Consolidated PO:** when several stores are short on the same fast mover, raise one PO to the supplier with store-wise delivery quantities. This often reaches volume or scheme slabs and earns a better price.

- **Expiry-aware transfers:** if Store A holds a batch that will expire before A can sell it, but Store C’s forecast can absorb it in time, transfer that batch first. This turns potential waste into sales.

- **Donor protection:** a transfer never takes the donor below its own requirement, even if the destination’s shortage is larger. A transfer must not create a stockout elsewhere.

- **Explain the decision:** the approval screen shows the reasoning, for example “Transferred 24 units from Store A (surplus 24 after its 15-day need + display min); PO for 16 units because no other store had surplus.”

### Transfer approval workflow

**[NEW in v2.2]** Both stores must agree before stock moves, so no store receives unexpected stock or loses stock without authorisation:

- The destination store supervisor accepts the proposed requirement.

- The donor store supervisor approves the release of surplus.

- The system re-checks the donor’s available surplus with that day’s stock (donor protection). If the surplus is gone, the transfer is cancelled and the need moves to the next PO run.

- The transfer is dispatched; the stock is recorded as in transit.

- The receiving supervisor confirms the quantity received.

- Inventory is updated through the movement ledger, including any discrepancy between sent and received quantities.

### Worked example

Store C is forecast to need 40 units of a biscuit SKU before its next delivery and holds 0. Store A holds 54 units against an own requirement of 30 (surplus 24). Store B is selling the item fast and has no surplus.

*Transfer 24 units from Store A to Store C; raise a PO for 16 units for Store C, because no other store has surplus.*

Demo story: “The system first checks whether we already own the stock somewhere we don’t need it, and only buys what’s genuinely missing.”

## 5.7 Purchase Order Management

Provide a structured purchasing workflow from recommendation to approval. The proposed workflow is:

- Identify a replenishment requirement (after inter-store transfers, including co-replenishment items).

- Recommend an order quantity.

- Select an eligible supplier using price, lead time, availability, and ordering constraints (and, from Phase 2, the supplier score).

- Generate a draft purchase order – consolidated across stores where several need the same product from the same supplier.

- Validate the order against budget, minimum order quantities, and other business rules.

- Request approval from an authorized user: Store Supervisor (L1) and Super Admin (L2); POs below a value threshold skip L2. On a consolidated PO, each Store Supervisor approves only their own store’s lines.

- Record the approval and submit the order through an authorized supplier integration when available.

- Track the order status and retain an audit history.

The initial PoC will generate draft purchase orders and demonstrate approval. It will not automatically send real orders to suppliers.

### Consolidated PO approval and rejection policy

**[NEW in v2.2]** A consolidated PO must not be blocked by one store’s decision. Approval therefore works at line level:

- **[NEW in v2.2]** **Line-level states:** each line is Pending, Approved, Edited, Rejected or Expired.

- **[NEW in v2.2]** **Approval deadline:** each PO has an L1 deadline (a business setting). At the deadline, undecided lines are escalated to the Super Admin or marked Expired.

- **[NEW in v2.2]** **Split approved lines:** if Store A approves and Store B rejects (or does not decide in time), Store A’s approved lines are split into a new PO that continues to L2 or approval. Store B’s rejected lines are closed with the reason recorded, and its need is re-evaluated in the next run.

- **[NEW in v2.2]** **L2 on the split PO:** the L2 threshold is checked against the value of the PO that continues, not the original consolidated value.

### Scheme-aware and cash-aware ordering

**[NEW in v2.x]** Indian distributors run slab offers such as “buy 10 cases, get 1 free”. The PO agent can recommend rounding up to reach a slab when the extra stock will sell within its shelf life, show the saving, and keep total spend within the owner’s weekly cash budget.

## 5.8 Expiry and Markdown Management

**[NEW in v2.x]** Track stock by batch with expiry dates and issue on a First-Expiry-First-Out (FEFO) basis. Batches unlikely to sell before expiry at the forecast rate trigger an action: expiry-aware transfer to a faster-selling store, a markdown (discount) recommendation, or a bundle with a related product. Commercial tools such as Wasteless dynamically price perishables based on expiry dates and demand; for the PoC a rule-based version is sufficient. Waste and write-off value is tracked as a KPI.

## 5.9 Supplier Scorecard

**[NEW in v2.x]** Rate each supplier on fill rate, on-time delivery and price trend, and feed the score into supplier selection in the PO agent.

## 5.10 WhatsApp Interface

**[NEW in v2.x]** Owners and supervisors receive the daily reorder list, approve POs with a button, or ask questions such as “what should I order this week?” in their own language. Rationale: even when retailers install a dedicated app, it often sits unused because they default back to WhatsApp, which they already use all day.

## 5.11 Shelf-Photo Vision

**[NEW in v2.x]** Staff photograph a shelf and the system detects empty spaces. This catches “phantom inventory” – where the system shows stock but the shelf is empty. Public datasets exist (SKU-110K, densely packed retail shelf images), and Ultralytics provides ready YOLO training configurations for it.

## 5.12 Agent Observability Dashboard

Provide a dedicated interface for monitoring individual agents and their executions. The dashboard will display:

- Agent name, purpose, execution status, and run history.

- Input data references and output summaries.

- Tools invoked and their execution results.

- Decision explanations and supporting evidence.

- Execution duration, retries, errors, and validation outcomes.

- Model and provider information where applicable.

- Input/output token usage and estimated model cost for actual model calls.

- Approval status and final business outcome.

A detailed run page will allow users to inspect the execution trace and understand what happened during a particular task. It will expose useful decision explanations and recorded actions rather than private internal chain-of-thought.

## 5.13 Store Inventory View (2D)

**[NEW in v2.2]** A standard 2D view of one store’s inventory, part of the PoC, showing for each product: available stock, shelf minimum (display stock), backroom stock, near-expiry batches, stockout risk and pending transfers. Filters by category, status and aisle. This directly supports the main business problem and comes before any 3D work.

## 5.14 3D Store Digital Twin (later extension)

**[NEW in v2.2]** A 3D view of each store (React Three Fiber / three.js) with shelves coloured by status – in stock, low, out of stock, near expiry – and click-through to recommendations. It is a demonstration feature that does not directly solve the main business problem, so it is built only after the 2D Store Inventory View, and only if a customer needs it. It requires store layout data (aisles, shelves, SKU positions).

# 6. Proposed Agent Architecture

The platform can be organized into four bounded agent responsibilities.

**Agent 1 — Sales Analytics Agent:** Analyses sales trends, product performance, gross margins, and anomalies across stores.

**Agent 2 — Local Demand Intelligence Agent:** Combines observed purchasing patterns with store context to identify potential assortment improvements and related-product opportunities.

**Agent 3 — Inventory and Replenishment Agent:** Evaluates inventory position, estimates stockout risk, and calculates suggested reorder quantities using defined business rules.

**Agent 4 — Purchase Order Agent:** Prepares draft purchase orders, validates supplier and quantity constraints, and requests human approval.

**[NEW in v2.x]** v2.x keeps all four and adds two, splitting the Local Demand Intelligence responsibility into forecasting and related-product work so each can be tested separately:

| **v1.0 agent** |** v2.x agent(s)** |** Responsibility** |
| --- | --- | --- |
| Agent 1 – Sales Analytics Agent | Sales Analytics Agent | Sales trends, product performance, gross margins and anomalies across stores; lost-sales estimation [NEW] |
| Agent 2 – Local Demand Intelligence Agent | Demand Forecasting Agent [NEW split] | Store-SKU demand, ABC-XYZ, location context and seasonality |
|  | Related-Product Agent [NEW split] | Basket rules, co-replenishment, substitutes, assortment gaps |
| Agent 3 – Inventory and Replenishment Agent | Inventory & Stock Balancing Agent | Inventory position, stockout risk, reorder quantities; own requirement, surplus, transfer vs PO [NEW] |
| Agent 4 – Purchase Order Agent | Purchase Order Agent | Draft POs, supplier and quantity validation, approval; consolidation, schemes, cash budget [NEW] |
| – | Freshness Agent [NEW] | Batch expiry risk, FEFO, markdown and expiry-aware transfer |

A workflow orchestrator will coordinate these responsibilities and record execution events. Deterministic calculations will be implemented as controlled tools or functions, while AI models will be used where they provide additional value.

For the initial PoC, these responsibilities may be implemented as separate application modules and deterministic functions. Independent LLM agents can be introduced incrementally after the workflow and evaluation requirements are established.

**[NEW in v2.x]** Design patterns from reference projects: calculations with one correct answer (requirement, surplus, reorder quantity, budget checks) are typed, unit-tested tool functions, with LLM reasoning reserved for judgement; the orchestrator caps the number of agent steps per request to bound cost and latency; evaluation is split between an LLM-as-judge check of agent behaviour and a code-based check of actual accuracy once results are known.

# 7. End-to-End Business Workflow

The proposed workflow is:

*Operational Data → Sales Analysis → Location Intelligence → Replenishment Recommendation → Draft Purchase Order → Human Approval → Authorized Order Submission → Audit and Monitoring*

**[NEW in v2.x]** Enhanced workflow (same path, with forecasting, related products and the transfer check added before the PO):

*Operational Data → Sales Analysis → Forecasting **&** Location Intelligence → Related-Product Analysis → Own Requirement per Store → Inter-Store Transfer (surplus only) → Consolidated Draft PO for Remaining Need → L1/L2 Approval → Authorized Order Submission → Delivery Tracking → Audit and Monitoring*

At each stage, the platform should record relevant inputs, outputs, validation results, and status changes.

If data is missing, an API fails, a supplier is unavailable, or a recommendation violates a business rule, the system should flag the issue rather than silently generating an unreliable action.

# 8. Application Flow

**[NEW in v2.x]** This section describes how data, agents, decisions and people move through the application, and how users navigate it.

## 8.1 End-to-End Flow Diagram

*Figure 1. Application flow (dashed lines: feedback loop and freshness path)*

## 8.2 Stage-by-Stage Description

| **Stage** |** What happens** |** Output** |
| --- | --- | --- |
| 1. Data ingestion and validation | POS sales, inventory and batch data, supplier price lists and schemes, and the festival calendar are loaded, cleaned and reconciled. Missing or stale data is flagged. | Validated data; data-quality alerts |
| 2. Demand forecasting | Baseline average daily sales, with enhanced models where they prove better; location context treated as hypotheses. | Store-SKU forecast |
| 3. Related-product analysis | Basket rules identify items to restock together and substitute pairs. | Co-replenishment and substitution list |
| 4. Own requirement and shortfall | Each store’s own requirement is compared with on-hand and incoming stock. | Shortfall and surplus per store-SKU |
| 5a. Inter-store transfer | Surplus in another own store is proposed if its incremental cost is lower than a PO and it is fast enough; donors are protected. Destination accepts, donor approves, then dispatch and receipt. | Transfer recommendation with evidence |
| 5b. Purchase order | Remaining need – or the full need when every store requires the product – goes to the PO Agent. | Draft consolidated PO |
| Approval | Line-level L1 by each store; deadline with escalation; approved lines split from rejected ones. Above threshold: L2. Approve, edit or reject with reason. | Approved, edited, rejected or split PO |
| 6. Submission | Sent through an authorized channel (draft only in the PoC). | Submitted PO and status |
| 7. Receipt | Deliveries and transfers received; inventory updated for the next cycle. | Updated stock; forecast vs actual |
| Freshness (parallel) | Near-expiry batches trigger transfer, markdown or bundle suggestions. | Expiry alerts and actions |
| Observability (all stages) | Inputs, tools, evidence, duration, tokens, cost, errors and outcome recorded. | Run history and audit trail |

## 8.3 Screen Flow (User Navigation)

*Login (role-based) → Executive Dashboard → Recommendations Inbox → Recommendation Detail (evidence) → Approve / Edit / Reject → Transfer **&** PO Tracking → Agent Observability (Run List → Run Detail)*

| **Screen** |** Purpose** |** Key actions** |
| --- | --- | --- |
| Login | Role-based access for Store Supervisor and Super Admin | Sign in; land on role-specific view |
| Executive Dashboard | Business health across stores | Filter by store, category, period; drill into lost sales, stockout risk, near-expiry value |
| Store View | Single-store performance and assortment | Fast/slow movers, ABC-XYZ class, related-product gaps |
| Store Inventory View (2D) [v2.2] | Stock position of one store | Available, shelf minimum, backroom, near-expiry, stockout risk, pending transfers |
| Recommendations Inbox | Pending transfers, POs and expiry actions | Sort by urgency or value; open a recommendation |
| Recommendation Detail | Why the action is recommended | Forecast, own requirement, surplus, transfer-vs-PO comparison, scheme saving |
| Approval | L1 / L2 decision | Approve, edit quantity, reject with reason |
| Transfer & PO Tracking | Status from draft to receipt | Track dispatch, delivery, receipt; audit history |
| Agent Observability | Monitor agent runs | Run list; run detail with tools, evidence, tokens, errors |
| Settings | Business rules | Display minimums, safety stock, PO threshold, budgets, suppliers |

## 8.4 Role-Based Journeys

### Store Supervisor (L1)

- Opens the Recommendations Inbox for their store each morning.

- Accepts incoming transfer proposals for their store and approves release of surplus for outgoing ones; confirms quantities received.

- Reviews draft POs with evidence; approves, edits or rejects. POs below the threshold are final after L1.

- Acts on expiry alerts (markdown, transfer or bundle).

- Confirms receipt of deliveries and transfers.

### Super Admin (L2)

- Monitors the Executive Dashboard across all stores.

- Approves POs above the value threshold after L1 approval.

- Reviews KPIs: lost revenue and lost profit, PO cost avoided through transfers, waste, forecast accuracy; decides escalated PO lines.

- Audits agent decisions, errors and AI cost on the Agent Observability Dashboard.

- Maintains business rules in Settings.

## 8.5 Daily Operating Cycle

| **Time** |** Activity** |
| --- | --- |
| Night (after store close) | Ingest the day’s sales and stock; run forecasting, related-product, stock balancing and freshness agents |
| Early morning | Transfer, PO and expiry recommendations ready in the inbox |
| Morning | Store Supervisors review and approve (L1); transfers dispatched |
| Midday | Super Admin approves high-value POs (L2); approved POs submitted |
| On delivery | Receipt recorded; inventory updated for the next cycle |

## 8.6 Exception Flow

- Missing or stale data: forecast marked low-confidence; no automatic recommendation for affected SKUs.

- Supplier unavailable or MOQ not met: next eligible supplier proposed, or item held for manual decision.

- Budget exceeded: PO split or prioritised by ABC class and stockout risk, and sent for review.

- Rejected recommendation: reason captured to evaluate and improve future recommendations.

- Agent or API failure: retried within limits, then logged on the Observability Dashboard.

- **[NEW in v2.2]** **Approval deadline passed:** undecided PO lines are escalated or expired; approved lines continue as a split PO.

- **[NEW in v2.2]** **Stock mismatch:** ledger stock differs from the POS snapshot – posted as an adjustment movement and flagged for review.

# 9. Proof of Concept Scope and Roadmap

To make the project feasible within the initial development period, I propose a limited PoC using synthetic or public data.

## 9.1 Included in the Initial PoC (v1.0 scope, unchanged)

- Multi-store executive dashboard.

- Store-level sales and product analysis.

- Fast-moving and slow-moving product identification.

- Inventory and stockout-risk calculations.

- Location-specific recommendation interface.

- Replenishment recommendations with supporting calculations.

- Draft purchase order creation and approval interactions.

- Agent dashboard and execution-detail pages.

- Mock execution logs, error states, and measured application metrics.

- Testing of the main workflow and important edge cases.

## 9.2 Enhancements Added to the PoC

**[NEW in v2.x]** These fit directly into the original story and are low effort:

- Inter-store transfer vs PO decision engine (5.6), including donor protection and decision explanations.

- Co-replenishment, substitution detection and assortment-gap suggestions (5.4).

- Lost revenue and lost profit in ₹, as separate KPIs (5.1).

- Consolidated POs across stores (5.7).

- ABC-XYZ classification (5.3).

- Expiry flags with FEFO and expiry-aware transfers (5.8) – extends the v1.0 expiry-risk flag.

- **[NEW in v2.2]** **2D Store Inventory View** (5.13).

- **[NEW in v2.2]** **Shelf vs backroom stock and inventory movement ledger** (5.5).

- **[NEW in v2.2]** **Two-sided transfer approval and line-level consolidated PO approval** (5.6, 5.7).

## 9.3 PoC Extensions (if time permits)

**[NEW in v2.x]** Valuable but optional, so the PoC stays focused on the original goal:

- Pattern-specific forecasting models with festival, salary-week and weather signals (5.3), compared against the baseline.

- Scheme-aware and cash-aware ordering (5.7).

- Rule-based markdown recommendations (5.8).

- **[NEW in v2.2]** **3D Store Digital Twin** (5.14), only after the 2D view and only if a customer needs it.

## 9.4 Later Phases

- **Phase 2:** WhatsApp interface (5.10), supplier scorecard (5.9), live POS integration for a pilot client, production-grade forecasting.

- **Phase 3:** Shelf-photo vision for empty-shelf and phantom-inventory detection (5.11).

## 9.5 Future Opportunity (not in current scope)

**[NEW in v2.x]** Extension to FMCG distributors serving many independent kirana stores (see 2.1). Recorded for later evaluation; it does not change the current target user.

## 9.6 Outside the Initial PoC Scope (v1.0, unchanged)

- Live integration with retailer point-of-sale systems.

- Direct integration with real supplier ordering systems.

- Autonomous submission of purchase orders.

- Production-grade demand forecasting across all product categories.

- Verified real-world geospatial and demographic intelligence.

- Enterprise-scale deployment, access governance, and disaster recovery.

These capabilities can be evaluated in subsequent phases after the PoC demonstrates business value and the necessary data access is confirmed.

## 9.7 Initial Prioritisation from Research

**[NEW in v2.x]** The original prioritisation of the enhancements, with where each sits in this version:

| **Feature** |** Value** |** Effort** |** Initial phase** |** v2.2 placement** |
| --- | --- | --- | --- | --- |
| Co-replenishment + substitution | High | Low–Med | PoC | PoC (9.2) |
| Inter-store transfer | High | Low | PoC | PoC (9.2) |
| Lost revenue / lost profit in ₹ | High | Low | PoC | PoC (9.2) |
| ABC-XYZ + festival-aware forecast | High | Medium | PoC | ABC-XYZ: PoC; models + signals: extension (9.3) |
| Scheme/cash-aware PO | Med–High | Low | PoC | Extension (9.3) |
| Expiry/FEFO + markdown | Medium | Medium | PoC (rule-based) | FEFO: PoC; markdown: extension |
| WhatsApp approval/chat | High | Medium | Phase 2 | Phase 2 |
| Supplier scorecard | Medium | Low | Phase 2 | Phase 2 |
| Shelf vision | Medium | High | Phase 3 | Phase 3 |

## 9.8 Demonstration Scenarios

**[NEW in v2.2]** Five scenarios demonstrate the core story end to end. Each ends with approval and is checked against the expected result:

| **#** |** Scenario** |** Expected result** |
| --- | --- | --- |
| 1 | A fast-moving product sells high in all stores; no store has surplus | PO raised for each short store, consolidated by supplier; L1 per store, L2 if above threshold |
| 2 | Store A has surplus; Store C is forecast to run short | Transfer proposed A → C; C accepts, A approves; stock moves through the ledger; no PO |
| 3 | Store A has surplus 24; Store C needs 40 | Transfer 24 from A and PO for 16; explanation shows both numbers |
| 4 | Bread is reordered; butter (high lift) will run short before the next delivery | Butter added to the order as co-replenishment, with the rule shown as evidence |
| 5 | A batch in Store A will expire before A can sell it; Store C can sell it in time | Expiry-aware transfer of that batch to C; otherwise markdown or expiry alert |

# 10. Data Requirements

The quality of the recommendations depends on the quality and availability of the underlying data. The proposed data entities include:

| **Entity** |** v1.0 fields** |** Added in v2.x** |
| --- | --- | --- |
| Stores | Store identifier, region, store type, location context | Display capacity |
| Products | SKU, category, brand, cost price, selling price, pack size | Shelf life, minimum display stock |
| Sales | Transaction date, store, SKU, units sold, selling price, discount | Bill / transaction ID (needed for basket analysis – to confirm with client) |
| Inventory | Available, reserved and incoming stock; expiry details where relevant | Batch number and expiry per batch; shelf and backroom quantity [v2.2] |
| Suppliers | Product availability, price, lead time, MOQ, ordering constraints | Schemes and slabs; performance history; lead time and delivery charge per store [v2.2] |
| Purchase Orders | Supplier, store, line items, total value, approval status, delivery status | Store-wise lines for consolidated POs; approval level; line-level approval status, approval deadline, parent PO for split POs [v2.2] |
| Agent Runs | Run ID, agent, status, timestamps, tool calls, token counts, errors, outputs | – |
| Location Context | Surrounding establishments, seasonal factors, data source, observation date | – |
| Transfers [NEW] | – | From store, to store, SKU, quantity, cost, transit time, status; destination acceptance, donor approval, received quantity [v2.2] |
| Inventory movements [v2.2] | – | Movement type, store, SKU, batch, quantity (+/−), reason, reference (bill, PO, transfer), user, time |
| Transfer routes [v2.2] | – | From store, to store, fixed trip cost, per-unit transport cost, handling cost, transit days |
| Cost settings [v2.2] | – | Holding cost rate per day, order fixed cost, approval deadline |
| Calendar [NEW] | – | Festivals, holidays, salary dates, promotions, local events |

Synthetic data will be used during development. In a real deployment, data quality, data freshness, missing values, product identifiers, and inventory reconciliation must be assessed before relying on the recommendations.

**[NEW in v2.x]** Public datasets for the PoC: M5 (Walmart multi-store daily sales) for forecasting and Instacart (basket-level orders) for market basket analysis.

# 11. Business Value and Success Metrics

The objective is to evaluate measurable business improvements rather than demonstrate AI functionality alone. The proposed KPIs are:

| **Business objective** |** Proposed KPI** |
| --- | --- |
| Improve product availability | Stockout rate |
| Reduce excess inventory | Excess inventory value and inventory turnover |
| Improve replenishment | Recommendation acceptance rate and reorder accuracy |
| Improve profitability | Gross profit and gross margin by store and product |
| Improve product assortment | Sales and profit contribution of newly introduced products |
| Reduce manual effort | Time required for analysis and PO preparation |
| Improve operational reliability | Workflow completion and error rates |
| Improve agent transparency | Trace completeness and percentage of runs with recorded evidence |
| Control AI usage | Token consumption and estimated cost per completed task |
| [UPDATED v2.2] Quantify missed revenue | Estimated lost revenue (₹) from stockouts |
| [UPDATED v2.2] Quantify missed profit | Estimated lost profit (₹) from stockouts |
| [NEW] Use own stock first | Transfer quantity and incremental cost saved through transfers |
| [NEW v2.2] Inventory accuracy | Ledger vs POS snapshot differences; transfer discrepancies |
| [NEW] Reduce waste | Expired / written-off stock value |
| [NEW] Forecast quality | WMAPE and bias by ABC-XYZ class vs baseline |
| [NEW] Related-product value | Sales uplift of co-replenished items |
| [NEW] Purchasing savings | Scheme savings captured |

Actual improvement targets will be established after a baseline is measured. Recommendations will initially be evaluated through historical replay or a controlled pilot before they are used for real purchasing decisions.

# 12. Risks and Mitigation

- **Poor or incomplete data:** Validate source data, document limitations, and flag missing or stale records.

- **Incorrect demand assumptions:** Distinguish actual observations from hypotheses and evaluate recommendations against historical outcomes.

- **Over-ordering or budget violations:** Enforce stock, supplier, pack-size, and budget constraints through deterministic validation.

- **Unreliable AI outputs:** Use structured outputs, tool permissions, validation rules, bounded execution, and explicit stopping conditions.

- **Unauthorized purchasing:** Require approval from an authorized person before submitting real orders.

- **Insufficient observability:** Record execution status, tool results, errors, latency, and model usage wherever applicable.

- **Privacy and security:** Apply role-based access, protect business data and credentials, and retain only the information required for the workflow.

- **[NEW in v2.x]** **Transfer creating a new stockout:** donor protection never lets a donor fall below its own requirement.

- **[NEW in v2.x]** **Over-ordering from scheme slabs:** slab quantity recommended only if it sells within shelf life and fits the cash budget.

- **[NEW in v2.x]** **Scope creep from enhancements:** v1.0 scope stays the core; extensions are optional and phased (Section 9).

- **[NEW in v2.x]** **Basket data not available:** confirm bill-level data early; fall back to category-level co-occurrence if needed.

- **[NEW in v2.2]** **Financially incorrect transfer decisions:** compare incremental costs only (5.6), not the purchase price of the units.

- **[NEW in v2.2]** **Consolidated PO blocked by one store:** line-level approval, deadline with escalation, and split of approved lines (5.7).

- **[NEW in v2.2]** **Unauthorised stock movement:** destination acceptance and donor approval before dispatch; receipt confirmation (5.6).

- **[NEW in v2.2]** **Inaccurate stock levels:** movement ledger with daily reconciliation against the POS snapshot (5.5).

- **[NEW in v2.2]** **Effort spent on 3D before core value:** 2D Store Inventory View first; 3D twin only as a later extension (5.13, 5.14).

# 13. My Approach as a Junior Forward Deployed Engineer

As a Junior FDE, I would approach this problem by combining technical implementation with an understanding of the business workflow. My planned approach is:

- **Discover:** Understand how supermarket owners currently analyse sales, manage inventory, and place orders.

- **Define:** Convert the business problem into user stories, workflow maps, acceptance criteria, and measurable KPIs.

- **Design:** Create a customer-facing interface that makes recommendations, evidence, errors, and next actions understandable.

- **Build:** Develop the PoC using synthetic data, reusable UI components, analytics functions, and controlled agent workflows.

- **Evaluate:** Test the system with realistic scenarios, compare recommendations against historical data, and record failures and limitations.

- **Demonstrate:** Present the working application, explain its business value, gather feedback, and document the production-readiness gaps.

The initial implementation will prioritize usability, correctness, explainability, and measurable outcomes over unnecessary technical complexity.

# 14. Expected Outcome

The expected outcome is a demonstrable PoC that helps a supermarket owner understand how sales, profitability, local demand, inventory, and purchasing decisions can be managed in one application.

The solution will demonstrate how analytics and bounded AI-agent workflows can reduce manual effort, improve the consistency of replenishment decisions, and provide visibility into automated actions.

The PoC will also establish what remains necessary before production deployment, including integration with real data sources, historical validation, security controls, operational monitoring, and authorized supplier workflows.

**[NEW in v2.x]** In addition, the PoC will show that the system uses stock already held in the business’s own stores before buying, restocks related products together, and expresses stockouts as lost revenue and lost profit in rupees.

# 15. Reference Projects and Learning Resources

**[NEW in v2.x]** Comparable projects reviewed during the enhancement research:

- **Deterministic-tool / agent partition (AWS case study, summarised on GitHub):** build typed tool functions for deterministic work such as replenishment quantities and budget validation; reserve LLM reasoning for judgement. The v1.0 design already follows this.

- **devthedevil/agentstore:** LangGraph + Claude supervisor routing to specialist retail agents, with a hard cap on supervisor–worker hops per request to bound cost – useful for the observability dashboard.

- **InvAgent (zefang-liu/InvAgent):** academic LLM multi-agent inventory system for multi-stage supply chains; relevant to the future distributor extension.

- **Google codelab – CrewAI, LangGraph, A2A and ADK:** retail inventory restock scenario with sourcing and procurement agents, close to the PO flow.

- **Nixtla statsforecast and Databricks intermittent-forecasting:** forecasting at scale on the M5 dataset; also realistic multi-store data for the PoC.

- **Elilora/Market-basket-analysis:** simple Apriori starter; Instacart dataset for real basket data.

- **rokopi-byte/shelf_management:** shelf detection and planogram compliance, for Phase 3.

- **Commercial references:** Wasteless (expiry-based markdown pricing); WhatsApp-based retailer ordering used widely by Indian FMCG distribution.

- **YouTube learning searches:** “M5 forecasting statsforecast tutorial”, “market basket analysis mlxtend”, “YOLO SKU-110K training”. Generic n8n inventory-agent demos were found to be less useful.

# 16. Technology Stack

**[NEW in v2.2]** The technology stack has been fixed for implementation:

| **Layer** |** Technology** |** Responsibility** |
| --- | --- | --- |
| Frontend | React + TypeScript | User interface, including the 2D Store Inventory View |
| API | Python + FastAPI | Backend services and REST endpoints |
| Validation | Pydantic | Structured request and response validation; OpenAPI contract for the frontend |
| Analytics | Python, Pandas | Sales, inventory, forecasting and basket calculations |
| Agent execution | Python modules | Bounded agent responsibilities calling deterministic tools |
| Background jobs | Celery + Celery Beat | Nightly run and scheduled jobs (approval deadlines) |
| Cache / broker | Redis | Caching with run-versioned keys; job messaging |
| Database | PostgreSQL | Operational and analytical data, movement ledger, materialized views |
| 3D extension | Three.js / React Three Fiber | Digital twin (later extension) |

Class and sequence diagrams for this stack are in the companion technical document (RetailPilot AI – Class and Sequence Diagrams, v3).

# 17. Implementation Plan (Next Steps)

**[NEW in v2.2]** The steps below take the frozen design into implementation. Steps 4 and 5 run in parallel with step 3.

### Step 1 – Finalize the business requirements

- Freeze the scope, user roles, business rules, acceptance criteria and the five demonstration scenarios (9.8).

- Confirm the v2.2 business rules: incremental cost comparison, transfer approval workflow, consolidated PO approval policy.

- Confirm data assumptions: bill-level sales data, transfer route costs, shelf vs backroom stock, supplier lead time per store.

- Agree parameter values: holding cost rate, order fixed cost, approval deadline, basket thresholds, L2 threshold, weekly budget.

### Step 2 – Finalize the database architecture

- Define all tables, relationships, primary keys and foreign keys.

- Define inventory movement rules and the movement ledger, including shelf and backroom quantities.

- Define line-level approval status, approval deadlines and the parent–child link for split POs.

- Define partitioning, indexes and materialized views to match the caching plan.

### Step 3 – Finalize the backend implementation design

- Define API endpoints, service responsibilities, Python modules and deterministic calculations.

- Define authentication and role checks per endpoint, and a standard for errors (conflict, forbidden, validation).

- Define background jobs (nightly run, approval-deadline job), retries and idempotency.

- Define cache keys and invalidation rules, and publish the OpenAPI contract for the frontend.

### Step 4 – Frontend and UX design

- Design the screens in Section 8.3, including the 2D Store Inventory View and the approval screens with evidence.

### Step 5 – Test and evaluation plan

- Generate synthetic data that reproduces the five demonstration scenarios; use M5 and Instacart for forecasting and basket tests.

- Unit-test deterministic calculations: own requirement, surplus, transfer decision, incremental costs, PO rounding and validation, lost revenue and profit.

- Evaluate recommendations through historical replay before any real purchasing decision.

# Conclusion

My understanding is that the core business problem is not simply analysing supermarket sales. It is converting fragmented operational data into reliable, location-specific decisions and carrying those decisions through a controlled purchasing workflow.

The proposed Retail Intelligence and AI-Powered Replenishment Platform addresses this problem by bringing together business analytics, inventory decision support, purchase order management, and agent observability.

As a Junior FDE, my immediate goal is to build and validate a focused proof of concept, demonstrate the complete user journey, and establish measurable evidence of value before expanding the system into a production-ready solution.

**[NEW in v2.x]** The v2.x enhancements deepen the same solution – related-product restocking, own-stock-first transfers, smarter forecasting, freshness and smarter purchasing – without changing the problem, the target user, or the human-supervised approach.

# Appendix A – Traceability: v1.0 to v2.2

| **v1.0 section** |** Location in v2.2** |** Status** |
| --- | --- | --- |
| 1. Executive Summary | 1 | Retained in full; enhancements added |
| 2. Business Problem Statement | 2 | Retained in full; FMCG context added |
| 3.1–3.6 Root causes | 3.1–3.6 | Retained in full; 3.7–3.9 added |
| 4.1 Unified Business Dashboard | 5.1 | Retained; lost sales, ABC-XYZ added |
| 4.2 Location-Specific Product Intelligence | 5.2 | Retained in full |
| 4.3 Inventory Analysis and Replenishment | 5.5 | Retained in full; shelf/backroom and ledger added (v2.2) |
| 4.4 Purchase Order Management | 5.7 | Retained; consolidation, L1/L2, schemes added |
| 4.5 Agent Observability Dashboard | 5.12 | Retained in full |
| 5. Proposed Agent Architecture | 6 | All four agents retained; two added |
| 6. End-to-End Business Workflow | 7 | Original flow retained; enhanced flow added |
| 7. Initial PoC Scope | 9.1, 9.6 | Retained in full; enhancements in 9.2–9.5 |
| 8. Data Requirements | 10 | All entities retained; fields added |
| 9. Business Value and Success Metrics | 11 | All KPIs retained; six added |
| 10. Risks and Mitigation | 12 | All retained; four added |
| 11. My Approach as a Junior FDE | 13 | Retained in full |
| 12. Expected Outcome | 14 | Retained in full; one paragraph added |
| Conclusion | Conclusion | Retained in full; one paragraph added |

# Appendix B – Enhancement Register

| **#** |** Enhancement** |** Section** |** Phase** |
| --- | --- | --- | --- |
| 1 | FMCG retail positioning and differentiation | 2.1 | – |
| 2 | Co-replenishment | 5.4 | PoC |
| 3 | Substitution detection | 5.4 | PoC |
| 4 | Assortment-gap suggestions | 5.4 | PoC |
| 5 | Shelf placement / bundle suggestions | 5.4 | PoC |
| 6 | ABC-XYZ classification | 5.3 | PoC |
| 7 | Pattern-specific forecasting (Croston, IMAPA, TSB) | 5.3 | Extension |
| 8 | Festival, salary-week and weather signals | 5.3 | Extension |
| 9 | Own requirement incl. display minimum | 5.6 | PoC |
| 10 | Transferable surplus and transfer vs PO rules | 5.6 | PoC |
| 11 | Raise PO when product sells high in all stores | 5.6 | PoC |
| 12 | Partial transfer + PO for remainder | 5.6 | PoC |
| 13 | Transfer only if cheaper and fast enough | 5.6 | PoC |
| 14 | Expiry-aware transfers | 5.6, 5.8 | PoC |
| 15 | Donor protection | 5.6 | PoC |
| 16 | Decision explanation on approval screen | 5.6 | PoC |
| 17 | Consolidated PO with store-wise quantities | 5.6, 5.7 | PoC |
| 18 | L1/L2 approval with value threshold | 5.7 | PoC |
| 19 | Lost revenue and lost profit in ₹ (separate KPIs, v2.2) | 5.1 | PoC |
| 20 | Scheme-aware ordering (slab offers) | 5.7 | Extension |
| 21 | Cash-aware ordering (weekly budget) | 5.7 | Extension |
| 22 | FEFO batch tracking | 5.8 | PoC |
| 23 | Rule-based markdowns | 5.8 | Extension |
| 24 | Supplier scorecard | 5.9 | Phase 2 |
| 25 | WhatsApp interface | 5.10 | Phase 2 |
| 26 | Shelf-photo vision / phantom inventory | 5.11 | Phase 3 |
| 27 | Freshness Agent; agent split | 6 | PoC |
| 28 | Agent step cap and split evaluation | 6 | PoC |
| 29 | Application flow, screens, roles, daily cycle, exceptions | 8 | PoC |
| 30 | Distributor / kirana extension | 2.1, 9.5 | Future |
| 31 | Public datasets (M5, Instacart) | 10 | PoC |
| 32 | Reference projects and learning resources | 15 | – |
| 33 | [v2.2] Incremental cost comparison for transfer vs PO | 5.6 | PoC |
| 34 | [v2.2] Delivery window per store and SKU | 5.3, 5.6 | PoC |
| 35 | [v2.2] Two-sided transfer approval workflow | 5.6 | PoC |
| 36 | [v2.2] Line-level consolidated PO approval, deadline, split | 5.7 | PoC |
| 37 | [v2.2] Basket data-quality controls and configurable thresholds | 5.4 | PoC |
| 38 | [v2.2] Shelf vs backroom stock | 5.5 | PoC |
| 39 | [v2.2] Inventory movement ledger and reconciliation | 5.5 | PoC |
| 40 | [v2.2] 2D Store Inventory View | 5.13 | PoC |
| 41 | [v2.2] 3D Store Digital Twin | 5.14 | Extension (after 2D) |
| 42 | [v2.2] Technology stack | 16 | – |
| 43 | [v2.2] Demonstration scenarios | 9.8 | PoC |
| 44 | [v2.2] Implementation plan | 17 | – |

# Appendix C – Change Log: v2.1 to v2.2

Changes made after the technical review of the design:

| **Review point** |** Change in v2.2** |** Section** |
| --- | --- | --- |
| A. Transfer cost calculation | Compare incremental costs (transport, handling, order and delivery charges, holding and expiry cost of donor surplus) instead of the full purchase price. v2.1 compared transfer cost with order fixed cost + unit price × qty. | 5.6 |
| B. Delivery window | Requirement uses each store-SKU’s own window (supplier lead time for that store + review period + safety days); forecast horizon covers the longest window. | 5.3, 5.6 |
| C. Lost revenue vs lost profit | Two separate KPIs with explicit formulas. v2.1 wording (“revenue lost … forecast demand × margin”) mixed the two. | 5.1, 11 |
| D. Transfer ownership | Six-step workflow: destination accepts, donor approves, re-check, dispatch, receipt, ledger update with discrepancies. | 5.6, 8 |
| E. Consolidated PO rejection | Line-level approval states, approval deadline with escalation, split of approved lines into a new PO. | 5.7, 8 |
| F. Basket data quality | Cleaning rules, configurable thresholds, complements and substitutes kept as separate analyses. | 5.4 |
| G. 3D digital twin priority | 2D Store Inventory View added to the PoC; 3D twin is a later extension. | 5.13, 5.14, 9 |
| Inventory accuracy | Shelf vs backroom stock; inventory movement ledger with daily reconciliation. | 5.5, 10 |
| Next steps | Technology stack and implementation plan added; five demonstration scenarios defined. | 9.8, 16, 17 |

RetailPilot AI – v2.2   |   Page