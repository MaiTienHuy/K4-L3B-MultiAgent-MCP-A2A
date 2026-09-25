# Kế hoạch triển khai K4 L3B — Multi-Agent MCP + A2A

## 1. Mục tiêu và phạm vi

Xây dựng hệ thống multi-agent điều tra khiếu nại thương mại điện tử, từ tiếp nhận case đến xác định đúng entity, thu thập bằng chứng qua MCP, phân tích nghiệp vụ, giải quyết mâu thuẫn và xuất kết quả có thể kiểm chứng.

Kế hoạch này phân công cho bốn thành viên: **Mai Tiến Huy, Lê Việt Hoàng, Trịnh Xuân Huy và Hoàng Ngọc Đức**. Các đầu việc và trạng thái bên dưới là kế hoạch thực hiện, không phải xác nhận đã hoàn thành.

Thời gian đề xuất là **10 ngày làm việc**, tính từ ngày nhóm bắt đầu. Đây là lịch nội bộ có thể điều chỉnh theo hạn nộp thực tế; không phải thời hạn do cuộc thi quy định. Nếu rút ngắn lịch, vẫn giữ các bước nghiệm thu.

### Kết quả cuối cần có

- Workflow hoạt động tại `src/student_agent/workflow.py`, với hàm `async def solve_case(case, gateway, trace) -> dict`.
- Xử lý entity resolution, customer context, order/product, shipment, payment/refund, policy và source conflict.
- Output tuân thủ `contracts/schemas/l3b-output-v2.schema.json`.
- Trace phản ánh hoạt động thực tế, tuân thủ `contracts/schemas/trace-event-v1.schema.json`.
- Evidence lấy từ MCP đúng team, run và case; không tự tạo hoặc sửa `evidence_ref`.
- Kiểm thử phù hợp, tài liệu `ARCHITECTURE.md` hoàn chỉnh và gói `dist/submission.zip` hợp lệ.
- Upload gói nộp lên Competition Workspace `/l3b` và chọn submission final.

### Nguồn yêu cầu trong repo

| Nguồn | Mục đích sử dụng |
| --- | --- |
| `README.md` | Cài đặt, đăng ký, input, lệnh chạy và quy tắc nộp bài |
| `contracts/README.md` | Xác định bộ contract công khai cần tuân thủ |
| `contracts/schemas/l3b-output-v2.schema.json` | Cấu trúc output L3B |
| `contracts/schemas/trace-event-v1.schema.json` | Cấu trúc sự kiện trace |
| `contracts/schemas/mcp-evidence-response-v1.schema.json` | Cấu trúc evidence từ MCP |
| `contracts/scoring/scoring-policy-v2.json` | Chính sách chấm điểm công khai |
| `ARCHITECTURE.md` | Các nội dung thiết kế cần hoàn thiện |

Các tên module mới trong kế hoạch là đề xuất. Giữ nguyên contract chính thức và tận dụng `mcp_gateway.py`, `trace.py`, `submission.py` hiện có trước khi bổ sung lớp hỗ trợ.

## 2. Phân công trách nhiệm

| Thành viên | Vai trò chính | Phạm vi chịu trách nhiệm | Người review chính |
| --- | --- | --- | --- |
| **Mai Tiến Huy** | Coordinator, Verifier, tích hợp | Luồng `solve_case`, giao diện A2A, tích hợp gateway, kiểm chứng kết quả, chạy tổng thể, đóng gói và nộp bài | Hoàng Ngọc Đức |
| **Lê Việt Hoàng** | Entity & Customer Agent | Tìm candidate, resolve entity, phân biệt định danh khách hàng, customer context và kiểm tra phạm vi entity/evidence | Trịnh Xuân Huy |
| **Trịnh Xuân Huy** | Order, Product & Shipment Agent | Nội dung đơn, sản phẩm, timeline vận chuyển, vấn đề giao nhận và conflict giữa order/shipment | Lê Việt Hoàng |
| **Hoàng Ngọc Đức** | Payment, Refund, Policy & Conflict Agent | Thanh toán, hoàn tiền, điều kiện chính sách, đề xuất xử lý và quy tắc phân xử source conflict | Mai Tiến Huy |

Mỗi người tự viết kiểm thử logic nghiệp vụ và tài liệu cho phần mình. Mai Tiến Huy tổng hợp và tích hợp; việc sửa lỗi của từng nhánh vẫn thuộc người phụ trách nhánh đó.

## 3. Tổng quan milestone

