import os
import pymupdf as fitz


def pdf_info(pdf_path):
    """Trả về thông tin cơ bản của file PDF."""
    doc = fitz.open(pdf_path)
    info = {
        'page_count': len(doc),
        'file_size_mb': os.path.getsize(pdf_path) / (1024 * 1024),
        'pages': [],
    }
    for i, page in enumerate(doc):
        info['pages'].append({
            'num': i + 1,
            'w': round(page.rect.width),
            'h': round(page.rect.height),
        })
    doc.close()
    return info


def merge_pdfs(input_paths, output_path):
    """Ghép danh sách file PDF (theo thứ tự) thành 1 file đầu ra."""
    out = fitz.open()
    for path in input_paths:
        doc = fitz.open(path)
        out.insert_pdf(doc)
        doc.close()
    out.save(output_path, garbage=4, deflate=True)
    out.close()


def parse_page_ranges(range_str, total_pages):
    """Phân tích '1-3,5,7-10' → list số trang (0-based, đã sort, không trùng)."""
    pages = set()
    for part in range_str.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            halves = part.split('-', 1)
            try:
                a = max(1, int(halves[0].strip()))
                b = min(total_pages, int(halves[1].strip()))
                pages.update(range(a - 1, b))
            except ValueError:
                pass
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages:
                    pages.add(p - 1)
            except ValueError:
                pass
    return sorted(pages)


def split_pdf(input_path, output_dir, ranges_str):
    """Tách PDF theo chuỗi dải trang, xuất mỗi đoạn thành 1 file.
    ranges_str='all' → mỗi trang 1 file riêng.
    Trả về list đường dẫn file đã xuất."""
    doc = fitz.open(input_path)
    total = len(doc)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_files = []

    if ranges_str.strip().lower() == 'all':
        for i in range(total):
            out = fitz.open()
            out.insert_pdf(doc, from_page=i, to_page=i)
            out_path = os.path.join(output_dir, f"{base_name}_trang{i + 1}.pdf")
            out.save(out_path, garbage=4, deflate=True)
            out.close()
            output_files.append(out_path)
    else:
        pages = parse_page_ranges(ranges_str, total)
        if not pages:
            doc.close()
            raise ValueError(f"Dải trang không hợp lệ: '{ranges_str}' (file có {total} trang)")

        # Gộp các trang liên tiếp thành từng đoạn
        segments = []
        seg = [pages[0]]
        for p in pages[1:]:
            if p == seg[-1] + 1:
                seg.append(p)
            else:
                segments.append(seg)
                seg = [p]
        segments.append(seg)

        for seg in segments:
            out = fitz.open()
            for p in seg:
                out.insert_pdf(doc, from_page=p, to_page=p)
            if len(seg) == 1:
                label = f"trang{seg[0] + 1}"
            else:
                label = f"trang{seg[0] + 1}-{seg[-1] + 1}"
            out_path = os.path.join(output_dir, f"{base_name}_{label}.pdf")
            out.save(out_path, garbage=4, deflate=True)
            out.close()
            output_files.append(out_path)

    doc.close()
    return output_files


def rotate_pages(input_path, output_path, pages_str, angle):
    """Xoay các trang chỉ định theo angle (90 / 180 / 270 độ).
    pages_str='all' để xoay toàn bộ."""
    doc = fitz.open(input_path)
    total = len(doc)
    targets = list(range(total)) if pages_str.strip().lower() == 'all' \
        else parse_page_ranges(pages_str, total)
    for i in targets:
        page = doc[i]
        page.set_rotation((page.rotation + angle) % 360)
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


def delete_pages(input_path, output_path, pages_str):
    """Xóa các trang chỉ định rồi lưu ra output_path."""
    doc = fitz.open(input_path)
    total = len(doc)
    to_delete = parse_page_ranges(pages_str, total)
    if not to_delete:
        doc.close()
        raise ValueError(f"Không có trang nào hợp lệ để xóa (file có {total} trang).")
    if len(to_delete) >= total:
        doc.close()
        raise ValueError("Không thể xóa toàn bộ trang của file PDF.")
    doc.delete_pages(to_delete)
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
