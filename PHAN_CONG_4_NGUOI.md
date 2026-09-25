# Phân công 4 người — Hoàn thành trong 1 ngày (240 phút)

> Bám sát 6 pha của đề bài. Mỗi người có việc riêng trong từng pha, hội tụ tại điểm sync cuối mỗi pha chính.

---

## Tổng quan phân công theo pha

| Pha | Thời gian | Mai Tiến Huy | Lê Việt Hoàng | Trịnh Xuân Huy | Hoàng Ngọc Đức |
|---|---|---|---|---|---|
| **1** | 0–30m | Setup env, API key, `mcp-tools` | Setup env | Setup env | Setup env |
| **2** | 30–65m | Coordinator + workflow skeleton + ARCHITECTURE.md | Entity/Customer Agent design | Order/Shipment Agent design | Payment Agent + Policy Agent + Verifier design |
| **3** | 65–110m | MCP gateway wrapper, cache, trace writer, tích hợp | Entity/Customer Agent code | Order/Shipment Agent code | Payment Agent code |
| **4** | 110–150m | Tích hợp + chạy thử case đầu | Hỗ trợ entity scope + fix | Policy Agent + Verifier code | Verifier hỗ trợ + confidence |
| **5** | 150–210m | `day09 run` + `day09 validate` + điều phối fix | Fix lỗi entity | Fix lỗi order/shipment | Fix lỗi payment/policy |
| **6** | 210–240m | `day09 package` + upload + chọn final | Review chéo entity | Review chéo shipment | Review chéo payment/conflict |

---

## ⏱️ Pha 1 — Đăng ký, Fork, Cài đặt (0–30 phút)

**Deliverable:** `day09 mcp-tools` chạy thành công, cả nhóm có tool list thực tế.

### Mai Tiến Huy *(chủ trì)*
- [ ] Fork repo, giữ nguyên tên `K4-L3B-MultiAgent-MCP-A2A`
- [ ] Tạo `.env` từ `.env.example`, điền Team API Key (không commit key)
- [ ] Chạy `day09 mcp-tools` → lấy danh sách tool thực tế
- [ ] **Chia ngay tool list cho cả nhóm**: ai gọi tool nào

### Lê Việt Hoàng / Trịnh Xuân Huy / Hoàng Ngọc Đức *(song song)*
- [ ] Clone repo về máy, tạo virtualenv, cài `.[dev]`
- [ ] Điền `.env` theo hướng dẫn MTH
- [ ] Chạy `day09 validate-inputs` → xác nhận: `OK: l3b / l3b-competition-v1 / 100 cases`
- [ ] Đọc nhanh `contracts/schemas/` — nắm tên field output của phần mình phụ trách

### Sync chốt cuối Pha 1 (5 phút)
- [x] MTH chia tool list (kết quả `day09 mcp-tools`):
  - **Lê Việt Hoàng** (Entity/Customer): `get_order`, `get_customer_history`
  - **Trịnh Xuân Huy** (Order/Shipment): `get_order`, `get_order_items`, `get_shipment_summary`, `get_sellers`, `get_product_context`
  - **Hoàng Ngọc Đức** (Payment/Policy): `get_order_payments`, `get_payment_timeline`, `get_refund_timeline`, `get_policy`
- [ ] Thống nhất kiểu dữ liệu trả về của từng specialist agent

---

## ⏱️ Pha 2 — Thiết kế A2A & Contract Schemas (30–65 phút)

**Deliverable:** Interface ổn định → 3 người có thể code độc lập ở Pha 3.

### Mai Tiến Huy *(Coordinator design)*
- [ ] Viết skeleton `workflow.py`:
  ```python
  async def solve_case(case, gateway, trace) -> dict:
      # 1. entity resolution
      # 2. parallel: order_agent + payment_agent + shipment_agent
      # 3. policy_agent
      # 4. verifier_agent
      # 5. build output → validate schema
  ```
- [ ] Chốt kiểu dữ liệu dùng chung: `AgentResult`, `EvidenceBundle`, `Conflict`
- [ ] Chốt A2A envelope nội bộ: `case_id`, findings, evidence_refs, limits
- [ ] Phác thảo `ARCHITECTURE.md`: sơ đồ luồng, tool permissions, retry policy
- [ ] Tạo fixture: mock `gateway.call()` + mock case JSON

