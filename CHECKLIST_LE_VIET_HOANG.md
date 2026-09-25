# Checklist công việc — Lê Việt Hoàng (Entity & Customer Agent)

> Cập nhật sau khi pull `a127117` và **triển khai xong phần không cần chờ ai**.
> Nhánh làm việc: `feat/lvh-entity-customer` (tách từ `feat/mth-coordinator`).
> Nguồn: `PHAN_CONG_4_NGUOI.md`, `KE_HOACH_MILESTONE.md`, `huong-dan.txt`, `README.md`, `contracts/`.
> Ký hiệu: ✅ xong · 🟡 xong phần của mình, còn phụ thuộc · ⛔ chờ người khác · ⬜ chưa tới lượt.

---

## A. Trạng thái tổng quan

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Môi trường / `.env` / CLI | ✅ | `day09 --help`, `validate-inputs` -> `OK: l3b / l3b-competition-v1 / 100 cases`, `mcp-tools` -> 10 tool |
| Discovery tool thật | ✅ | `scripts/discover_mcp_tools.py` -> `traces/mcp_tools.json` |
| Payload thật của 2 tool của mình | ✅ | `scripts/probe_mcp_payload.py` -> `traces/mcp_probe_*.json` |
| Package `agents/` (đang chặn cả nhóm) | ✅ (tạm) | `agents/__init__.py` + stub 2 module của TXH/HNĐ để CLI import được |
| Module `entity_customer.py` | ✅ | `src/student_agent/agents/entity_customer.py` |
| Kiểm thử module | ✅ | `tests/test_entity_customer.py` — 12/12 pass |
| Chạy với MCP thật (1 case) | ✅ | `traces/_smoke_entity.py` -> resolved, 2 evidence_ref thật, phát hiện source conflict |
| Tích hợp end-to-end 100 case | ⛔ | chờ `order_shipment.py` + `payment_policy.py` |
| Sửa lỗi/kiểm chứng/đóng gói | ⛔ | chờ M3–M6 |

---

## B. Hợp đồng đã chốt (từ code + discovery — code là chuẩn)

**Tool được cấp cho bạn (đã xác minh bằng discovery thật):**

| Tool | Tham số bắt buộc | Payload trả về |
|---|---|---|
| `get_order` | `case_id`, `order_id` | `order_id, customer_id, order_status, order_purchase_timestamp, order_approved_at, order_delivered_carrier_date, order_delivered_customer_date, order_estimated_delivery_date` |
| `get_customer_history` | `case_id`, `customer_unique_id` | `customer_unique_id, orders[]{order_id, customer_id, order_status, ...timestamps}` |

Hành vi đã kiểm chứng: `get_order` với order id không tồn tại -> gateway raise `RuntimeError`
(không phải data rỗng) ⇒ trong code được xử lý là **candidate bị loại**, không phải lỗi hệ thống.

**Input case (100/100 case giống cấu trúc):** `claimed_order_id` (hex32), `candidate_order_ids`
(đúng 2 phần tử: claimed order + `candidate-00X` tổng hợp), `customer_unique_id_hint`
(đuôi khớp claimed order), `investigation_scope.include_customer_history = true`.

**`EntityResult` (13 trường, khớp `workflow.py`):** `case_id, status, resolved_order_ids,
rejected_candidates, order_ids, item_ids, seller_ids, payment_references, shipment_ids,
customer_unique_id, related_order_ids, confidence, ambiguous, evidence_refs` + `notes` (bổ sung).

**Ngưỡng confidence theo `ARCHITECTURE.md` §3:** exact claimed order `0.85`; resolve được nhưng
không phải claimed `0.65`; nhiều candidate (ambiguous) `0.50`; không tìm thấy `0.00`;
customer history không xác minh được thì hạ về `0.65`. Không bao giờ gán `1.0`.

**Trace của bạn (schema `trace-event-v1`):** `task_assigned` -> `tool_result_consumed`
(mỗi evidence) -> `handoff` (target `coordinator`, `decision_code` = `entity_resolved` /
`entity_ambiguous` / `entity_not_found`). Actor luôn là `entity-agent`.

**Bất biến bắt buộc:** mọi call có `case_id`; không tự tạo/sửa `evidence_ref`; chỉ dùng ref do
MCP trả về; không dùng chéo case; không hardcode đáp án theo `case_id`.

---

## C. Đã xong (làm được ngay, không cần chờ ai)

### C1. Khảo sát (M0 / Pha 1)
- [x] Môi trường: venv + `pip install -e ".[dev]"`, `.env` đã có Team API Key.
- [x] `pytest -q`, `day09 --help`, `day09 validate-inputs`, `day09 mcp-tools` đều chạy được.
- [x] Thống kê input 100 case: loại định danh, số candidate, scope, hint.
- [x] Chọn case đại diện: `L3B_CASE_001` (exact ID), `L3B_CASE_002` (candidate sai),
      các case có conflict nguồn trong customer history.