| Mốc | Thời gian dự kiến | Kết quả chính | Điều kiện bắt đầu |
| --- | --- | --- | --- |
| **M0 — Chuẩn bị và khảo sát** | Ngày 1 | Môi trường, input, schema và danh sách tool được kiểm tra | Bắt đầu dự án |
| **M1 — Chốt thiết kế và giao diện** | Ngày 2 | Giao diện agent/A2A, luồng evidence và quy tắc MCP thống nhất | M0 hoàn thành |
| **M2 — Xây các module nghiệp vụ** | Ngày 3–4 | Coordinator và các specialist chạy được với kiểm thử độc lập | M1 hoàn thành |
| **M3 — Tích hợp luồng đầu cuối** | Ngày 5–6 | Case đại diện chạy qua toàn bộ workflow | Các module M2 đạt giao diện đã chốt |
| **M4 — Kiểm chứng và sửa lỗi nghiệp vụ** | Ngày 7–8 | Toàn bộ input được xử lý, lỗi trọng yếu được sửa | M3 hoàn thành |
| **M5 — Tối ưu MCP và hoàn thiện tài liệu** | Ngày 9 | Giảm call thừa, chốt cấu hình và tài liệu tái lập | M4 đạt tiêu chí nghiệm thu |
| **M6 — Đóng gói và nộp bài** | Ngày 10 | ZIP hợp lệ, upload thành công, chọn final | M5 hoàn thành |

Luồng phụ thuộc chính:

```text
M0 → M1 → M2 → M3 → M4 → M5 → M6
          │
          ├─ Mai Tiến Huy: Coordinator + Verifier + hỗ trợ MCP
          ├─ Lê Việt Hoàng: Entity + Customer
          ├─ Trịnh Xuân Huy: Order + Product + Shipment
          └─ Hoàng Ngọc Đức: Payment + Refund + Policy + Conflict
```

## 4. M0 — Chuẩn bị môi trường và khảo sát yêu cầu

**Thời gian:** ngày 1. **Chủ trì:** Mai Tiến Huy.

**Mục tiêu:** cả nhóm nắm được cách chạy repo, dữ liệu đầu vào, schema đầu ra và công cụ MCP thực tế.

### Mai Tiến Huy

- [ ] Giữ nguyên tên gốc repo khi fork; thống nhất nhánh làm việc và cách review.
- [ ] Cài Python 3.11 trở lên, tạo môi trường ảo và cài `.[dev]`.
- [ ] Đăng ký team, lưu Team API Key vào cấu hình cục bộ; không commit khóa.
- [ ] Kiểm tra cấu hình Competition API và MCP endpoint.
- [ ] Lấy input L3B đúng release, kiểm tra `case-set.json` và thư mục `inputs/`.
- [ ] Chạy `pytest -q`, `day09 --help`, `day09 validate-inputs` và `day09 mcp-tools`.
- [ ] Ghi nhận lỗi nền hoặc thiếu quyền truy cập trước khi bắt đầu triển khai.

### Lê Việt Hoàng

- [ ] Đọc cấu trúc input; thống kê các loại định danh và thông tin hỗ trợ tìm đơn.
- [ ] Chọn case đại diện có exact order ID, thiếu exact ID và nhiều candidate nếu bộ input có các loại này.
- [ ] Đọc các trường output liên quan đến entity/customer.
- [ ] Xác định tool tra cứu entity/customer từ discovery và ghi lại input cần truyền.

### Trịnh Xuân Huy

- [ ] Đọc các trường output liên quan đến order, sản phẩm và shipment.
- [ ] Khảo sát thông tin thời gian và trạng thái xuất hiện trong input/evidence được phép truy cập.
- [ ] Lập danh sách tình huống cần kiểm tra: giao trễ, chưa giao, hủy đơn và dữ liệu thiếu.
- [ ] Xác định tool order/product/shipment từ discovery.

### Hoàng Ngọc Đức

- [ ] Đọc các trường output liên quan đến payment, refund, policy và conflict.
- [ ] Đọc trọng số, điều kiện loại và giới hạn feedback trong scoring policy công khai.
- [ ] Xác định tool payment/refund/policy từ discovery.
- [ ] Lập danh sách lỗi tài chính cần tránh: tính trùng khoản thu, nhầm trả góp với thu trùng, nhầm yêu cầu hoàn tiền với hoàn tiền đã hoàn tất.

### Sản phẩm bàn giao và nghiệm thu

- [ ] Mỗi thành viên chạy được môi trường và hiểu các lệnh CLI cần dùng.
- [ ] Input chính thức vượt qua `day09 validate-inputs`.
- [ ] Có danh sách tool thực tế và ánh xạ tool sang người phụ trách; không đoán tên tool.
- [ ] Có danh sách case đại diện để dùng ở M3; nếu thiếu một tình huống, dùng fixture kiểm thử cục bộ ở M2.
- [ ] Phân biệt rõ dữ liệu fixture với evidence thật: fixture không được đưa vào submission.

**Bàn giao sang M1:** cấu trúc input/output, năng lực tool, các giới hạn và lỗi môi trường còn tồn tại.

## 5. M1 — Chốt kiến trúc, A2A và quy tắc evidence

**Thời gian:** ngày 2. **Chủ trì:** Mai Tiến Huy; cả nhóm duyệt giao diện.

**Mục tiêu:** bốn người có thể phát triển độc lập mà các module vẫn ghép được với nhau.