### Lê Việt Hoàng *(Entity/Customer Agent design)*
- [ ] Đọc `l3b-output-v2.schema.json` → ghi lại các field liên quan entity/customer
- [ ] Chốt input nhận từ coordinator: raw case dict
- [ ] Chốt output trả về: `{ entity_id, customer_id, customer_unique_id, confidence, evidence_refs, ambiguous: bool }`
- [x] Liệt kê tool cần gọi: `get_order`, `get_customer_history`

### Trịnh Xuân Huy *(Order/Shipment Agent design)*
- [ ] Đọc `l3b-output-v2.schema.json` → ghi lại các field order, shipment, timeline
- [ ] Chốt input: `entity_id` + `case` từ coordinator
- [ ] Chốt output: `{ order_data, shipment_timeline, delivery_status, conflicts, evidence_refs }`
- [x] Liệt kê tool cần gọi: `get_order`, `get_order_items`, `get_shipment_summary`, `get_sellers`, `get_product_context`

### Hoàng Ngọc Đức *(Payment + Policy + Verifier design)*
- [ ] Đọc `l3b-output-v2.schema.json` → field payment, refund, resolution, confidence
- [ ] Chốt output Payment Agent: `{ payments, refund_status, amount, evidence_refs }`
- [ ] Đọc `contracts/scoring/scoring-policy-v2.json` → hiểu `primary_issue`, `responsible_party`, `financial_resolution`
- [ ] Thiết kế Policy Agent output: `{ primary_issue, responsible_parties, recommended_refund_brl, resolution_actions }`
- [ ] Thiết kế Verifier: cross-field check + confidence calibration `[0.0–1.0]`

### Sync chốt cuối Pha 2 (5 phút)
- [ ] Cả 4 người xác nhận interface input/output của từng agent
- [ ] MTH push fixture + type definitions lên branch chung
- [ ] Bắt đầu Pha 3 độc lập

---

## ⏱️ Pha 3 — Triển khai Specialist Agents & MCP Gateway (65–110 phút)

**Deliverable:** Từng agent gọi được MCP, ghi trace đúng, kiểm thử bằng fixture.

> ⚠️ **Nguyên tắc MCP bắt buộc — vi phạm = 0 điểm:**
> - Luôn truyền `case_id` cho mọi MCP call
> - KHÔNG tự sinh hoặc sửa `evidence_ref`
> - Ghi event `tool_result_consumed` vào trace sau mỗi lần dùng evidence

### Mai Tiến Huy *(MCP Gateway wrapper + Cache + Trace + Coordinator)*
- [ ] Viết MCP cache: `tool_name + params + case_id` → tránh gọi trùng
- [ ] Retry có giới hạn cho lỗi transient (không retry 403)
- [ ] Triển khai `trace.emit()` wrapper, đảm bảo ghi đủ event lifecycle:
  `case_received → task_assigned → tool_result_consumed → handoff → policy_decided → verification_completed → case_finalized`
- [ ] Viết coordinator: nhận entity result → dispatch song song order+shipment+payment agent
- [ ] Kiểm thử cách ly 2 case (không rò cache giữa case)

### Lê Việt Hoàng *(Entity & Customer Agent)*
- [ ] Triển khai `entity_customer.py`:
  - Exact order ID lookup nếu input có
  - Candidate search phạm vi hẹp → mở rộng có điều kiện
  - Đối chiếu thuộc tính case vs candidate
  - Phân biệt `customer_id` vs `customer_unique_id`
  - Trả `ambiguous=True` khi chưa đủ căn cứ
- [ ] Gọi MCP đúng pattern:
  ```python
  evidence = await gateway.call("get_order", case_id=case["case_id"], order_id=order_id)
  trace.emit(case_id=..., event_type="tool_result_consumed", actor="entity-agent", ...)
  ```
- [ ] Kiểm thử fixture: exact ID đúng, exact ID sai, nhiều candidate, không tìm thấy

### Trịnh Xuân Huy *(Order + Shipment Agent)*
- [x] Triển khai `order_shipment.py`:
  - Đọc order/item/product qua MCP
  - Dựng timeline từ mốc thực tế, giữ nguyên dữ liệu thiếu
  - So sánh expected delivery vs actual delivery
  - Phân tích: giao trễ, chưa giao, hủy đơn — phải có evidence
  - Phát hiện conflict trạng thái đơn vs shipment