- [x] Xác định field output của mình: `entity_resolution`, `customer_context`, `affected_entities`.
- [x] Lấy **tên tool + tham số thật** từ discovery (không đoán): `get_order`, `get_customer_history`.
- [x] Lấy **payload thật** của 2 tool để biết cấu trúc `data`.

### C2. Thiết kế (M1 / Pha 2 — phần của mình)
- [x] Chốt kết quả entity resolution: entity chọn, candidate bị loại, lý do, điểm chưa chắc chắn
      (thể hiện qua `EntityResult.rejected_candidates` + `notes`).
- [x] Chốt điều kiện bàn giao: `resolved` / `ambiguous` / `not_found` + `decision_code` khi handoff.
- [x] Quy tắc xếp hạng candidate (tất định, không chọn vì "đứng đầu"): ưu tiên claimed order,
      loại candidate sai định dạng id, khi nhiều candidate resolve thì xếp theo độ đầy đủ dữ kiện.
- [x] Chốt customer context chuyển cho 2 nhánh: `customer_unique_id`, `related_order_ids`,
      và cảnh báo mâu thuẫn `order_history_conflict:*` trong `notes`.

### C3. Triển khai (M2 / Pha 3)
- [x] `src/student_agent/agents/entity_customer.py`:
  - exact lookup `claimed_order_id` trước; chỉ mở rộng sang candidate khác khi thất bại
    (ngân sách tối đa 3 lookup/case);
  - loại `candidate-00X` **không tốn MCP call** (không phải order id hex32) — có ghi lý do;
  - `RuntimeError` từ gateway = candidate bị loại, không crash;
  - phân biệt `customer_id` (row) và `customer_unique_id` (khách hàng) — chỉ lấy unique id
    từ `get_customer_history` hoặc hint của đề;
  - xác minh hint: history phải chứa order đã resolve, nếu không thì trả `customer_unique_id = null`
    (không dùng sai phạm vi);
  - `ambiguous = True` khi nhiều candidate cùng resolve;
  - emit đủ `task_assigned`, `tool_result_consumed`, `handoff`; không tạo `evidence_ref` giả.
- [x] Tạo package `agents/` + stub `order_shipment.py`, `payment_policy.py` (thuộc TXH/HNĐ)
      để toàn bộ CLI hoạt động trở lại.

### C4. Kiểm thử (M2 — phần của mình)
- [x] `tests/test_entity_customer.py` — 12/12 pass (dùng gateway giả + `Contracts` thật +
      `TraceWriter` thật, không gọi MCP):
  1. exact claimed order -> resolved 0.85 + customer context;
  2. candidate tổng hợp bị loại và **không** phát sinh call;
  3. claimed sai -> fallback candidate hợp lệ, 0.65;
  4. nhiều candidate resolve -> ambiguous 0.5;
  5. không tìm thấy -> not_found 0.0;
  6. hint sai -> `customer_unique_id` null;
  7. `include_customer_history=false` -> bỏ call thừa;
  8. trace đủ lifecycle + evidence linkage;
  9. mọi `evidence_ref` đều là ref do gateway trả về;
  10. lỗi không phải RuntimeError vẫn propagate (không che lỗi);
  11. thiếu `case_id` -> raise;
  12. tích hợp `workflow._build_output` + validate schema `l3b-output-v2`.
- [x] Smoke test với **MCP thật** (case 001): status `resolved`, 2 `evidence_ref` thật,
      phát hiện mâu thuẫn nguồn `order_history_conflict` (5 mốc thời gian khác nhau giữa
      `get_order` và `get_customer_history` cho cùng `order_id`).

---

## D. Việc tiếp theo của bạn (vẫn chưa cần chờ ai)

- [ ] Review lại `ARCHITECTURE.md` §3 + §6 (MTH viết trước phần của bạn) và gửi đề xuất chỉnh
      qua MTH — nội dung đề xuất ở mục G bên dưới.
- [ ] Mở rộng test cho nhánh `candidate` hợp lệ nhưng **không** thuộc khách hàng của hint.
- [ ] Rà `notes`/`decision_code` xem verifier (HNĐ) có dùng được để suy ra `data_conflicts` không;
      nếu cần thì thống nhất thêm trường A2A.
- [ ] Chuẩn bị nội dung tài liệu M5: candidate ranking/rejection, threshold, điều kiện handoff
      (đã có trong docstring module — chỉ cần chuyển thành văn bản cho `ARCHITECTURE.md`).
