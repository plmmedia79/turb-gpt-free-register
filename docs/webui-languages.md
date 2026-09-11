# Ngôn ngữ WebUI

WebUI có hai lựa chọn: `vi` (Tiếng Việt, mặc định) và `zh-CN` (中文). Nút chọn xuất hiện trên trang đăng nhập và cả hai phiên bản giao diện. Lựa chọn được lưu trong cookie `webui_language` trong một năm. Tham số URL `lang` hợp lệ được ưu tiên hơn cookie; giá trị không hỗ trợ sẽ dùng cookie hợp lệ hoặc tiếng Việt mặc định.

## Cách bổ sung hoặc sửa bản dịch

- Các tệp `webui/locales/*-vi.json` ánh xạ câu tiếng Trung gốc sang tiếng Việt. Giữ nguyên tên biến như `{count}`, tên cấu hình, đường dẫn và giá trị kỹ thuật trong bản dịch.
- Nội dung HTML tĩnh dùng `{{ tr('原文') }}` để giữ cơ chế escape của Jinja.
- Nội dung JavaScript dùng `t('原文 {count}', {count: value})`. Tiếp tục dùng hàm `esc()` hiện có khi đưa dữ liệu vào HTML. Hàm dịch không phải hàm escape HTML.
- Cấu hình vẫn dùng khóa và nhóm gốc để đọc/ghi, lọc và điều hướng; chỉ dịch nhãn và hướng dẫn tại điểm hiển thị.
- Nội dung người dùng nhập, email, token và nhật ký chẩn đoán gốc không được tự động dịch. API giữ nguyên hợp đồng dữ liệu.
- Khởi động lại WebUI sau khi sửa catalog vì máy chủ lưu catalog trong bộ nhớ.

Ưu tiên cách nói rõ thao tác: “Kho email”, “Mã xác minh”, “Mã truy cập”, “Thông tin xác thực Codex”. Giữ tên dịch vụ như RoxyBrowser, CloakBrowser, IMAP và OAuth để người dùng đối chiếu với cấu hình của dịch vụ.

## Kiểm tra

```bash
.venv/bin/python -m unittest tests.test_webui_i18n tests.test_webui_auth
```

Ngoài kiểm tra tự động, mở cả giao diện mới và cũ, chuyển ngôn ngữ, kiểm tra các tab, hộp thoại, phân trang và phần hướng dẫn cấu hình. Lưu ý độ dài tiếng Việt trên màn hình hẹp.
