#  Mở file NÀY (ChayGiaoDien.pyw) để chạy giao diện KHÔNG hiện cửa sổ cmd đen.
#  (.pyw chạy bằng pythonw.exe -> không kèm console)
import os
import sys

# pythonw.exe không có console -> sys.stdout/stderr = None, khiến print()/colorama lỗi.
# Gán tạm về file rỗng để mọi print trong lúc khởi động không làm sập chương trình.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import GiaoDien

GiaoDien.App().mainloop()