### Mai Tiến Huy

- [ ] Thiết kế luồng: nhận case → resolve entity → điều tra chuyên môn → xử lý conflict → verifier → output.
- [ ] Chốt kiểu dữ liệu dùng chung và giao diện gọi specialist.
- [ ] Thiết kế thông điệp A2A nội bộ: bên gửi, bên nhận, nhiệm vụ, `case_id`, mã tương quan, dữ liệu bàn giao và evidence refs.
- [ ] Chốt timeout, giới hạn số vòng bàn giao lại và cách xử lý specialist lỗi.
- [ ] Phân biệt thông điệp A2A nội bộ với trace công khai; chỉ ghi trường/event được schema trace hỗ trợ.
- [ ] Kiểm tra khả năng tái sử dụng gateway/trace hiện có; thiết kế cache và chống gọi trùng trong cùng case.

### Lê Việt Hoàng

- [ ] Chốt kết quả entity resolution: entity được chọn, candidate bị loại, lý do dựa trên dữ kiện và điểm chưa chắc chắn.
- [ ] Chốt điều kiện bàn giao: đủ định danh để điều tra, còn mơ hồ hoặc không tìm thấy.
- [ ] Đề xuất quy tắc xếp hạng candidate; không chọn chỉ vì candidate xuất hiện đầu tiên.
- [ ] Xác định thông tin customer context cần chuyển cho hai nhánh chuyên môn.

### Trịnh Xuân Huy

- [ ] Chốt cấu trúc timeline và cách biểu diễn mốc thời gian bị thiếu.
- [ ] Chốt kết quả nhánh vận chuyển: findings, evidence hỗ trợ, conflict và giới hạn kết luận.
- [ ] Thống nhất dữ liệu nào cần chuyển cho nhánh policy để đánh giá hướng xử lý.

### Hoàng Ngọc Đức

- [ ] Chốt cấu trúc kết quả payment/refund/policy và cách biểu diễn số tiền chưa xác định.
- [ ] Thiết kế bản ghi conflict: vấn đề mâu thuẫn, nguồn liên quan, cách phân xử hoặc trạng thái chưa giải quyết.
- [ ] Đề xuất nguyên tắc ưu tiên nguồn theo policy, phạm vi và thời điểm; không mặc định tool gọi sau luôn đúng hơn.
- [ ] Thống nhất cách dùng mức chắc chắn của từng nhánh để hỗ trợ confidence cuối cùng.

### Giao diện nội bộ tối thiểu đề xuất

| Thành phần | Nội dung |
| --- | --- |
| Phạm vi | `case_id`, định danh nhiệm vụ/thông điệp và entity liên quan |
| Kết quả | Findings có cấu trúc và trạng thái xử lý của agent |
| Bằng chứng | Evidence refs nguyên bản, gắn với từng finding/claim |
| Hạn chế | Dữ liệu thiếu, candidate chưa phân biệt được, conflict còn mở |
| Bàn giao | Thông tin cần cho agent tiếp theo và yêu cầu xác minh bổ sung nếu có |

Đây là giao diện nội bộ, không phải schema output chính thức. Khi triển khai, chỉ dùng các giá trị và field hợp lệ theo contract ở biên xuất kết quả.

### Sản phẩm bàn giao và nghiệm thu

- [ ] Cả bốn người thống nhất chữ ký hàm, kiểu dữ liệu và cách xử lý lỗi.
- [ ] Có sơ đồ luồng và bảng quyền tool theo actor trong bản nháp `ARCHITECTURE.md`.
- [ ] Chốt quy tắc cache theo case/run, retry hữu hạn và điều kiện dừng điều tra.
- [ ] Chốt invariant: đúng entity, đúng evidence scope, không tự tạo ref, không dùng chéo case/run.
- [ ] Chốt cách biểu diễn thiếu bằng chứng theo schema; không tạo câu trả lời giả để pass validate.

**Bàn giao sang M2:** giao diện ổn định và bộ fixture tối thiểu để các module phát triển song song.

## 6. M2 — Triển khai coordinator và các specialist

**Thời gian:** ngày 3–4. **Chủ trì:** mỗi thành viên tự phụ trách module của mình.

**Mục tiêu:** các module thực hiện được trách nhiệm nghiệp vụ và có kiểm thử trước khi tích hợp.

### Mai Tiến Huy — Coordinator, hỗ trợ MCP và Verifier

- [ ] Triển khai khung `solve_case` và trạng thái điều tra riêng cho từng case.
- [ ] Tích hợp tool discovery, kiểm tra response và lưu evidence nhận từ gateway.
- [ ] Triển khai cache theo tool + tham số + phạm vi case/run, bao gồm tránh request trùng khi các nhánh chạy đồng thời.
- [ ] Thiết lập retry chỉ cho lỗi phù hợp, có giới hạn; không retry vô hạn hoặc đổi `case_id` để vượt lỗi.
- [ ] Điều phối specialist dựa trên entity đã resolve và loại khiếu nại; tránh gọi mọi tool cho mọi case.
- [ ] Triển khai verifier ban đầu cho schema, entity scope, claim/evidence linkage và dữ liệu specialist lỗi.
- [ ] Ghi các sự kiện quan sát được như `task_assigned`, `handoff`, `verification_completed` theo contract.
- [ ] Kiểm thử cách ly hai case, cache, retry và timeout bằng gateway giả lập.

