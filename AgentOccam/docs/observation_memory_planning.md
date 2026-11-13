# Các đoạn code xử lý quan sát, bộ nhớ và kế hoạch

Phạm vi: luồng AgentOccam chạy WebArena với accessibility tree và cấu hình Qwen chỉ gửi text. Đường dẫn bên dưới tính từ thư mục `AgentOccam/` của repository; số dòng là vị trí tại thời điểm viết, tên hàm dùng để tìm lại khi code thay đổi.

```text
Trang web → accessibility tree → đơn giản hóa → CURRENT OBSERVATION
LLM xuất OBSERVATION HIGHLIGHT → trích cây con → lưu theo bước → INTERACTION HISTORY
LLM xuất branch / prune → cập nhật cây kế hoạch → PREVIOUS PLANS
Ba phần trên → ghép prompt → gửi LLM ở lần gọi tiếp theo
```

## 1. Quan sát và đơn giản hóa trang

| Vị trí | Chức năng |
| --- | --- |
| `eval_webarena.py` — chỗ tạo `WebArenaEnvironmentWrapper` | Chọn `observation_type="accessibility_tree"` cho luồng đánh giá. |
| `browser_env/processors.py:723` — `fetch_page_accessibility_tree()` | Gọi `Accessibility.getFullAXTree` lấy cây từ trình duyệt, loại node trùng ID. |
| `browser_env/processors.py:59, 826` — `TreeNode`, `parse_accessibility_tree()` | Tạo cây Python gồm ID, role, name, properties, parent, children; bỏ qua một số node rỗng. |
| `AgentOccam/obs_opt.py:388` — `prune_tree()` | Làm sạch ký tự/thuộc tính, bỏ text trùng và một số node ảnh, gộp text/menu/list, định dạng bảng và heading. Đây là xử lý bằng quy tắc; tham số `objective` hiện không được dùng trong thân hàm. |
| `AgentOccam/obs_opt.py:367` — `translate_node_to_str()` | Duyệt node được giữ, chuyển thành văn bản thụt dòng theo cây; lấy tối đa 1.000 dòng. Chế độ `concise` giữ ID cho các role tương tác và ẩn ID của nhiều role còn lại. |
| `AgentOccam/env.py:94` — `observation()` | Khi `env.prune=True`, gọi đơn giản hóa và trả về `{"text": ..., "image": ..., "node": ...}`. `text` phục vụ prompt, `node` phục vụ xử lý highlight. |

Nhánh HTML riêng nằm ở `browser_env/processors.py:983`: `fetch_page_html()` → `parse_my_html()` → `HtmlParser.parse_tree()`. Luồng đánh giá nói trên dùng accessibility tree, dù một số biến mang tên `DOM`.

## 2. Bộ nhớ theo phần tử từ OBSERVATION HIGHLIGHT

| Vị trí | Chức năng |
| --- | --- |
| `AgentOccam/prompts/output_specifications/observation_highlight.txt:1` | Yêu cầu LLM xuất ID phần tử quan trọng, phân cách bằng dấu phẩy, ví dụ `1321, 52, 756`. |
| `AgentOccam/AgentOccam.py:139` — `parse_elements()` | Tách các trường như ACTION và OBSERVATION HIGHLIGHT từ câu trả lời của LLM. |
| `AgentOccam/AgentOccam.py:870` — `get_observation_highlight()` | Tìm node theo ID; chọn node và hậu duệ, tổ tiên, cùng các node anh em có tên. Chỉ giữ cây highlight nếu có ít hơn 30 node; nếu không, đặt thành `None`. |
| `AgentOccam/obs_opt.py:373` — `construct_new_DOM_with_visible_nodes()` | Sao chép các node `visible=True` thành cây độc lập, giữ quan hệ cha–con. |
| `AgentOccam/AgentOccam.py:1451` — đoạn lưu lịch sử trong `act()` | Lưu cây highlight, ID liên quan hành động và observation summary vào `previous_interactions` theo từng bước. Summary lấy từ OBSERVATION DESCRIPTION của LLM. |
| `AgentOccam/AgentOccam.py:204` — `del_observation_node()` | Chuyển cây quan sát cũ thành `node_str`, rồi bỏ cấu trúc cây đầy đủ; cây highlight đã sao chép được giữ riêng. |
| `AgentOccam/AgentOccam.py:464` — `get_interaction_history()` | Chọn lịch sử theo `active_node.steps_taken`; dùng highlight dưới 200 từ hoặc summary thay thế, rồi tạo INTERACTION HISTORY. Nếu quan sát giống hiện tại, có thể dùng câu tham chiếu CURRENT OBSERVATION. |

Đây là **cây nhớ riêng cho từng bước**, không phải một cây hợp nhất tất cả trang. Với `interaction_history.step_num: 3` và `verbose: True`, ba bước gần nhất trong lịch sử được chọn dùng nội dung chi tiết; các bước cũ hơn dùng summary.

