"""
Mods 目录扫描器 - 解析已安装的 Minecraft mod 信息
"""
import os
import zipfile
import json
import re
from typing import List, Dict, Optional


def scan_mods_directory(mods_path: str) -> List[Dict]:
    """
    扫描 mods 目录，解析每个 jar 文件的 mod 信息。
    
    返回列表，每项包含:
    - file_name: jar 文件名
    - mod_id: mod ID
    - display_name: 显示名称
    - version: 版本号
    - dependencies: 依赖列表
    - mc_version: 目标 MC 版本（如果能识别）
    """
    if not os.path.isdir(mods_path):
        return []

    mods = []
    for filename in os.listdir(mods_path):
        if not filename.endswith(".jar"):
            continue
        jar_path = os.path.join(mods_path, filename)
        mod_info = parse_jar(jar_path, filename)
        if mod_info:
            mods.append(mod_info)

    return mods


def parse_jar(jar_path: str, filename: str) -> Optional[Dict]:
    """解析单个 jar 文件获取 mod 信息"""
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            # 优先尝试 Forge 新格式 (mods.toml)
            info = try_parse_mods_toml(zf, filename)
            if info:
                return info

            # 尝试旧格式 (mcmod.info)
            info = try_parse_mcmod_info(zf, filename)
            if info:
                return info

            # 尝试 Fabric 格式 (fabric.mod.json)
            info = try_parse_fabric_mod_json(zf, filename)
            if info:
                return info

    except (zipfile.BadZipFile, IOError):
        pass

    # 无法解析时从文件名推断
    return infer_from_filename(filename)


def try_parse_mods_toml(zf: zipfile.ZipFile, filename: str) -> Optional[Dict]:
    """解析 META-INF/mods.toml (Forge 1.13+)"""
    try:
        with zf.open("META-INF/mods.toml") as f:
            content = f.read().decode("utf-8", errors="replace")
    except KeyError:
        return None

    # 简单 TOML 解析（不引入额外依赖）
    mod_id = extract_toml_value(content, "modId")
    display_name = extract_toml_value(content, "displayName")
    version = extract_toml_value(content, "version")

    if not mod_id:
        return None

    # 提取依赖
    dependencies = extract_toml_dependencies(content, mod_id)

    return {
        "file_name": filename,
        "file_path": None,  # 将在外部设置
        "mod_id": mod_id,
        "display_name": display_name or mod_id,
        "version": version or "unknown",
        "dependencies": dependencies,
        "loader": "forge",
        "mc_version": guess_mc_version_from_filename(filename),
    }


def try_parse_mcmod_info(zf: zipfile.ZipFile, filename: str) -> Optional[Dict]:
    """解析 mcmod.info (Forge 旧格式)"""
    try:
        with zf.open("mcmod.info") as f:
            content = f.read().decode("utf-8", errors="replace")
    except KeyError:
        return None

    try:
        # mcmod.info 可能是 JSON 数组或对象
        data = json.loads(content)
        if isinstance(data, list) and len(data) > 0:
            info = data[0]
        elif isinstance(data, dict) and "modList" in data:
            info = data["modList"][0] if data["modList"] else None
        else:
            info = data

        if not info:
            return None

        return {
            "file_name": filename,
            "file_path": None,
            "mod_id": info.get("modid", ""),
            "display_name": info.get("name", ""),
            "version": info.get("version", "unknown"),
            "dependencies": info.get("dependencies", []),
            "loader": "forge",
            "mc_version": info.get("mcversion", guess_mc_version_from_filename(filename)),
        }
    except (json.JSONDecodeError, IndexError, KeyError):
        return None


def try_parse_fabric_mod_json(zf: zipfile.ZipFile, filename: str) -> Optional[Dict]:
    """解析 fabric.mod.json (Fabric)"""
    try:
        with zf.open("fabric.mod.json") as f:
            content = f.read().decode("utf-8", errors="replace")
    except KeyError:
        return None

    try:
        data = json.loads(content)
        return {
            "file_name": filename,
            "file_path": None,
            "mod_id": data.get("id", ""),
            "display_name": data.get("name", ""),
            "version": data.get("version", "unknown"),
            "dependencies": list(data.get("depends", {}).keys()),
            "loader": "fabric",
            "mc_version": guess_mc_version_from_filename(filename),
        }
    except (json.JSONDecodeError, KeyError):
        return None


def infer_from_filename(filename: str) -> Dict:
    """从文件名推断 mod 信息"""
    name = filename.replace(".jar", "")
    # 尝试分离名称和版本: mod-name-1.2.3.jar
    match = re.match(r"^(.+?)-(\d+\.\d+.*)$", name)
    if match:
        mod_name = match.group(1)
        version = match.group(2)
    else:
        mod_name = name
        version = "unknown"

    return {
        "file_name": filename,
        "file_path": None,
        "mod_id": mod_name.lower().replace("-", "_").replace(" ", "_"),
        "display_name": mod_name,
        "version": version,
        "dependencies": [],
        "loader": "unknown",
        "mc_version": guess_mc_version_from_filename(filename),
    }


def extract_toml_value(content: str, key: str) -> Optional[str]:
    """从 TOML 内容中提取简单键值对"""
    # 匹配 key="value" 或 key='value'
    pattern = rf'{key}\s*=\s*["\']([^"\']*)["\']'
    match = re.search(pattern, content)
    if match:
        value = match.group(1)
        # 排除变量引用
        if value.startswith("${"):
            return None
        return value
    return None


def extract_toml_dependencies(content: str, mod_id: str) -> List[str]:
    """从 mods.toml 中提取依赖的 mod ID"""
    deps = []
    # 匹配 [[dependencies.modid]] 段落中的 modId
    dep_section_pattern = rf'\[\[dependencies\.{re.escape(mod_id)}\]\]'
    sections = re.split(dep_section_pattern, content)

    for section in sections[1:]:  # 跳过第一段（非依赖部分）
        dep_id = extract_toml_value(section.split("[[")[0], "modId")
        if dep_id and dep_id not in ("forge", "minecraft"):
            deps.append(dep_id)

    return deps


def guess_mc_version_from_filename(filename: str) -> Optional[str]:
    """从文件名猜测 Minecraft 版本"""
    match = re.search(r"(1\.\d+(?:\.\d+)?)", filename)
    if match:
        return match.group(1)
    return None


def detect_server_version(mods_path: str) -> Optional[str]:
    """
    尝试从 mods 目录的上级目录检测服务器 MC 版本。
    检查 server.properties 或 version.json 等文件。
    """
    server_root = os.path.dirname(mods_path)

    # 检查 server.properties 中是否有版本信息
    props_file = os.path.join(server_root, "server.properties")
    if os.path.exists(props_file):
        try:
            with open(props_file, "r", encoding="utf-8") as f:
                for line in f:
                    # 某些服务端会记录版本
                    pass
        except IOError:
            pass

    # 检查 version.json
    version_file = os.path.join(server_root, "version.json")
    if os.path.exists(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("id") or data.get("name")
        except (json.JSONDecodeError, IOError):
            pass

    return None
