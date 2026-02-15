from setuptools import setup

setup(
    name="FireworkShow",
    version="1.0.0",
    options={
        'build_apps': {
            # --- 1. 程序入口 ---
            # 左边是生成的exe名字，右边是你的python脚本
            'gui_apps': {
                'FireworkShow': 'src/main.py',
            },

            # --- 2. 插件列表 ---
            'plugins': [
                'pandagl',        # 对应 libpandagl.dll
                'p3openal_audio', # 对应 libp3openal_audio.dll
                'p3ffmpeg',
            ],

            # --- 3. 资源文件包含 ---
            'include_patterns': [
                '**/*.pkl',      # 缓存文件
                '**/*.mp3',      # 音乐
                '**/*.wav',      # 音效
                '**/*.otf',      # 字体 otf
                '**/*.TTC',      # 字体 TTC
                '**/*.ttf',      # 字体 TTF (新增：覆盖 arial.ttf 和 simhei.ttf)
                '**/*.ttc',      # 字体 ttc (防止大小写敏感问题)
                '**/*.json',     # 脚本 (新增：覆盖 script.json)
            ],

            # --- 4. 平台设置 ---
            # 强制指定构建为 Windows 64位
            'platforms': [
                'win_amd64', 
            ],
            
            # --- 5. 图标设置 ---
            'icons': {
                'FireworkShow': ['icon.ico'],
            },
            
            # (可选) 错误日志：如果闪退，日志会生成在用户AppData目录下
            'log_filename': '$USER_APPDATA/FireworkShow/output.log',
        }
    }
)