- [ ] Đo số call/case của nhánh mình (hiện tại: 2 call/case ở luồng thường) để đưa vào báo cáo M5.

---

## E. Phải chờ ai — chờ cái gì

| # | Chờ ai | Chờ gì | Chặn việc gì của bạn |
|---|---|---|---|
| 1 | Trịnh Xuân Huy | `agents/order_shipment.py` thật (`get_order_items`, `get_shipment_summary`, `get_sellers`, `get_product_context`) | `day09 run`, kiểm chứng M4, review chéo M6 |
| 2 | Hoàng Ngọc Đức | `agents/payment_policy.py` thật (`run_payment`, `decide_policy`, `verify_and_calibrate`) | `day09 run`, event `verification_completed`, confidence cuối |
| 3 | Mai Tiến Huy | Sửa `workflow._build_output`: `item_ids`/`seller_ids`/`shipment_ids`/`payment_references` phải lấy từ kết quả TXH/HNĐ (xem mục F‑5) | Điểm semantic/evidence của 100 case |
| 4 | Mai Tiến Huy | Chốt ai emit `task_assigned`/`handoff` (bạn đã emit) để không trùng event | Điểm workflow (5%) |
| 5 | Mai Tiến Huy | Bảng lỗi P0–P3 sau `day09 run` + `day09 validate` | Sửa lỗi nghiệp vụ M4 |
| 6 | MTH + HNĐ | Chốt ai làm Verifier (tài liệu đang mâu thuẫn) | `verification_completed`, calibration |
| 7 | Trịnh Xuân Huy | Review chéo module của bạn (TXH là reviewer chính) | Merge vào nhánh chung |
| 8 | Cả nhóm | Quy ước chỉ 1 người chạy batch tại một thời điểm (CLI xoá `outputs/`, `traces/`) | Tránh mất dữ liệu của nhau |

---

## F. Xung đột: đã xử lý / còn lại

### Đã xử lý
1. ✅ **Nghiêm trọng nhất — package `agents/` không tồn tại** làm mọi lệnh `day09` chết.
   Đã tạo `agents/__init__.py` + `entity_customer.py`; 2 stub cho TXH/HNĐ để CLI hoạt động
   trở lại. **TXH/HNĐ cần thay ruột 2 file stub đó.**
2. ✅ **Tên tool mâu thuẫn 3 nguồn** (README/PHAN_CONG/ARCHITECTURE) — MTH đã cập nhật theo
   `day09 mcp-tools`; bạn xác minh độc lập bằng script discovery (`get_order`,
   `get_customer_history`, kèm toàn bộ tham số).
3. ✅ **PHAN_CONG ghi output entity là `{entity_id, customer_id, ...}`** trong khi `workflow.py`
   cần 13 trường khác tên. Module của bạn đã khớp **code** (nguồn chân lý).
   Việc còn lại: nhờ MTH sửa lại dòng đó trong `PHAN_CONG_4_NGUOI.md` cho khỏi hiểu nhầm.
4. ✅ **Nghi ngờ thiếu quyền tool sản phẩm** — đã rõ: entity agent chỉ có `get_order` +
   `get_customer_history`; đối chiếu candidate dùng dữ liệu có sẵn trong `get_order`
   (status, các mốc thời gian, `customer_id`), không gọi `get_product_context`.

### Còn lại (cần chốt)
5. ❗ **`workflow._build_output` lấy toàn bộ `affected_entities` từ `entity_result`** ⇒
   `item_ids`, `seller_ids`, `shipment_ids`, `payment_references` sẽ **luôn rỗng** vì bạn
   không được gọi các tool tạo ra chúng. Đề xuất sửa (MTH):
   ```python
   "affected_entities": {
       "order_ids": entity_result.order_ids[:20],
       "item_ids": shipment_result.item_ids[:20],
       "seller_ids": shipment_result.seller_ids[:20],
       "shipment_ids": shipment_result.shipment_ids[:20],
       "payment_references": payment_result.payment_references[:20],
   },
   ```
6. ⛔ **Ai làm Verifier**: `PHAN_CONG_4_NGUOI.md` giao HNĐ (design Pha 2 + code Pha 4),
   `KE_HOACH_MILESTONE.md` giao MTH; code thực tế `payment_policy.verify_and_calibrate`
   nằm ở file của HNĐ ⇒ cần chốt và sửa 1 trong 2 tài liệu.
7. ⛔ **Trùng event trace**: bạn emit `task_assigned` + `tool_result_consumed` + `handoff`.
   Nếu MTH bổ sung các event này vào coordinator (hoặc TXH/HNĐ cũng emit `handoff`) thì
   trace bị trùng ⇒ chốt phân công theo actor như trên.
