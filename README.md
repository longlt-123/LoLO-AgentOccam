# Nhóm 3 người chạy AgentOccam với Qwen3-14B trên Vast.ai

Hướng dẫn cho Windows 11 + PowerShell, Docker shopping chạy local và một GPU RTX 3090 24 GB thuê trên Vast.ai. Model dùng trong hướng dẫn: `Qwen/Qwen3-14B-AWQ`, phục vụ bằng vLLM qua API tương thích OpenAI.

Lệnh vLLM bên dưới đã được người dùng chạy và log báo `Application startup complete`. README tổng hợp quy trình; không khẳng định toàn bộ benchmark đã chạy thành công.

## 0. Thiết lập cho nhóm ba người

Bản này dùng chung một instance GPU: một người quản lý vLLM, ba người có thể SSH và mở tunnel riêng. Thực hiện phần này trước bước thuê instance bên dưới.

### Tạo Team và mời thành viên

- Mỗi người có tài khoản Vast riêng.
- Người phụ trách bấm tên/email ở Context Switcher → Create Team; đặt tên nhóm.
- Chuyển một phần credit cá nhân vào Team khi tạo hoặc thực hiện sau trong Billing.
- Vào Members → Invite, nhập email và vai trò; hai thành viên nhận lời mời qua email.
- Trước khi thuê máy, chuyển Context Switcher sang Team. Các thành viên cũng chọn Team để xem tài nguyên chung.

Team có tài nguyên và số dư riêng với tài khoản cá nhân. Không mặc định instance đang thuê cá nhân tự chuyển vào Team sau khi tạo nhóm. Với máy đang chạy, kiểm tra khả năng chuyển với Vast support; chưa cần Destroy máy hiện tại. Nếu cần cộng tác ngay, chủ máy có thể cấp SSH bằng public key riêng của từng người trên instance hiện có, nhưng việc này không chuyển quyền sở hữu/billing vào Team.

### Phân quyền

| Người | Vai trò đề xuất | Công việc |
|---|---|---|
| Người phụ trách | Owner | Thanh toán, thuê máy, chạy/dừng model |
| Hai thành viên | Member | Xem và tương tác với instance, chạy thử nghiệm |

Member mặc định còn có quyền tạo instance. Nếu muốn chỉ một người được thuê máy, Owner cần xem và cấu hình Custom Role trong Members → Roles; không coi Member là quyền chỉ đọc. Manager có quyền rộng gần Owner, chỉ cần khi muốn người khác cùng quản trị.

### Mỗi người dùng SSH key riêng

Từng người thực hiện mục 3 trên laptop của mình, thêm public key vào tài khoản Vast cá nhân. Theo Teams Quickstart, instance non-VM hỗ trợ key từ tài khoản cá nhân của thành viên hoặc thêm trực tiếp vào instance. Với VM, key cần được thêm trước khi tạo VM. Nếu gặp Permission denied, kiểm tra key và đúng instance/context.

Không gửi private key cho nhau. Cả ba dùng host/port chung của instance nhưng dùng private key của chính mình.

### Cùng dùng model

- Chỉ một người cài môi trường và chạy một tiến trình vLLM theo mục 4–5.
- Mỗi người mở tunnel theo mục 6 trên laptop riêng. Cả ba đều dùng cổng local 18000 được vì chúng nằm trên ba máy khác nhau.
- Mỗi người cấu hình OPENAI_BASE_URL và API key vLLM theo mục 8; chia sẻ key qua kênh riêng, không ghi vào repo.
- Mỗi laptop tự chạy AgentOccam và Docker shopping theo hướng dẫn local. Team trên Vast không tự đồng bộ website hoặc trajectory giữa các laptop.
- Không chạy ba bản vLLM cùng model trên GPU 24 GB. Với max-num-seqs=1, các request đồng thời phải chờ; nên chia lịch chạy benchmark trước khi tối ưu concurrency.
- Mỗi người dùng tên thư mục output khác nhau khi gom kết quả. Nếu dùng chung một shopping backend, tránh các task thay đổi trạng thái chạy đồng thời làm nhiễu đánh giá.
- SSH cùng tài khoản root nghĩa là cùng quyền trên filesystem và tiến trình; Team role trên web không tạo ba Linux user độc lập. Thống nhất một người quản lý server, không Ctrl+C phiên model của nhau.

