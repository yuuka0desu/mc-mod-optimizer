"""
配置管理模块 - 管理 AI API 配置和应用设置
"""
import json
import os
import sys


# 应用数据目录名称
APP_DIR_NAME = "MCModOptimizer"


def get_app_data_dir() -> str:
    """
    获取应用数据目录。
    
    优先使用 exe 同级目录下的 MCModOptimizer 文件夹，
    第一次运行时自动创建。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，exe 所在目录
        base = os.path.dirname(sys.executable)
    else:
        # 开发环境，脚本所在目录
        base = os.path.dirname(os.path.abspath(__file__))

    app_dir = os.path.join(base, APP_DIR_NAME)

    # 第一次运行时自动创建目录结构
    if not os.path.isdir(app_dir):
        os.makedirs(app_dir, exist_ok=True)
        # 创建子目录
        os.makedirs(os.path.join(app_dir, "output"), exist_ok=True)

    return app_dir


def get_default_output_dir() -> str:
    """获取默认输出目录"""
    return os.path.join(get_app_data_dir(), "output")


# 应用数据目录
APP_DATA_DIR = get_app_data_dir()

# 配置文件路径
CONFIG_FILE = os.path.join(APP_DATA_DIR, "settings.json")

DEFAULT_CONFIG = {
    "ai_backend": "openai",  # openai / claude
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "gpt-4o",
    "claude_api_key": "",
    "claude_model": "claude-sonnet-4-20250514",
    "last_log_path": "",
    "last_mods_path": "",
    "last_output_path": "",
    "minecraft_version": "1.20.1",
    "forge_version": "47.2.0",
    "optimize_mode": "server",  # server / client
    "mod_id": "serverfix",
    "auto_build": False,
}


def load_config() -> dict:
    """加载配置文件，不存在则返回默认配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并默认值（处理新增字段）
            config = {**DEFAULT_CONFIG, **saved}
            return config
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    """保存配置到文件"""
    # 确保目录存在
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"保存配置失败: {e}")
