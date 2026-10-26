# Disposable PostgreSQL integration-test plan

Run only against a newly created, disposable PostgreSQL database (for example,
`nexora_product_fencing_test_<run-id>`). Require an explicit `TEST_DATABASE_URL`
and refuse known development/production database names. Never load a service
`.env` file or fall back to `DATABASE_URL`. Apply the Product Service schema
fixture and migration 001 only to this database; drop the disposable database
after the suite. This plan has not been executed.

Use independent connections and barriers so requests overlap at the service
boundary. Assert each pair is equivalent to one serial execution under the
reservation UUID advisory lock:

1. **Concurrent reserve with same UUID and payload:** launch two reserve calls
   at the same generation. Exactly one decrements stock; both settle as
   `RESERVED`, with one reservation row and one ledger row.
2. **Concurrent release with same UUID:** launch two releases for the active
   reservation. Stock is restored once; both settle as `RELEASED`.
3. **Concurrent cancel with same UUID:** launch two cancels for an absent UUID.
   One tombstone remains, repeated result is idempotent, and stock is unchanged.
4. **Reserve/release/cancel contention:** overlap calls on one UUID, record the
   lock-serialized order, and verify final ledger/reservation states agree and
   stock changed at most once for each actual reserve/release transition.
5. **Stale generations:** write a higher-generation operation, then issue lower
   generation reserve, release, and cancel calls. Each is rejected without
   changing ledger, reservation, or stock.
6. **Cancel before delayed reserve:** commit a cancellation tombstone at
   generation N, then release a previously paused reserve request at generation
   N-1. It is rejected and stock/reservations remain unchanged.
7. **Rollback atomicity:** in the disposable database only, install a temporary
   test trigger that raises after the product stock update (and a second case
   after the reservation-row write). Confirm the transaction rolls back all
   product stock, reservation, and ledger changes. Remove the trigger with the
   disposable database teardown.

Capture initial and final values from `products`, `stock_reservations`, and
`reservation_operations` by the test UUID. Do not use shared product IDs or
existing Nexora records.
