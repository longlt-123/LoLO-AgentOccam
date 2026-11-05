# Chạy so sánh ba phiên bản dừng

Ba config nằm trong `AgentOccam/configs/`, tính từ thư mục chạy `D:\INT3011E\AgentOccam`:

| Phiên bản | File config | `agent.stop_guard.mode` |
| --- | --- | --- |
| Baseline | `AgentOccam_shopping_qwen_baseline.yml` | `baseline` |
| Prompt-only | `AgentOccam_shopping_qwen_prompt_only.yml` | `prompt_only` |
| Evidence-gated stop | `AgentOccam_shopping_qwen_evidence_gated.yml` | `evidence_gated` |

Cả ba dùng `qwen3-14b`, cùng danh sách và thứ tự task (tại ngày 06/11/2026 đặt `[47, 49]` để thử;
danh sách 60 task đầy đủ nằm trong comment của config),
cùng history, tắt critic/judge, và ngân sách 15 bước theo cấu hình hiện tại. Chúng chỉ khác `mode` và
`logname` (cả cấp ngoài lẫn `agent.others.logname`) để tránh trộn file kết quả.

## Khác biệt thực sự giữa ba phiên bản

| Thành phần | Baseline | Prompt-only | Evidence-gated |
| --- | --- | --- | --- |
| Prompt AgentOccam gốc | Có | Có | Có |
| Hướng dẫn bổ sung về bằng chứng | Không | Có | Giống hệt Prompt-only |
| Bộ nhớ bằng chứng `StopGuard` | Không khởi tạo | Không khởi tạo | Có |
| Coverage/feedback trong input actor | Không | Không | Có, với task được hỗ trợ |
| Đọc thêm metadata sắp xếp từ DOM | Không | Không | Có |
| Chặn `stop` | Không | Không | Có, khi thiếu bằng chứng |

Baseline ở đây là hành vi AgentOccam trước khi thêm cơ chế chống premature stopping.
Đặc biệt, nó giữ nguyên lời nhắc bước cuối gốc: "Wrap up your observations and
return your answer with `stop [answer]` to maximize the reward." Hai phiên bản còn
lại dùng cùng hướng dẫn mới, kể cả lời nhắc không đoán khi hết ngân sách.

Prompt chung nằm trong `AgentOccam/stop_policy.py` (`EVIDENCE_GUIDANCE`). Chỉnh nó
sẽ tác động giống nhau lên Prompt-only và Evidence-gated. Prompt này hướng dẫn
thu thập đủ bằng chứng, không ép agent đọc hết mọi trang khi đã có witness đủ.

Mode mới được ưu tiên sử dụng trong ba config. Config cũ không có `mode` vẫn được
đọc: `enabled: true` tương ứng Evidence-gated, `enabled: false` tương ứng Baseline.
Nếu khai báo cả `mode` và `enabled` mâu thuẫn, chương trình báo lỗi để tránh chạy
nhầm phiên bản. `requirement: auto` chỉ dùng cho guard của Evidence-gated.

Cả ba config lưu cùng `order_history_sort`, đã xác minh từ mã nguồn container
Shopping tại `http://localhost:7770`; chỉ Evidence-gated sử dụng nó. Quy tắc này
cho phép chứng minh đã bao phủ khoảng ngày mà không cần đọc hết các trang khi
giao diện không có `aria-sort`. Xem [nguồn xác minh](shopping_order_sort.md).
Baseline/Prompt-only không đọc hay đưa quy tắc này vào prompt. JSON kết quả lưu
`stop_guard_config` để audit biết quy tắc nào được cấu hình; điều này không thay
đổi hành vi của hai phiên bản không có guard.

`max_steps` cấp ngoài quyết định ngân sách môi trường. Khi bắt đầu task, agent
đồng bộ ngân sách actor với `env.max_steps`, tránh môi trường dừng ở bước 15 nhưng
actor vẫn được nhắc rằng có 20 bước. Khi đổi ngân sách thí nghiệm, đổi giống nhau
trong cả ba config.