### Lê Việt Hoàng — Entity và Customer

- [ ] Triển khai kiểm tra exact order ID khi input cung cấp.
- [ ] Triển khai tìm candidate có phạm vi hẹp và mở rộng có điều kiện khi chưa đủ dữ liệu.
- [ ] Đối chiếu thuộc tính case với candidate: thời gian, sản phẩm, giá trị hoặc thông tin thực tế có sẵn.
- [ ] Xếp hạng/chọn/loại candidate bằng dữ kiện và giữ lại lý do kiểm chứng được.
- [ ] Phân biệt `customer_id` với `customer_unique_id`; không gộp nhầm khách hàng.
- [ ] Lấy customer history khi giúp resolve hoặc bổ sung bối cảnh liên quan.
- [ ] Trả trạng thái mơ hồ nếu chưa đủ căn cứ, tránh chọn đơn tùy tiện.
- [ ] Ghi `tool_result_consumed` khi dùng evidence và bàn giao entity cho coordinator.
- [ ] Kiểm thử exact ID sai, nhiều candidate, không có candidate và cùng khách hàng trên nhiều đơn.

### Trịnh Xuân Huy — Order, Product và Shipment

- [ ] Triển khai đọc thông tin đơn/item/product cần thiết cho khiếu nại.
- [ ] Dựng timeline từ các mốc thực tế được cung cấp, giữ nguyên ý nghĩa múi giờ và dữ liệu thiếu.
- [ ] Đối chiếu ngày giao dự kiến với ngày giao thực tế khi có đủ mốc.
- [ ] Phân tích giao trễ, chưa giao, hủy đơn và các vấn đề sản phẩm được evidence hỗ trợ.
- [ ] Không suy ra giao thiếu/sai hàng chỉ từ trạng thái vận chuyển hoặc lời khai đơn lẻ.
- [ ] Phát hiện conflict giữa trạng thái đơn và thông tin shipment.
- [ ] Bàn giao findings/timeline/conflict kèm evidence cho coordinator và nhánh policy.
- [ ] Kiểm thử đúng hạn, trễ hạn, thiếu ngày giao, hủy đơn và trạng thái mâu thuẫn.

### Hoàng Ngọc Đức — Payment, Refund, Policy và Conflict

- [ ] Triển khai đối chiếu các khoản thanh toán, phương thức và trạng thái được evidence cung cấp.
- [ ] Phân biệt nhiều khoản thanh toán, trả góp và dấu hiệu thu trùng; không kết luận chỉ theo số dòng dữ liệu.
- [ ] Triển khai phân tích refund: yêu cầu, đang xử lý, hoàn tất, một phần/toàn phần theo dữ kiện có sẵn.
- [ ] Đối chiếu số tiền, đơn vị tiền tệ và giao dịch liên quan; dùng cách tính phù hợp với tiền tệ.
- [ ] Tra policy liên quan đến case và xác định điều kiện áp dụng.
- [ ] Đề xuất hành động và số tiền khi đủ căn cứ; ghi rõ điểm còn thiếu khi chưa đủ.
- [ ] Triển khai quy tắc phân xử conflict và lưu trạng thái unresolved khi không thể kết luận.
- [ ] Kiểm thử hoàn tiền một phần, refund đang xử lý, payment nhiều dòng, thiếu policy và nguồn mâu thuẫn.

### Sản phẩm bàn giao và nghiệm thu

- [ ] Các module gọi được qua giao diện M1, không phụ thuộc biến dùng chung giữa các case.
- [ ] Kiểm thử nghiệp vụ của từng người vượt qua; fixture không đi vào luồng nộp bài.
- [ ] Kết quả chuyên môn có evidence linkage và thể hiện rõ phần chưa xác định.
- [ ] Có review chéo theo bảng phân công trước khi merge.
- [ ] Mỗi người cập nhật phần thiết kế của mình trong `ARCHITECTURE.md`.

**Bàn giao sang M3:** module tích hợp được, danh sách kiểm thử đã chạy và các giới hạn đã biết.

## 7. M3 — Tích hợp workflow và trace đầu cuối

**Thời gian:** ngày 5–6. **Chủ trì:** Mai Tiến Huy.

**Mục tiêu:** xử lý một tập case đại diện qua toàn bộ hệ thống bằng evidence thật từ MCP.

### Mai Tiến Huy

