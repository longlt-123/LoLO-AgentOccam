# Kiểm tra bằng chứng trước khi `stop`

`StopGuard` chặn kết luận sớm cho các truy vấn **lịch sử đơn hàng Magento Shopping**.
Không gọi thêm LLM. Module đọc objective, URL, observation của trình duyệt và quy
tắc sắp xếp của bản cài đặt nếu được khai báo rõ trong config sau khi xác minh mã
nguồn; không dùng đáp án chuẩn, reward, suy luận hay ghi chú của model làm bằng chứng.

## Ba thành phần

1. **Theo dõi phạm vi:** lưu riêng các hàng đơn hàng đã nhìn thấy và vị trí của chúng
   trong `Items 1 to 10 of 37 total`. Bộ nhớ này tồn tại qua các bước, không bị mất
   khi actor rút gọn history hoặc prune plan. URL trang và thao tác click không chứng
   minh đã đọc trang đó. Đọc lại một trang không tăng độ bao phủ.
2. **Điều kiện kết thúc:** `stop_requirements.py` đọc loại yêu cầu, số kết quả cần
   tìm, trạng thái và khoảng ngày. `check()` cho phép dừng khi đủ bằng chứng cho yêu
   cầu đó; không mặc định phải đọc hết mọi trang. Điều kiện chưa hiểu được không
   được bỏ qua để tạo một quy tắc dừng sớm rộng hơn yêu cầu thực tế.
3. **Chặn thực thi:** sau khi judge chọn action, trước `finalize_action()` và
   `env.step()`. Nếu thiếu bằng chứng, thay action bằng chuỗi rỗng, đưa phản hồi vào
   input lượt sau và giữ đề xuất gốc trong trajectory. Batch chứa navigation rồi
   `stop` cũng bị chặn: phải quan sát kết quả navigation trước khi kết luận.

| Loại yêu cầu | Bằng chứng tối thiểu |
| --- | --- |
| Hỏi có đơn phù hợp hay không (`existence`) | Trả lời Có: một đơn khớp **tất cả** điều kiện; trả lời Không: đủ phạm vi liên quan |
| Tìm N đơn (`sample`) | Đã thấy đủ N mã đơn khác nhau khớp điều kiện, và câu trả lời liệt kê các mã đó |
| Đếm, tổng, trung bình, số tiền đã chi | Đủ lịch sử, hoặc đã chứng minh bao phủ trọn khoảng ngày được hỏi |
| Liệt kê toàn bộ | Đủ lịch sử, hoặc đủ khoảng ngày được hỏi |
| Đơn mới nhất/đầu tiên | Đọc liên tục từ vị trí 1 đến đơn đầu tiên phù hợp, với thứ tự ngày được giao diện hoặc mã nguồn của bản cài đặt xác nhận |
| Cao nhất/thấp nhất khác | Đủ mọi hàng; chưa có shortcut cho sắp xếp theo giá |
| Tra cứu thuộc tính của mã đơn cụ thể | Đã nhìn thấy mã đó trong bảng Orders; câu trả lời không phủ định |
| Không có, bằng 0, không tìm thấy | Đủ phạm vi liên quan, hoặc trang lịch sử hiển thị rõ `You have placed no orders.` |
| Truy vấn đơn hàng khác chưa nhận dạng được | Yêu cầu đủ mọi hàng một cách bảo thủ |

Ví dụ được parser hiểu:

```text
Do I have any fulfilled orders in January 2023?
Find 3 pending orders
Show me one completed order
What is the status of order 000000170?
What is the status of my latest order?
How much did I spend on orders in January 2023?
List all orders from 2023-01-01 to 2023-01-31
Today is 6/12/2023. Tell me how many fulfilled orders I have over the past month, and the total amount of money I spent.
Today is 2023-06-12. Find 3 pending orders in the past two weeks
```

`fulfilled`/`completed` được ánh xạ sang `Complete` cho bộ Shopping này;
`cancelled` tương đương `Canceled`. Trạng thái và ngày phải khớp trên **cùng một
đơn**, không ghép trạng thái của đơn A với ngày của đơn B. Mẫu tìm N đơn cần trả
mã đơn để kiểm tra kết quả thực sự là những đơn đã quan sát, không chỉ nói "đã tìm đủ".

