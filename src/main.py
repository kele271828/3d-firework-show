import sys
import os
import json
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.filter.CommonFilters import CommonFilters
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    Vec3, Point3, ColorBlendAttrib, Texture, PNMImage, 
    NodePath, TransparencyAttrib, CardMaker, LColor,
    loadPrcFileData,TextNode
)
import random
import math
import text_manager

# ==========================================
# 资源路径处理函数（必须在代码最前面添加）
# ==========================================
def fix_panda3d_path(path):
    """将Windows路径转换为Panda3D兼容的路径格式"""
    if path and isinstance(path, str):
        # 将反斜杠替换为正斜杠
        path = path.replace('\\', '/')
        # 如果有Windows盘符，转换为Unix风格
        if len(path) > 2 and path[1] == ':':
            # D:/path/to/file -> /D/path/to/file
            path = f"/{path[0].lower()}{path[2:]}"
    return path
def resource_path(relative_path):
    """获取资源文件的绝对路径（兼容开发环境和打包环境）"""
    try:
        # PyInstaller创建临时文件夹，存储在_MEIPASS中
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)


# 配置窗口与渲染属性
loadPrcFileData("", """
    framebuffer-multisample 1
    multisamples 2
    win-size 1920 1080
    text-encoding utf8
    sync-video 1
    window-title Firework Show 2026
""")

# ==========================================
# 初始化文字管理器
# ==========================================
# 1. 获取管理器实例
text_mgr = text_manager.get_manager(resource_path)

# 2. 读取脚本 (为了预扫描)
CFG_PATH = "../config/config.json"

with open(resource_path(CFG_PATH), "r", encoding='utf-8') as f:
    script_data = json.load(f)

# 3. 预扫描并生成缺失文字 (核心需求)
print("正在检查文字资源...")
text_mgr.scan_script_and_update(script_data)

# ==========================================
# 1. 资源生成 (Assets)
# ==========================================


def randomColor():
    """生成随机颜色"""
    return (random.random(), random.random(), random.random())

def create_particle_texture():
    """生成高斯模糊纹理"""
    size = 64
    image = PNMImage(size, size)
    image.addAlpha()
    image.alphaFill(0.0)
    center = size / 2
    max_dist = size / 2
    
    for x in range(size):
        for y in range(size):
            dist = math.sqrt((x - center)**2 + (y - center)**2)
            if dist <= max_dist:
                alpha = 1.0 - (dist / max_dist)
                alpha = pow(alpha, 3) 
                image.setXel(x, y, 1.0, 1.0, 1.0) 
                image.setAlpha(x, y, alpha)
                
    tex = Texture()
    tex.load(image)
    return tex

# ==========================================
# 2. 粒子系统核心 (Core Systems)
# ==========================================