8. ⛔ **`_GatewayWithCache.clear_case_cache()` là dead code** (lọc theo `Case_id` không tồn tại
   trong evidence) — báo MTH sửa hoặc bỏ.
9. ⛔ **Retry đối với lỗi "order không tồn tại"**: `_GatewayWithCache` retry 3 lần cho mọi
   `RuntimeError`, kể cả trường hợp order id không tồn tại ⇒ nếu có nhánh phải probe candidate
   giả sẽ tốn 3 call. Nhánh của bạn tránh được (không probe candidate sai định dạng), nhưng
   TXH/HNĐ nên biết.
10. ⛔ **`case-set.json` + `case-release` test**: `tests/test_release_safety.py` fail trên máy
    local vì có `case-set.json` — đây là hành vi cố ý của repo, không phải lỗi của nhóm.

---

## G. Đề xuất nội dung cho `ARCHITECTURE.md` §3 (MTH copy vào)

> Entity resolution: exact lookup `claimed_order_id` qua `get_order` trước; chỉ mở rộng sang
> các `candidate_order_ids` khi exact lookup thất bại (gateway raise `RuntimeError` cho order id
> không tồn tại). Candidate không có dạng order id hex 32 ký tự bị loại bằng quy tắc tất định và
> ghi lý do, không tiêu tốn MCP call.
>
> Customer context: `get_order` chỉ trả `customer_id` (định danh dòng), nên `customer_unique_id`
> chỉ được lấy từ `get_customer_history`; nếu history không chứa order đã resolve thì trả `null`
> thay vì dùng hint của đề (tránh sai phạm vi). Khi cùng một `order_id` có mốc thời gian khác nhau
> giữa hai nguồn, agent ghi nhận `order_history_conflict` trong handoff để verifier xử lý.
>
> Ngưỡng confidence: exact claimed `0.85`; resolved không phải claimed `0.65`; nhiều candidate
> (`ambiguous = True`) `0.50`; không tìm thấy `0.00`; history không xác minh được thì hạ trần `0.65`.
>
> Handoff: `decision_code` = `entity_resolved` / `entity_ambiguous` / `entity_not_found`,
> `target = coordinator`; kèm `resolved_order_count`, `rejected_candidate_count`, `confidence`,
> `ambiguous`, `customer_history_verified`, `notes`.
>
> Cache/anti-loop: nhánh entity chỉ gọi tối đa 3 order lookup + 1 customer history mỗi case;
> không gọi lại cùng tham số trong cùng case (đã có cache của gateway).

---

## H. Artifact đã tạo (nhánh `feat/lvh-entity-customer`)

| Đường dẫn | Nội dung | Ghi chú |
|---|---|---|
| `src/student_agent/agents/entity_customer.py` | Agent của bạn (code chính) | Thuộc bạn |
| `src/student_agent/agents/__init__.py` | Package `agents` | Dùng chung |
| `src/student_agent/agents/order_shipment.py` | **Stub** cho TXH | TXH thay ruột |
| `src/student_agent/agents/payment_policy.py` | **Stub** cho HNĐ | HNĐ thay ruột |
| `tests/test_entity_customer.py` | 12 test (không cần MCP) | Thuộc bạn |
| `scripts/discover_mcp_tools.py` | In tên + tham số tool thật | Tiện cho cả nhóm |
| `scripts/probe_mcp_payload.py` | Gọi thử 1 tool để xem payload | Tiện cho cả nhóm |
| `CHECKLIST_LE_VIET_HOANG.md` | File này | — |
| `traces/mcp_tools.json`, `traces/mcp_probe_*.json` | Kết quả discovery/probe (gitignored) | Bằng chứng khảo sát |

---

## I. Lệnh dùng hằng ngày

```powershell
cd C:\Users\ADMIN\Desktop\K4-L3B-MultiAgent-MCP-A2A
git pull                                   # đang ở nhánh feat/lvh-entity-customer
git switch feat/mth-coordinator            # khi cần lấy cập nhật của MTH rồi merge vào nhánh mình
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests/test_entity_customer.py -v
.venv\Scripts\day09.exe validate-inputs
.venv\Scripts\day09.exe mcp-tools
.venv\Scripts\python.exe scripts\discover_mcp_tools.py          # xem lại tool + tham số
.venv\Scripts\python.exe scripts\probe_mcp_payload.py get_order --case-id L3B_CASE_001 order_id=<hex32>
```

Lưu ý môi trường: `ruff` trên máy này bị Application Control policy chặn (WinError 4551) nên
không chạy được lint tự động; đã kiểm tra thủ công (dòng ≤ 100 ký tự, thứ tự import).