Parser dùng mẫu câu tiếng Anh có giới hạn, không phải một mô hình hiểu ngôn ngữ
tổng quát. Các điều kiện chưa hỗ trợ như "containing food", "over $100", nhiều
yêu cầu ghép tùy ý hoặc ngày tương đối thiếu mốc tham chiếu không được phép dùng
shortcut. Các nhánh không hiểu đầy đủ vẫn dùng quy tắc coverage cũ. Riêng câu đếm
đơn **và** tính tổng chi tiêu trong cùng một kỳ được hiểu là một phạm vi aggregate.

### Ngày tương đối theo objective

Parser nhận tiền tố `Today is DATE.` làm mốc tham chiếu, **không dùng đồng hồ của
máy đang chạy**. Với các mẫu đã hỗ trợ, `over/in/during the past [N] days/weeks/months/years`
được chuyển thành khoảng ngày bao gồm hai đầu. Không có N thì dùng 1; N nhận số
hoặc các từ số từ one đến ten. Ngày/tuần trừ theo số ngày; tháng/năm trừ theo lịch,
giữ ngày trong tháng và chặn ở cuối tháng đích nếu cần, ví dụ 31/03/2024 trừ một
tháng thành 29/02/2024. Ngày số trong objective theo quy ước Mỹ.

Vì vậy `Today is 6/12/2023` + `past month` thành **2023-05-12 → 2023-06-12**,
không phải toàn bộ tháng 5. Ngày mốc sai hoặc thiếu, khoảng vượt giới hạn và điều
kiện bổ sung không hiểu được đều không được dùng để dừng sớm.

### Khi nào khoảng ngày đã được bao phủ?

`env.py` chỉ cung cấp metadata `order_history_sort` khi bảng DOM
`table#my-orders-table` có đúng một tiêu đề đang sắp xếp, tên `Date`, với
`aria-sort="ascending"` hoặc `"descending"`.

Nếu giao diện không có metadata này, có thể dùng `agent.stop_guard.order_history_sort`
để khai báo thứ tự mặc định đã xác minh từ mã nguồn **đúng bản cài đặt**. Config
Shopping đi kèm dùng nguồn `magento_history_source`: container `shopping_final_0712`
tại `http://localhost:7770` gọi `setOrder('created_at', 'desc')` cho lịch sử đơn.
Chi tiết mã nguồn, hash và cách kiểm tra nằm trong [ghi nhận xác minh](shopping_order_sort.md).
Đây là thông tin cấu trúc của website, không phải đáp án hoặc dữ liệu đơn chưa đọc.

Quy tắc này chỉ áp dụng cho đúng origin và đường dẫn `/sales/order/history/`, với
query chỉ gồm tham số phân trang/kích thước trang. Query sort tắt fallback; query
filter chưa hỗ trợ không được tính coverage. Metadata DOM có mặt được ưu tiên hơn
config. Không có cả metadata DOM lẫn quy tắc bản cài đặt thì shortcut ngày vẫn tắt.
Guard không tin tham số sort trên URL, ghi chú của model, hay việc vài ngày trên
trang đầu trông có vẻ giảm dần. Hai nhánh tìm một/đủ N kết quả không cần thứ tự ngày.

Với sắp xếp giảm dần và yêu cầu tháng 1/2023, đọc liên tục từ item 1 đến một đơn
**trước 01/01/2023** chứng minh các đơn chưa đọc đều ở ngoài tháng 1. Khi đó có thể
dừng dù chưa đọc hết các trang. Đơn ngày 01/01 vẫn chưa đủ vì có thể còn các đơn
cùng ngày trên trang kế. Với sắp xếp tăng dần, phải đọc qua ngày cuối của khoảng.
Các trang đóng góp phải có cùng thứ tự sắp xếp đáng tin cậy, không bị thiếu vị trí,
và ngày thực tế phải nhất quán với thứ tự được khai báo. Metadata DOM được thu
qua observation dạng dict trong cấu hình `env.prune: true`; quy tắc bản cài đặt
cũng dùng được với observation dạng text đã lưu.