class Particle:
    """
    全能粒子类
    Args:
        pos (tuple): (x, y, z) 初始位置
        v (tuple): (vx, vy, vz) 初始速度
        color (tuple): (r, g, b) 颜色
        size (float): 缩放大小
        lifetime_ms (int): 寿命(毫秒)
        drag_coeff (float): 空气阻力系数 (0-1)
        trace_frames (int): 轨迹残影数量 (0=关闭). 实现为产生静止的残影粒子.
        tail_config (tuple): 尾焰配置 (发射速率particles/sec, 喷射速度, 颜色, 寿命ms). None=关闭.
        flash_config (tuple): 闪烁配置 (振幅0-1, 周期秒). None=关闭.
    """
    def __init__(self, pos, v, color, size, lifetime_ms, drag_coeff=0.0, 
                 trace_frames=0, tail_config=None, flash_config=None):
        
        self.node = ParticleSystem.get_node()
        self.node.setPos(Point3(*pos))
        self.color = color
        self.node.setColorScale(LColor(color[0], color[1], color[2], 1.0))
        self.size = size
        self.node.setScale(size)
        
        self.velocity = Vec3(*v)
        self.life_max = lifetime_ms / 1000.0
        self.life_cur = 0.0
        self.drag = drag_coeff
        self.gravity = Vec3(0, 0, -GRAVITY) # 默认重力
        
        self.trace_frames = trace_frames
        self.tail_config = tail_config # (rate, speed, color, life_ms)
        self.flash_config = flash_config # (amp, period)
        
        self.tail_timer = 0.0
        self.base_alpha = 1.0
        self.is_ghost = False # 标记是否为纯视觉残影

    def update(self, dt):
        self.life_cur += dt
        if self.life_cur >= self.life_max:
            return False # 死亡

        # 1. 物理计算
        if not self.is_ghost:
            self.velocity += self.gravity * dt
            if self.drag > 0:
                self.velocity *= pow(1.0 - self.drag, dt * 10) # 修正阻力计算使其与帧率无关
            self.node.setPos(self.node.getPos() + self.velocity * dt)

        # 2. 视觉效果 (淡出)
        life_ratio = 1.0 - (self.life_cur / self.life_max)
        
        current_alpha = life_ratio
        self.node.setAlphaScale(current_alpha)

        # 3. Flash (闪烁特效)
        if self.flash_config and self.flash_config[1] > 0:
            amp, period = self.flash_config
            if self.life_cur % period > period * 0.7:
                self.node.setColorScale(LColor(1-(1-self.color[0])/amp, 1-(1-self.color[1])/amp, 1-(1-self.color[2])/amp, 1.0))
                self.node.setScale(self.size * amp)
            else:
                self.node.setScale(self.size)
        
        # 如果是残影粒子，只做淡出，不产生新东西
        if self.is_ghost:
            #self.node.setScale(self.node.getScale().x * life_ratio)
            return True

        curr_pos = self.node.getPos()

        # 4. Trace (轨迹/残影)
        # 逻辑：每帧在其当前位置留下一个静止的、短命的粒子
        if self.trace_frames > 0:
            # 残影寿命与trace数值挂钩，例如 trace=5，则残影存活约 0.1秒
            ghost_life = self.trace_frames * 0.02 
            ParticleSystem.spawn_ghost(curr_pos, self.node.getColorScale(), self.node.getScale(), ghost_life)

        # 5. Tail (尾焰/喷射)
        # 逻辑：主动向四周喷射微小粒子
        if self.tail_config:
            rate, speed, col, t_life = self.tail_config
            interval = 1.0 / rate
            self.tail_timer += dt
            while self.tail_timer > interval:
                self.tail_timer -= interval
                # 随机喷射方向
                rand_dir = Vec3(random.uniform(-1,1), random.uniform(-1,1), random.uniform(-1,1)).normalized()
                # 尾焰粒子通常不具备Trace和Tail，防止递归爆炸
                ParticleSystem.add(
                    pos=(curr_pos.x, curr_pos.y, curr_pos.z),
                    v=(rand_dir.x * speed, rand_dir.y * speed, rand_dir.z * speed),
                    color=col,
                    size=self.node.getScale().x * 0.5,
                    lifetime_ms=t_life,
                    drag=0.1,
                    trace=0, tail=None, flash=None
                )

        return True

    def cleanup(self):
        self.node.removeNode()


class Firework:
    """
    烟花弹类
    """
    def __init__(self, start_pos, start_v, explode_time_ms, color, size, trace_frames, tail_cfg, strategy_func):
        self.pos = Vec3(*start_pos)
        self.velocity = Vec3(*start_v)
        self.explode_time = explode_time_ms / 1000.0
        self.age = 0
        self.color = color
        self.size = size
        self.strategy = strategy_func
        self.exploded = False

        # 发射阶段的视觉粒子
        self.shell_particle = Particle(
            start_pos, start_v, color, size, explode_time_ms + 200, 
            drag_coeff=0.0, trace_frames=trace_frames, tail_config=tail_cfg, flash_config=None
        )
        # 修改重力以适应发射
        self.shell_particle.gravity = Vec3(0, 0, -GRAVITY) 

    def update(self, dt):
        if self.exploded:
            return False

        self.age += dt
        # 更新绑定的粒子物理
        self.shell_particle.update(dt)
        self.pos = self.shell_particle.node.getPos()
        self.velocity = self.shell_particle.velocity

        if self.age >= self.explode_time:
            self.explode()
            return False
        return True

    def explode(self):
        self.exploded = True
        self.shell_particle.cleanup()
        
        # 播放音效
        AudioManager.play("explosion")
        
        # 执行爆炸逻辑
        pos_tuple = (self.pos.x, self.pos.y, self.pos.z)
        self.strategy(pos_tuple, self.color, self.size)


