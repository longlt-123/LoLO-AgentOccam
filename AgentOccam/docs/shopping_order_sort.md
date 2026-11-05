# Nguồn thứ tự ngày của lịch sử đơn Shopping

Đã kiểm tra trực tiếp ngày 2026-11-05, bằng thao tác chỉ đọc trên container
`shopping`, image hiển thị `shopping_final_0712`, ánh xạ cổng `7770 → 80`.

File trong container:

```text
/var/www/magento2/vendor/magento/module-sales/Block/Order/History.php
```

Trong `getOrders()`, collection của khách hàng được tạo và lọc theo trạng thái
hiển thị ở frontend, sau đó gọi:

```php
->setOrder('created_at', 'desc');
```

Trong `_prepareLayout()`, pager dùng chính collection này qua
`$pager->setCollection($this->getOrders())`, rồi load collection. Thứ tự mặc định
áp dụng cho toàn bộ collection trước khi phân trang, nên các trang tiếp theo chứa
các đơn cũ hơn hoặc cùng ngày, không chỉ các hàng nhìn thấy ở trang 1 được sắp xếp.

SHA-256 của file đã đọc:

```text
9bc70887666e2fde89d40a7f380835410bd2ec13e68b2f19a8697dea2de9c418
```

Các lệnh đọc lại để đối chiếu:

```powershell
docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'
docker exec shopping cat /var/www/magento2/vendor/magento/module-sales/Block/Order/History.php
docker exec shopping sha256sum /var/www/magento2/vendor/magento/module-sales/Block/Order/History.php
```

`agent.stop_guard.order_history_sort` lưu origin, chiều giảm dần và tham chiếu này.
Guard chỉ áp dụng cho đúng origin/đường dẫn lịch sử và phân trang mặc định; vẫn
kiểm tra ngày quan sát được, số hàng và vị trí liên tục. Không dùng nhãn evaluator
hoặc đọc đơn chưa được agent quan sát. Nguồn này được ghi thành
`magento_history_source`, tách biệt với metadata `orders_table_aria_sort` của DOM.

Đây là cấu hình đã xác minh cho bản cài đặt trên, không phải khẳng định mọi website
Magento đều dùng cùng thứ tự. Hash giúp truy vết file đã kiểm tra, không phải kiểm
tra runtime tự động. Khi đổi image, mã nguồn, plugin can thiệp collection hoặc
origin, cần kiểm tra lại đường đi tạo collection/pager và cập nhật tham chiếu;
nếu chưa xác minh, bỏ `order_history_sort` để guard quay về dùng metadata DOM hoặc
coverage đầy đủ.
