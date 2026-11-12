# File cây quyết định của từng task

Khi chạy `eval_webarena.py` với `logging: True`, mỗi task hoàn tất sẽ tự sinh
`<task_id>-decision-tree.txt` trong cùng thư mục với JSON và trash:

```text
AgentOccam-Trajectories/<logname>/
  47.json
  47-trash.txt
  47-decision-tree.txt
  summary.csv
```

Không cần bật thêm tùy chọn hoặc cài thư viện. File dùng UTF-8, mở trực tiếp bằng
VS Code hoặc trình soạn thảo văn bản.

File gồm mục tiêu, model, kết quả cuối cùng và hai phần:

- `PLAN TREE`: cây kế hoạch thật của actor, giữ cả nhánh bị prune. `ACTIVE` là
  kế hoạch đang hoạt động cuối task, `VISIBLE` là nút còn hiển thị, `PRUNED` là
  nhánh bị ẩn. Mỗi nút có bước tạo, URL, ghi chú và lý do quay lại nếu có.
- `DECISIONS`: các bước theo thứ tự chạy, bắt đầu từ 0 giống log của actor.
  Mỗi bước gồm URL, kế hoạch sau quyết định, tóm tắt quan sát, lý do, hành động
  được chọn, kết quả và quyết định Stop Guard nếu có. Khi judge nhận nhiều ứng
  viên, các đề xuất của actor cũng được hiển thị. `Environment action` ghi lệnh
  thực thi thay thế nếu có, ví dụ `prune` dẫn tới `goto`.

Ví dụ rút gọn của một lượt stop bị chặn:

```text
Task decisions
+-- Step 0
|   +-- Reason: Open the order history.
|   `-- Selected action: click [1756]
`-- Step 1
    +-- Proposed action: stop [0 fulfilled orders, $0.00 spent]
    +-- Stop Guard: REJECTED
    |   `-- Reason: insufficient_evidence
    `-- Selected action: (none; empty environment step)
```

Lịch sử quyết định được giữ riêng theo thứ tự thời gian vì `prune` có thể gom
lịch sử về nút cha và ID kế hoạch có thể được dùng lại. Một đề xuất stop bị chặn
vẫn xuất hiện, nhưng không được ghi thành hành động đã thực thi. Nếu task không
dùng `branch`, cây kế hoạch có thể chỉ có nút gốc; các bước vẫn có đầy đủ trong
`DECISIONS`.

Việc xuất file không gọi thêm model và không thay đổi hành vi agent. Agent không
có cây kế hoạch vẫn xuất được lịch sử quyết định từ trajectory. Task đã có JSON
và bị runner bỏ qua sẽ không tự sinh lại file; task bị exception trước khi ghi
JSON cũng chưa có báo cáo này.