class ParticleSystem:
    """
    粒子管理器 (单例模式)
    """
    particles = []
    fireworks = []
    shared_card = None
    node_root = None

    @classmethod
    def setup(cls, render_node):
        cls.node_root = render_node.attachNewNode("particle_root")
        cm = CardMaker('p')
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)
        cls.shared_card = NodePath(cm.generate())
        cls.shared_card.setTexture(create_particle_texture())
        cls.shared_card.setTransparency(TransparencyAttrib.M_alpha)
        cls.shared_card.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.M_add))
        cls.shared_card.setBillboardPointEye()

    @classmethod
    def get_node(cls):
        """复制共享几何体"""
        n = cls.shared_card.copyTo(cls.node_root)
        return n

    @classmethod
    def add(cls, pos, v, color, size, lifetime_ms, drag=0.0, trace=0, tail=None, flash=None):
        p = Particle(pos, v, color, size, lifetime_ms, drag, trace, tail, flash)
        cls.particles.append(p)

    @classmethod
    def spawn_ghost(cls, pos, color_scale, size, duration):
        """生成一个不动的、纯视觉的残影粒子"""
        # 为了性能，直接复用Particle类但标记为ghost
        p = Particle(
            pos=(pos.x, pos.y, pos.z),
            v=(0,0,0),
            color=(1,1,1), # 颜色会被下面的setColorScale覆盖
            size=size.x, # 假设均匀缩放
            lifetime_ms=duration*1000,
            drag_coeff=0, trace_frames=0, tail_config=None, flash_config=None
        )
        p.node.setColorScale(color_scale)
        p.is_ghost = True
        cls.particles.append(p)

    @classmethod
    def launch_firework(cls, pos, v, time, color, size, trace_frames, tail_cfg, strategy):
        f = Firework(pos, v, time, color, size, trace_frames, tail_cfg, strategy)
        AudioManager.play("launch")
        cls.fireworks.append(f)
        # print(pos,v,time)

    @classmethod
    def update(cls, task):
        dt = globalClock.getDt()
        
        # 更新烟花弹
        cls.fireworks = [f for f in cls.fireworks if f.update(dt)]
        
        # 更新粒子
        active_particles = []
        for p in cls.particles:
            if p.update(dt):
                active_particles.append(p)
            else:
                p.cleanup()
        cls.particles = active_particles
        
        return Task.cont

# ==========================================
# 3. 爆炸策略与导演 (Strategies & Director)
# ==========================================