- [ ] Ghép các module vào `solve_case`, kiểm soát timeout và giới hạn concurrency.
- [ ] Chạy song song các nhánh độc lập sau khi entity đủ rõ; chờ kết quả cần thiết trước khi chốt policy/action.
- [ ] Tích hợp bước xử lý conflict và verifier trước khi xuất JSON.
- [ ] Ánh xạ kết quả nội bộ sang schema L3B chính thức.
- [ ] Kiểm tra trace phản ánh đúng task assignment, handoff, evidence được dùng và verification thực tế.

### Lê Việt Hoàng

- [ ] Kiểm tra entity bàn giao cho hai nhánh đúng order/customer và đúng case.
- [ ] Kiểm tra customer context không bị bỏ mất hoặc dùng sai phạm vi.
- [ ] Sửa lỗi resolve phát hiện khi chạy thật; kiểm tra nhánh mơ hồ không tiếp tục điều tra trên một order tùy ý.

### Trịnh Xuân Huy

- [ ] Đối chiếu timeline trong output với evidence gốc.
- [ ] Kiểm tra findings giao nhận được chuyển đầy đủ sang policy và verifier.
- [ ] Sửa lỗi mapping trạng thái, thời gian và xử lý đơn nhiều item nếu phát sinh.

### Hoàng Ngọc Đức

- [ ] Đối chiếu kết luận tài chính và policy với findings vận chuyển thực tế.
- [ ] Kiểm tra conflict được chuyển đến đúng agent và không gây vòng lặp bàn giao.
- [ ] Review tính nhất quán giữa kết luận, trách nhiệm, hành động và số tiền nếu schema có các trường này.

### Bộ case đại diện

| Nhóm tình huống | Điều cần chứng minh |
| --- | --- |
| Exact order ID | Đi đúng entity, thu thập evidence phù hợp |
| Thiếu ID hoặc nhiều candidate | Resolve có căn cứ hoặc thể hiện rõ chưa đủ căn cứ |
| Shipment bất thường | Timeline và kết luận giao nhận phù hợp |
| Payment/refund bất thường | Không tính trùng, phân biệt trạng thái giao dịch |
| Source conflict | Mâu thuẫn được nhận diện và xử lý/giữ mở có lý do |
| Lỗi tool hoặc evidence thiếu | Dừng/retry có giới hạn, không tạo bằng chứng giả |

Các tình huống lỗi có thể kiểm thử bằng fixture riêng khi không xuất hiện trong input thật. Không cố tạo lỗi bằng cách làm thay đổi hệ thống bên ngoài.

### Sản phẩm bàn giao và nghiệm thu

- [ ] Tập case đại diện chạy xuyên suốt mà không còn lỗi tích hợp chặn luồng.
- [ ] Output vượt qua validator và được review nghiệp vụ; pass schema chưa đồng nghĩa đúng nghiệp vụ.
- [ ] Evidence ref trong output khớp evidence đã nhận và tiêu thụ của case tương ứng.
- [ ] Trace không ghi handoff hoặc verification chưa xảy ra.
- [ ] Chạy ít nhất hai case trong cùng tiến trình để kiểm tra không rò rỉ cache/context giữa case.

**Bàn giao sang M4:** phiên bản tích hợp, output/trace cùng lần chạy và danh sách vấn đề còn lại.

## 8. M4 — Kiểm chứng toàn bộ input và sửa lỗi nghiệp vụ

**Thời gian:** ngày 7–8. **Chủ trì:** Mai Tiến Huy điều phối; từng người sửa nhánh mình.

**Mục tiêu:** kiểm tra độ đúng trên toàn bộ bộ input, ưu tiên lỗi có thể làm case nhận 0 điểm và lỗi kết luận nghiệp vụ.

### Mai Tiến Huy

- [ ] Chạy toàn bộ input bằng `day09 run`, kiểm tra bằng `day09 validate`.
- [ ] Đối chiếu tập `case_id` cần nộp với output thực tế, tránh thiếu hoặc lẫn output cũ.
- [ ] Tổng hợp bảng lỗi gồm case, biểu hiện, mức ưu tiên, người xử lý và kết quả kiểm tra lại.
- [ ] Rà soát consistency giữa các field và confidence cuối.
- [ ] Kiểm tra phạm vi team/run/case theo metadata và công cụ audit/feedback được cấp; ghi rõ giới hạn nếu local validator không xác minh được phía server.

### Lê Việt Hoàng

- [ ] Review các case thiếu exact ID, nhiều candidate và resolve có confidence cao bất thường.
- [ ] Kiểm tra candidate bị loại có lý do phù hợp, không bỏ qua candidate tốt hơn.
- [ ] Kiểm tra lịch sử khách hàng không bị dùng thay bằng chứng trực tiếp về khiếu nại.
- [ ] Sửa lỗi entity/customer và bổ sung kiểm thử hồi quy cho lỗi thực tế.

### Trịnh Xuân Huy

