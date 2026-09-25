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

## 8. Nguon du lieu "authoritative" vs nguon nhieu (quy tac phan xu conflict)

MCP tra ve, cho cung mot `order_id`, hai nhom ban ghi:

- **phien ban cua `get_order`**: cac moc thoi gian ma `get_order` tra ve;
- **phien ban trong `get_customer_history`**: cung `order_id` nhung
  `order_purchase_timestamp` khac han (lech vai thang). Day moi la phien ban ma khach hang
  thuc su trai qua.

Kiem chung tren du lieu that (case 001-010, probe `get_customer_history`): claim topic
**luon** la van de cua phien ban thu hai, khong phai cua phien ban `get_order`. Vi du:

- case 001: `get_order` mua `2018-05-11` (giao dung han), nhung history con mot phien ban mua
  `2017-12-20`, giao `2018-01-04` > du kien `2017-12-30` (tre) - claim la
  `late_delivery_logistics`;
- case 007 nguoc lai: `get_order` giao tre, con phien ban thu hai giao dung han - claim la
  `unsupported_claim`.

Quy tac (cai dat trong `entity_customer._truth_order_row`):

1. Entity agent doc `get_customer_history`; phien ban co `order_purchase_timestamp` khac
   `get_order` duoc chon lam **timeline su that** (`EntityResult.truth_order`).
2. Hai specialist dung timeline do lam `order` + `anchors`, nen `pick_consistent()` giu cac
   ban ghi thuoc phien ban su that (item row, shipping limit, capture, refund event).
3. Conflict duoc ghi vao `data_conflicts` voi `selected_source = get_customer_history` va
   `resolution_code = claimed_timeline_selected`.
4. Neu history khong co phien ban thu hai (khop `get_order`) thi giu nguyen `get_order`,
   hanh vi nhu cu.

Luu y: "tre giao hay khong" duoc quyet dinh bang **timeline su that**
(`delivered_customer > estimated`); event `delivered_late` bo sung `actor`
(`seller` vs `logistics_provider`) de **quy trach nhiem**.


## 9. Cac nhanh quyet dinh da trien khai

- Entity (`entity_customer.py`): exact lookup `claimed_order_id`; candidate sai dinh dang bi
  loai bang quy tac tat dinh (khong ton call); confidence 0.85 / 0.65 / 0.50 / 0.00.
- Order/Shipment (`order_shipment.py`): `verdict` theo **timeline su that** (§8) + actor cua
  event (`on_time`, `seller_delay`, `logistics_delay`, `lost`, `returned`, `conflicting`,
  `insufficient_evidence`); tinh `item_total_brl` tren cac item row thuoc timeline su that;
  `verdict` duoc can chinh theo `CLAIM_SHIPMENT_VERDICT` de chu the do claim topic quyet dinh.
- Payment/Refund (`payment_policy.py::run_payment`): `captured/refunded/refundable_total_brl`
  tu cac capture/refund event thuoc timeline su that; co `get_refund_timeline` tra
  `RuntimeError` khi don khong co refund (duoc coi la "khong co evidence", khong retry, khong
  bia ref). Mot timeline co the chua dong thoi dau hieu cua ca hai phien ban (vi du mot valid
  split payment nam canh mot failed refund); `verdict` duoc can chinh theo
  `CLAIM_PAYMENT_VERDICT` de claim topic quyet dinh dau hieu nao dang bi tranh chap.
- Policy (`decide_policy`): `primary_issue` la **chu the tranh chap** ma case khai bao - topic
  dau tien trong `customer_request.claims` khop mot issue code (10 gia tri cua enum). Day la
  cau tra loi cho "case nay dang kien cai gi", nen evidence **khong** duoc am tham doi nhan
  chu the chi vi mot trong hai nguon nguoc nhau (order row vs. lifecycle events) noi khac.
  Cac issue khac ma evidence thuc su phat hien duoc giu trong `secondary_issues`.
  Fallback (input la, claim khong neu issue nao): thu tu uu tien evidence
  `unavailable_order_paid` -> `canceled_order_paid` -> `late_delivery_seller` /
  `late_delivery_logistics` -> `refund_failed` -> `refund_pending` -> `payment_mismatch`
  -> `duplicate_charge` -> `valid_split_payment` -> `unsupported_claim`.
  `case_status`, `recommended_action`, `refund_brl` lay tu policy rule tra qua
  `get_policy(policy_version)` (policy la chan ly cho so tien). `responsible_parties` lay
  `party_type` tu policy nhung `party_id` cua seller duoc thay bang seller_id that ma
  evidence da resolve (`affected_entities.seller_ids`) - policy chi mang placeholder.
- Verifier (`verify_and_calibrate`): cross-field (late_seller phai co seller, late_logistics
  phai co logistics_provider, refund > 0 <=> issue can hanh dong), action khong trung,
  va tran confidence: 0.85 khi con `data_conflicts`, 0.80 khi refund `pending`, 0.60 khi
  entity ambiguous, 0.40 khi entity not_found / khong co evidence. Khong bao gio > 0.95.

## 10. Vong doi trace va hieu qua MCP

- Event moi case (dung thu tu): `case_received` -> `task_assigned` ->
  `tool_result_consumed` -> `handoff` -> `policy_decided` -> `verification_completed` ->
  `case_finalized`. `case_received` / `case_finalized` do `solve_case` so huu duy nhat.
- Vai tro actor: `coordinator`, `entity-agent`, `order-shipment-agent`, `payment-agent`,
  `policy-agent`, `verifier-agent`.
- Retry: chi retry loi van chuyen (network/timeout). `RuntimeError` (tool error, 403/401,
  order/refund khong ton tai) **khong retry** vi la quyet dinh tat dinh - tranh dot call
  audit. Cache theo `(tool, case_id, params)` trong pham vi mot case.
- Ngan sach call/case: order, customer_history, order_items, shipment_summary, sellers,
  product_context, payment_timeline, refund_timeline, policy (9 call; `get_order` dung lai
  ban cache cua entity agent nen khong ton call thu hai).