class ExplosionStrategies:
    @staticmethod
    def standard(pos, color, size_scale):
        count = 100
        for _ in range(count):
            speed = random.uniform(10, 25)
            # 球面随机向量
            theta = random.uniform(0, 2*math.pi)
            phi = random.uniform(0, math.pi)
            vx = speed * math.sin(phi) * math.cos(theta)
            vy = speed * math.sin(phi) * math.sin(theta)
            vz = speed * math.cos(phi)
            
            # 特性：带拖尾，无Tail
            ParticleSystem.add(
                pos, (vx, vy, vz), color, size=0.6*size_scale, lifetime_ms=1500,
                drag=0.05, trace=35, tail=None, flash=None
            )

    @staticmethod
    def standard_rc(pos, color, size_scale):
        count = 100
        for _ in range(count):
            speed = random.uniform(10, 25)
            # 球面随机向量
            theta = random.uniform(0, 2*math.pi)
            phi = random.uniform(0, math.pi)
            vx = speed * math.sin(phi) * math.cos(theta)
            vy = speed * math.sin(phi) * math.sin(theta)
            vz = speed * math.cos(phi)
            
            # 特性：带拖尾，无Tail
            ParticleSystem.add(
                pos, (vx, vy, vz), randomColor(), size=0.6*size_scale, lifetime_ms=1500,
                drag=0.05, trace=25, tail=None, flash=None
            )

    @staticmethod
    def heart(pos, color, size_scale):
        count = 50
        for theta in range(count):
            theta = theta * 2 * math.pi / count
            speed = 20
            for vx in [-1, 0, 1]:
                #vx = random.uniform(-1, 1)
                vy = speed * (1-math.sin(theta)) * math.cos(theta)
                vz = speed * (1-math.sin(theta)) * math.sin(theta)
                
                # 特性：带拖尾，无Tail
                ParticleSystem.add(
                    pos, (vx, vy, vz), color, size=0.6*size_scale, lifetime_ms=2400,
                    drag=0.05, trace=0, tail=(20, 2, randomColor(), 400), flash=(1.5, 0.2)
                )

    @staticmethod
    def glitter_bomb(pos, color, size_scale):
        """闪光弹：强闪烁，不规则运动"""
        count = 120
        for _ in range(count):
            speed = random.uniform(15, 30)
            v = Vec3(random.uniform(-1,1), random.uniform(-1,1), random.uniform(-1,1)).normalized() * speed
            
            ParticleSystem.add(
                pos, (v.x, v.y, v.z), color, size=0.5*size_scale, lifetime_ms=4500,
                drag=0.1, trace=0, tail=None, flash=(2.0, 1) # 剧烈高频闪烁
            )

    @staticmethod
    def text_shape_3d(pos, color, size_scale, text):
        """文字形状"""
        # === 修改点：使用管理器获取数据 ===
        # points = font_data_3d[text] # 旧代码
        points = text_manager.get_manager().get_word_data(text) # 新代码
        
        if not points:
            print(f"Warning: Empty points for text '{text}'")
            return

        for i in points:
            # i 是 (x, y, z)
            # 这里的坐标偏移和缩放逻辑保持不变
            v = Vec3(i[0] + random.uniform(-0.3, 0.3), 
                     i[1] + random.uniform(-0.3, 0.3), 
                     i[2] + random.uniform(-0.3, 0.3)) * 2 # 适当扩大间距
            
            # 为了让字立起来或者朝向正确，可能需要根据原来的数据调整轴向
            # 原来的数据: i[2] 对应 -i[2]? 
            # 你的旧代码里是: -i[2]。
            # 我的 text_manager 生成的 z 是正向向上的 (0~15)。
            # 如果要保持一致，可能不需要负号，或者取决于你的相机视角。
            # 这里先按照通用逻辑写：
            
            # 假设字是正着立在 XY 平面上
            final_v = Vec3(v.x, v.y, v.z)
            
            # 如果发现字是倒着的，可以改成:
            # final_v = Vec3(v.x, v.y, -v.z) 

            ParticleSystem.add(
                pos, (final_v.x, final_v.y, final_v.z), color, 
                size=0.5*size_scale, lifetime_ms=4500,
                drag=0.2, trace=0, tail=None, flash=None
            )

class AudioManager:
    """简单的音效管理器占位符"""
    sounds = {}
    
    @classmethod
    def load(cls, loader):
        cls.sounds["launch"] = loader.loadSfx(fix_panda3d_path(resource_path("../assets/audio/fsx/launch.mp3")))
        cls.sounds["explosion"] = loader.loadSfx(fix_panda3d_path(resource_path("../assets/audio/fsx/bomb.wav")))
        pass

    @classmethod
    def play(cls, name):
        if name in cls.sounds:
            cls.sounds[name].play()
        else:
            # print(f"[Audio] Playing {name}") # 调试用
            pass

# ==========================================
# 策略映射表 & 辅助函数
# ==========================================

# 1. 建立字符串到函数的映射
STRATEGY_MAP = {
    "standard": ExplosionStrategies.standard,
    "standard_rc": ExplosionStrategies.standard_rc,
    "heart": ExplosionStrategies.heart,
    "glitter": ExplosionStrategies.glitter_bomb,
    "text_shape_3d": ExplosionStrategies.text_shape_3d 
}

# 2. 颜色解析工具
def parse_color(c_data):
    """支持 [r,g,b] 列表或 "random" 字符串"""
    if c_data == "random":
        return randomColor()
    return (c_data[0], c_data[1], c_data[2])

