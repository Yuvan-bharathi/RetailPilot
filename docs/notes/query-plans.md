# Top-10 Query Execution Plans (D-38, spec §11)

Recorded on: 2026-11-04 08:31:16 UTC
Database: PostgreSQL 16 (retailpilot)

Plans generated using `EXPLAIN (ANALYZE, BUFFERS)` to verify index usage
and ensure no unindexed sequential scans occur on high-cardinality tables.

---

## 1. Recommendation Inbox (Pending, Ranked)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT rec_id, store_id, product_id, rec_type, priority_rank, status, created_at
        FROM recommendation
        WHERE store_id = :store_id AND status = 'PENDING'
        ORDER BY priority_rank ASC, created_at DESC
        LIMIT 50;
```

```text
Limit  (cost=8.15..8.20 rows=2 width=122) (actual time=0.043..0.043 rows=0 loops=1)
  Buffers: shared hit=11
  ->  Incremental Sort  (cost=8.15..8.20 rows=2 width=122) (actual time=0.042..0.042 rows=0 loops=1)
        Sort Key: priority_rank, created_at DESC
        Presorted Key: priority_rank
        Full-sort Groups: 1  Sort Method: quicksort  Average Memory: 25kB  Peak Memory: 25kB
        Buffers: shared hit=11
        ->  Index Scan using ix_recommendation_inbox_pending on recommendation  (cost=0.12..8.14 rows=1 width=122) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Buffers: shared hit=2
Planning:
  Buffers: shared hit=163
Planning Time: 0.324 ms
Execution Time: 0.060 ms
```

---

## 2. L1 PO Review Queue (Pending Lines for Store)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT po_line_id, po_id, store_id, product_id, line_status, qty, unit_price
        FROM po_line
        WHERE store_id = :store_id AND line_status = 'PENDING';
```

```text
Index Scan using ix_po_line_store_pending on po_line  (cost=0.12..8.14 rows=1 width=118) (actual time=0.002..0.002 rows=0 loops=1)
  Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
  Buffers: shared hit=2
Planning:
  Buffers: shared hit=129
Planning Time: 1.382 ms
Execution Time: 0.012 ms
```

---

## 3. PO Approval Deadline Job (Overdue L1 Orders)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT po_id, parent_po_id, status, l1_deadline, total_value
        FROM purchase_order
        WHERE status = 'PENDING_L1' AND l1_deadline <= :now;
```

```text
Index Scan using ix_purchase_order_l1_deadline_pending on purchase_order  (cost=0.12..8.14 rows=1 width=90) (actual time=0.002..0.002 rows=0 loops=1)
  Index Cond: (l1_deadline <= '2026-11-04 08:31:16.042238+00'::timestamp with time zone)
  Buffers: shared hit=1
Planning:
  Buffers: shared hit=113 read=6
Planning Time: 1.302 ms
Execution Time: 0.016 ms
```

---

## 4. Active Outbound Transfers (Donor Store Queue)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT transfer_id, from_store_id, to_store_id, product_id, qty, status
        FROM transfer_order
        WHERE from_store_id = :store_id
          AND status IN ('PROPOSED', 'DEST_ACCEPTED', 'APPROVED_RELEASE', 'DISPATCHED');
```

```text
Index Scan using ix_transfer_order_from_store_id on transfer_order  (cost=0.15..8.17 rows=1 width=100) (actual time=0.006..0.007 rows=0 loops=1)
  Index Cond: (from_store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
  Filter: (status = ANY ('{PROPOSED,DEST_ACCEPTED,APPROVED_RELEASE,DISPATCHED}'::text[]))
  Buffers: shared hit=2
Planning:
  Buffers: shared hit=229
Planning Time: 1.943 ms
Execution Time: 0.033 ms
```

---

## 5. Active Inbound Transfers (Destination Store Queue)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT transfer_id, from_store_id, to_store_id, product_id, qty, status
        FROM transfer_order
        WHERE to_store_id = :store_id
          AND status IN ('PROPOSED', 'DEST_ACCEPTED', 'APPROVED_RELEASE', 'DISPATCHED');