Lưu ý: hàm lịch sử đang gọi `mode="name_only"`, nên tham số `retained_ids` truyền kèm không làm ID xuất hiện trong chuỗi. Chế độ `name_retained_id_only` mới dùng tham số này.

## 3. Vì sao bật/tắt visible?

`visible` là cờ chọn node trong cây Python, không làm phần tử trên trang web ẩn/hiện.

- Khi đơn giản hóa: đánh dấu node bị loại bằng `False`, rồi dựng cây chỉ chứa node được giữ.
- Khi tạo highlight: tắt toàn bộ → bật phần cần nhớ → sao chép cây highlight → bật lại cây quan sát nguồn để các bước sau còn đọc được đầy đủ.
- Code khôi phục bằng cách bật tất cả, không lưu trạng thái cũ từng node. Cách này dựa trên đầu vào đã là cây chỉ chứa các node được giữ sau đơn giản hóa.

## 4. Cây kế hoạch

| Vị trí | Chức năng |
| --- | --- |
| `AgentOccam/AgentOccam.py:215` — `PlanTreeNode` | Lưu ID, nội dung kế hoạch, độ sâu, URL, bước tạo, cha/con, ghi chú, lý do quay lại và `steps_taken`. |
| `AgentOccam/AgentOccam.py:1339` — `init_actor()` | Tạo kế hoạch gốc ID 0 từ mục tiêu nhiệm vụ. |
| `AgentOccam/prompts/planning_specifications/branch.txt` và `prune.txt` | Quy định cú pháp `branch [parent_plan_id] [new_subplan_intent]` và `prune [resume_plan_id] [reason]` cho LLM. |
| `AgentOccam/AgentOccam.py:655, 697` — `parse_plan()`, `planning()` | Phân tích lệnh, tìm node theo ID và gọi thao tác tương ứng; hành động thông thường được ghi vào `active_node.steps_taken`. |
| `AgentOccam/AgentOccam.py:692` — `branch_planning()` | Tạo kế hoạch con, nối vào cha và chuyển kế hoạch hoạt động sang node mới. |
| `AgentOccam/AgentOccam.py:668` — `prune_planning()` | Ẩn nhánh, kích hoạt lại node đích, gom lịch sử từ cây con, lưu lý do quay lại và trả lệnh `goto` về URL đã lưu. |
| `AgentOccam/AgentOccam.py:443` — `get_previous_plans()` | Chuyển các node kế hoạch hiển thị thành văn bản thụt dòng, đánh dấu Active Plan, bổ sung ghi chú/lý do quay lại để đưa vào PREVIOUS PLANS. |

LLM quyết định nội dung và thời điểm `branch`/`prune`; Python cập nhật cây. File `*-decision-tree.txt` là báo cáo do `AgentOccam/decision_tree.py:91` tạo, không phải file được đọc lại để làm prompt.

## 5. Ghép prompt và gửi LLM

| Vị trí | Chức năng |
| --- | --- |
| `AgentOccam/AgentOccam.py:538` — `get_online_input()` | Ghép mục tiêu, PREVIOUS PLANS, INTERACTION HISTORY và CURRENT OBSERVATION theo danh sách `config.input`. |
| `AgentOccam/AgentOccam.py:588` — `get_actor_instruction()` | Ghép quy định đầu ra, lệnh kế hoạch và lệnh điều hướng thành system instruction. |
| `AgentOccam/AgentOccam.py:918` — `Actor.predict_action()` | Gọi hai hàm trên, đóng gói message rồi gọi `call_model_with_message()`. |
| `AgentOccam/llms/gpt.py:120` — `arrange_message_for_gpt()` | Chuyển các mục text/image thành message API. Qwen cũng dùng bộ đóng gói này. |

## 6. Vì sao observation có image nhưng LLM chỉ nhận text?

- `browser_env/processors.py:1132` — `ObservationHandler.get_observation()` hiện tạo `image` bằng `np.zeros`: ảnh đen giả để giữ cấu trúc và kích thước dữ liệu, không gọi image processor để lấy screenshot tại đây.
- `AgentOccam/AgentOccam.py:566` chỉ thêm ảnh hiện tại vào prompt nếu `"image" in self.config.current_observation.type`.
- `AgentOccam/AgentOccam.py:513` chỉ thêm ảnh lịch sử nếu `"image" in interaction_history_config.type`.
- `AgentOccam/configs/AgentOccam_shopping_qwen_baseline.yml:33` đặt cả hai loại thành `["text"]`, nên ảnh không được gửi cho LLM.
- `browser_env/envs.py:291` — `modify_page()` vẫn có thao tác chụp ảnh raw/marked ở môi trường. Chỉ gửi text cho LLM không đồng nghĩa tắt mọi thao tác screenshot.
