import os
import sys
import pickle as pkl
import platform
from PIL import Image, ImageFont, ImageDraw

# ==========================================
# 核心逻辑：字模生成 (恢复大画布裁剪逻辑)
# ==========================================
class CharToBitmap:
    def __init__(self, font_path=None, size=16):
        self.size = size
        if font_path is None:
            font_path = self._get_default_font()
        try:
            self.font = ImageFont.truetype(font_path, size)
        except IOError:
            print(f"Warning: 无法加载字体 {font_path}，尝试使用默认 Arial")
            try:
                self.font = ImageFont.truetype("arial.ttf", size)
            except:
                print("Error: 无法加载任何字体，文字生成将失败。")
                self.font = None

    def _get_default_font(self):
        """自动寻找系统字体"""
        sys_plat = platform.system()
        paths = []
        if sys_plat == "Windows":
            paths = ["C:\\Windows\\Fonts\\msyh.ttc", "C:\\Windows\\Fonts\\simhei.ttf", "C:\\Windows\\Fonts\\arial.ttf"]
        elif sys_plat == "Darwin":
            paths = ["/System/Library/Fonts/PingFang.ttc", "/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial.ttf"]
        else:
            paths = ["/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
            
        for p in paths:
            if os.path.exists(p):
                return p
        return "arial.ttf"

    def get_coordinates_set(self, char):
        """
        获取汉字所有“亮点”的坐标集合 (set格式，方便查询)
        【关键修复】使用大画布绘制+裁剪+居中逻辑，防止边缘被切
        Returns: set of (x, y)
        """
        if not self.font: return set()

        # 1. 创建 3 倍大小的临时画布，防止字画出界
        temp_size = self.size * 3
        temp_img = Image.new("1", (temp_size, temp_size), 0)
        draw = ImageDraw.Draw(temp_img)
        
        # 2. 随意画在画布中间
        draw.text((self.size, self.size), char, font=self.font, fill=1)
        
        # 3. 获取内容的实际边界 (Bounding Box)
        bbox = temp_img.getbbox()
        if not bbox:
            return set()
            
        # 4. 裁剪出只有字的最小矩形
        cropped = temp_img.crop(bbox)
        w, h = cropped.size
        
        # 5. 创建最终的目标画布
        final_img = Image.new("1", (self.size, self.size), 0)
        
        # 6. 计算绝对居中位置
        paste_x = (self.size - w) // 2
        paste_y = (self.size - h) // 2
        
        # 7. 贴上去
        final_img.paste(cropped, (paste_x, paste_y))

        # 8. 提取坐标
        coords = set()
        for py in range(self.size):
            for px in range(self.size):
                if final_img.getpixel((px, py)) > 0:
                    coords.add((px, py)) 
        return coords

# ==========================================
# 核心逻辑：3D 转换与缓存管理 (保持不变)
# ==========================================
class Text3DManager:
    def __init__(self, cache_file="../assets/models/word_bank_3d.pkl", font_size=16):
        self.cache_file = cache_file
        self.font_size = font_size
        self.converter = CharToBitmap(size=font_size, font_path="../assets/fonts/SourceHanSansSC-Normal.otf")
        self.data_3d = {}
        self.data_2d_cache = {} 
        self.load_cache()

    def load_cache(self):
        """加载本地缓存"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "rb") as f:
                    self.data_3d = pkl.load(f)
                print(f"[TextManager] 已加载缓存: {len(self.data_3d)} 个词条")
            except Exception as e:
                print(f"[TextManager] 缓存损坏，将重新生成: {e}")
                self.data_3d = {}
        else:
            print("[TextManager] 无缓存文件，初始化为空。")

    def save_cache(self):
        """保存缓存到本地"""
        try:
            folder = os.path.dirname(self.cache_file)
            if folder and not os.path.exists(folder):
                os.makedirs(folder)
            
            with open(self.cache_file, "wb") as f:
                pkl.dump(self.data_3d, f)
            print(f"[TextManager] 缓存已保存至 {self.cache_file}")
        except Exception as e:
            print(f"[TextManager] 保存缓存失败: {e}")

    def _get_2d_points(self, char):
        """获取单字的 2D 点集 (带运行时缓存)"""
        if char not in self.data_2d_cache:
            self.data_2d_cache[char] = self.converter.get_coordinates_set(char)
        return self.data_2d_cache[char]

    def get_word_data(self, key):
        """获取 3D 点数据。如果不存在，则自动生成。"""
        if key in self.data_3d:
            return self.data_3d[key]
        
        print(f"[TextManager] 生成新词条: '{key}' ...")
        points_3d = self._generate_3d_geometry(key)
        self.data_3d[key] = points_3d
        return points_3d

    def _generate_3d_geometry(self, key):
        """执行 3D 几何生成的数学逻辑"""
        parts = key.split("-")
        points = []
        fs = self.font_size

        # --- 模式 1: 单字 (挤压拉伸) ---
        if len(parts) == 1:
            char = parts[0]
            pixels = self._get_2d_points(char)
            # 2D图的 y 是向下的 (0在上面)，翻转一下变成 z 向上
            for x, z in pixels:
                real_z = (fs - 1) - z 
                points.append((x, 0, real_z))
                points.append((x, 1, real_z))
                points.append((x, -1, real_z))

        # --- 模式 2: 双字 (正交交叉) ---
        elif len(parts) == 2:
            char_x = parts[0]
            char_y = parts[1]
            set_x = self._get_2d_points(char_x)
            set_y = self._get_2d_points(char_y)

            for i in range(fs): # x
                for j in range(fs): # y
                    for k in range(fs): # z (raw image y)
                        if (i, k) in set_x and (j, k) in set_y:
                            real_z = (fs - 1) - k
                            points.append((i, j, real_z))

        # --- 模式 3: 三字 (三视图交叉) ---
        elif len(parts) == 3:
            char_1 = parts[0]
            char_2 = parts[1]
            char_3 = parts[2]
            set_1 = self._get_2d_points(char_1)
            set_2 = self._get_2d_points(char_2)
            set_3 = self._get_2d_points(char_3)
            
            for i in range(fs):
                for j in range(fs):
                    for k in range(fs):
                        if (i, k) in set_1 and (j, k) in set_2 and (i, 15-j) in set_3:
                            real_z = (fs - 1) - k
                            points.append((i, j, real_z))

        return points

    def scan_script_and_update(self, json_data):
        """扫描脚本 JSON，找出所有需要的文字，检查缺失并自动生成。"""
        needed_keys = set()
        if "firework" in json_data:
            for group in json_data["firework"]:
                events = group[1]
                for event in events:
                    strategy = event.get("strategy")
                    if isinstance(strategy, dict):
                        if strategy.get("name") == "text_shape_3d":
                            args = strategy.get("args", [])
                            if args:
                                needed_keys.add(args[0])

        dirty = False
        for key in needed_keys:
            if key not in self.data_3d:
                self.get_word_data(key)
                dirty = True
        
        if dirty:
            self.save_cache()
            print("[TextManager] 发现新词条，缓存已更新。")
        else:
            print("[TextManager] 所有词条完整，无需更新。")

_instance = None
def get_manager(resource_path_func=None):
    global _instance
    if _instance is None:
        path = "word_bank_3d.pkl"
        if resource_path_func:
            path = resource_path_func("word_bank_3d.pkl")
        _instance = Text3DManager(path)
    return _instance

if __name__ == "__main__":
    mgr = Text3DManager()
    mgr.get_word_data("测试")
    mgr.save_cache()
