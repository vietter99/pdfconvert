import os
import sys
import re
import json
import time
import queue
import threading
import subprocess


# --- TỰ ĐỘNG CÀI THƯ VIỆN GIAO DIỆN ---
def ensure_gui_packages():
    for pkg, imp in {'customtkinter': 'customtkinter'}.items():
        try:
            __import__(imp)
        except ImportError:
            print(f"[*] Installing GUI library: {pkg} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])


ensure_gui_packages()

import customtkinter as ctk
from tkinter import filedialog, messagebox

# Tái dùng toàn bộ logic xử lý PDF/OCR từ file gốc (không viết lại)
import Auto_PDF as core

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_JSON = os.path.join(BASE_DIR, 'config.json')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def load_settings():
    data = {
        'input_dir': os.path.join(BASE_DIR, 'DauVao'),
        'output_dir': os.path.join(BASE_DIR, 'DauRa'),
        'mode': '1',
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


class LogWriter:
    """Chuyển mọi print() của phần xử lý vào khung log trên giao diện (đã bỏ mã màu ANSI)."""
    def __init__(self, q):
        self.q = q

    def write(self, text):
        clean = ANSI_RE.sub('', text)
        if clean.strip():
            self.q.put(clean)

    def flush(self):
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.log_queue = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        self.title("Xử lý PDF - BY VIỆT")
        self.geometry("760x640")
        self.minsize(680, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        pad = {'padx': 20, 'pady': (0, 12)}

        # Tiêu đề
        ctk.CTkLabel(self, text="PHẦN MỀM XỬ LÝ PDF",
                     font=ctk.CTkFont(size=24, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(20, 4), sticky="w")
        ctk.CTkLabel(self, text="Tự động nén, đổi tên theo mã số, theo dõi thư mục scan",
                     text_color=("gray40", "gray60")).grid(
            row=1, column=0, padx=20, pady=(0, 16), sticky="w")

        # Khung chọn thư mục
        folder_frame = ctk.CTkFrame(self)
        folder_frame.grid(row=2, column=0, sticky="ew", **pad)
        folder_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(folder_frame, text="Thư mục ĐẦU VÀO (scan):").grid(
            row=0, column=0, padx=12, pady=12, sticky="w")
        self.in_entry = ctk.CTkEntry(folder_frame)
        self.in_entry.grid(row=0, column=1, padx=8, pady=12, sticky="ew")
        self.in_entry.insert(0, self.settings['input_dir'])
        ctk.CTkButton(folder_frame, text="Chọn...", width=90,
                      command=self.pick_input).grid(row=0, column=2, padx=12, pady=12)

        ctk.CTkLabel(folder_frame, text="Thư mục ĐẦU RA (kết quả):").grid(
            row=1, column=0, padx=12, pady=(0, 12), sticky="w")
        self.out_entry = ctk.CTkEntry(folder_frame)
        self.out_entry.grid(row=1, column=1, padx=8, pady=(0, 12), sticky="ew")
        self.out_entry.insert(0, self.settings['output_dir'])
        ctk.CTkButton(folder_frame, text="Chọn...", width=90,
                      command=self.pick_output).grid(row=1, column=2, padx=12, pady=(0, 12))

        # Khung chế độ + chất lượng nén
        mode_frame = ctk.CTkFrame(self)
        mode_frame.grid(row=3, column=0, sticky="ew", **pad)
        mode_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(mode_frame, text="Chế độ xử lý:",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 6), sticky="w")
        self.mode_var = ctk.StringVar(value=self.settings['mode'])
        self.mode_menu = ctk.CTkSegmentedButton(
            mode_frame,
            values=["Lấy 3 số", "Lấy 4 số", "Giữ nguyên tên"],
            command=self.on_mode_change)
        self.mode_menu.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        self.mode_menu.set({'1': "Lấy 3 số", '2': "Lấy 4 số", '3': "Giữ nguyên tên"}[self.settings['mode']])

        self.mode_hint = ctk.CTkLabel(mode_frame, text="", text_color=("gray40", "gray60"))
        self.mode_hint.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="w")

        q_row = ctk.CTkFrame(mode_frame, fg_color="transparent")
        q_row.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        q_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(q_row, text="Mức nén ảnh:").grid(row=0, column=0, sticky="w")
        self.q_value = ctk.CTkLabel(q_row, text=str(self.settings['jpeg_quality']), width=36)
        self.q_value.grid(row=0, column=2, padx=(8, 0))
        self.q_slider = ctk.CTkSlider(q_row, from_=20, to=95, number_of_steps=75,
                                      command=self.on_quality_change)
        self.q_slider.grid(row=0, column=1, padx=12, sticky="ew")
        self.q_slider.set(self.settings['jpeg_quality'])

        # Nút điều khiển
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 12))
        btn_frame.grid_columnconfigure(0, weight=1)
        self.start_btn = ctk.CTkButton(btn_frame, text="▶  BẮT ĐẦU THEO DÕI",
                                       height=44, font=ctk.CTkFont(size=15, weight="bold"),
                                       command=self.toggle_watch)
        self.start_btn.grid(row=0, column=0, sticky="ew")
        self._btn_fg = self.start_btn.cget("fg_color")
        self._btn_hover = self.start_btn.cget("hover_color")

        # Khung log
        self.log_box = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=5, column=0, sticky="nsew", padx=20, pady=(0, 16))
        self.log_box.configure(state="disabled")

        self.on_mode_change(self.mode_menu.get())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self.drain_log)

    # --- Sự kiện ---
    def pick_input(self):
        d = filedialog.askdirectory(title="Chọn thư mục đầu vào")
        if d:
            self.in_entry.delete(0, "end")
            self.in_entry.insert(0, d)

    def pick_output(self):
        d = filedialog.askdirectory(title="Chọn thư mục đầu ra")
        if d:
            self.out_entry.delete(0, "end")
            self.out_entry.insert(0, d)

    def on_mode_change(self, _value):
        mode = self.current_mode()
        hints = {
            '1': "OCR đọc mã số, lấy 3 số cuối để đặt tên file.",
            '2': "OCR đọc mã số, lấy 4 số cuối để đặt tên file.",
            '3': "Chỉ nén + ép phẳng chữ ký/mộc đỏ, giữ nguyên tên file (không OCR).",
        }
        self.mode_hint.configure(text=hints[mode])

    def on_quality_change(self, value):
        self.q_value.configure(text=str(int(value)))

    def current_mode(self):
        return {"Lấy 3 số": '1', "Lấy 4 số": '2', "Giữ nguyên tên": '3'}[self.mode_menu.get()]

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg if msg.endswith("\n") else msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def drain_log(self):
        try:
            while True:
                self.log(self.log_queue.get_nowait().rstrip("\n"))
        except queue.Empty:
            pass
        self.after(150, self.drain_log)

    # --- Theo dõi ---
    def toggle_watch(self):
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.start_btn.configure(text="Đang dừng...", state="disabled")
            return
        self.start_watch()

    def start_watch(self):
        input_dir = self.in_entry.get().strip()
        output_dir = self.out_entry.get().strip()
        mode = self.current_mode()
        quality = int(self.q_slider.get())

        if mode in ('1', '2') and not core.kiem_tra_tesseract():
            messagebox.showerror(
                "Thiếu Tesseract-OCR",
                "Chế độ đọc mã số cần cài Tesseract-OCR.\n\n"
                "Tải tại: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "Nhớ tick chọn 'Vietnamese' khi cài.\n\n"
                "Hoặc dùng chế độ 'Giữ nguyên tên' (không cần OCR).")
            return

        if not input_dir:
            messagebox.showwarning("Thiếu thư mục", "Hãy chọn thư mục đầu vào.")
            return

        self.settings = {'input_dir': input_dir, 'output_dir': output_dir,
                         'mode': mode, 'jpeg_quality': quality}
        save_settings(self.settings)
        core.JPEG_QUALITY = quality  # áp mức nén người dùng chọn

        self.stop_event.clear()
        self.set_running(True)
        self.worker = threading.Thread(
            target=self.watch_loop,
            args=(input_dir, output_dir, mode), daemon=True)
        self.worker.start()

    def set_running(self, running):
        if running:
            self.start_btn.configure(text="■  DỪNG THEO DÕI", state="normal",
                                     fg_color=("#c0392b", "#922b21"), hover_color="#7b241c")
            for w in (self.in_entry, self.out_entry, self.mode_menu, self.q_slider):
                w.configure(state="disabled")
        else:
            self.start_btn.configure(text="▶  BẮT ĐẦU THEO DÕI", state="normal",
                                     fg_color=self._btn_fg, hover_color=self._btn_hover)
            for w in (self.in_entry, self.out_entry, self.mode_menu, self.q_slider):
                w.configure(state="normal")

    def watch_loop(self, input_dir, output_dir, mode):
        old_stdout = sys.stdout
        sys.stdout = LogWriter(self.log_queue)
        try:
            log_dir = os.path.join(BASE_DIR, 'Loi_OCR')
            processed_dir = os.path.join(input_dir, 'DaXuLy')
            for d in (input_dir, output_dir, log_dir, processed_dir):
                os.makedirs(d, exist_ok=True)

            extract = core.extract_serial_number_3so if mode == '1' else core.extract_serial_number_4so
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
                        core.process_one_file_giu_ten(filename, input_dir, output_dir, processed_dir)
                    else:
                        core.process_one_file(filename, input_dir, output_dir,
                                              log_dir, processed_dir, extract)
                self.stop_event.wait(core.WATCH_INTERVAL_SECONDS)

            print("Đã dừng theo dõi.")
        except Exception as e:
            print(f"LỖI: {e}")
        finally:
            sys.stdout = old_stdout
            self.after(0, lambda: self.set_running(False))

    def on_close(self):
        self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