Tài liệu: [Teams Quickstart](https://docs.vast.ai/guides/teams/teams-quickstart), [Teams Overview](https://docs.vast.ai/guides/teams/teams-overview), [Teams Roles](https://docs.vast.ai/guides/teams/teams-roles).

## 1. Kiến trúc và quy ước

| Thành phần | Chạy ở đâu | Vai trò |
|---|---|---|
| Docker shopping | Windows / Docker Desktop | Website benchmark |
| AgentOccam + Playwright | Windows, venv dự án | Đọc trang, tạo prompt, thực hiện action và lưu kết quả |
| Qwen3-14B-AWQ + vLLM | Máy Vast | Nhận prompt và sinh câu trả lời |
| SSH tunnel | PowerShell trên Windows | Chuyển cổng local 18000 tới cổng 8000 của Vast |

AgentOccam gửi văn bản qua tunnel; model không cần truy cập trực tiếp website shopping. Không cần đưa Docker shopping lên Vast.

Các giá trị cần thay:

- `SSH_HOST`, `SSH_PORT`: lấy từ nút Connect/SSH trên Vast; không mặc định port 22.
- `YOUR_RANDOM_SECRET`: mật khẩu API tự đặt, dùng giống nhau ở server và client. Không phải token Hugging Face hay API key quản lý Vast.
- `D:\INT3011E`: thư mục dự án Windows trong setup này; đổi nếu bạn đặt nơi khác.

Lệnh `powershell` chạy trên Windows. Lệnh `bash` chạy trong terminal Linux của Vast. Không copy dấu nhắc như `PS ...>` hoặc `/workspace$` vào lệnh.

## 2. Thuê instance Vast.ai

1. Đăng nhập [Vast.ai Console](https://console.vast.ai/), nạp số dư để chạy thử.
2. Chọn template **PyTorch có SSH**, ví dụ **PyTorch (cuDNN Devel)**; chọn launch mode SSH hoặc Jupyter + SSH.
3. Chọn offer theo cấu hình khởi đầu sau.
4. Xem tổng giá thuê, disk và mạng trên offer rồi bấm Rent.
5. Đợi instance sẵn sàng, lấy thông tin kết nối qua Connect.

| Mục | Cấu hình đề xuất |
|---|---|
| GPU | 1 × RTX 3090, 24 GB VRAM |
| RAM hệ thống | Từ 32 GB |
| CPU | Khoảng 4–8 vCPU trở lên |
| Disk | Khoảng 60 GB cho model và môi trường |
| Kiểu thuê | On-demand cho lần thử đầu |
| Host | Ưu tiên Verified, reliability cao, mạng tải xuống tốt |

Đây là cấu hình khởi đầu, không phải bảo đảm mọi độ dài prompt đều vừa VRAM. Giá thay đổi theo offer. Không cần mở cổng API 8000 ra Internet khi dùng tunnel.

## 3. Tạo SSH key trên Windows

Chỉ tạo nếu chưa có key này. Nếu chương trình hỏi ghi đè key cũ, không ghi đè key đang sử dụng.

```powershell
New-Item -ItemType Directory -Force "$HOME\.ssh"
ssh-keygen -t ed25519 -f "$HOME\.ssh\vast_ed25519"
Get-Content "$HOME\.ssh\vast_ed25519.pub"
```

Copy toàn bộ một dòng public key, từ `ssh-ed25519` đến phần tên máy cuối dòng, vào SSH Keys trên Vast và lưu.

- `vast_ed25519.pub`: public key, thêm lên Vast.
- `vast_ed25519`: private key, giữ trên Windows; không đưa vào Git.

Kết nối:

```powershell
ssh -i "$HOME\.ssh\vast_ed25519" `
  -p SSH_PORT `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  root@SSH_HOST
```

Dùng đúng username trong lệnh Connect nếu khác `root`. Kiểm tra host fingerprint khi kết nối lần đầu.

## 4. Tạo môi trường vLLM trên Vast — chỉ lần đầu

Kiểm tra GPU và Python:

```bash
nvidia-smi
python3 --version
```

Tạo venv riêng trên Vast; không cài vLLM vào venv Windows:

```bash
mkdir -p /workspace
cd /workspace
python3 -m venv /workspace/vllm-env
source /workspace/vllm-env/bin/activate
python -m pip install --upgrade pip
python -m pip install vllm
```

Nếu thiếu `venv` hoặc `tmux`, trên template Ubuntu/Debian có quyền root:

```bash
apt-get update
apt-get install -y python3-venv tmux
```

Sau đó chạy lại bước còn thiếu. Phiên bản Python, CUDA và NVIDIA driver phải phù hợp bản vLLM cài đặt. Nếu môi trường hiện tại đã chạy thành công, không cần cài lại hoặc nâng cấp.

Ghi lại phiên bản để tái lập benchmark:

```bash
python -m pip show vllm torch transformers
python -m pip freeze > /workspace/vllm-requirements-lock.txt
```

### Hugging Face token — tùy chọn

Model công khai có thể tải không cần token. Cảnh báo `unauthenticated requests to the HF Hub` không tự nó có nghĩa tải thất bại.

Để thêm token, tạo token Read tại [Hugging Face Tokens](https://huggingface.co/settings/tokens), rồi nhập trong terminal sẽ khởi chạy vLLM:

```bash
read -rsp "Hugging Face token: " HF_TOKEN
export HF_TOKEN
echo
```

Token không hiện khi gõ. Biến này chỉ được tiến trình khởi chạy sau đó kế thừa; không tác động ngược lên lần tải đang chạy.

## 5. Chạy model trong tmux trên Vast

Tạo phiên:

```bash
tmux new -s model
```

Nếu đã có phiên, dùng `tmux attach -t model` thay vì tạo lại. Trong phiên tmux:

```bash
source /workspace/vllm-env/bin/activate
export HF_HOME=/workspace/hf-cache

vllm serve Qwen/Qwen3-14B-AWQ \
  --served-model-name qwen3-14b \
  --host 127.0.0.1 \
  --port 8000 \
  --dtype half \
  --max-model-len 16384 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.90 \
  --api-key YOUR_RANDOM_SECRET
```

Thay `YOUR_RANDOM_SECRET` trước khi chạy. Lần đầu model được tải về cache; lần sau dùng lại cache còn trên instance.

| Tham số | Ý nghĩa |
|---|---|
| `--served-model-name qwen3-14b` | Tên client gửi trong request, cũng là tên trong YAML |
| `--host 127.0.0.1` | Chỉ lắng nghe trong máy Vast; truy cập qua tunnel |
| `--port 8000` | Cổng vLLM trên Vast |
| `--max-model-len 16384` | Ngân sách tổng token đầu vào và đầu ra |
| `--max-num-seqs 1` | Tối đa một sequence xử lý đồng thời trong cấu hình này |
| `--gpu-memory-utilization 0.90` | Ngân sách bộ nhớ GPU cho vLLM |

Đợi dòng:

```text
Application startup complete.
```

Server lúc này chờ request; terminal không quay về dấu nhắc là bình thường.

- Rời tmux nhưng giữ server: **Ctrl+B**, thả tay, rồi **D**.
- Quay lại: `tmux attach -t model`.
- Xem phiên: `tmux ls`.
- Dừng server có chủ ý: vào phiên và **Ctrl+C**.

`tmux` giúp khi mất SSH; không giữ tiến trình qua Stop/Restart instance. Nếu template đã có tmux riêng, có thể dùng phiên đó, tránh lồng thêm phiên không cần thiết.

## 6. Mở SSH tunnel — Windows, cửa sổ riêng

```powershell
ssh -i "$HOME\.ssh\vast_ed25519" `
  -p SSH_PORT `
  -N `
  -L 18000:127.0.0.1:8000 `
  -o ExitOnForwardFailure=yes `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  root@SSH_HOST
```

Giữ cửa sổ mở. Không có output sau khi kết nối là bình thường.

`127.0.0.1:18000` trên Windows được chuyển tới `127.0.0.1:8000` trên Vast. Nếu tunnel đóng, AgentOccam mất kết nối dù model vẫn chạy trong tmux.

## 7. Chuẩn bị AgentOccam — Windows

### Dùng lại môi trường đang chạy được

```powershell
cd D:\INT3011E
.\.venv\Scripts\Activate.ps1
cd .\AgentOccam
```

Không tạo lại venv nếu bạn đã chạy WebArena thành công.

### Chỉ khi cài mới môi trường local

Ví dụ với Python 3.10 đã cài và hai thư mục repo sẵn có:

```powershell
cd D:\INT3011E
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

cd .\webarena
python -m pip install -r requirements.txt
python -m pip install -e .

cd ..\AgentOccam
python -m pip install -r requirements.txt
python -m pip install openai pyyaml playwright
python -m playwright install chromium
python -m pip check
```

Đây là trình tự cài cơ bản, không phải lockfile đã kiểm chứng cho mọi revision. Nếu `pip check` báo xung đột, xử lý theo phiên bản requirements của repo; không nâng cấp hàng loạt thư viện trong môi trường đang chạy tốt. Setup benchmark, task JSON, URL và đăng nhập shopping vẫn phải được hoàn thành như lần chạy local trước.

## 8. Bật shopping và cấu hình endpoint

Khởi động Docker Desktop, rồi trong terminal chạy AgentOccam:

```powershell
docker start shopping
curl.exe -I http://localhost:7770
```

Dùng tên container/cổng thực tế nếu khác ví dụ. Task `start_url`, cấu hình shopping và URL Magento phải nhất quán với setup local đã chạy được.

Đặt biến môi trường trong chính terminal chạy eval:

```powershell
$env:OPENAI_API_KEY = "YOUR_RANDOM_SECRET"
$env:OPENAI_BASE_URL = "http://127.0.0.1:18000/v1"
Remove-Item Env:AZURE_ENDPOINT -ErrorAction SilentlyContinue
```

Key trùng `--api-key` trên Vast. Không đặt URL theo dạng Markdown `[url](url)`. Mở PowerShell mới phải đặt lại biến. Giữ các biến môi trường WebArena cần thiết từ setup local; hai biến trên chỉ cấu hình LLM.

Trong `gpt.py` đã gửi, nhánh text gọi `OpenAI()`, tự đọc hai biến chuẩn này. Vì vậy **không cần sửa endpoint trong gpt.py để gọi text qua Vast**. Các biến `VAST_LLM_*` không được file gốc tự đọc.

## 9. Test kết nối và sinh câu trả lời

### Kiểm tra danh sách model

```powershell
python -c "from openai import OpenAI; print(OpenAI().models.list())"
```

Kết quả cần có `qwen3-14b`. Bước này xác nhận kết nối và tên model, chưa xác nhận inference.

### Test inference ngắn, không tạo file

```powershell
@'
from openai import OpenAI

client = OpenAI(timeout=180.0, max_retries=1)
response = client.chat.completions.create(
    model="qwen3-14b",
    messages=[{"role": "user", "content": "Reply with exactly: Connection successful"}],
    max_tokens=128,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
print(response.choices[0].message.content)
print(response.usage)
'@ | python -
```

Thư viện OpenAI ở đây chỉ là client; request gửi tới Vast theo `OPENAI_BASE_URL`. Không cần OpenAI API key thật cho request này.

## 10. Cấu hình và chạy AgentOccam

Dùng YAML shopping hiện có:

```text
AgentOccam/configs/AgentOccam_shopping_qwen.yml
```

Đổi các trường model của agent muốn dùng Qwen thành giá trị sau, giữ đúng cấu trúc và thụt lề YAML:

```yaml
model: qwen3-14b
```

Đây là một trường cần sửa, không phải nội dung đầy đủ để ghi đè YAML. Tên phải trùng `--served-model-name`; dùng chữ thường vì code dò chuỗi `qwen` có phân biệt hoa/thường.

File `AgentOccam.py` đã gửi có mapping sau; giữ nguyên, không thêm trùng:

```python
MODEL_FAMILIES.append("qwen")
CALL_MODEL_MAP["qwen"] = call_gpt
CALL_MODEL_WITH_MESSAGES_FUNCTION_MAP["qwen"] = call_gpt_with_messages
ARRANGE_MESSAGE_FOR_MODEL_MAP["qwen"] = arrange_message_for_gpt
```

Chạy từ `D:\INT3011E\AgentOccam`:

```powershell
python eval_webarena.py --config AgentOccam/configs/AgentOccam_shopping_qwen.yml
```

Lệnh này dùng tập task được YAML/script chọn, không tự giới hạn một task. Sau khi smoke test ổn mới mở rộng 60 task. Với WebChoreArena, dùng entrypoint và YAML tương ứng của repo; không mặc định đổi tên script là đủ.

Quan sát các mốc:

1. Website mở và observation được tạo.
2. vLLM nhận request chat completion.
3. Agent sinh action hợp lệ, browser thực hiện action.
4. Task kết thúc, evaluator chạy và log/summary được lưu.

Đường dẫn output phụ thuộc cấu hình; xem dòng `Saved log to ...`. Không coi task đã được chấm hợp lệ nếu evaluator phát sinh lỗi API.

## 11. Các giới hạn cần biết trước benchmark

### Nhánh ảnh trong gpt.py

File gốc có nhánh gửi ảnh bằng `requests.post` trực tiếp tới `https://api.openai.com/v1/chat/completions`, hardcode `gpt-4-turbo`. Nhánh đó **không dùng OPENAI_BASE_URL**. Qwen3-14B-AWQ ở đây là model text: không đưa ảnh vào prompt. Lưu screenshot cho log không đồng nghĩa gửi screenshot vào LLM.

### Thinking và độ dài output

Lệnh vLLM cơ bản ở mục 5 chưa tắt thinking. Request test ở mục 9 chỉ tắt thinking cho chính request test; nó không thay đổi các request AgentOccam sau đó.

Nếu muốn tắt thinking cho AgentOccam, thêm vào các lời gọi `client.chat.completions.create(...)` tương ứng trong `gpt.py`:

```python
max_tokens=2048,
extra_body={"chat_template_kwargs": {"enable_thinking": False}},
```

Đây là thay đổi tùy chọn để kiểm soát sinh nội dung, không cần cho việc đổi endpoint. Kiểm tra output có bị cắt (`finish_reason == "length"`) trước khi đưa vào parser. Giữ cùng thiết lập thinking, sampling và context khi so sánh các lần benchmark.

### Evaluator có thể gọi model khác

Đổi model agent trong YAML không tự đổi model chấm điểm. Nếu gặp:

```text
The model `gpt-4-1106-preview` does not exist.
```

hãy tìm nơi hardcode model trong mã đang dùng (nếu có ripgrep):

```powershell
rg -n 'gpt-4-1106-preview|call_claude|OpenAI\(' . ..\webarena -g '*.py'
```

Hoặc dùng Find in Files của VS Code. Kiểm tra evaluator/config tương ứng trước khi sửa. Nếu chuyển judge sang Qwen thì phải ghi rõ đã đổi evaluator; điểm số không còn mặc nhiên tương đương benchmark với judge gốc. Không đổi alias server thành tên GPT để che lỗi.

Trong `AgentOccam.py` còn có lời gọi trực tiếp `call_claude(...)` cho viết lại objective; nếu luồng đó được dùng, hai biến OpenAI không chuyển nó sang Qwen.

## 12. Khởi chạy lại những lần sau

Không cần cài lại thư viện hoặc tải lại model nếu instance và cache còn nguyên.

1. Kiểm tra instance hoạt động; lấy lại SSH host/port hiện tại từ Connect.
2. SSH vào Vast, chạy `tmux ls` và attach phiên model nếu còn.
3. Nếu vLLM đã dừng, activate venv và chạy lại lệnh mục 5; không chạy thêm bản thứ hai khi server cũ còn chiếm GPU/cổng.
4. Mở tunnel ở PowerShell riêng theo mục 6.
5. Mở terminal AgentOccam: activate venv, bật Docker shopping, đặt lại biến môi trường.
6. Test `/v1/models`, rồi chạy lệnh eval mục 10.

Nếu instance được restart, các tiến trình và biến môi trường shell trước đó không còn; cần khởi chạy lại. Nếu Destroy, môi trường và cache trên instance bị xóa.

## 13. Xử lý lỗi thường gặp

| Lỗi/hiện tượng | Cách kiểm tra và xử lý |
|---|---|
| `Connection ... closed by remote host` | Kiểm tra trạng thái Vast, SSH lại; dùng keepalive và tmux. Nếu tunnel ngắt phải mở lại tunnel. |
| Terminal dừng ở `Application startup complete` | Bình thường: server đang chờ request. |
| HF Hub unauthenticated warning | Nếu vẫn tải thì chờ; token Read là tùy chọn cho model công khai. |
| `Connection refused` / API connection error | Kiểm tra tunnel, cổng local 18000, server Vast 8000 và tiến trình vLLM. |
| `401 Unauthorized` | So sánh OPENAI_API_KEY với --api-key; không dùng token HF thay thế. |
| `Address already in use` | Cổng đã có tiến trình; kiểm tra server/tunnel cũ trước khi chạy thêm. |
| Model `qwen3-14b` not found | Xem `models.list()` và tên --served-model-name; kiểm tra YAML. |
| Model GPT khác not found | Tìm model hardcode ở evaluator hoặc helper; không chỉ sửa YAML agent. |
| CUDA out of memory | Xem `nvidia-smi`, loại trừ server chạy trùng; thử context 8192 thay 16384 rồi kiểm tra prompt có vừa không. |
| Prompt quá dài / context exceeded | Rút gọn observation/history hoặc điều chỉnh context nếu VRAM cho phép; giảm context không giải quyết prompt dài. |
| Screenshot/Playwright timeout | Đây là bước browser trên Windows; kiểm tra website và tải hệ thống local riêng với API Vast. |
| `Permission denied (publickey)` | Kiểm tra username, port, public key đã thêm và private key dùng với -i. |
| `Bad permissions` cho SSH key/config | Sửa quyền file SSH trên Windows; đây không phải lỗi model. |

Để xem tài nguyên trên Vast:

```bash
nvidia-smi
free -h
df -h /workspace
```

## 14. Kết thúc phiên và chi phí

- Đóng SSH/tunnel hoặc dừng vLLM không đồng nghĩa dừng thuê GPU.
- **Stop instance** khi muốn tạm dừng compute và giữ dữ liệu; vẫn có phí lưu trữ. Khởi động lại phụ thuộc GPU có sẵn.
- **Destroy instance** khi không dùng tiếp: xóa dữ liệu instance. Tải các file cần giữ trước khi Destroy.
- Trajectory AgentOccam chạy trên Windows thường được lưu ở Windows theo cấu hình; kiểm tra output thực tế.

## 15. Checklist trước khi chạy 60 task

- [ ] vLLM sẵn sàng và SSH tunnel còn mở.
- [ ] Test inference trả được văn bản.
- [ ] YAML dùng đúng `qwen3-14b`, các task/URL shopping đúng.
- [ ] Agent chỉ gửi text; không rơi vào nhánh ảnh hardcode OpenAI.
- [ ] Không còn lời gọi model phụ ngoài dự kiến.
- [ ] Evaluator hoạt động; lỗi chấm điểm không bị tính nhầm thành agent thất bại.
- [ ] Đã kiểm tra 1–2 task và log được lưu.
- [ ] Ghi lại model, quantization, phiên bản vLLM, thinking, context và các thay đổi evaluator.

## Tài liệu tham khảo

- [Vast.ai — quản lý instance, Stop và Destroy](https://docs.vast.ai/guides/instances/manage-instances)
- [Vast.ai — thiết lập template](https://docs.vast.ai/guides/templates/template-settings)
- [Qwen3-14B-AWQ — model card](https://huggingface.co/Qwen/Qwen3-14B-AWQ)
- [vLLM — GPU installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- [vLLM — serve CLI](https://docs.vllm.ai/en/latest/cli/serve/)
- [vLLM — reasoning outputs](https://docs.vllm.ai/en/latest/features/reasoning_outputs/)

Tổng hợp ngày 16/10/2026 theo setup và mã nguồn đã cung cấp. README không chứa private SSH key, HF token hay API secret thực tế.
