import os
import ctypes
from PIL import Image

class SH1107Device:
    """
    Direct hardware SH1107 128x128 OLED driver using open-drain bitbanging.
    Optimized with C-level pixel packing and dirty page tracking.
    Immune to ACK/NACK errors from unidirectional level shifters.
    """
    def __init__(self, width=128, height=128, rotate=0):
        self.width = width
        self.height = height
        self.rotate = rotate
        self.bounding_box = (0, 0, width - 1, height - 1)
        
        lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libsh1107.so")
        if not os.path.exists(lib_path):
            c_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libsh1107.c")
            os.system(f"gcc -O3 -shared -fPIC {c_src} -o {lib_path}")
            
        self._lib = ctypes.CDLL(lib_path)
        self._lib.sh1107_init.restype = ctypes.c_int
        self._lib.sh1107_contrast.argtypes = [ctypes.c_uint8]
        self._lib.sh1107_display_raw.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int]
        
        ret = self._lib.sh1107_init()
        if ret != 0:
            raise RuntimeError(f"Failed to initialize SH1107 (error {ret})")
            
        self.clear()

    def display(self, image):
        if self.rotate == 1:
            image = image.rotate(90)
        elif self.rotate == 2:
            image = image.rotate(180)
        elif self.rotate == 3:
            image = image.rotate(270)
            
        if image.mode != "1":
            image = image.convert("1")
            
        # image.tobytes() produces 128x128 raw 1bpp in 0.1ms!
        raw_bytes = image.tobytes()
        c_buf = (ctypes.c_uint8 * 2048).from_buffer_copy(raw_bytes)
        self._lib.sh1107_display_raw(c_buf, 0)

    def clear(self):
        self._lib.sh1107_clear()

    def contrast(self, val):
        self._lib.sh1107_contrast(int(val) & 0xFF)

    def show(self):
        pass

    def hide(self):
        self.clear()