class ShowDirector:
    def __init__(self, main_app):
        self.app = main_app
        self.timer = 0
        self.active = True
        
        # --- 1. 加载 JSON ---
        try:
            with open(resource_path(CFG_PATH), "r", encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取脚本失败: {e}")
            data = {"firework": [], "camera": []}

        # --- 2. 预处理烟花数据 ---
        # 你的结构是: [ [time, [events...]], [time, [events...]] ]
        # 我们确保它是按时间排序的
        self.fw_data = sorted(data.get("firework", []), key=lambda x: x[0])
        self.fw_idx = 0

        # --- 3. 预处理相机数据 ---
        raw_cam = data.get("camera", [])
        self.cam_script = []
        for cam in raw_cam:
            self.cam_script.append({
                "time": cam["time"],
                "pos": Vec3(*cam["pos"]),
                "look_at": Vec3(*cam["look_at"]),
                "up": Vec3(*cam.get("up", [0,0,1]))
            })
        self.cam_script.sort(key=lambda x: x["time"])
        self.cam_idx = 0

    def update(self, dt):
        if not self.active: return
        self.timer += dt

        # ==========================
        # 1. 摄像机运镜 (插值逻辑)
        # ==========================
        if self.cam_idx < len(self.cam_script) - 1:
            f1 = self.cam_script[self.cam_idx]
            f2 = self.cam_script[self.cam_idx + 1]
            
            if self.timer >= f2["time"]:
                self.cam_idx += 1
            else:
                # 线性插值
                factor = (self.timer - f1["time"]) / (f2["time"] - f1["time"])
                factor = max(0.0, min(1.0, factor))
                
                curr_pos = f1["pos"] + (f2["pos"] - f1["pos"]) * factor
                curr_look = f1["look_at"] + (f2["look_at"] - f1["look_at"]) * factor
                # up 向量通常不需要插值，直接用当前的或者插值皆可，这里简单处理
                
                self.app.camera.setPos(curr_pos)
                self.app.camera.lookAt(curr_look, f1["up"])

        # ==========================
        # 2. 烟花触发逻辑
        # ==========================
        while self.fw_idx < len(self.fw_data):
            # 获取当前这一组: [time, [event_dict_1, event_dict_2...]]
            group = self.fw_data[self.fw_idx]
            trigger_time = group[0]
            events = group[1]

            if self.timer >= trigger_time:
                # 到了时间，执行该组所有事件
                for event in events:
                    self.process_event(event)
                
                # 指针后移
                self.fw_idx += 1
            else:
                # 时间未到，后面的更不用看了（因为排过序了）
                break

    # ... (前面的 __init__ 和 update 方法保持不变) ...

    def resolve_value(self, val):
        """
        辅助函数：解析参数
        如果参数是 {"min": a, "max": b} 格式，则返回随机值
        如果是列表且包含 min/max，则对列表每一项做随机
        """
        if isinstance(val, dict) and "min" in val and "max" in val:
            min_v = val["min"]
            max_v = val["max"]
            
            # 情况1: 向量/列表随机 (例如 pos: [-10, -10] 到 [10, 10])
            if isinstance(min_v, list) and isinstance(max_v, list):
                return [random.uniform(a, b) for a, b in zip(min_v, max_v)]
            
            # 情况2: 标量随机 (例如 time: 2.0 到 4.0)
            return random.uniform(min_v, max_v)
            
        return val

    def process_event(self, p):
        """解析并执行单个烟花事件 (支持 repeat 和 range)"""
        evt_type = p.get("type", "launch_to")

        if evt_type == "end":
            self.end_intro()
            return

        if evt_type == "launch_to":
            # 获取重复次数，默认为 1
            repeat_count = p.get("repeat", 1)
            
            for _ in range(repeat_count):
                # === 关键：每次循环都重新解析随机值 ===
                
                # 1. 位置解析 (支持 min/max 范围)
                raw_pos = p.get("pos", [0,0,80])
                pos = self.resolve_value(raw_pos)
                pos_vec = (pos[0], pos[1], 0) # 地面投影点
                target_z = pos[2] # 目标高度

                # 2. 时间解析 (支持 min/max 范围)
                raw_time = p.get("time", 2.0)
                duration = self.resolve_value(raw_time)

                # 3. 颜色解析
                color = parse_color(p.get("color", "random"))
                
                # 4. 其他参数
                size = self.resolve_value(p.get("size", 0.6))
                trace = p.get("trace", 0)

                # 5. 尾焰解析
                tail_dict = p.get("tail")
                tail_cfg = None
                if tail_dict:
                    tail_cfg = (
                        tail_dict.get("count", 20),
                        tail_dict.get("velocity", 5),
                        parse_color(tail_dict.get("color", color)), 
                        tail_dict.get("time", 500)
                    )

                # 6. 策略解析
                strat_data = p.get("strategy", {})
                if isinstance(strat_data, str):
                    strat_name = strat_data
                    strat_args = []
                else:
                    strat_name = strat_data.get("name", "standard")
                    strat_args = strat_data.get("args", [])

                base_func = STRATEGY_MAP.get(strat_name, ExplosionStrategies.standard)
                # 再次封装以支持 lambda 参数传递
                real_strategy = lambda _p, _c, _s: base_func(_p, _c, _s, *strat_args)

                # 7. 物理计算并发射
                # h = v0*t - 0.5*g*t^2  => v0 = h/t + 0.5*g*t
                # 防止 duration 随机出 0 或负数
                if duration <= 0.1: duration = 0.1
                
                vz = target_z / duration + 0.5 * GRAVITY * duration
                v = (0, 0, vz)

                ParticleSystem.launch_firework(
                    pos_vec, v, duration * 1000, 
                    color, size, trace, tail_cfg, real_strategy
                )
    def end_intro(self):
        self.active = False
        self.app.enable_interaction()


# ==========================================
# 4. 主程序 (Main Application)
# ==========================================

class FireworkShow(ShowBase):
    def __init__(self):
        super().__init__()
        
        # --- 1. 环境配置 ---
        self.setBackgroundColor(0, 0, 0.05)
        self.disableMouse() 
        # self.setFrameRateMeter(True)
        self.camLens.setFov(90)

        # --- 2. 光效与后期 ---
        self.filters = CommonFilters(self.win, self.cam)
        self.filters.setBloom(blend=(0, 0, 0, 1), desat=-0.5, intensity=2.5, size="medium")
        
        # --- 3. 初始化子系统 ---
        ParticleSystem.setup(render)
        AudioManager.load(self.loader)
        self.director = ShowDirector(self)
        self.is_paused = True
        # --- 4. 背景音乐 (新增) ---
        # 请确保目录下有 bgm.mp3 或者修改为你自己的文件名
        try:
            self.bgm = self.loader.loadMusic(fix_panda3d_path(resource_path("../assets/audio/bgm/bgm.mp3"))) 
            self.bgm.setLoop(True)
            self.bgm.setVolume(0.5)
            self.bgm.play()
        except:
            pass
            # print("Warning: bgm.mp3 not found.")

        # --- 5. UI 文字提示 (新增) ---
        try:
            self.font = self.loader.loadFont(fix_panda3d_path(resource_path("../assets/fonts/SourceHanSansSC-Normal.otf")))
        except:
            # print("未找到字体文件，将使用默认字体(无法显示中文)")
            self.font = None

        self.ui_text = OnscreenText(
            text="欢迎欣赏2026烟花秀！\n建议使用全屏\n按下 Ctrl 键开始\n再次按 Ctrl 暂停/继续。\nEnter 键跳过开场秀。",
            font=self.font,            # <--- 关键：应用字体
            pos=(0, 0.3), 
            scale=0.07,                # 中文稍微调大一点才看得清
            fg=(1, 1, 0.5, 1), 
            bg=(0, 0, 0, 0.6),   # 半透明黑色背景板，确保文字清晰
            align=TextNode.ACenter,
            shadow=(0, 0, 0, 0.5), 
            mayChange=True
        )

        # --- 6. 任务管理 ---
        self.taskMgr.add(self.update_particles, "ParticleUpdate")
        self.taskMgr.add(self.update_director, "DirectorUpdate")
        
        # --- 7. 交互状态 ---
        self.interactive_mode = False
        
        # print("=== 烟花秀启动 ===")
        # 绑定暂停键 (Ctrl)
        self.accept("lcontrol", self.toggle_pause) 
        # 绑定退出键
        self.accept("escape", self.start_exit_sequence)
        # 绑定跳过键
        self.accept("enter", self.director.end_intro)

        self.win.setCloseRequestEvent('window-close-attempt')
        self.accept('window-close-attempt', self.start_exit_sequence)
        
        # 防止用户多次点击导致多次触发
        self.is_exiting = False

    def start_exit_sequence(self):
        """处理关闭请求：显示文字并安排延迟退出"""
        if self.is_exiting:
            return
        self.is_exiting = True

        # print("捕捉到关闭请求，显示告别语...")

        # 1. 禁用交互，防止用户继续发射烟花
        self.interactive_mode = False 
        self.ignoreAll() # 忽略所有按键（除了当前这个流程内部逻辑）

        self.taskMgr.remove("AutoCleanTextTask")
        
        # 2. 显示全屏告别文字
        # 我们可以创建一个新的 OnscreenText，也可以复用 self.ui_text
        if hasattr(self, 'ui_text'):
            self.ui_text.destroy() # 清除旧的 UI
            
        self.goodbye_text = OnscreenText(
            text="新年快乐，万事如意！\n\n 2026 \n\n(程序将在 3 秒后关闭...)",
            font=self.font,
            pos=(0, 0.3),
            scale=0.08,
            fg=(1, 0.8, 0.2, 1), # 金色文字
            bg=(0, 0, 0, 0.6),   # 半透明黑色背景板，确保文字清晰
            align=TextNode.ACenter,
            mayChange=False
        )

        # 3. 安排 3 秒后执行真正的退出
        self.taskMgr.doMethodLater(3.0, self.finalize_exit, 'FinalExitTask')

    def finalize_exit(self, task):
        """执行真正的退出"""
        sys.exit()

    def toggle_pause(self):
        """切换暂停状态"""
        self.is_paused = not self.is_paused
        if not self.is_paused:
            self.ui_text.setText("")
        # print(f"Paused: {self.is_paused}")

    def update_particles(self, task):
        """粒子更新任务 (含暂停逻辑)"""
        if self.is_paused:
            return Task.cont
            
        return ParticleSystem.update(task)

    def update_director(self, task):
        """导演脚本更新任务 (含暂停逻辑)"""
        if self.is_paused:
            return Task.cont

        dt = globalClock.getDt()
        self.director.update(dt)
        return Task.cont

    def enable_interaction(self, task=None):
        self.interactive_mode = True
        self.enableMouse() # 启用默认的 Trackball 鼠标控制
        
        # 绑定按键
        self.accept("space", self.user_random_launch)
        self.accept("mouse1", self.user_click_launch)
        self.accept("r", self.restart_show)
        
        self.ui_text.setText("交互模式已开启！\n点击鼠标左键发射烟花。\n按空格键随机发射烟花。\n按 R 键重播开场秀。\n按 Ctrl 键暂停/继续。\n按住鼠标右键拖动视角。\n按住鼠标中键拖动旋转视角。\n按住鼠标右键拖动缩放视角。")
        self.taskMgr.doMethodLater(15.0, self.clean_ui_text, "AutoCleanTextTask")
        # print("\n[交互模式已开启]")
        if self.is_paused:
            self.is_paused = False
        if task:
            return Task.done

    def clean_ui_text(self, event=None):
        self.ui_text.setText("")
        return Task.done
    
    def restart_show(self):
        self.interactive_mode = False
        self.disableMouse()
        
        # 重置摄像机位置到初始状态 (可选，根据你的导演脚本第一帧调整)
        self.camera.setPos(0, -20, 25)
        self.camera.lookAt(0, 0, 40)
        
        self.director = ShowDirector(self) # 重置导演
        # print("重播开场秀...")

        # 【修复】重新绑定 Enter 键到新导演的 end_intro 方法
        self.ignore("enter") # 先取消旧的
        self.accept("enter", self.director.end_intro) # 绑新的

    def user_exit(self):
        sys.exit()

    def launch_firework_at(self, target_pos, start_pos=None, color_tuple=None):
        """
        发射烟花打击特定目标点
        Args:
            target_pos (Vec3): 爆炸目标点
            start_pos (Vec3, optional): 发射起点. 默认为目标点在地面上的投影.
        """
        if color_tuple is None:
            color_tuple = (random.random(), random.random(), random.random())
        
        strategy = random.choice([
            ExplosionStrategies.standard, 
            ExplosionStrategies.standard_rc, 
            ExplosionStrategies.glitter_bomb,
            ExplosionStrategies.heart
        ])

        # 1. 确定起点
        if start_pos is None:
            # 默认从目标正下方的地面发射，或者稍微随机一点
            start_pos = Vec3(target_pos.x, target_pos.y, 0)

        # 2. 物理反推计算
        # 我们希望烟花恰好到达 target_pos 时速度接近 0 (达到最高点)，或者刚好时间到。
        # 这里使用简单的物理：S = v0*t - 0.5*g*t^2
        # 为了视觉效果，我们设定一个从起点到终点的飞行时间。
        # 高度差
        h_diff = target_pos.z - start_pos.z
        if h_diff < 10: h_diff = 10 # 防止过低
        
        # 估算时间：根据高度差，假设初始垂直速度足以克服重力
        # v_z = sqrt(2 * g * h)
        # time = v_z / g
        vz_initial = math.sqrt(2 * GRAVITY * h_diff)
        flight_time = vz_initial / GRAVITY
        
        # 修正：如果目标很远，增加一点时间让它飞过去
        flight_time = max(flight_time, 1.5) 

        # 计算水平速度：Vx = Dx / t
        vx = (target_pos.x - start_pos.x) / flight_time
        vy = (target_pos.y - start_pos.y) / flight_time
        # 重新计算垂直速度以匹配时间： h = vz*t - 0.5*g*t^2  =>  vz = (h + 0.5*g*t^2) / t
        vz = (h_diff + 0.5 * GRAVITY * (flight_time**2)) / flight_time

        v_launch = (vx, vy, vz)
        tail_cfg = (50, 5, color_tuple, 800)
        
        # 发射！
        ParticleSystem.launch_firework(
            (start_pos.x, start_pos.y, start_pos.z), 
            v_launch, 
            flight_time * 1000, 
            color_tuple, 
            0.4, 10, tail_cfg, strategy
        )

    def user_random_launch(self):
        if self.is_paused: return
        pos = Vec3(random.uniform(-40, 40), random.uniform(-40, 40), random.uniform(50, 90))
        self.launch_firework_at(pos)

    def user_click_launch(self):
        """
        修改后的点击逻辑：
        获取鼠标在 3D 空间的方向，在摄像机前方一定距离处生成爆炸目标点。
        """
        if not self.interactive_mode or self.is_paused: return
        
        if self.mouseWatcherNode.hasMouse():
            mpos = self.mouseWatcherNode.getMouse()
            
            # 1. 获取鼠标射线
            near_p = Point3()
            far_p = Point3()
            self.camLens.extrude(mpos, near_p, far_p)
            
            # 转换到世界坐标
            p_near = render.getRelativePoint(self.cam, near_p)
            p_far = render.getRelativePoint(self.cam, far_p)
            
            # 2. 计算方向向量
            direction = (p_far - p_near).normalized()
            
            # 3. 设定目标距离 (例如：摄像机前方 60 米处)
            # 也可以根据摄像机高度动态调整，这里用固定距离比较直观
            target_distance = 60.0 
            target_pos = p_near + direction * target_distance
            
            # 4. 如果目标点太低（比如打到地底下了），强制抬高一点
            if target_pos.z < 20:
                target_pos.z = 20

            # 5. 为了增加趣味性，让烟花从屏幕下方发射，而不是垂直从地面发射
            # 我们获取摄像机位置下方作为发射点
            cam_pos = self.camera.getPos()
            # 发射点在摄像机前方一点点，下方 20 米
            launch_origin = cam_pos + self.camera.getQuat().getForward() * 10 - Vec3(0, 0, 20)
            if launch_origin.z < 0: launch_origin.z = 0 # 地面以上

            # 调用通用发射函数
            self.launch_firework_at(target_pos, start_pos=launch_origin)

if __name__ == "__main__":
    GRAVITY = 9.8
    app = FireworkShow()
    app.run()