```

```text
Index Scan using ix_transfer_order_to_store_id on transfer_order  (cost=0.15..8.17 rows=1 width=100) (actual time=0.005..0.005 rows=0 loops=1)
  Index Cond: (to_store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
  Filter: (status = ANY ('{PROPOSED,DEST_ACCEPTED,APPROVED_RELEASE,DISPATCHED}'::text[]))
  Buffers: shared hit=2
Planning:
  Buffers: shared hit=10
Planning Time: 0.108 ms
Execution Time: 0.014 ms
```

---

## 6. Stock Movements Tab (Keyset Keyset-Cursor Paging, D-37)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT movement_id, store_id, product_id, occurred_at, movement_type, qty, location
        FROM inventory_movement
        WHERE store_id = :store_id
          AND (occurred_at, movement_id) < (:occurred_at, :movement_id)
        ORDER BY occurred_at DESC, movement_id DESC
        LIMIT 50;
```

```text
Limit  (cost=4.27..205.47 rows=25 width=124) (actual time=0.120..0.123 rows=0 loops=1)
  Buffers: shared hit=50
  ->  Merge Append  (cost=4.27..205.47 rows=25 width=124) (actual time=0.119..0.122 rows=0 loops=1)
        Sort Key: inventory_movement.occurred_at DESC, inventory_movement.movement_id DESC
        Buffers: shared hit=50
        ->  Index Scan using inventory_movement_2026_01_store_id_occurred_at_movement_id_idx on inventory_movement_2026_01 inventory_movement_1  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_02_store_id_occurred_at_movement_id_idx on inventory_movement_2026_02 inventory_movement_2  (cost=0.15..8.17 rows=1 width=124) (actual time=0.007..0.007 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_03_store_id_occurred_at_movement_id_idx on inventory_movement_2026_03 inventory_movement_3  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_04_store_id_occurred_at_movement_id_idx on inventory_movement_2026_04 inventory_movement_4  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_05_store_id_occurred_at_movement_id_idx on inventory_movement_2026_05 inventory_movement_5  (cost=0.15..8.17 rows=1 width=124) (actual time=0.006..0.006 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_06_store_id_occurred_at_movement_id_idx on inventory_movement_2026_06 inventory_movement_6  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_07_store_id_occurred_at_movement_id_idx on inventory_movement_2026_07 inventory_movement_7  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_08_store_id_occurred_at_movement_id_idx on inventory_movement_2026_08 inventory_movement_8  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_09_store_id_occurred_at_movement_id_idx on inventory_movement_2026_09 inventory_movement_9  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_10_store_id_occurred_at_movement_id_idx on inventory_movement_2026_10 inventory_movement_10  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.006 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_11_store_id_occurred_at_movement_id_idx on inventory_movement_2026_11 inventory_movement_11  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_12_store_id_occurred_at_movement_id_idx on inventory_movement_2026_12 inventory_movement_12  (cost=0.15..8.17 rows=1 width=124) (actual time=0.007..0.007 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_01_store_id_occurred_at_movement_id_idx on inventory_movement_2027_01 inventory_movement_13  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_02_store_id_occurred_at_movement_id_idx on inventory_movement_2027_02 inventory_movement_14  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_03_store_id_occurred_at_movement_id_idx on inventory_movement_2027_03 inventory_movement_15  (cost=0.15..8.17 rows=1 width=124) (actual time=0.006..0.006 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_04_store_id_occurred_at_movement_id_idx on inventory_movement_2027_04 inventory_movement_16  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_05_store_id_occurred_at_movement_id_idx on inventory_movement_2027_05 inventory_movement_17  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_06_store_id_occurred_at_movement_id_idx on inventory_movement_2027_06 inventory_movement_18  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_07_store_id_occurred_at_movement_id_idx on inventory_movement_2027_07 inventory_movement_19  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_08_store_id_occurred_at_movement_id_idx on inventory_movement_2027_08 inventory_movement_20  (cost=0.15..8.17 rows=1 width=124) (actual time=0.006..0.006 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_09_store_id_occurred_at_movement_id_idx on inventory_movement_2027_09 inventory_movement_21  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_10_store_id_occurred_at_movement_id_idx on inventory_movement_2027_10 inventory_movement_22  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_11_store_id_occurred_at_movement_id_idx on inventory_movement_2027_11 inventory_movement_23  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_12_store_id_occurred_at_movement_id_idx on inventory_movement_2027_12 inventory_movement_24  (cost=0.15..8.17 rows=1 width=124) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_default_store_id_occurred_at_movement_id_idx on inventory_movement_default inventory_movement_25  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (ROW(occurred_at, movement_id) < ROW('2026-11-04 08:31:16.042238+00'::timestamp with time zone, 'de2cf233-fec8-470c-ba74-34abb9b8b6a8'::uuid)))
              Buffers: shared hit=2
Planning:
  Buffers: shared hit=3739 read=150 dirtied=1
Planning Time: 36.384 ms
Execution Time: 0.386 ms
```

---

## 7. Per-Product Ledger History

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT movement_id, store_id, product_id, occurred_at, movement_type, qty, location
        FROM inventory_movement
        WHERE store_id = :store_id AND product_id = :product_id
        ORDER BY occurred_at DESC
        LIMIT 50;
```

```text
Limit  (cost=4.27..205.47 rows=25 width=124) (actual time=0.107..0.110 rows=0 loops=1)
  Buffers: shared hit=50
  ->  Merge Append  (cost=4.27..205.47 rows=25 width=124) (actual time=0.106..0.108 rows=0 loops=1)
        Sort Key: inventory_movement.occurred_at DESC
        Buffers: shared hit=50
        ->  Index Scan using inventory_movement_2026_01_store_id_occurred_at_movement_id_idx on inventory_movement_2026_01 inventory_movement_1  (cost=0.15..8.17 rows=1 width=124) (actual time=0.009..0.009 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_02_store_id_occurred_at_movement_id_idx on inventory_movement_2026_02 inventory_movement_2  (cost=0.15..8.17 rows=1 width=124) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_03_store_id_occurred_at_movement_id_idx on inventory_movement_2026_03 inventory_movement_3  (cost=0.15..8.17 rows=1 width=124) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_04_store_id_occurred_at_movement_id_idx on inventory_movement_2026_04 inventory_movement_4  (cost=0.15..8.17 rows=1 width=124) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_05_store_id_occurred_at_movement_id_idx on inventory_movement_2026_05 inventory_movement_5  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_06_store_id_occurred_at_movement_id_idx on inventory_movement_2026_06 inventory_movement_6  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_07_store_id_occurred_at_movement_id_idx on inventory_movement_2026_07 inventory_movement_7  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_08_store_id_occurred_at_movement_id_idx on inventory_movement_2026_08 inventory_movement_8  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_09_store_id_occurred_at_movement_id_idx on inventory_movement_2026_09 inventory_movement_9  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_10_store_id_occurred_at_movement_id_idx on inventory_movement_2026_10 inventory_movement_10  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_11_store_id_occurred_at_movement_id_idx on inventory_movement_2026_11 inventory_movement_11  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2026_12_store_id_occurred_at_movement_id_idx on inventory_movement_2026_12 inventory_movement_12  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_01_store_id_occurred_at_movement_id_idx on inventory_movement_2027_01 inventory_movement_13  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_02_store_id_occurred_at_movement_id_idx on inventory_movement_2027_02 inventory_movement_14  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_03_store_id_occurred_at_movement_id_idx on inventory_movement_2027_03 inventory_movement_15  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_04_store_id_occurred_at_movement_id_idx on inventory_movement_2027_04 inventory_movement_16  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_05_store_id_occurred_at_movement_id_idx on inventory_movement_2027_05 inventory_movement_17  (cost=0.15..8.17 rows=1 width=124) (actual time=0.006..0.006 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_06_store_id_occurred_at_movement_id_idx on inventory_movement_2027_06 inventory_movement_18  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_07_store_id_occurred_at_movement_id_idx on inventory_movement_2027_07 inventory_movement_19  (cost=0.15..8.17 rows=1 width=124) (actual time=0.005..0.005 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_08_store_id_occurred_at_movement_id_idx on inventory_movement_2027_08 inventory_movement_20  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_09_store_id_occurred_at_movement_id_idx on inventory_movement_2027_09 inventory_movement_21  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_10_store_id_occurred_at_movement_id_idx on inventory_movement_2027_10 inventory_movement_22  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_11_store_id_occurred_at_movement_id_idx on inventory_movement_2027_11 inventory_movement_23  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_2027_12_store_id_occurred_at_movement_id_idx on inventory_movement_2027_12 inventory_movement_24  (cost=0.15..8.17 rows=1 width=124) (actual time=0.004..0.004 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
        ->  Index Scan using inventory_movement_default_store_id_occurred_at_movement_id_idx on inventory_movement_default inventory_movement_25  (cost=0.15..8.17 rows=1 width=124) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Filter: (product_id = 'f563350c-5ceb-4a23-8657-c75779b71008'::uuid)
              Buffers: shared hit=2
Planning:
  Buffers: shared hit=150
Planning Time: 2.146 ms
Execution Time: 0.238 ms
```

---

## 8. Store Inventory Positions (Active Stock by Product)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT store_id, product_id, shelf_qty, backroom_qty, reserved, incoming
        FROM inventory_position
        WHERE store_id = :store_id
        ORDER BY product_id
        LIMIT 50;
```

```text
Limit  (cost=12.68..12.69 rows=4 width=48) (actual time=0.014..0.015 rows=0 loops=1)
  Buffers: shared hit=2
  ->  Sort  (cost=12.68..12.69 rows=4 width=48) (actual time=0.012..0.013 rows=0 loops=1)
        Sort Key: product_id
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=2
        ->  Bitmap Heap Scan on inventory_position  (cost=4.18..12.64 rows=4 width=48) (actual time=0.007..0.007 rows=0 loops=1)
              Recheck Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
              Buffers: shared hit=2
              ->  Bitmap Index Scan on pk_inventory_position  (cost=0.00..4.18 rows=4 width=0) (actual time=0.003..0.004 rows=0 loops=1)
                    Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
                    Buffers: shared hit=2
Planning:
  Buffers: shared hit=50 read=2
Planning Time: 0.847 ms
Execution Time: 0.068 ms
```

---

## 9. Freshness Scan (Expiring Batches with Stock, D-38)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT batch_id, store_id, product_id, batch_no, qty, expiry_date
        FROM batch
        WHERE store_id = :store_id AND qty > 0
        ORDER BY expiry_date ASC
        LIMIT 50;
```

```text
Limit  (cost=0.12..8.14 rows=1 width=88) (actual time=0.004..0.004 rows=0 loops=1)
  Buffers: shared hit=2
  ->  Index Scan using ix_batch_store_expiry_held on batch  (cost=0.12..8.14 rows=1 width=88) (actual time=0.003..0.003 rows=0 loops=1)
        Index Cond: (store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid)
        Buffers: shared hit=2
Planning:
  Buffers: shared hit=97 read=4
Planning Time: 1.098 ms
Execution Time: 0.020 ms
```

---

## 10. Sales Aggregate for Demand Window (Daily Baseline Ingestion)

```sql
EXPLAIN (ANALYZE, BUFFERS)
        SELECT product_id, SUM(qty) AS total_sold
        FROM sales_line
        WHERE store_id = :store_id
          AND txn_date >= :start_date
          AND is_voided = FALSE
          AND is_return = FALSE
        GROUP BY product_id;
```

```text
GroupAggregate  (cost=2.72..132.00 rows=16 width=24) (actual time=0.048..0.050 rows=0 loops=1)
  Group Key: sales_line.product_id
  Buffers: shared hit=32
  ->  Merge Append  (cost=2.72..131.76 rows=16 width=20) (actual time=0.047..0.049 rows=0 loops=1)
        Sort Key: sales_line.product_id
        Buffers: shared hit=32
        ->  Index Scan using sales_line_2026_10_store_id_product_id_txn_date_idx on sales_line_2026_10 sales_line_1  (cost=0.15..8.19 rows=1 width=20) (actual time=0.006..0.006 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2026_11_store_id_product_id_txn_date_idx on sales_line_2026_11 sales_line_2  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2026_12_store_id_product_id_txn_date_idx on sales_line_2026_12 sales_line_3  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_01_store_id_product_id_txn_date_idx on sales_line_2027_01 sales_line_4  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_02_store_id_product_id_txn_date_idx on sales_line_2027_02 sales_line_5  (cost=0.15..8.19 rows=1 width=20) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_03_store_id_product_id_txn_date_idx on sales_line_2027_03 sales_line_6  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_04_store_id_product_id_txn_date_idx on sales_line_2027_04 sales_line_7  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_05_store_id_product_id_txn_date_idx on sales_line_2027_05 sales_line_8  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_06_store_id_product_id_txn_date_idx on sales_line_2027_06 sales_line_9  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_07_store_id_product_id_txn_date_idx on sales_line_2027_07 sales_line_10  (cost=0.15..8.19 rows=1 width=20) (actual time=0.003..0.003 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_08_store_id_product_id_txn_date_idx on sales_line_2027_08 sales_line_11  (cost=0.15..8.19 rows=1 width=20) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_09_store_id_product_id_txn_date_idx on sales_line_2027_09 sales_line_12  (cost=0.15..8.19 rows=1 width=20) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_10_store_id_product_id_txn_date_idx on sales_line_2027_10 sales_line_13  (cost=0.15..8.19 rows=1 width=20) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_11_store_id_product_id_txn_date_idx on sales_line_2027_11 sales_line_14  (cost=0.15..8.19 rows=1 width=20) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_2027_12_store_id_product_id_txn_date_idx on sales_line_2027_12 sales_line_15  (cost=0.15..8.19 rows=1 width=20) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
        ->  Index Scan using sales_line_default_store_id_product_id_txn_date_idx on sales_line_default sales_line_16  (cost=0.15..8.19 rows=1 width=20) (actual time=0.002..0.002 rows=0 loops=1)
              Index Cond: ((store_id = '3b4adb9b-f43f-5785-a224-8a7b5ab98da8'::uuid) AND (txn_date >= '2026-10-05'::date))
              Filter: ((NOT is_voided) AND (NOT is_return))
              Buffers: shared hit=2
Planning:
  Buffers: shared hit=1697
Planning Time: 8.395 ms
Execution Time: 0.160 ms
```

---