Trong observation lịch sử của task 47 đã lưu làm fixture kiểm thử (bước 2 của
lượt chạy cũ): bảng đã đọc từ item 1 xuống ngày 09/02/2023, trước
mốc 12/05/2023. Đơn duy nhất trong kỳ là ngày 17/05 nhưng `Canceled`, nên không có
đơn `Complete` phù hợp. Với thứ tự giảm dần đã xác minh, phạm vi cần xét đã đầy đủ
dù mới đọc 10/37 đơn: guard cho phép `stop [0 fulfilled orders, $0.00 total spent]`.
Các lượt chạy khác có thể ở trang khác tại bước 2. Nếu URL là `/customer/account/`
với Recent Orders, adapter hiện chưa có bằng chứng coverage lịch sử và vẫn chặn.

Phạm vi được phân biệt theo origin, đường dẫn và query, bỏ riêng `p`, `page`,
`limit`, `page_size`. Các thứ tự sắp xếp khác nhau không được gộp vị trí. Nếu tổng
số bản ghi thay đổi hoặc bản ghi đổi vị trí, coverage cũ bị hủy. Đổi kích thước trang
vẫn có thể hoàn tất phạm vi, ví dụ hiển thị cả 37 đơn trên một trang.

Một trang chỉ được tính khi số hàng **thực sự đọc được** khớp khoảng item được
hiển thị. Observation bị cắt, không có metadata, hoặc hàng trùng không chứng minh
phạm vi đầy đủ. `Recent Orders` và thông báo rỗng ở sidebar không phải lịch sử đầy đủ.

## Cấu hình

Để so sánh Baseline, Prompt-only và Evidence-gated bằng ba config riêng, xem
[hướng dẫn chạy thí nghiệm](stop_ablation.md). `agent.stop_guard.mode` nhận
`baseline`, `prompt_only`, `evidence_gated`; các giá trị `enabled` dưới đây là
cách cấu hình cũ vẫn được hỗ trợ. Prompt-only không khởi tạo guard.

Mặc định bật cho site `shopping` với objective tiếng Anh có `order`, `purchase` hoặc `spent`, trừ
các tác vụ sửa dữ liệu như cancel/place/update. Cấu hình Shopping đã bật rõ:

```yaml
agent:
  stop_guard:
    enabled: true
    requirement: auto
    # Tùy chọn; chỉ khai báo sau khi xác minh đúng bản cài đặt.
    order_history_sort:
      origin: "http://localhost:7770"
      direction: "descending"
      source: "magento_history_source"
      reference: "shopping_final_0712:Magento/Sales/Block/Order/History.php:sha256=9bc70887666e2fde89d40a7f380835410bd2ec13e68b2f19a8697dea2de9c418"
```

`requirement` có thể là `auto`, `aggregate`, `enumeration`, `comparison`, `lookup`,
`existence`, `sample`. Với `auto`, ưu tiên parser điều kiện cụ thể, sau đó mới đến
heuristic từ khóa cũ. Override khác loại parser nhận diện không tự tạo điều kiện
witness; ví dụ ép `aggregate` cho câu "Find 3 orders" vẫn yêu cầu coverage.
Giá trị khác báo lỗi. Override này chọn quy tắc, không mở rộng site/schema hỗ trợ.
Đặt `enabled: false` để chạy đối chứng không có guard. Khi so sánh, dùng logname
khác cho mỗi lần chạy vì evaluator bỏ qua task đã có file kết quả.

Lượt từ chối vẫn tiêu thụ một bước thông qua `env.step("")`; không có browser action
được thực thi. Giới hạn `max_steps` hiện có vẫn áp dụng. Nếu hết ngân sách trong
lượt bị từ chối, kết quả là `success=0`, `reward=0`,
`termination_reason=insufficient_evidence_budget_exhausted`; không thông qua đáp án
đoán chỉ vì đã thử nhiều lần. Phản hồi đi thẳng vào input actor, kể cả khi critic tắt.

Trajectory ghi `action` thực thi, `proposed_action` bị chặn và `stop_guard` chứa
quyết định, loại yêu cầu, `requirement` đã parse (gồm khoảng ngày/mốc tham chiếu),
coverage, phản hồi và số lần từ chối. Với task ngoài phạm vi, quyết định ghi
`reason=unsupported_task`, không ngụ ý đáp án đã được kiểm chứng.