- [ ] Review các case kết luận giao trễ, chưa giao, hủy đơn hoặc có dữ liệu thời gian thiếu.
- [ ] Kiểm tra kết luận không vượt quá phạm vi evidence shipment/product.
- [ ] Xác minh conflict order/shipment đã xuất hiện trong kết quả xử lý.
- [ ] Sửa lỗi timeline/trạng thái và bổ sung kiểm thử hồi quy.

### Hoàng Ngọc Đức

- [ ] Review các case có refund, nhiều khoản payment, số tiền đề xuất hoặc policy ngoại lệ.
- [ ] Kiểm tra số tiền và hành động nhất quán với trạng thái thanh toán/hoàn tiền.
- [ ] Review conflict chưa giải quyết và cách ảnh hưởng đến confidence.
- [ ] Sửa lỗi payment/policy/conflict và bổ sung kiểm thử hồi quy.

### Thứ tự xử lý lỗi

| Ưu tiên | Loại lỗi | Yêu cầu xử lý |
| --- | --- | --- |
| **P0** | Sai case, output không chấm được, ref tự tạo/không tồn tại, evidence sai phạm vi, thiếu evidence bắt buộc | Chặn nộp bài; xử lý trước |
| **P1** | Sai entity, sai kết luận, tính sai tiền, hành động trái policy, bỏ qua conflict ảnh hưởng quyết định | Sửa trước khi tối ưu call |
| **P2** | Confidence chưa hợp lý, customer context thiếu, trace chưa phản ánh đủ phối hợp | Sửa và kiểm tra lại case liên quan |
| **P3** | Gọi tool trùng, truy vấn rộng không cần thiết, retry thừa, tài liệu thiếu | Xử lý trong M5 sau khi bảo đảm độ đúng |

### Sản phẩm bàn giao và nghiệm thu

- [ ] Có output cho toàn bộ case bắt buộc và tất cả vượt qua schema validation.
- [ ] Không còn lỗi P0/P1 đã phát hiện chưa xử lý.
- [ ] Kiểm thử hồi quy xác nhận các lỗi nghiệp vụ đã sửa.
- [ ] Confidence giảm hợp lý khi entity mơ hồ, thiếu evidence hoặc conflict ảnh hưởng kết luận; không gán cùng một mức cao cho mọi case.
- [ ] Có danh sách hạn chế còn lại và tác động, không tuyên bố điểm số khi chưa có feedback chính thức.

**Bàn giao sang M5:** phiên bản đã kiểm chứng, số liệu call/latency hiện tại và danh sách tối ưu có căn cứ.

## 9. M5 — Tối ưu MCP, hoàn thiện thiết kế và khả năng tái lập

**Thời gian:** ngày 9. **Chủ trì:** Mai Tiến Huy; mỗi người tối ưu nhánh mình.

**Mục tiêu:** giảm chi phí truy vấn không cần thiết mà vẫn giữ bằng chứng đủ mạnh và kết luận đúng.

### Mai Tiến Huy

- [ ] Tổng hợp số call/case, call trùng, retry, cache hit và thời gian xử lý bằng số liệu có thể quan sát.
- [ ] Kiểm tra giới hạn concurrency, timeout và ngân sách truy vấn theo độ phức tạp case.
- [ ] Loại bỏ bước gọi tool không đóng góp cho xác định entity, findings, giải quyết conflict hoặc xác minh kết luận.
- [ ] Chốt cấu hình thực thi và lệnh tái lập; không ghi API key vào tài liệu.
- [ ] Tổng hợp `ARCHITECTURE.md`, bảo đảm mô tả khớp code cuối.

### Lê Việt Hoàng

- [ ] Thu hẹp truy vấn candidate trước khi mở rộng; tránh quét lịch sử không cần thiết.
- [ ] Tận dụng dữ liệu entity/customer đã có trong cùng case.
- [ ] Hoàn thiện phần candidate ranking/rejection, threshold và điều kiện handoff trong tài liệu.

### Trịnh Xuân Huy

- [ ] Tránh đọc lại order/shipment đã có đủ dữ liệu trong cache.
- [ ] Chỉ lấy product/item detail khi liên quan đến khiếu nại hoặc cần phân biệt entity.
- [ ] Hoàn thiện tài liệu timeline, giới hạn suy luận và conflict order/shipment.

### Hoàng Ngọc Đức

- [ ] Chỉ gọi payment/refund/policy cần thiết cho kết luận và điều kiện của case.
- [ ] Loại bỏ tra policy lặp trong cùng case mà không tái dùng evidence chéo case/run.
- [ ] Hoàn thiện quy tắc số tiền, source precedence và unresolved conflict.

### Nội dung bắt buộc rà soát trong `ARCHITECTURE.md`

- [ ] System overview và sơ đồ luồng thực tế.
- [ ] Agent ownership, input/output và quyền gọi tool.
- [ ] Entity resolution, A2A envelope, correlation theo case, timeout và chống vòng lặp.
- [ ] Evidence lifecycle, claim linkage và conflict lifecycle.
- [ ] Failure policy, retry budget, cache strategy và fallback có căn cứ.
- [ ] Verification invariants.
- [ ] Model/config nếu có, dependencies, concurrency, seed nếu có và lệnh tái lập.