- [x] Ghi `tool_result_consumed` sau mỗi MCP call
- [x] Kiểm thử fixture: giao đúng hạn, trễ hạn, thiếu date, hủy đơn, conflict

### Hoàng Ngọc Đức *(Payment Agent)*
- [ ] Triển khai `payment_policy.py` — phần Payment:
  - Đối chiếu khoản thanh toán, phương thức, trạng thái từ evidence
  - Phân biệt: nhiều khoản payment, trả góp, thu trùng
  - Phân tích refund: yêu cầu / đang xử lý / hoàn tất / một phần / toàn phần
  - Đối chiếu số tiền + đơn vị tiền tệ
- [ ] Ghi `tool_result_consumed` sau mỗi MCP call
- [ ] Kiểm thử fixture: refund một phần, payment nhiều dòng, refund đang xử lý

---

## ⏱️ Pha 4 — Policy Engine, Verifier & Tích hợp (110–150 phút)

**Deliverable:** Workflow chạy được end-to-end với ít nhất 5 case đại diện.

### Mai Tiến Huy *(Tích hợp + Chạy thử)*
- [ ] Ghép entity → order/shipment/payment → policy → verifier vào `solve_case`
- [ ] Map kết quả internal sang schema `l3b-output-v2.schema.json` chính xác
- [ ] Chạy 5 case đại diện với evidence thật
- [ ] Kiểm tra trace.jsonl có đủ lifecycle events
- [ ] Báo lỗi tích hợp cho người liên quan sửa ngay

### Lê Việt Hoàng *(Hỗ trợ fix entity + scope)*
- [ ] Sửa lỗi entity resolution phát sinh khi chạy evidence thật
- [ ] Xác nhận entity bàn giao đúng `case_id`, không rò giữa case
- [ ] Kiểm tra customer context không bị bỏ mất khi truyền sang policy

### Trịnh Xuân Huy *(Hỗ trợ fix order/shipment)*
- [ ] Sửa lỗi timeline mapping, trạng thái, xử lý đơn nhiều item
- [ ] Xác nhận findings shipment được truyền đầy đủ sang policy

### Hoàng Ngọc Đức *(Policy Agent + Verifier)*
- [ ] Triển khai Policy Agent dựa trên `scoring-policy-v2.json`:
  - `primary_issue`: `canceled_order_paid`, `late_delivery_seller`, `late_delivery_logistics`, `payment_mismatch`, ...
  - `responsible_parties`: `seller`, `platform`, `logistics_provider`, `payment_provider`, `customer`
  - `recommended_refund_brl` + `refund_lines`
  - `resolution_actions`
- [ ] Triển khai Verifier:
  - Cross-field check: `primary_issue` vs `responsible_parties` nhất quán
  - Confidence calibration `[0.0–1.0]`: không gán `1.0` khi có conflict
  - Phân xử conflict nguồn mâu thuẫn, lưu `unresolved` khi không thể kết luận
- [ ] Kiểm thử: conflict chưa giải quyết, thiếu policy, confidence thấp hợp lý

---

## ⏱️ Pha 5 — Batch Run 100 Cases & Validate (150–210 phút)

**Deliverable:** `day09 validate` in `OK: 100 outputs / N trace events`.

### Mai Tiến Huy *(Điều phối + Chạy batch)*
- [ ] Chạy `day09 run` — xử lý toàn bộ 100 case
- [ ] Chạy `day09 validate` — kiểm tra schema + trace
- [ ] Tổng hợp lỗi theo ưu tiên và giao cho người phụ trách:

| Ưu tiên | Loại lỗi | Xử lý |
|---|---|---|
| **P0** | Sai schema, evidence_ref tự tạo, sai case_id, sai phạm vi | Phải sửa ngay — chặn nộp |
| **P1** | Sai entity, kết luận sai, tính sai tiền, bỏ qua conflict | Sửa trước khi đóng gói |
| **P2** | Confidence không hợp lý, trace thiếu event, customer context mất | Sửa nếu còn thời gian |
| **P3** | Gọi tool trùng, retry thừa | Bỏ qua nếu hết giờ |

