import os
import sys
import subprocess

# --- 1. TỰ ĐỘNG CÀI ĐẶT THƯ VIỆN THIẾU ---
def ensure_packages():
    packages = {
        'pymupdf': 'fitz',
        'pytesseract': 'pytesseract',
        'pillow': 'PIL',
        'colorama': 'colorama'
    }
    for pkg, imp in packages.items():
        try:
            __import__(imp)
        except ImportError:
            print(f"[*] Đang tự động tải và cài đặt thư viện: {pkg} (chỉ tốn vài giây)...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])
            print(f"[+] Đã cài xong {pkg}!")

ensure_packages()
# ----------------------------------------

import re
import shutil
import time
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import colorama
from colorama import Fore, Style

# Bật hỗ trợ màu sắc trên màn hình Console Windows
colorama.init(autoreset=True)

# --- 2. KIỂM TRA PHẦN MỀM TESSERACT-OCR ---
TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
if not os.path.exists(TESSERACT_PATH):
    print("\n" + "="*60)
    print(" [!] LỖI: CHƯA CÀI ĐẶT PHẦN MỀM NHẬN DIỆN CHỮ TESSERACT-OCR")
    print("="*60)
    print("Máy tính của bạn chưa có bộ đọc chữ Tesseract.")
    print("Vui lòng tải và cài đặt theo link sau:")
    print("-> Link tải: https://github.com/UB-Mannheim/tesseract/wiki")
    print("\n*LƯU Ý QUAN TRỌNG KHI CÀI ĐẶT:")
    print("  Khi đến bước chọn thành phần (Choose Components),")
    print("  hãy bấm dấu [+] ở mục 'Additional language data (download)'")
    print("  và TICK CHỌN 'Vietnamese' để máy đọc được tiếng Việt nhé!")
    print("="*60 + "\n")
    input("Nhấn Enter để thoát và đi cài phần mềm...")
    sys.exit()

# CẤU HÌNH ĐƯỜNG DẪN TESSERACT
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# CHẤT LƯỢNG NÉN ẢNH TRONG PDF (0-100, càng thấp file càng nhẹ)
# 50 = nén sâu, chữ vẫn đọc được, dung lượng nhẹ hơn nữa
JPEG_QUALITY = 50

# THỜI GIAN GIỮA MỖI LẦN TỰ ĐỘNG KIỂM TRA THƯ MỤC ĐẦU VÀO (GIÂY)
WATCH_INTERVAL_SECONDS = 3

def is_xoa_dangky_bien_phap(full_text):
    """Nhận diện 'Phiếu yêu cầu xóa đăng ký biện pháp bảo đảm' (xóa thế chấp ngân hàng).
    Kiểm tra 2 cụm từ RIÊNG LẺ (không đòi liền nhau) vì tiêu đề hay bị OCR/layout 2 cột
    cắt rời 'biện pháp' và 'bảo đảm' ra 2 dòng khác nhau."""
    has_xoa_dangky = re.search(r'x[oóòỏõ]a\s*đ[aăâ]ng\s*k[yý]', full_text, re.IGNORECASE)
    has_bien_phap = re.search(r'bi[eệê]n\s*ph[aáà]p', full_text, re.IGNORECASE)
    has_bao_dam = re.search(r'b[aả]o\s*[đd][aả]m', full_text, re.IGNORECASE)
    return bool(has_xoa_dangky and (has_bien_phap or has_bao_dam))


def extract_phat_hanh_number(full_text, so_luong_so):
    """Lấy số GCN đầu tiên được liệt kê (dùng cho phiếu xóa đăng ký biện pháp bảo đảm -
    không có 'Mã hồ sơ'). Tài liệu ghi số này theo 2 kiểu câu chữ khác nhau:
    'Số phát hành: BN 589373' hoặc 'Giấy chứng nhận QSDĐ số BG 623746'."""
    match = re.search(r'ph[aá]t\s*h[aà]nh[:.\s]*([A-ZĐ]{1,3}\s*\d{5,8})', full_text, re.IGNORECASE)
    if not match:
        match = re.search(
            r'gi[aấ]y\s*ch[uứ]ng\s*nh[aậ]n[^\n]{0,40}?s[oố][:.\s]*([A-ZĐ]{1,3}\s*\d{5,8})',
            full_text, re.IGNORECASE
        )
    if not match:
        return None
    raw = re.sub(r'[\s.\-:]', '', match.group(1).upper())
    return raw[-so_luong_so:] if len(raw) >= so_luong_so else raw


def extract_serial_number_3so(pdf_path):
    """[CHẾ ĐỘ 3 SỐ] Đọc các trang của PDF và tìm số phát hành bằng Tesseract"""
    try:
        doc = fitz.open(pdf_path)

        # Lặp qua tối đa 10 trang đầu
        max_pages = min(len(doc), 10)
        full_text = ""
        first_raw_number = None

        # ĐỌC HẾT TOÀN BỘ TRANG TRƯỚC (không dừng sớm), để việc phân loại
        # phiếu/bìa đỏ bên dưới luôn dựa trên đầy đủ nội dung, tránh đọc nhầm
        # khi từ khóa phân loại nằm ở trang sau trang chứa mã số.
        for page_num in range(max_pages):
            page = doc.load_page(page_num)

            # Tăng chất lượng ảnh lên một chút để Tesseract dễ đọc hơn
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            # Sử dụng OCR Tesseract (Dùng cả tiếng Việt và Anh)
            try:
                text = pytesseract.image_to_string(img, lang='vie+eng')
            except:
                text = pytesseract.image_to_string(img, lang='eng')

            full_text += f"\n--- NỘI DUNG TRANG {page_num} ---\n{text}\n"

            if first_raw_number is None:
                # BỘ LỌC CHÍNH XÁC
                keyword_regex = r'(?:ph[aàeé]t\s*h[aàeé]nh|GCN|hanh|S[oó06]?\s*ph[aàeé]t|đ[aấ]t\s*s[oốô]).*?(?<![A-ZĐ])([A-ZĐ]{1,2}\s*[-.:]?\s*\d{5,8}|\b\d{6,8}\b)'
                match = re.search(keyword_regex, text, re.IGNORECASE)

                # BỘ LỌC PHỤ
                if not match:
                    # (?<![A-ZĐ]) đảm bảo không lấy chữ nằm cuối một từ viết hoa (tránh bắt nhầm CCCD thành CD)
                    match = re.search(r'(?<![A-ZĐ])([A-ZĐ]{1,2}\s*[-.:]?\s*\d{5,8})\b', text)

                # BỘ LỌC RIÊNG CHO SỐ GCN DẠNG 'DĐ' (OCR hay đọc nhầm Đ thành 0/O,
                # phá vỡ 2 mẫu regex trên vì thiếu đủ 5-8 chữ số liền sau prefix)
                if not match:
                    match = re.search(r'\b(D[BOĐ08]\s*[-.:]?\s*\d{6,8})\b', text, re.IGNORECASE)

                if match:
                    first_raw_number = match.group(1).upper()

        doc.close()

        # Phiếu xóa đăng ký biện pháp bảo đảm (xóa thế chấp ngân hàng): không có
        # 'Mã hồ sơ', lấy số từ dòng 'phát hành: BN xxxxxx' của GCN đầu tiên liệt kê.
        if is_xoa_dangky_bien_phap(full_text):
            so_hieu = extract_phat_hanh_number(full_text, 3)
            return so_hieu, True, full_text

        if first_raw_number is None:
            return None, False, full_text

        raw_number = first_raw_number

        # Sửa lỗi OCR chỉ ở ĐẦU mã số
        raw_number = re.sub(r'^(ĐB|DB|DO|D0)', 'DĐ', raw_number)
        raw_number = re.sub(r'^(A\||AT)', 'AI', raw_number)

        # Làm sạch
        clean_number = re.sub(r'[\s.\-:]', '', raw_number)

        # Phân loại thông minh: Phiếu (+) vs Bìa đỏ (không +) - dựa trên TOÀN BỘ nội dung
        is_phieu = False

        # Các từ khóa CỦA PHIẾU (chắc chắn là phiếu)
        keywords_phieu = r'(phi[eế]u\s*th[aẩảâáàam]+\s*tra|phi[eế]u\s*chuy[eể]n\s*th[oô]ng\s*tin|phi[eế]u\s*y[eê]u\s*c[aầ]u|bi[eế]n\s*đ[oộ]ng)'
        # Các từ khóa CỦA BÌA ĐỎ (chắc chắn là bìa)
        keywords_bia = r'(gi[aấ]y\s*ch[uứ]ng\s*nh[aậ]n\s*quy[eề]n\s*s[uử]\s*d[uụ]ng\s*đ[aấ]t)'

        if re.search(keywords_phieu, full_text, re.IGNORECASE):
            # Đã chắc chắn là phiếu (tiêu đề/nội dung có từ khóa phiếu) -> giữ nguyên.
            # KHÔNG dùng cụm 'giấy chứng nhận quyền sử dụng đất' để ghi đè về bìa đỏ nữa,
            # vì phiếu thẩm tra/thẩm định nào cũng nhắc tới cụm này (đang cấp GCN).
            is_phieu = True
        elif re.search(keywords_bia, full_text, re.IGNORECASE):
            is_phieu = False

        # Phiếu (+): Lấy 3 số cuối từ Mã hồ sơ (VD: H15.50-260623-1231 -> lấy 231), KHÔNG lấy số GCN/bìa
        if is_phieu:
            ma_hs_match = re.search(r'M[aã]\s*h[oồ\s]*s[oơ\s]*[:.\-]?\s*([A-Za-z0-9.\-/_]+)', full_text, re.IGNORECASE)
            if ma_hs_match:
                ma_hs_str = ma_hs_match.group(1)
                # Ưu tiên lấy 3 số nằm ngay sau cụm 6 số (ngày tháng, VD: 260623-1231)
                id_match = re.search(r'\d{6}[^\d]*(\d{3,4})', ma_hs_str)
                if id_match:
                    clean_number = id_match.group(1)[-3:]
                else:
                    cln_ma = re.sub(r'[\s._]', '', ma_hs_str)
                    cln_ma = cln_ma.split('/')[0].split('-')[-1]
                    clean_number = cln_ma[-3:] if len(cln_ma) >= 3 else clean_number
            else:
                clean_number = clean_number[-3:] if len(clean_number) >= 3 else clean_number
        else:
            # Bìa đỏ: Chỉ lấy 3 con số cuối cùng của mã số GCN
            clean_number = clean_number[-3:] if len(clean_number) >= 3 else clean_number

        return clean_number, is_phieu, full_text
    except Exception as e:
        print(f"Lỗi khi đọc file {os.path.basename(pdf_path)}: {e}")
        return None, False, ""

def extract_serial_number_4so(pdf_path):
    """[CHẾ ĐỘ 4 SỐ] Đọc các trang của PDF và tìm số phát hành bằng Tesseract"""
    try:
        doc = fitz.open(pdf_path)

        # Lặp qua tối đa 10 trang đầu
        max_pages = min(len(doc), 10)
        full_text = ""
        first_raw_number = None

        # ĐỌC HẾT TOÀN BỘ TRANG TRƯỚC (không dừng sớm), để việc phân loại
        # phiếu/bìa đỏ bên dưới luôn dựa trên đầy đủ nội dung. Trước đây hàm
        # return ngay khi gặp mã số đầu tiên, nên nếu từ khóa "phiếu thẩm tra"
        # nằm ở trang sau thì bị bỏ sót -> nhận nhầm phiếu thành bìa đỏ và lấy
        # nhầm "số phát hành" thay vì "mã hồ sơ".
        for page_num in range(max_pages):
            page = doc.load_page(page_num)

            # Tăng chất lượng ảnh lên một chút để Tesseract dễ đọc hơn
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            # Sử dụng OCR Tesseract (Dùng cả tiếng Việt và Anh)
            try:
                text = pytesseract.image_to_string(img, lang='vie+eng')
            except:
                text = pytesseract.image_to_string(img, lang='eng')

            full_text += f"\n--- NỘI DUNG TRANG {page_num} ---\n{text}\n"

            if first_raw_number is None:
                # BỘ LỌC CHÍNH XÁC
                keyword_regex = r'(?:ph[aàeé]t\s*h[aàeé]nh|GCN|hanh|S[oó06]?\s*ph[aàeé]t|đ[aấ]t\s*s[oốô]).*?(?<![A-ZĐ])([A-ZĐ]{1,2}\s*[-.:]?\s*\d{5,8}|\b\d{6,8}\b)'
                match = re.search(keyword_regex, text, re.IGNORECASE)

                # BỘ LỌC PHỤ
                if not match:
                    # (?<![A-ZĐ]) đảm bảo không lấy chữ nằm cuối một từ viết hoa (tránh bắt nhầm CCCD thành CD)
                    match = re.search(r'(?<![A-ZĐ])([A-ZĐ]{1,2}\s*[-.:]?\s*\d{5,8})\b', text)

                # BỘ LỌC RIÊNG CHO SỐ GCN DẠNG 'DĐ' (OCR hay đọc nhầm Đ thành 0/O,
                # phá vỡ 2 mẫu regex trên vì thiếu đủ 5-8 chữ số liền sau prefix)
                if not match:
                    match = re.search(r'\b(D[BOĐ08]\s*[-.:]?\s*\d{6,8})\b', text, re.IGNORECASE)

                if match:
                    first_raw_number = match.group(1).upper()

        doc.close()

        # Phiếu xóa đăng ký biện pháp bảo đảm (xóa thế chấp ngân hàng): không có
        # 'Mã hồ sơ', lấy số từ dòng 'phát hành: BN xxxxxx' của GCN đầu tiên liệt kê.
        if is_xoa_dangky_bien_phap(full_text):
            so_hieu = extract_phat_hanh_number(full_text, 4)
            return so_hieu, True, full_text

        if first_raw_number is None:
            return None, False, full_text

        raw_number = first_raw_number

        # Sửa lỗi OCR chỉ ở ĐẦU mã số
        raw_number = re.sub(r'^(ĐB|DB|DO|D0)', 'DĐ', raw_number)
        raw_number = re.sub(r'^(A\||AT)', 'AI', raw_number)

        # Làm sạch
        clean_number = re.sub(r'[\s.\-:]', '', raw_number)

        # Phân loại thông minh: Phiếu (+) vs Bìa đỏ (không +) - dựa trên TOÀN BỘ nội dung
        is_phieu = False

        # Các từ khóa CỦA PHIẾU (chắc chắn là phiếu)
        keywords_phieu = r'(phi[eế]u\s*th[aẩảâáàam]+\s*tra|phi[eế]u\s*chuy[eể]n\s*th[oô]ng\s*tin|phi[eế]u\s*y[eê]u\s*c[aầ]u|bi[eế]n\s*đ[oộ]ng)'
        # Các từ khóa CỦA BÌA ĐỎ (chắc chắn là bìa)
        keywords_bia = r'(gi[aấ]y\s*ch[uứ]ng\s*nh[aậ]n\s*quy[eề]n\s*s[uử]\s*d[uụ]ng\s*đ[aấ]t)'

        if re.search(keywords_phieu, full_text, re.IGNORECASE):
            # Đã chắc chắn là phiếu (tiêu đề/nội dung có từ khóa phiếu) -> giữ nguyên.
            # KHÔNG dùng cụm 'giấy chứng nhận quyền sử dụng đất' để ghi đè về bìa đỏ nữa,
            # vì phiếu thẩm tra/thẩm định nào cũng nhắc tới cụm này (đang cấp GCN).
            is_phieu = True
        elif re.search(keywords_bia, full_text, re.IGNORECASE):
            is_phieu = False

        # Xử lý lấy số cuối tùy theo loại
        if is_phieu:
            # Phiếu (+): Lấy 4 số cuối từ Mã hồ sơ (VD: H15.50-260623-1231 -> lấy 1231)
            ma_hs_match = re.search(r'M[aã]\s*h[oồ\s]*s[oơ\s]*[:.\-]?\s*([A-Za-z0-9.\-/_]+)', full_text, re.IGNORECASE)
            if ma_hs_match:
                ma_hs_str = ma_hs_match.group(1)
                # Ưu tiên lấy 4 số nằm ngay sau cụm 6 số (ngày tháng, VD: 260623-1231)
                id_match = re.search(r'\d{6}[^\d]*(\d{4})', ma_hs_str)
                if id_match:
                    clean_number = id_match.group(1)
                else:
                    # Dự phòng: Lấy 4 số/chữ cuối cùng của chuỗi mã hồ sơ
                    cln_ma = re.sub(r'[\s._]', '', ma_hs_str)
                    # Bỏ các phần tử sau dấu / nếu có (VD: 1231/0367 -> lấy 1231)
                    cln_ma = cln_ma.split('/')[0].split('-')[-1]
                    clean_number = cln_ma[-4:] if len(cln_ma) >= 4 else clean_number
            else:
                clean_number = clean_number[-4:] if len(clean_number) >= 4 else clean_number
        else:
            # Bìa đỏ: Chỉ lấy 4 con số cuối cùng của mã số GCN
            clean_number = clean_number[-4:] if len(clean_number) >= 4 else clean_number

        return clean_number, is_phieu, full_text
    except Exception as e:
        print(f"Lỗi khi đọc file {os.path.basename(pdf_path)}: {e}")
        return None, False, ""

def process_and_flatten_pdf(input_path, output_path):
    """Chuyển file PDF sang định dạng chuẩn Microsoft Print to PDF"""
    doc = fitz.open(input_path)
    out_pdf = fitz.open()  # Tạo file PDF mới tinh

    # ÉP DÍNH toàn bộ chữ ký, mộc đỏ vào mặt giấy
    for page in doc:
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        
        # Tạo tờ giấy mới chuẩn khổ Letter (8.5 x 11 inch) giống hệt Microsoft Print to PDF
        is_landscape = page.rect.width > page.rect.height
        if is_landscape:
            target_w, target_h = 792.0, 612.0  # 11 x 8.5 inch
        else:
            target_w, target_h = 612.0, 792.0  # 8.5 x 11 inch

        out_page = out_pdf.new_page(width=target_w, height=target_h)

        # Giả lập chức năng "Fit to printer margins" (Thu nhỏ ~93.73%)
        scale = min(target_w / page.rect.width, target_h / page.rect.height)
        new_w = page.rect.width * scale
        new_h = page.rect.height * scale

        # Giả lập chức năng "Auto-Center" (Canh giữa giấy)
        x0 = (target_w - new_w) / 2
        y0 = (target_h - new_h) / 2
        target_rect = fitz.Rect(x0, y0, x0 + new_w, y0 + new_h)

        # Nén ảnh sang JPEG trước khi nhúng (thay vì nhúng pixmap thô/Flate)
        # -> giảm dung lượng file PDF rất nhiều lần, vẫn giữ định dạng .pdf
        jpg_bytes = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
        out_page.insert_image(target_rect, stream=jpg_bytes)

    # Thêm Metadata để giả lập y hệt "Microsoft Print To PDF"
    now_date = fitz.get_pdf_now()
    metadata = {
        "producer": "Microsoft: Print To PDF",
        "creator": "",
        "title": "",
        "author": "",
        "subject": "",
        "creationDate": now_date,
        "modDate": now_date
    }
    out_pdf.set_metadata(metadata)

    # Lưu file mới ra lò (nén tối đa phần dữ liệu thừa/font/nội dung)
    out_pdf.save(output_path, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True)
    out_pdf.close()
    doc.close()

def load_config(base_dir):
    """Đọc đường dẫn thư mục Đầu Vào / Đầu Ra từ config.txt.
    Nếu chưa có file config.txt thì tự tạo với đường dẫn mặc định (DauVao/DauRa cạnh script)."""
    config_path = os.path.join(base_dir, 'config.txt')
    default_input = os.path.join(base_dir, 'DauVao')
    default_output = os.path.join(base_dir, 'DauRa')

    if not os.path.exists(config_path):
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(
                "# Sửa 2 đường dẫn bên dưới rồi lưu lại (Ctrl+S) để tool đọc/xuất đúng thư mục bạn muốn.\n"
                "# Ví dụ: DauVao=D:\\May_Scan\\Output\n"
                f"DauVao={default_input}\n"
                f"DauRa={default_output}\n"
            )
        return default_input, default_output

    input_dir, output_dir = default_input, default_output
    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key, value = key.strip().lower(), value.strip()
            if not value:
                continue
            if key == 'dauvao':
                input_dir = value
            elif key == 'daura':
                output_dir = value

    return input_dir, output_dir


def is_file_stable(path, wait_seconds=1.0):
    """Kiểm tra file đã ghi xong chưa (dung lượng không đổi sau X giây)
    -> tránh đọc file khi máy scan còn đang ghi dở gây lỗi/đọc sai."""
    try:
        size1 = os.path.getsize(path)
        time.sleep(wait_seconds)
        size2 = os.path.getsize(path)
        return size1 == size2 and size1 > 0
    except OSError:
        return False


def process_one_file(filename, input_dir, output_dir, log_dir, processed_dir, extract_serial_number):
    input_path = os.path.join(input_dir, filename)

    # BƯỚC 1: ĐỌC TÊN
    serial_number, is_phieu, ocr_text = extract_serial_number(input_path)

    if serial_number:
        suffix = "+" if is_phieu else ""
        new_filename = f"{serial_number}{suffix}.pdf"
    else:
        # Nếu không đọc được mã: Xuất LOG ra thư mục Loi_OCR và GIỮ NGUYÊN TÊN GỐC
        new_filename = filename
        with open(os.path.join(log_dir, f"LOG_LOI_{filename}.txt"), "w", encoding="utf-8") as f:
            f.write(ocr_text)
        print(f"{Fore.YELLOW} [?] Lỗi đọc chữ: Không rõ mã số của '{filename}', sẽ giữ nguyên tên cũ!")

    output_path = os.path.join(output_dir, new_filename)

    # Đổi tên tự động nếu bị trùng file ở đầu ra
    if os.path.exists(output_path):
        base, ext = os.path.splitext(new_filename)
        count = 1
        while os.path.exists(os.path.join(output_dir, f"{base}_{count}{ext}")):
            count += 1
        output_path = os.path.join(output_dir, f"{base}_{count}{ext}")

    # BƯỚC 2: IN PDF & LƯU VÀO ĐẦU RA
    try:
        process_and_flatten_pdf(input_path, output_path)

        # Lưu bản ĐÃ CONVERT (không phải file scan thô) vào 'DaXuLy' để lục lại sau,
        # dùng đúng tên đã đổi (mã số) -> khớp với file thật đang nằm ở đầu ra.
        out_filename = os.path.basename(output_path)
        archive_path = os.path.join(processed_dir, out_filename)
        if os.path.exists(archive_path):
            base, ext = os.path.splitext(out_filename)
            count = 1
            while os.path.exists(os.path.join(processed_dir, f"{base}_{count}{ext}")):
                count += 1
            archive_path = os.path.join(processed_dir, f"{base}_{count}{ext}")
        shutil.copy2(output_path, archive_path)

        # Xong việc lưu bản đã convert -> không cần giữ file scan thô nữa, tránh đọc trùng lần sau
        os.remove(input_path)

        if serial_number:
            print(f"{Fore.GREEN} [+] THÀNH CÔNG: {filename} -> {os.path.basename(output_path)}")
        else:
            print(f"{Fore.CYAN} [+] ĐÃ IN PDF (Chưa đổi tên): {filename} -> {os.path.basename(output_path)}")
    except Exception as e:
        print(f"{Fore.RED} [!] LỖI KHI XỬ LÝ: {filename} -> {e}")


def process_one_file_giu_ten(filename, input_dir, output_dir, processed_dir):
    """Chế độ 3: chỉ ép phẳng + nén, KHÔNG OCR, KHÔNG đổi tên -> giữ nguyên tên file gốc."""
    input_path = os.path.join(input_dir, filename)
    output_path = os.path.join(output_dir, filename)

    # Đổi tên tự động nếu bị trùng file ở đầu ra (vẫn giữ tên gốc làm nền)
    if os.path.exists(output_path):
        base, ext = os.path.splitext(filename)
        count = 1
        while os.path.exists(os.path.join(output_dir, f"{base}_{count}{ext}")):
            count += 1
        output_path = os.path.join(output_dir, f"{base}_{count}{ext}")

    try:
        process_and_flatten_pdf(input_path, output_path)

        # Lưu bản ĐÃ CONVERT (không phải file scan thô) vào 'DaXuLy' để lục lại sau
        out_filename = os.path.basename(output_path)
        archive_path = os.path.join(processed_dir, out_filename)
        if os.path.exists(archive_path):
            base, ext = os.path.splitext(out_filename)
            count = 1
            while os.path.exists(os.path.join(processed_dir, f"{base}_{count}{ext}")):
                count += 1
            archive_path = os.path.join(processed_dir, f"{base}_{count}{ext}")
        shutil.copy2(output_path, archive_path)

        os.remove(input_path)

        print(f"{Fore.GREEN} [+] ĐÃ CONVERT (giữ nguyên tên): {filename} -> {os.path.basename(output_path)}")
    except Exception as e:
        print(f"{Fore.RED} [!] LỖI KHI XỬ LÝ: {filename} -> {e}")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir, output_dir = load_config(base_dir)
    log_dir = os.path.join(base_dir, 'Loi_OCR')
    processed_dir = os.path.join(input_dir, 'DaXuLy')

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    if not os.path.exists(input_dir):
        os.makedirs(input_dir)
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)

    print(f"{Fore.CYAN}{Style.BRIGHT}=== PHẦN MỀM XỬ LÝ PDF BY VIỆT ===")
    print(f"{Fore.CYAN}Thư mục đầu vào : {input_dir}")
    print(f"{Fore.CYAN}Thư mục đầu ra  : {output_dir}\n")

    # CHỌN CHẾ ĐỘ XỬ LÝ (chỉ hỏi 1 lần lúc khởi động)
    print(f"{Fore.CYAN}Chọn chế độ xử lý:")
    print("  [1] Lấy 3 số cuối (OCR đổi tên)")
    print("  [2] Lấy 4 số cuối (OCR đổi tên)")
    print("  [3] Chỉ nén, GIỮ NGUYÊN TÊN (không OCR, không đổi tên)")
    mode = ""
    while mode not in ("1", "2", "3"):
        mode = input("Nhập lựa chọn (1, 2 hoặc 3): ").strip()
    extract_serial_number = extract_serial_number_3so if mode == "1" else extract_serial_number_4so

    print(f"\n{Fore.YELLOW}Đang theo dõi thư mục đầu vào, cứ {WATCH_INTERVAL_SECONDS} giây kiểm tra 1 lần.")
    print(f"{Fore.YELLOW}Cứ scan file mới vào thư mục đầu vào là tool sẽ tự động xử lý.")
    print(f"{Fore.YELLOW}Nhấn Ctrl+C để dừng theo dõi.\n")

    try:
        while True:
            files = [f for f in os.listdir(input_dir)
                     if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(input_dir, f))]

            for filename in files:
                input_path = os.path.join(input_dir, filename)
                # Bỏ qua file scan đang ghi dở, để lần kiểm tra sau xử lý tiếp
                if not is_file_stable(input_path):
                    continue
                if mode == "3":
                    process_one_file_giu_ten(filename, input_dir, output_dir, processed_dir)
                else:
                    process_one_file(filename, input_dir, output_dir, log_dir, processed_dir, extract_serial_number)

            time.sleep(WATCH_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print(f"\n{Fore.CYAN}Đã dừng theo dõi.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("\nLỗi! Nhấn Enter để thoát...")