## Cách chạy trên PowerShell

Dùng cùng môi trường WebArena, tài khoản đăng nhập, endpoint Qwen và biến môi
trường mà bạn dùng với config Shopping trước đây. Các lệnh dưới không tự cài đặt
dịch vụ hay reset database.

Đặt thư mục làm việc:

```powershell
Set-Location D:\INT3011E\AgentOccam
```

Chạy Baseline:

```powershell
..\.venv\Scripts\python.exe eval_webarena.py --config AgentOccam/configs/AgentOccam_shopping_qwen_baseline.yml
```

Đưa website về cùng trạng thái ban đầu nếu lượt trước làm thay đổi dữ liệu, rồi chạy Prompt-only:

```powershell
..\.venv\Scripts\python.exe eval_webarena.py --config AgentOccam/configs/AgentOccam_shopping_qwen_prompt_only.yml
```

Khôi phục cùng trạng thái ban đầu trước Evidence-gated:

```powershell
..\.venv\Scripts\python.exe eval_webarena.py --config AgentOccam/configs/AgentOccam_shopping_qwen_evidence_gated.yml
```

Nên chạy từng phiên bản tuần tự: các task dùng chung tài khoản/dữ liệu website.
`env.reset()` hiện chỉ mở lại môi trường với task config, không chứng minh database
đã trở về snapshot ban đầu. Với task có hành động sửa dữ liệu, dùng quy trình reset
WebArena của bạn để bảo đảm cả ba phiên bản có cùng điều kiện bắt đầu.

Để thử nhanh trước khi chạy đủ 60 task, sửa **cả ba** file thành:

```yaml
env:
  # Giữ các thuộc tính env khác.
  task_ids: [47]
```

Sau khi thử, đổi `logname` trước lần đo chính thức. Runner sẽ bỏ qua một task nếu
file `<task_id>.json` của nó đã tồn tại trong thư mục kết quả. Không trộn lần thử
và lần đo chính thức trong cùng thư mục, kể cả khi cấu hình đã đổi.

## Kết quả và chỉ số so sánh

Kết quả mặc định nằm ở:

```text
D:\INT3011E\AgentOccam-Trajectories\
  AgentOccam_Qwen14bShopping_baseline\
  AgentOccam_Qwen14bShopping_prompt_only\
  AgentOccam_Qwen14bShopping_evidence_gated\
```

Mỗi thư mục có config đã dùng, `<task_id>.json`, `<task_id>-trash.txt` và
`summary.csv`. Các trường dùng để so sánh:

| Trường | Ý nghĩa |
| --- | --- |
| `success` | Điểm thành công 0/1 từ evaluator |
| `num_actions` | Số lượt môi trường; lượt chặn stop cũng tiêu thụ ngân sách |
| `task_seconds` | Thời gian chạy task, gồm khởi tạo môi trường và gọi model |
| `stop_mode` | Phiên bản thực sự đã chạy |
| `stop_guard_rejections` | Số lần guard chặn stop; bằng 0 ở Baseline/Prompt-only |

Ví dụ tổng hợp khi **cả ba đã hoàn thành cùng danh sách task**, chạy từ `D:\INT3011E\AgentOccam`:

```powershell
foreach ($variant in @('baseline', 'prompt_only', 'evidence_gated')) {
    $rows = @(Import-Csv "../AgentOccam-Trajectories/AgentOccam_Qwen14bShopping_$variant/summary.csv")
    [pscustomobject]@{
        Variant = $variant
        Tasks = $rows.Count
        SuccessRate = ($rows | Measure-Object -Property success -Average).Average
        MeanSteps = ($rows | Measure-Object -Property num_actions -Average).Average
        MeanSeconds = ($rows | Measure-Object -Property task_seconds -Average).Average
        RejectedStops = ($rows | Measure-Object -Property stop_guard_rejections -Sum).Sum
    }
}
```