### Sản phẩm bàn giao và nghiệm thu

- [ ] Có đối chiếu trước/sau trên cùng nhóm case cho các tối ưu đã áp dụng.
- [ ] Không giảm call bằng cách bỏ evidence bắt buộc hoặc làm suy yếu kết luận.
- [ ] Không còn retry không giới hạn hoặc cache evidence dùng chung giữa các case/run.
- [ ] Kiểm thử liên quan vượt qua sau tối ưu; chỉ chạy lại toàn bộ khi cần xác nhận thay đổi ảnh hưởng rộng.
- [ ] Tài liệu thiết kế hoàn chỉnh, không còn TODO liên quan đến phần đã triển khai.

**Bàn giao sang M6:** phiên bản ứng viên nộp bài, cấu hình đã chốt và checklist nghiệm thu.

## 10. M6 — Chạy bản cuối, đóng gói và nộp bài

**Thời gian:** ngày 10. **Chủ trì:** Mai Tiến Huy; cả nhóm duyệt kết quả cuối.

**Mục tiêu:** tạo gói nộp hợp lệ từ output và trace nhất quán, nộp đúng nơi và chọn đúng phiên bản final.

### Mai Tiến Huy

- [ ] Chốt phiên bản source/config; ghi commit dùng để tạo submission.
- [ ] Chuẩn bị lần chạy cuối với output/trace nhất quán theo cơ chế của CLI, tránh trộn dữ liệu từ các run.
- [ ] Chạy kiểm thử và các lệnh bắt buộc bên dưới; kiểm tra trạng thái thành công.
- [ ] Kiểm tra danh sách file trong ZIP và manifest.
- [ ] Upload `dist/submission.zip` lên `/l3b`, kiểm tra phản hồi và chọn submission final.
- [ ] Ghi lại submission ID, phiên bản code và thời điểm nộp để cả nhóm tra cứu.

### Lê Việt Hoàng

- [ ] Kiểm tra chéo entity/evidence của các case khó trong bản cuối.
- [ ] Đối chiếu tập case trong output với input yêu cầu.
- [ ] Xác nhận không lẫn fixture hoặc ref từ lần chạy thử khác.

### Trịnh Xuân Huy

- [ ] Kiểm tra chéo timeline và findings shipment của các case đã từng có lỗi.
- [ ] Đối chiếu output cuối với trace và evidence liên quan.
- [ ] Kiểm tra tài liệu order/shipment khớp hành vi phiên bản nộp.

### Hoàng Ngọc Đức

- [ ] Kiểm tra chéo số tiền, refund, policy và conflict của các case đã từng có lỗi.
- [ ] Review tính nhất quán của kết luận/action/confidence trong bản cuối.
- [ ] Cùng Mai Tiến Huy kiểm tra ZIP không chứa dữ liệu ngoài danh mục cho phép.

### Lệnh thực hiện

```bash
pytest -q
day09 validate-inputs
day09 run
day09 validate
day09 package --output dist/submission.zip
```

Các lệnh chạy trong môi trường đã cài đặt và cấu hình đúng. Khi cần tùy chọn chọn case/run, kiểm tra `day09 --help` và trợ giúp của subcommand; không giả định CLI hỗ trợ flag chưa được xác minh.

### Nội dung ZIP được phép

```text
manifest.json
trace.jsonl
outputs/<case_id>.json
```

### Điều kiện kết thúc dự án

- [ ] Kiểm thử và validator thành công.
- [ ] Output/trace dùng cho gói nộp thuộc lần chạy phù hợp, không ghép ref từ run khác.
- [ ] ZIP chỉ chứa manifest, trace và output; không có source, input, `.env`, API key hoặc debug log.
- [ ] Workspace xác nhận nhận submission; các lỗi được hệ thống trả về đã được xử lý.
- [ ] Đã chọn đúng submission làm final.
- [ ] Cả bốn thành viên biết submission ID và vị trí lưu phiên bản code/tài liệu tương ứng.

## 11. Quy tắc phối hợp hằng ngày

### Cập nhật tiến độ

Mỗi ngày dành khoảng 10–15 phút để mỗi người báo cáo: việc đã hoàn thành có bằng chứng, việc tiếp theo và vướng mắc cần ai hỗ trợ. Không dùng trạng thái “xong” nếu chưa có sản phẩm bàn giao và kiểm tra phù hợp.

Nếu vướng mắc ảnh hưởng giao diện chung hoặc chặn thành viên khác, báo ngay cho Mai Tiến Huy và người nhận bàn giao. Khi MCP không truy cập được, tiếp tục phần thiết kế/kiểm thử bằng fixture; vẫn phải kiểm tra MCP thật trước khi nghiệm thu các mốc phụ thuộc evidence thật.