### Lê Việt Hoàng
- [ ] Nhận bảng lỗi từ MTH → sửa lỗi entity/customer trong nhánh mình
- [ ] Bổ sung regression test cho lỗi thực tế phát hiện
- [ ] Kiểm tra case thiếu ID, nhiều candidate, confidence cao bất thường

### Trịnh Xuân Huy
- [ ] Nhận bảng lỗi → sửa lỗi order/shipment/timeline
- [ ] Kiểm tra kết luận không vượt phạm vi evidence
- [ ] Xác minh conflict order/shipment hiển thị đúng trong output

### Hoàng Ngọc Đức
- [ ] Nhận bảng lỗi → sửa lỗi payment/policy/conflict
- [ ] Kiểm tra số tiền, refund, responsible_parties nhất quán
- [ ] Review conflict chưa giải quyết và tác động đến confidence

---

## ⏱️ Pha 6 — Đóng gói & Nộp bài (210–240 phút)

**Deliverable:** `submission.zip` upload thành công, chọn final.

### Mai Tiến Huy *(chủ trì nộp bài)*
- [ ] Chạy lệnh đóng gói:
  ```bash
  day09 package --output dist/submission.zip
  ```
  *Pass signal: `OK: .../dist/submission.zip`*
- [ ] Kiểm tra cấu trúc ZIP — **chỉ được chứa 3 thứ, không có thư mục bọc ngoài:**
  ```
  submission.zip
  ├── manifest.json
  ├── trace.jsonl
  └── outputs/
      ├── <case_id>.json  (đúng 100 files)
      └── ...
  ```
- [ ] Xác nhận `manifest.json` đúng schema `submission-manifest-v2`:
  - `variant_id: "l3b"`, `competition_id`, `case_set_version`, `generated_at`
- [ ] Upload lên Competition Workspace `/l3b`
- [ ] Chọn submission làm **final**
- [ ] Ghi lại submission ID + thời điểm nộp cho cả nhóm

### Lê Việt Hoàng
- [ ] Kiểm tra chéo: entity/evidence của 10 case khó trong bản cuối
- [ ] Xác nhận không lẫn fixture hoặc ref từ lần chạy thử

### Trịnh Xuân Huy
- [ ] Kiểm tra chéo: timeline/shipment của các case đã từng có lỗi
- [ ] Đối chiếu output cuối với trace và evidence liên quan

### Hoàng Ngọc Đức
- [ ] Kiểm tra chéo: số tiền/refund/policy/conflict bản cuối
- [ ] Cùng MTH xác nhận ZIP không chứa source code, `.env`, API key, debug log

---

## 📋 Sở hữu file code

| File | Người phụ trách |
|---|---|
| `src/student_agent/workflow.py` | Mai Tiến Huy |
| `src/student_agent/agents/entity_customer.py` | Lê Việt Hoàng |
| `src/student_agent/agents/order_shipment.py` | Trịnh Xuân Huy |
| `src/student_agent/agents/payment_policy.py` | Hoàng Ngọc Đức |
| `ARCHITECTURE.md` | Cả nhóm — MTH tổng hợp |

---

## 📊 Tiêu chí chấm điểm — ai dẫn dắt

| Tiêu chí | Trọng số | Người dẫn dắt |
|---|---:|---|
| Semantic (kết luận đúng) | 40% | Cả nhóm theo nhánh |
| Evidence (bằng chứng hỗ trợ) | 15% | LVH kiểm tra scope entity |
| Provenance (evidence_ref thật, đúng scope) | 15% | Mai Tiến Huy |
| Consistency (nhất quán đa trường) | 10% | MTH + HNĐ |
| Schema (output đúng format) | 5% | Mai Tiến Huy |
| Calibration (confidence hợp lý) | 5% | HNĐ + MTH |
| Workflow (trace lifecycle đầy đủ) | 5% | Mai Tiến Huy |
| Efficiency (ít call trùng, retry hợp lý) | 5% | Cả nhóm |

---

## ✅ Checklist trước khi MTH merge module

- [ ] Module nhận đúng interface đã chốt ở Pha 2
- [ ] Tất cả MCP call đều có `case_id` + ghi `tool_result_consumed`
- [ ] `evidence_ref` nguyên bản từ MCP — không tự tạo, không sửa
- [ ] Fixture test đã chạy qua
- [ ] Không hardcode đáp án theo `case_id`
- [ ] Trace chỉ ghi hoạt động quan sát được, không ghi suy luận riêng
