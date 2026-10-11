import os
import sys
import re
import json
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox


def _ensure_packages():
    for pkg in ('customtkinter',):
        try:
            __import__(pkg)
        except ImportError:
            print(f"[*] Installing: {pkg} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])


_ensure_packages()

import customtkinter as ctk
import Auto_PDF as core

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_JSON = os.path.join(BASE_DIR, 'config.json')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

CLR_OK   = '#4ade80'
CLR_ERR  = '#f87171'
CLR_WARN = '#fbbf24'
CLR_INFO = '#93c5fd'
CLR_MUTED = '#6b7280'


class LogWriter:
    """Chuyển hướng stdout → queue để hiển thị trong log box."""
    def __init__(self, q):
        self._q = q

    def write(self, text):
        if text and text.strip():
            self._q.put(text)

    def flush(self):
        pass


def load_settings():
    data = {
        'input_dir':    os.path.join(BASE_DIR, 'DauVao'),
        'output_dir':   os.path.join(BASE_DIR, 'DauRa'),
        'mode':         '1',
        'jpeg_quality': core.JPEG_QUALITY,
    }
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
                data.update(json.load(f))
        except Exception:
            pass
    return data


def save_settings(data):
    try:
        with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.log_queue = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()
        self._stat_ok  = 0
        self._stat_err = 0
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Xử lý PDF — BY VIỆT")
        self.geometry("840x760")
        self.minsize(720, 620)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()
        self._init_log_tags()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._drain_log)

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="PHẦN MỀM XỬ LÝ PDF",
                     font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, sticky="w")

        stats_row = ctk.CTkFrame(hdr, fg_color="transparent")
        stats_row.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self._ok_var  = tk.StringVar(value="0")
        self._err_var = tk.StringVar(value="0")

        self._stat_chip(stats_row, "Đã xử lý", self._ok_var,  CLR_OK ).pack(side="left", padx=(0, 8))
        self._stat_chip(stats_row, "Lỗi",      self._err_var, CLR_ERR).pack(side="left", padx=(0, 8))

        self._status_label = ctk.CTkLabel(stats_row, text="● Dừng",
                                          text_color=CLR_MUTED,
                                          font=ctk.CTkFont(size=13))
        self._status_label.pack(side="left", padx=(4, 0))

    def _stat_chip(self, parent, label, var, color):
        f = ctk.CTkFrame(parent, corner_radius=8)
        ctk.CTkLabel(f, textvariable=var, text_color=color,
                     font=ctk.CTkFont(size=18, weight="bold"),
                     width=38).pack(side="left", padx=(10, 4), pady=(4, 4))
        ctk.CTkLabel(f, text=label, text_color=CLR_MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 10), pady=(4, 4))
        return f

    # ── Tabs ──────────────────────────────────────────────────────────────────
    def _build_tabs(self):
        self._tabs = ctk.CTkTabview(self, anchor="nw")
        self._tabs.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
        self._tabs.add("⚡  Theo Dõi Tự Động")
        self._build_watch_tab(self._tabs.tab("⚡  Theo Dõi Tự Động"))

    # ── Tab 1 : Theo Dõi ──────────────────────────────────────────────────────
    def _build_watch_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(5, weight=1)
        P = dict(padx=8, pady=(0, 10))

        # Thư mục đầu vào / đầu ra
        ff = ctk.CTkFrame(tab)
        ff.grid(row=0, column=0, sticky="ew", **P)
        ff.grid_columnconfigure(1, weight=1)
        for i, (lbl, attr, key, cmd) in enumerate([
            ("Thư mục ĐẦU VÀO:", 'in_entry',  'input_dir',  self._pick_input),
            ("Thư mục ĐẦU RA:",  'out_entry', 'output_dir', self._pick_output),
        ]):
            ctk.CTkLabel(ff, text=lbl, width=170, anchor="w").grid(
                row=i, column=0, padx=12, pady=10, sticky="w")
            e = ctk.CTkEntry(ff)
            e.grid(row=i, column=1, padx=6, pady=10, sticky="ew")
            e.insert(0, self.settings[key])
            setattr(self, attr, e)
            ctk.CTkButton(ff, text="Chọn...", width=80, command=cmd).grid(
                row=i, column=2, padx=12, pady=10)

        # Chế độ + mức nén
        mf = ctk.CTkFrame(tab)
        mf.grid(row=1, column=0, sticky="ew", **P)
        mf.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(mf, text="Chế độ xử lý:",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w")
        self._mode_btn = ctk.CTkSegmentedButton(
            mf,
            values=["Lấy 3 số", "Lấy 4 số", "Giữ nguyên tên"],
            command=self._on_mode_change)
        self._mode_btn.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="ew")
        self._mode_btn.set(
            {'1': "Lấy 3 số", '2': "Lấy 4 số", '3': "Giữ nguyên tên"}[self.settings['mode']])

        self._mode_hint = ctk.CTkLabel(mf, text="", text_color=CLR_MUTED)
        self._mode_hint.grid(row=2, column=0, padx=12, pady=(0, 4), sticky="w")

        qr = ctk.CTkFrame(mf, fg_color="transparent")
        qr.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        qr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(qr, text="Mức nén ảnh:").grid(row=0, column=0, sticky="w")
        self._q_label = ctk.CTkLabel(qr, text=str(self.settings['jpeg_quality']), width=36)
        self._q_label.grid(row=0, column=2, padx=(8, 0))
        self._q_slider = ctk.CTkSlider(qr, from_=20, to=95, number_of_steps=75,
                                       command=self._on_quality_change)
        self._q_slider.grid(row=0, column=1, padx=12, sticky="ew")
        self._q_slider.set(self.settings['jpeg_quality'])

        # Row 2: action buttons
        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        btn_row.grid_columnconfigure(0, weight=1)

        self._start_btn = ctk.CTkButton(
            btn_row, text="▶  BẮT ĐẦU THEO DÕI", height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._toggle_watch)
        self._start_btn.grid(row=0, column=0, sticky="ew")
        self._btn_fg    = self._start_btn.cget("fg_color")
        self._btn_hover = self._start_btn.cget("hover_color")

        ctk.CTkButton(btn_row, text="🔍 Xem Trước Đổi Tên", width=170, height=44,
                      command=self._start_preview_rename).grid(row=0, column=1, padx=(8, 0))

        # Row 3: rename preview area
        pf = ctk.CTkFrame(tab)
        pf.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))
        pf.grid_columnconfigure(0, weight=1)

        ph = ctk.CTkFrame(pf, fg_color="transparent")
        ph.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        ph.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(ph, text="Xem Trước Đổi Tên",
                     font=ctk.CTkFont(weight="bold"),
                     text_color=CLR_INFO).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(ph, text="🔄 Làm mới", width=90,
                      command=self._start_preview_rename).grid(row=0, column=1)

        self._preview_rename_box = ctk.CTkTextbox(
            pf, font=ctk.CTkFont(family="Consolas", size=11), height=100)
        self._preview_rename_box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._preview_rename_box.configure(state="disabled")
        pr_tb = self._preview_rename_box._textbox
        for tag, color in [('ok', CLR_OK), ('err', CLR_ERR),
                           ('warn', CLR_WARN), ('info', CLR_INFO), ('muted', CLR_MUTED)]:
            pr_tb.tag_config(tag, foreground=color)
        self._pr_insert("Nhấn 🔍 Xem Trước để quét thư mục đầu vào…", 'muted')

        # Row 4: log header + clear button
        log_hdr = ctk.CTkFrame(tab, fg_color="transparent")
        log_hdr.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 2))
        log_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_hdr, text="📋 Nhật ký xử lý",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(log_hdr, text="🗑 Xóa log", width=90,
                      command=self._clear_log).grid(row=0, column=1)

        # Row 5: log box
        self._log_box = ctk.CTkTextbox(
            tab, font=ctk.CTkFont(family="Consolas", size=12))
        self._log_box.grid(row=5, column=0, sticky="nsew", padx=8, pady=(0, 4))
        self._log_box.configure(state="disabled")

        self._on_mode_change(self._mode_btn.get())


    # ── Watch tab: log init & drain ───────────────────────────────────────────
    def _init_log_tags(self):
        tb = self._log_box._textbox
        tb.tag_config('ok',   foreground=CLR_OK)
        tb.tag_config('err',  foreground=CLR_ERR)
        tb.tag_config('warn', foreground=CLR_WARN)
        tb.tag_config('info', foreground=CLR_INFO)

    def _drain_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._write_watch_log(msg.rstrip('\n'))
        except queue.Empty:
            pass
        self.after(150, self._drain_log)

    def _write_watch_log(self, msg):
        clean = ANSI_RE.sub('', msg)
        if '[+]' in clean:
            tag = 'ok'
            if any(k in clean for k in ('THÀNH CÔNG', 'ĐÃ CONVERT', 'ĐÃ IN PDF')):
                self._stat_ok += 1
                self._ok_var.set(str(self._stat_ok))
        elif '[!]' in clean:
            tag = 'err'
            self._stat_err += 1
            self._err_var.set(str(self._stat_err))
        elif '[?]' in clean:
            tag = 'warn'
        else:
            tag = 'info'
        tb = self._log_box._textbox
        tb.configure(state='normal')
        tb.insert('end', clean + '\n', tag)
        tb.see('end')
        tb.configure(state='disabled')

    # ── Watch tab: events ─────────────────────────────────────────────────────
    def _pick_input(self):
        d = filedialog.askdirectory(title="Chọn thư mục đầu vào")
        if d:
            self.in_entry.delete(0, "end")
            self.in_entry.insert(0, d)

    def _pick_output(self):
        d = filedialog.askdirectory(title="Chọn thư mục đầu ra")
        if d:
            self.out_entry.delete(0, "end")
            self.out_entry.insert(0, d)

    def _on_mode_change(self, _v):
        hints = {
            '1': "OCR đọc mã số, lấy 3 số cuối để đặt tên file.",
            '2': "OCR đọc mã số, lấy 4 số cuối để đặt tên file.",
            '3': "Chỉ nén + ép phẳng chữ ký/mộc đỏ, giữ nguyên tên file (không OCR).",
        }
        self._mode_hint.configure(text=hints[self._current_mode()])

    def _on_quality_change(self, value):
        self._q_label.configure(text=str(int(value)))

    def _current_mode(self):
        return {"Lấy 3 số": '1', "Lấy 4 số": '2', "Giữ nguyên tên": '3'}[self._mode_btn.get()]

    # ── Watch control ─────────────────────────────────────────────────────────
    def _toggle_watch(self):
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self._start_btn.configure(text="Đang dừng…", state="disabled")
        else:
            self._start_watch()

    def _start_watch(self):
        input_dir  = self.in_entry.get().strip()
        output_dir = self.out_entry.get().strip()
        mode       = self._current_mode()
        quality    = int(self._q_slider.get())

        if mode in ('1', '2') and not core.kiem_tra_tesseract():
            messagebox.showerror(
                "Thiếu Tesseract-OCR",
                "Chế độ đọc mã số cần cài Tesseract-OCR.\n\n"
                "Tải tại: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "Nhớ tick 'Vietnamese' khi cài.\n\n"
                "Hoặc dùng chế độ 'Giữ nguyên tên' (không cần OCR).")
            return
        if not input_dir:
            messagebox.showwarning("Thiếu thư mục", "Hãy chọn thư mục đầu vào.")
            return

        self.settings = {'input_dir': input_dir, 'output_dir': output_dir,
                         'mode': mode, 'jpeg_quality': quality}
        save_settings(self.settings)
        core.JPEG_QUALITY = quality

        self.stop_event.clear()
        self._set_running(True)
        self.worker = threading.Thread(
            target=self._watch_loop,
            args=(input_dir, output_dir, mode), daemon=True)
        self.worker.start()

    def _set_running(self, running):
        if running:
            self._start_btn.configure(
                text="■  DỪNG THEO DÕI", state="normal",
                fg_color=("#c0392b", "#922b21"), hover_color="#7b241c")
            self._status_label.configure(text="● Đang chạy", text_color=CLR_OK)
            for w in (self.in_entry, self.out_entry, self._mode_btn, self._q_slider):
                w.configure(state="disabled")
        else:
            self._start_btn.configure(
                text="▶  BẮT ĐẦU THEO DÕI", state="normal",
                fg_color=self._btn_fg, hover_color=self._btn_hover)
            self._status_label.configure(text="● Dừng", text_color=CLR_MUTED)
            for w in (self.in_entry, self.out_entry, self._mode_btn, self._q_slider):
                w.configure(state="normal")

    def _watch_loop(self, input_dir, output_dir, mode):
        old_stdout = sys.stdout
        sys.stdout = LogWriter(self.log_queue)
        try:
            log_dir       = os.path.join(BASE_DIR, 'Loi_OCR')
            processed_dir = os.path.join(input_dir, 'DaXuLy')
            for d in (input_dir, output_dir, log_dir, processed_dir):
                os.makedirs(d, exist_ok=True)

            extract = core.extract_serial_number_3so if mode == '1' \
                else core.extract_serial_number_4so
            print(f"Bắt đầu theo dõi: {input_dir}")
            print(f"Xuất kết quả ra : {output_dir}")

            while not self.stop_event.is_set():
                files = [f for f in os.listdir(input_dir)
                         if f.lower().endswith('.pdf')
                         and os.path.isfile(os.path.join(input_dir, f))]
                for filename in files:
                    if self.stop_event.is_set():
                        break
                    if not core.is_file_stable(os.path.join(input_dir, filename)):
                        continue
                    if mode == '3':
                        core.process_one_file_giu_ten(
                            filename, input_dir, output_dir, processed_dir)
                    else:
                        core.process_one_file(
                            filename, input_dir, output_dir,
                            log_dir, processed_dir, extract)
                self.stop_event.wait(core.WATCH_INTERVAL_SECONDS)

            print("Đã dừng theo dõi.")
        except Exception as e:
            print(f"LỖI: {e}")
        finally:
            sys.stdout = old_stdout
            self.after(0, lambda: self._set_running(False))

    # ── Log helpers ───────────────────────────────────────────────────────────
    def _clear_log(self):
        tb = self._log_box._textbox
        tb.configure(state='normal')
        tb.delete('1.0', 'end')
        tb.configure(state='disabled')

    def _pr_insert(self, msg, tag='info'):
        tb = self._preview_rename_box._textbox
        tb.configure(state='normal')
        tb.insert('end', msg + '\n', tag)
        tb.see('end')
        tb.configure(state='disabled')

    def _pr_clear(self):
        tb = self._preview_rename_box._textbox
        tb.configure(state='normal')
        tb.delete('1.0', 'end')
        tb.configure(state='disabled')

    # ── Rename preview ────────────────────────────────────────────────────────
    def _start_preview_rename(self):
        input_dir = self.in_entry.get().strip()
        mode = self._current_mode()

        self._pr_clear()
        if not input_dir or not os.path.isdir(input_dir):
            self._pr_insert("Thư mục đầu vào không hợp lệ.", 'err')
            return
        if mode == '3':
            self._pr_insert("Chế độ Giữ nguyên tên — không đổi tên file.", 'muted')
            return

        pdfs = sorted(f for f in os.listdir(input_dir) if f.lower().endswith('.pdf'))
        if not pdfs:
            self._pr_insert("Không có file PDF nào trong thư mục đầu vào.", 'warn')
            return

        self._pr_insert(f"Quét {len(pdfs)} file… (OCR mỗi file ~1-3 giây)", 'info')
        extract_fn = (core.extract_serial_number_3so if mode == '1'
                      else core.extract_serial_number_4so)

        def run():
            for filename in pdfs:
                path = os.path.join(input_dir, filename)
                try:
                    serial = extract_fn(path)
                    if serial:
                        line, tag = f"  {filename}  →  {serial}.pdf", 'ok'
                    else:
                        line, tag = f"  {filename}  →  OCR thất bại", 'err'
                except Exception as e:
                    line, tag = f"  {filename}  →  Lỗi: {e}", 'err'
                self.after(0, lambda l=line, t=tag: self._pr_insert(l, t))
            self.after(0, lambda: self._pr_insert("─ Xong ─", 'muted'))

        threading.Thread(target=run, daemon=True).start()

    def _on_close(self):
        self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