### Quyền sở hữu code đề xuất

| Phạm vi | Người phụ trách |
| --- | --- |
| `src/student_agent/workflow.py`, verifier, hỗ trợ gateway và giao diện dùng chung | Mai Tiến Huy |
| `src/student_agent/agents/entity_customer.py` nếu tách module | Lê Việt Hoàng |
| `src/student_agent/agents/order_shipment.py` nếu tách module | Trịnh Xuân Huy |
| `src/student_agent/agents/payment_policy.py` và conflict logic nếu tách module | Hoàng Ngọc Đức |
| Kiểm thử từng module | Người viết module; người review kiểm tra chất lượng |
| `ARCHITECTURE.md` | Cả nhóm đóng góp; Mai Tiến Huy tổng hợp |

Thống nhất việc sửa file dùng chung trước khi thay đổi để tránh xung đột. Không đổi schema công khai để hợp thức hóa output sai. Không cần tạo dịch vụ A2A riêng chỉ để tăng số thành phần; chọn cách triển khai đáp ứng contract và thể hiện được sự phối hợp thực tế.

### Checklist trước khi merge

- [ ] Phạm vi thay đổi rõ ràng, đúng trách nhiệm module.
- [ ] Kiểm thử phù hợp đã chạy; bug fix có kiểm thử hồi quy khi cần.
- [ ] Không hardcode đáp án theo case ID hoặc đưa dữ liệu fixture vào submission.
- [ ] Tool được discovery, tham số đúng và `case_id` được truyền xuyên suốt.
- [ ] Evidence refs nguyên bản, claim được gắn bằng chứng phù hợp.
- [ ] Trace chỉ phản ánh hoạt động quan sát được, không ghi suy luận riêng hoặc bí mật.
- [ ] Có ít nhất một người review; tài liệu được cập nhật khi thiết kế thay đổi.

## 12. Theo dõi chất lượng theo tiêu chí chấm điểm

| Tiêu chí | Trọng số công khai | Người dẫn dắt | Cách kiểm tra trong nhóm |
| --- | ---: | --- | --- |
| Semantic | 40% | Cả nhóm theo nhánh nghiệp vụ | Review case khó và kiểm thử các quy tắc nghiệp vụ |
| Evidence | 15% | Cả nhóm; Lê Việt Hoàng kiểm tra scope entity | Kiểm tra evidence hỗ trợ từng kết luận và đáp ứng yêu cầu case |
| Provenance | 15% | Mai Tiến Huy | Đối chiếu gateway result, ref và phạm vi team/run/case; dùng audit được cấp |
| Consistency | 10% | Mai Tiến Huy, Hoàng Ngọc Đức | Kiểm tra entity, timeline, số tiền, action và conflict nhất quán |
| Schema | 5% | Mai Tiến Huy | Validator chính thức trong repo |
| Calibration | 5% | Cả nhóm; Mai Tiến Huy tổng hợp | Review confidence ở case rõ, mơ hồ, thiếu evidence và có conflict |
| Workflow | 5% | Mai Tiến Huy, các chủ agent | Trace thể hiện task assignment, handoff, consumption và verification thực tế |
| Efficiency | 5% | Cả nhóm | Đo call/case, call trùng, retry, cache và truy vấn không cần thiết |

Số liệu tự kiểm tra dùng để cải thiện chất lượng; không thay thế kết quả scorer chính thức. Ưu tiên loại bỏ lỗi khiến case nhận 0 điểm, sau đó cải thiện độ đúng và bằng chứng, rồi tối ưu efficiency.

## 13. Bảng cập nhật tiến độ nhóm

Điền ngày thực tế và liên kết PR/commit hoặc kết quả kiểm tra khi thực hiện. Các ô chưa có bằng chứng được giữ ở trạng thái chưa bắt đầu hoặc đang làm.

| Milestone | Trạng thái | Ngày hoàn thành thực tế | Bằng chứng nghiệm thu | Vướng mắc/người xử lý |
| --- | --- | --- | --- | --- |
| M0 | Chưa bắt đầu | — | — | — |
| M1 | Chưa bắt đầu | — | — | — |
| M2 | Chưa bắt đầu | — | — | — |
| M3 | Chưa bắt đầu | — | — | — |
| M4 | Chưa bắt đầu | — | — | — |
| M5 | Chưa bắt đầu | — | — | — |
| M6 | Chưa bắt đầu | — | — | — |

Mẫu theo dõi đầu việc phát sinh:

| Mã việc | Milestone | Nội dung | Người thực hiện | Người review | Trạng thái | Bằng chứng/PR |
| --- | --- | --- | --- | --- | --- | --- |
| Mx-01 | Mx | Điền đầu việc cụ thể | Họ tên | Họ tên | Chưa bắt đầu / Đang làm / Chờ review / Hoàn thành / Bị chặn | Liên kết hoặc kết quả kiểm tra |