Nếu một phiên bản bị gián đoạn, chạy tiếp bằng chính config đó, hoặc chỉ so sánh
giao của các `task_id` đã hoàn thành. Cùng số lượng dòng chưa chắc cùng tập task.
Để đo nhiều lần, đổi cả `logname` và `agent.others.logname` sang tên tương ứng như
`AgentOccam_Qwen14bShopping_baseline_run2` trong mỗi config, và reset môi trường
giống nhau. Seed Python hiện là 42, nhưng runner không bảo đảm seed của model hoặc
suy luận LLM hoàn toàn xác định.

## Phạm vi của kết quả

Prompt bổ sung được áp dụng cho mọi task của hai phiên bản có prompt. Guard hiện
chỉ kiểm tra các yêu cầu đọc lịch sử đơn hàng Magento Shopping được hỗ trợ. Do đó
nên báo cáo cả kết quả toàn bộ 60 task và nhóm task được guard hỗ trợ; không suy
diễn rằng guard đã kiểm tra mọi loại task Shopping.

Số lần chặn không phải số đáp án sai đã được sửa: một đáp án được evaluator chấm
đúng vẫn có thể thiếu bằng chứng. Đọc trajectory và các trường `stop_guard`,
`proposed_action` để phân tích quá trình. Có thể dùng `scripts/audit_stop_guard.py`
để kiểm tra bằng chứng offline trên log của cả ba phiên bản; audit là đánh giá
theo cùng rule, không phải nhãn đúng/sai độc lập hay một lần chạy lại model.

## Kiểm thử code trước khi chạy model

Từ `D:\INT3011E\AgentOccam`:

```powershell
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Kiểm thử xác nhận prompt của Prompt-only/Evidence-gated giống nhau, Baseline giữ
prompt gốc, hai phiên bản không có guard không thu thập coverage/không chặn stop,
và các config dùng cùng thiết lập thử nghiệm. Đây là kiểm thử offline; không thay
thế chạy thực tế trên Qwen và browser.

## Phân biệt guard chặn stop và lỗi browser

Khi guard từ chối kết thúc, console in `[StopGuard] Rejected proposal: ...` cùng
phần bằng chứng còn thiếu. Bước tương ứng hiện `<no browser action>`; đây là lượt
bị chặn, không phải click bị lỗi.

Khi `stop` được chấp nhận, wrapper ghi đáp án, đặt trạng thái kết thúc và gọi
evaluator ngay trên trạng thái hiện có; không gọi browser step hoặc chụp screenshot
mới cho lệnh `stop`. Vì vậy timeout screenshot không làm mất quyết định kết thúc
và khiến actor phải sinh thêm một câu trả lời. Evaluator có thể gọi LLM để chấm
đáp án (ví dụ in `judgement: correct`); đó là bước chấm điểm, không phải lượt actor
tiếp tục duyệt website. Sửa luồng kết thúc này áp dụng chung cho cả ba phiên bản.

Lỗi browser như phản hồi CDP thiếu `value` được in kèm traceback. Wrapper thử lấy
lại observation một lần, **không thực hiện lại action** vì thao tác có thể đã thành
công trước khi bước đọc trang lỗi. Các command còn lại trong batch bị bỏ qua vì
có thể chứa ID cũ. `last_action_error` được ghi vào trajectory và chuyển cho actor.
Nếu refresh cũng thất bại, task dừng với `termination_reason=observation_refresh_failed`,
`success=0`; không tiếp tục dùng DOM cũ hoặc biến lỗi browser thành đáp án suy đoán.

Sau khi sửa code, khởi động lại lượt chạy để Python nạp bản mới. Dùng `logname` mới
cho lượt đo sau sửa để không trộn với các task đã chạy bằng phiên bản browser cũ.
