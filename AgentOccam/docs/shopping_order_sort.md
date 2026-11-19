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

## Nguồn Recent Orders (xác minh ngày 2026-11-19)

Đã đọc trực tiếp trên cùng container `shopping`, image `shopping_final_0712`:

* `vendor/magento/module-sales/Block/Order/Recent.php`:
  SHA-256 `e4b4ffe5450cc0feb7e76978a2872b34e5cdddc40a92bea5629e36f5ae6ed55a`.
* `vendor/magento/module-sales/view/frontend/templates/order/recent.phtml`:
  SHA-256 `a1a67908f475268937ce2ac32913e16933549bbc470abc84e7d71085f2992bf9`.

`getRecentOrders()` lọc theo khách hàng đăng nhập, store hiện tại và trạng thái
hiển thị frontend, rồi gọi `addAttributeToSort('created_at', 'desc')`,
`setPageSize(self::ORDER_LIMIT)` với `ORDER_LIMIT = 5`. Template lặp trực tiếp
collection đó, theo các cột Order, Date, Ship To, Order Total, Status, Action.
Vì vậy đây là 5 đơn mới nhất của khách hàng ở storefront này, không phải 5 đơn
bất kỳ hoặc các đơn có mã lớn nhất. Không mở rộng quy tắc sang đơn ở store khác.

`agent.stop_guard.recent_orders_sort` khai báo nguồn `magento_recent_source`
riêng với origin chính xác. Guard chỉ dùng tại `/customer/account/`, không có
query, cho yêu cầu `comparison` chiều giảm dần đã parse được. Cần đọc đủ 5 hàng
khác nhau, đúng header và thứ tự ngày; bảng rút gọn hoặc nhỏ hơn giới hạn này
chưa đủ chứng minh prefix. Trường hợp đó chuyển sang My Orders.

Evidence được giữ qua bước xem chi tiết đơn và có lý do cho phép dừng
`recent_order_first_match`. Không dùng bảng này để chứng minh tổng số đơn,
tổng tiền, không tồn tại đơn, hoặc đơn cũ nhất. Không dùng đáp án chuẩn hay
trạng thái do model tự kể. Nếu đổi image/store/customization cần xác minh lại
nguồn trước khi giữ cấu hình; hash là dấu vết kiểm tra, không phải kiểm tra runtime.
