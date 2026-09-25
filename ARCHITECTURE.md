# L3B Architecture Record

Team phai cap nhat tai lieu nay cung source. Muc tieu la mo ta quyet dinh co the kiem chung, khong ghi prompt bi mat hoac chain-of-thought.

## 1. System overview

`	ext
Input Case
   |
   v
[Entity/Customer Agent] --> entity_result (resolved_order_ids, customer_unique_id, ...)
   |
   v
[Coordinator] ------------ dispatch parallel -----------------------------------------+
   |                                                                                    |
   +---> [Order/Shipment Agent] --> shipment_result (verdict, timeline, ...)           |
   |                                                                                    |
   +---> [Payment Agent] -------> payment_result (verdict, totals_brl, ...)            |
                                                                                        |
All results --> [Policy Engine] --> policy_result (primary_issue, refund)               |
                     |                                                                  |
                     v                                                                  |
              [Verifier Agent] --> confidence calibration                               |
                     |                                                                  |
                     v                                                                  |
              Build output dict --> validate schema --> write output JSON               |
                                                                                        |
            MCP Gateway (with per-case cache, retry, trace) --------------------------->+
                     |
                     v
              trace.jsonl (append-only lifecycle events)
`

## 2. Agent ownership

| Actor | Input | Trach nhiem | Tool permission | Output/handoff |
| --- | --- | --- | --- | --- |
| Entity/Customer | raw case dict | Resolve order ID, fetch customer context, detect ambiguity | get_order, get_customer_history | EntityResult -> Coordinator |
| Coordinator | case + entity_result | Dispatch parallel agents, collect results, call policy, build output | none (delegates) | final output dict |
| Order/Shipment | entity_result + case | Fetch order details, shipment timeline, detect delays & conflicts | get_order, get_order_items, get_shipment_summary, get_sellers, get_product_context | OrderShipmentResult -> Coordinator |
| Payment | entity_result + case | Reconcile payments, check refund status, sum BRL amounts | get_order_payments, get_payment_timeline, get_refund_timeline, get_policy | PaymentResult -> Coordinator |
| Policy Engine | all specialist results | Map evidence -> primary_issue, responsible_parties, refund recommendation | none (pure logic) | PolicyResult -> Verifier |
| Verifier | all results + policy | Cross-field consistency, confidence calibration [0.0-1.0] | none (pure logic) | {confidence, verification_issues} |

Ap dung least privilege: entity-agent khong goi payment tools, payment-agent khong goi shipment tools.

## 3. Entity resolution va A2A protocol

- Candidate ranking: claimed_order_id duoc uu tien dau, sau do candidate_order_ids trong case.
- Exact lookup: Goi get_order(order_id=claimed_order_id) truoc. Neu data tra ve rong -> rejected.
- Confidence threshold: Single exact match -> 0.85; match nhung khong phai claimed -> 0.65; multiple matches -> 0.5 (ambiguous).
- Handoff format: EntityResult dataclass voi case_id, resolved_order_ids, rejected_candidates, customer_unique_id, confidence, ambiguous.
- A2A envelope: Tat ca agents nhan case_id tu case dict goc. Khong tu sinh case_id.
- Timeout: MCP calls co timeout 300s (httpx2 config). Sau 3 lan retry transient, raise loi.
- Anti-loop: _GatewayWithCache dung SHA256 key (tool_name, case_id, params) -> moi unique call chi chay 1 lan.

## 4. Evidence va conflict lifecycle

- Validate MCP response: gateway.call() goi contracts.validate_evidence() tu dong.
- Luu evidence_ref: Moi ket qua MCP co evidence_ref dang ev_... Khong tao moi, khong sua.
- Ghi trace: Sau moi MCP call -> trace.emit(event_type="tool_result_consumed", evidence_refs=[ev_ref]).
- Chon source conflict: Khi order status != shipment status -> ghi data_conflicts voi resolution_code="status_conflict_unresolved".
- Evidence scope: _GatewayWithCache.clear_case_cache(case_id) sau khi finalize de tranh ro giua case.
- Map evidence -> output: evidence_refs trong output chua refs tu tat ca agents, deduplicated, max 30.

## 5. Failure and efficiency policy

| Failure | Retry budget | Fallback | Trace event/code |
| --- | --- | --- | --- |
| MCP timeout / 5xx | 2 retries (0.3s, 0.6s) | Bo qua tool, ghi verdict=insufficient_evidence | handoff voi decision_code=tool_error |
| 403 / 401 | 0 (raise ngay) | Raise RuntimeError | --- |
| Entity not found | 0 | EntityResult(status="not_found", confidence=0.0) | handoff / entity_not_found |
| Entity ambiguous | 0 | Dung candidate dau tien, confidence<=0.5 | handoff / entity_ambiguous |
| Source conflict | 0 | Ghi data_conflicts, resolution_code=status_conflict_unresolved | verification_completed |
| Invalid specialist result | 0 | Verifier giam confidence | verification_completed |

Cache strategy: Key = SHA256(tool_name + case_id + sorted params). Cache la in-memory, per-run.

## 6. Verification invariants

Truoc finalize, verifier kiem tra:
1. entity_result.status != "not_found" (confidence toi da 0.4 neu not_found)
2. primary_issue in ("late_delivery_seller") -> seller phai co trong responsible_parties
3. primary_issue in ("late_delivery_logistics") -> logistics_provider phai co trong responsible_parties
4. confidence khong bao gio = 1.0 khi co data_conflicts
5. confidence <= 0.6 khi entity_result.ambiguous = True
6. evidence_refs chi chua gia tri tu MCP, pattern ^ev_[A-Za-z0-9_-]{20,96}$
7. recommended_refund_brl >= 0, currency = "BRL"
8. resolution_actions khong trung nhau (uniqueItems)

## 7. Reproducibility

- Python >= 3.11, asyncio, httpx2
- Dependencies: jsonschema[format]>=4.25, mcp>=2, python-dotenv>=1.1
- Concurrency: Pha 2 dung asyncio.gather(shipment_task, payment_task) -- 2 parallel tasks per case
- Random seed: Khong dung random. Confidence duoc tinh deterministically tu evidence.
- Lenh chay: day09 run -> day09 validate -> day09 package --output dist/submission.zip
- API key: luu trong .env, khong commit.