Các quyết định cho phép dừng sớm ghi `reason=matching_witness`,
`requested_matches_found`, `observed_target_order`, `ordered_first_match` hoặc
`requested_date_range_covered`, kèm mã đơn/phạm vi làm bằng chứng. Metadata sắp xếp
được lưu trong trajectory; `stop_guard_config` cấp ngoài ghi lại quy tắc bản cài
đặt để script audit có thể replay. Bằng chứng khoảng ngày có `matching_order_ids`
và `sort_sources` chỉ rõ nguồn thứ tự đã dùng. Phản hồi từ chối cũ được xóa khi có
bằng chứng mới, tránh tiếp tục yêu cầu đọc lại những phần đã đủ.

## Kiểm thử và kiểm tra trajectory cũ

Chạy từ thư mục gốc `D:\INT3011E` (không cần browser, API key hay LLM):

```powershell
.venv/Scripts/python.exe -m unittest discover -s AgentOccam/tests -v
.venv/Scripts/python.exe AgentOccam/scripts/audit_stop_guard.py AgentOccam-Trajectories/AgentOccam_Qwen14bShopping_evidence_gated/47.json --config AgentOccam/AgentOccam/configs/AgentOccam_shopping_qwen_evidence_gated.yml
```

Script audit cũng nhận thư mục chứa nhiều trajectory. Đây là replay quan sát đã
lưu, không chạy lại agent và không chứng minh agent sẽ tự sửa được sau phản hồi.
Mặc định dùng `stop_guard_config` đã ghi trong JSON. Với log cũ thiếu quy tắc sắp
xếp và không có metadata DOM, truyền `--config` để kiểm tra lại theo quy tắc đã
xác minh của bản cài đặt. Với observation lịch sử trong fixture task 47, đề xuất
được chấp nhận với `reason=requested_date_range_covered`. Không truyền quy tắc thì
vẫn chặn vì chưa có bằng chứng về thứ tự các trang chưa đọc. Audit không sửa
trajectory, reward hoặc `summary.csv` của lượt chạy cũ.

## Giới hạn có chủ đích

- Adapter hiện đọc bảng concise `Orders` tại `/sales/order/history/` và thông báo
  phân trang của Magento. Site khác, tác vụ thay đổi dữ liệu và schema DOM khác
  cần adapter/rule riêng. Heuristic phân loại objective hiện dành cho tiếng Anh.
- Chưa xác minh ngữ nghĩa bộ lọc ngày/trạng thái. Query có tham số filter chưa hỗ
  trợ không được tính; hãy đọc lịch sử không lọc hoặc hiển thị tất cả đơn. Không
  lấy một kết quả lọc bất kỳ làm bằng chứng cho toàn bộ yêu cầu.
- Guard kiểm tra độ bao phủ và các witness phù hợp trong những mẫu câu đã hỗ trợ;
  chưa kiểm chứng mọi phép cộng hay mọi phát biểu trong câu trả lời. Nhánh đầy đủ
  lịch sử vẫn là kiểm tra coverage, không phải bộ chấm đáp án. Mapping `fulfilled`
  sang `Complete` là quy ước của adapter Shopping, không dùng cho mọi website.
- Khoảng ngày hỗ trợ tháng có tên tiếng Anh và năm, `from DATE to DATE`, hoặc
  `past [N] days/weeks/months/years` với tiền tố `Today is DATE.`. Khoảng bao gồm
  hai đầu; ngày dạng số dùng `MM/DD/YY`, `MM/DD/YYYY` hoặc ISO `YYYY-MM-DD`. Những
  mẫu tương đối khác và ngôn ngữ khác chưa có shortcut.
- Không phát hiện được mọi thay đổi âm thầm của dữ liệu giữa hai lần đọc. Bằng
  chứng sắp xếp đến từ khai báo của website hoặc quy tắc mã nguồn đã xác minh;
  nếu website khai báo sai hoặc bản cài đặt thay đổi, guard không thể kiểm chứng
  các hàng chưa đọc. Hash trong config dùng để truy vết, không tự kiểm tra container
  ở mỗi bước; cần xác minh lại hoặc bỏ cấu hình này khi đổi website/mã nguồn.
- Các hàng đã đọc được gửi lại cho actor để tránh quên khi history rút gọn; với
  lịch sử rất lớn cần thêm cơ chế tổng hợp dữ liệu và giới hạn context.
