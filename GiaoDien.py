import os
import sys
import re
import json
import queue
import shutil
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
import pymupdf as fitz
from PIL import Image, ImageTk
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
        self._merge_files: list[str] = []
        self._preview_visible = False
        self._preview_doc = None
        self._preview_page = 0
        self._preview_photo = None

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
        self._tabs.add("🔧  Công Cụ PDF")
        self._build_watch_tab(self._tabs.tab("⚡  Theo Dõi Tự Động"))
        self._build_tools_tab(self._tabs.tab("🔧  Công Cụ PDF"))

    # ── Tab 1 : Theo Dõi ──────────────────────────────────────────────────────
    def _build_watch_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)
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

        # Nút bắt đầu / dừng
        self._start_btn = ctk.CTkButton(
            tab, text="▶  BẮT ĐẦU THEO DÕI", height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._toggle_watch)
        self._start_btn.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 10))
        self._btn_fg    = self._start_btn.cget("fg_color")
        self._btn_hover = self._start_btn.cget("hover_color")

        # Log box
        self._log_box = ctk.CTkTextbox(
            tab, font=ctk.CTkFont(family="Consolas", size=12))
        self._log_box.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 4))
        self._log_box.configure(state="disabled")

        self._on_mode_change(self._mode_btn.get())

    # ── Tab 2 : Công Cụ PDF ───────────────────────────────────────────────────
    def _build_tools_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Top bar: tool selector + preview toggle
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 10))
        top.grid_columnconfigure(0, weight=1)

        self._tool_sel = ctk.CTkSegmentedButton(
            top,
            values=["📎 Ghép PDF", "✂ Tách PDF", "↻ Xoay Trang", "ℹ Thông Tin"],
            command=self._switch_tool)
        self._tool_sel.grid(row=0, column=0, sticky="ew")
        self._tool_sel.set("📎 Ghép PDF")

        self._preview_btn = ctk.CTkButton(
            top, text="👁 Xem Trước", width=120,
            command=self._toggle_preview)
        self._preview_btn.grid(row=0, column=1, padx=(8, 0))

        # Body: tools col 0, preview col 1
        self._body_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self._body_frame.grid(row=1, column=0, sticky="nsew")
        self._body_frame.grid_columnconfigure(0, weight=3)
        self._body_frame.grid_rowconfigure(0, weight=1)

        container = ctk.CTkFrame(self._body_frame, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        self._tool_frames: dict[str, ctk.CTkFrame] = {}
        for name, builder in [
            ("📎 Ghép PDF",   self._build_merge_tool),
            ("✂ Tách PDF",   self._build_split_tool),
            ("↻ Xoay Trang", self._build_rotate_tool),
            ("ℹ Thông Tin",  self._build_info_tool),
        ]:
            f = ctk.CTkFrame(container, fg_color="transparent")
            f.grid(row=0, column=0, sticky="nsew")
            f.grid_columnconfigure(0, weight=1)
            builder(f)
            self._tool_frames[name] = f

        self._switch_tool("📎 Ghép PDF")
        self._build_preview_panel()

    def _switch_tool(self, name):
        for f in self._tool_frames.values():
            f.grid_remove()
        self._tool_frames[name].grid()

    # ── Preview panel ─────────────────────────────────────────────────────────
    def _build_preview_panel(self):
        self._preview_frame = ctk.CTkFrame(self._body_frame, width=300)
        self._preview_frame.grid_rowconfigure(1, weight=1)
        self._preview_frame.grid_columnconfigure(0, weight=1)

        nav = ctk.CTkFrame(self._preview_frame, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        ctk.CTkButton(nav, text="◀", width=32,
                      command=lambda: self._preview_nav(-1)).pack(side="left")
        self._page_label = ctk.CTkLabel(nav, text="— / —", width=80)
        self._page_label.pack(side="left", expand=True)
        ctk.CTkButton(nav, text="▶", width=32,
                      command=lambda: self._preview_nav(1)).pack(side="left")

        cf = ctk.CTkFrame(self._preview_frame)
        cf.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        cf.grid_rowconfigure(0, weight=1)
        cf.grid_columnconfigure(0, weight=1)

        self._preview_canvas = tk.Canvas(cf, bg="#1a1a2e", highlightthickness=0)
        vsb = tk.Scrollbar(cf, orient="vertical", command=self._preview_canvas.yview)
        self._preview_canvas.configure(yscrollcommand=vsb.set)
        self._preview_canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._preview_canvas.bind("<Configure>", lambda e: self._render_preview())

    def _toggle_preview(self):
        self._preview_visible = not self._preview_visible
        if self._preview_visible:
            self._body_frame.grid_columnconfigure(1, weight=2)
            self._preview_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
            self._preview_btn.configure(text="✕ Ẩn Preview")
            self.geometry("1200x760")
            self._render_preview()
        else:
            self._preview_frame.grid_remove()
            self._body_frame.grid_columnconfigure(1, weight=0)
            self._preview_btn.configure(text="👁 Xem Trước")
            self.geometry("840x760")

    def _load_preview(self, path):
        try:
            if self._preview_doc:
                self._preview_doc.close()
            self._preview_doc = fitz.open(path)
            self._preview_page = 0
            if self._preview_visible:
                self._render_preview()
        except Exception:
            pass

    def _preview_nav(self, delta):
        if not self._preview_doc:
            return
        total = len(self._preview_doc)
        self._preview_page = max(0, min(total - 1, self._preview_page + delta))
        self._render_preview()

    def _render_preview(self):
        if not self._preview_doc or not self._preview_visible:
            return
        doc = self._preview_doc
        total = len(doc)
        page = doc[self._preview_page]
        self._page_label.configure(text=f"{self._preview_page + 1} / {total}")
        cw = self._preview_canvas.winfo_width() or 280
        if cw < 10:
            cw = 280
        scale = cw / page.rect.width
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self._preview_photo = ImageTk.PhotoImage(img)
        self._preview_canvas.configure(
            scrollregion=(0, 0, pix.width, pix.height))
        self._preview_canvas.delete("all")
        self._preview_canvas.create_image(0, 0, anchor="nw",
                                          image=self._preview_photo)

    # ── Ghép PDF ──────────────────────────────────────────────────────────────
    def _build_merge_tool(self, p):
        p.grid_rowconfigure(1, weight=1)
        P = dict(padx=8, pady=(0, 8))

        # Nút điều khiển danh sách
        btn_row = ctk.CTkFrame(p, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="ew", **P)
        _grey = dict(fg_color=("gray70","gray30"), hover_color=("gray60","gray40"),
                     text_color=("black","white"))
        ctk.CTkButton(btn_row, text="+ Thêm file", width=110,
                      command=self._merge_add).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_row, text="− Xóa chọn", width=110,
                      command=self._merge_remove, **_grey).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_row, text="↑ Lên",   width=72,
                      command=lambda: self._merge_move(-1), **_grey).pack(side="left", padx=(0,4))
        ctk.CTkButton(btn_row, text="↓ Xuống", width=80,
                      command=lambda: self._merge_move(1),  **_grey).pack(side="left")

        # Listbox
        lf = ctk.CTkFrame(p)
        lf.grid(row=1, column=0, sticky="nsew", **P)
        lf.grid_rowconfigure(0, weight=1)
        lf.grid_columnconfigure(0, weight=1)

        self._merge_lb = tk.Listbox(
            lf, bg="#1e2130", fg="#d0d4e0",
            selectbackground="#3b82f6", selectforeground="white",
            relief="flat", bd=0, highlightthickness=0,
            font=("Consolas", 11), activestyle="none")
        sb = tk.Scrollbar(lf, command=self._merge_lb.yview)
        self._merge_lb.config(yscrollcommand=sb.set)
        self._merge_lb.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        sb.grid(row=0, column=1, sticky="ns", pady=6)

        # Đầu ra
        out_row = ctk.CTkFrame(p, fg_color="transparent")
        out_row.grid(row=2, column=0, sticky="ew", **P)
        out_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(out_row, text="Lưu ra:", width=70).grid(row=0, column=0, sticky="w")
        self._merge_out = ctk.CTkEntry(out_row, placeholder_text="Chọn file đầu ra…")
        self._merge_out.grid(row=0, column=1, padx=8, sticky="ew")
        ctk.CTkButton(out_row, text="Chọn…", width=80,
                      command=self._merge_pick_out).grid(row=0, column=2)

        ctk.CTkButton(p, text="▶  GHÉP PDF", height=40,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._do_merge).grid(row=3, column=0, sticky="ew", padx=8, pady=(4,4))
        self._make_tool_log(p, 4, '_merge_log')

    def _merge_add(self):
        paths = filedialog.askopenfilenames(
            title="Chọn file PDF để ghép",
            filetypes=[("PDF files", "*.pdf")])
        for path in paths:
            if path not in self._merge_files:
                self._merge_files.append(path)
                self._merge_lb.insert("end", os.path.basename(path))

    def _merge_remove(self):
        sel = self._merge_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self._merge_lb.delete(idx)
        self._merge_files.pop(idx)

    def _merge_move(self, direction):
        sel = self._merge_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._merge_files):
            return
        self._merge_files[idx], self._merge_files[new_idx] = \
            self._merge_files[new_idx], self._merge_files[idx]
        a = self._merge_lb.get(idx)
        b = self._merge_lb.get(new_idx)
        self._merge_lb.delete(idx);    self._merge_lb.insert(idx,     b)
        self._merge_lb.delete(new_idx); self._merge_lb.insert(new_idx, a)
        self._merge_lb.selection_set(new_idx)

    def _merge_pick_out(self):
        p = filedialog.asksaveasfilename(
            title="Lưu file PDF ghép", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if p:
            self._merge_out.delete(0, "end")
            self._merge_out.insert(0, p)

    def _do_merge(self):
        if len(self._merge_files) < 2:
            messagebox.showwarning("Thiếu file", "Cần ít nhất 2 file PDF để ghép.")
            return
        out_path = self._merge_out.get().strip()
        if not out_path:
            messagebox.showwarning("Thiếu đường dẫn", "Chọn file đầu ra trước.")
            return
        self._tlog('_merge_log', f"Đang ghép {len(self._merge_files)} file…", 'info')
        files = list(self._merge_files)

        def run():
            try:
                import tools as T
                T.merge_pdfs(files, out_path)
                size = os.path.getsize(out_path) / (1024 * 1024)
                self.after(0, lambda: self._tlog(
                    '_merge_log',
                    f"✓ Xong → {os.path.basename(out_path)} ({size:.1f} MB)", 'ok'))
            except Exception as e:
                self.after(0, lambda: self._tlog('_merge_log', f"✗ Lỗi: {e}", 'err'))

        threading.Thread(target=run, daemon=True).start()

    # ── Tách PDF ──────────────────────────────────────────────────────────────
    def _build_split_tool(self, p):
        P = dict(padx=8, pady=(0, 8))
        for i, (lbl, attr, ph, cmd) in enumerate([
            ("File PDF:",           '_split_in',    "",                          self._split_pick_in),
            ("Trang:",              '_split_range', "vd: 1-3,5,7-10 hoặc all",  None),
            ("Lưu ra thư mục:",     '_split_out',   "",                          self._split_pick_out),
        ]):
            row = ctk.CTkFrame(p, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", **P)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=lbl, width=145, anchor="w").grid(row=0, column=0, sticky="w")
            e = ctk.CTkEntry(row, placeholder_text=ph)
            e.grid(row=0, column=1, padx=8, sticky="ew")
            setattr(self, attr, e)
            if cmd:
                ctk.CTkButton(row, text="Chọn…", width=80, command=cmd).grid(row=0, column=2)

        ctk.CTkButton(p, text="▶  TÁCH PDF", height=40,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._do_split).grid(row=3, column=0, sticky="ew", padx=8, pady=(4,4))
        self._make_tool_log(p, 4, '_split_log')

    def _split_pick_in(self):
        self._pick_pdf_into(self._split_in)

    def _split_pick_out(self):
        d = filedialog.askdirectory(title="Chọn thư mục lưu kết quả")
        if d:
            self._split_out.delete(0, "end")
            self._split_out.insert(0, d)

    def _do_split(self):
        in_path   = self._split_in.get().strip()
        ranges    = self._split_range.get().strip()
        out_dir   = self._split_out.get().strip()
        if not in_path:
            messagebox.showwarning("Thiếu", "Chọn file PDF đầu vào."); return
        if not ranges:
            messagebox.showwarning("Thiếu", "Nhập dải trang."); return
        if not out_dir:
            messagebox.showwarning("Thiếu", "Chọn thư mục đầu ra."); return
        self._tlog('_split_log', f"Đang tách: {os.path.basename(in_path)}…", 'info')

        def run():
            try:
                import tools as T
                files = T.split_pdf(in_path, out_dir, ranges)
                self.after(0, lambda: self._tlog(
                    '_split_log', f"✓ Tách xong → {len(files)} file trong {out_dir}", 'ok'))
            except Exception as e:
                self.after(0, lambda: self._tlog('_split_log', f"✗ Lỗi: {e}", 'err'))

        threading.Thread(target=run, daemon=True).start()

    # ── Xoay Trang ────────────────────────────────────────────────────────────
    def _build_rotate_tool(self, p):
        P = dict(padx=8, pady=(0, 8))

        # File đầu vào
        r0 = ctk.CTkFrame(p, fg_color="transparent")
        r0.grid(row=0, column=0, sticky="ew", **P)
        r0.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(r0, text="File PDF:", width=120, anchor="w").grid(row=0, column=0, sticky="w")
        self._rot_in = ctk.CTkEntry(r0)
        self._rot_in.grid(row=0, column=1, padx=8, sticky="ew")
        ctk.CTkButton(r0, text="Chọn…", width=80,
                      command=lambda: self._pick_pdf_into(self._rot_in)).grid(row=0, column=2)

        # Trang
        r1 = ctk.CTkFrame(p, fg_color="transparent")
        r1.grid(row=1, column=0, sticky="ew", **P)
        r1.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(r1, text="Trang:", width=120, anchor="w").grid(row=0, column=0, sticky="w")
        self._rot_pages = ctk.CTkEntry(r1, placeholder_text="all  hoặc  1-3,5")
        self._rot_pages.grid(row=0, column=1, padx=8, sticky="ew")

        # Góc xoay
        r2 = ctk.CTkFrame(p, fg_color="transparent")
        r2.grid(row=2, column=0, sticky="ew", **P)
        ctk.CTkLabel(r2, text="Góc xoay:", width=120, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(8, 0))
        self._rot_angle = ctk.CTkSegmentedButton(r2, values=["90°", "180°", "270°"])
        self._rot_angle.set("90°")
        self._rot_angle.grid(row=0, column=1, padx=8, sticky="w")

        # File đầu ra
        r3 = ctk.CTkFrame(p, fg_color="transparent")
        r3.grid(row=3, column=0, sticky="ew", **P)
        r3.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(r3, text="Lưu ra:", width=120, anchor="w").grid(row=0, column=0, sticky="w")
        self._rot_out = ctk.CTkEntry(r3, placeholder_text="Để trống = ghi đè file gốc")
        self._rot_out.grid(row=0, column=1, padx=8, sticky="ew")
        ctk.CTkButton(r3, text="Chọn…", width=80,
                      command=self._rot_pick_out).grid(row=0, column=2)

        ctk.CTkButton(p, text="▶  XOAY TRANG", height=40,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._do_rotate).grid(row=4, column=0, sticky="ew", padx=8, pady=(4,4))
        self._make_tool_log(p, 5, '_rot_log')

    def _rot_pick_out(self):
        path = filedialog.asksaveasfilename(
            title="Lưu file PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if path:
            self._rot_out.delete(0, "end")
            self._rot_out.insert(0, path)

    def _do_rotate(self):
        in_path   = self._rot_in.get().strip()
        pages_str = self._rot_pages.get().strip() or 'all'
        angle     = int(self._rot_angle.get().rstrip('°'))
        out_path  = self._rot_out.get().strip() or in_path
        if not in_path:
            messagebox.showwarning("Thiếu", "Chọn file PDF."); return
        self._tlog('_rot_log', f"Đang xoay trang {pages_str} @ {angle}°…", 'info')

        def run():
            try:
                import tools as T
                if out_path == in_path:
                    tmp = in_path + '._tmp_rot.pdf'
                    T.rotate_pages(in_path, tmp, pages_str, angle)
                    shutil.move(tmp, in_path)
                    result = in_path
                else:
                    T.rotate_pages(in_path, out_path, pages_str, angle)
                    result = out_path
                self.after(0, lambda: self._tlog(
                    '_rot_log', f"✓ Xong → {os.path.basename(result)}", 'ok'))
            except Exception as e:
                self.after(0, lambda: self._tlog('_rot_log', f"✗ Lỗi: {e}", 'err'))

        threading.Thread(target=run, daemon=True).start()

    # ── Thông Tin ─────────────────────────────────────────────────────────────
    def _build_info_tool(self, p):
        p.grid_rowconfigure(1, weight=1)
        P = dict(padx=8, pady=(0, 8))

        r0 = ctk.CTkFrame(p, fg_color="transparent")
        r0.grid(row=0, column=0, sticky="ew", **P)
        r0.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(r0, text="File PDF:", width=80, anchor="w").grid(row=0, column=0, sticky="w")
        self._info_in = ctk.CTkEntry(r0)
        self._info_in.grid(row=0, column=1, padx=8, sticky="ew")
        ctk.CTkButton(r0, text="Chọn…", width=80,
                      command=lambda: self._pick_pdf_into(self._info_in)).grid(row=0, column=2)
        ctk.CTkButton(r0, text="📋 Xem", width=70,
                      command=self._do_info).grid(row=0, column=3, padx=(6, 0))

        self._make_tool_log(p, 1, '_info_log')

    def _do_info(self):
        in_path = self._info_in.get().strip()
        if not in_path:
            messagebox.showwarning("Thiếu", "Chọn file PDF."); return
        try:
            import tools as T
            info = T.pdf_info(in_path)
            lines = [
                f"File    : {os.path.basename(in_path)}",
                f"Số trang: {info['page_count']}",
                f"Dung lượng: {info['file_size_mb']:.2f} MB",
                "─" * 36,
            ]
            for pg in info['pages'][:30]:
                lines.append(f"  Trang {pg['num']:>3}: {pg['w']} × {pg['h']} pt")
            if info['page_count'] > 30:
                lines.append(f"  … (còn {info['page_count'] - 30} trang)")
            for line in lines:
                self._tlog('_info_log', line, 'info')
        except Exception as e:
            self._tlog('_info_log', f"✗ Lỗi: {e}", 'err')

    # ── Tool log helpers ──────────────────────────────────────────────────────
    def _make_tool_log(self, parent, row, attr):
        log = ctk.CTkTextbox(parent, font=ctk.CTkFont(family="Consolas", size=11), height=130)
        log.grid(row=row, column=0, sticky="nsew", padx=8, pady=(0, 4))
        log.configure(state="disabled")
        setattr(self, attr, log)
        tb = log._textbox
        tb.tag_config('ok',   foreground=CLR_OK)
        tb.tag_config('err',  foreground=CLR_ERR)
        tb.tag_config('warn', foreground=CLR_WARN)
        tb.tag_config('info', foreground=CLR_INFO)

    def _tlog(self, attr, msg, tag='info'):
        log = getattr(self, attr)
        tb = log._textbox
        tb.configure(state='normal')
        tb.insert('end', msg + '\n', tag)
        tb.see('end')
        tb.configure(state='disabled')

    # ── Shared helper ─────────────────────────────────────────────────────────
    def _pick_pdf_into(self, entry):
        p = filedialog.askopenfilename(title="Chọn file PDF",
                                       filetypes=[("PDF files", "*.pdf")])
        if p:
            entry.delete(0, "end")
            entry.insert(0, p)
            self._load_preview(p)

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

    def _on_close(self):
        self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
