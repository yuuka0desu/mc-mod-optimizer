"""
Forge Mod 项目生成器 - 将 AI 生成的代码组装成完整的 Forge mod 项目
"""
import os
import sys
import shutil
import subprocess
from typing import Dict, List, Optional, Callable


def _get_resource_dir() -> str:
    """获取资源目录（兼容 PyInstaller）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


TEMPLATES_DIR = os.path.join(_get_resource_dir(), "templates")


class ProjectBuilder:
    """Forge mod 项目生成器"""

    def __init__(self, output_dir: str, mod_id: str, mc_version: str = "1.20.1",
                 forge_version: str = "47.2.0"):
        self.output_dir = output_dir
        self.mod_id = mod_id
        self.mc_version = mc_version
        self.forge_version = forge_version
        self.project_dir = os.path.join(output_dir, mod_id)

    def build(self, generated_code: Dict, source_mods_path: str = None) -> str:
        """
        构建完整的 Forge mod 项目。
        
        Args:
            generated_code: AI 生成的代码字典
            source_mods_path: 源 mods 目录路径（用于复制依赖 jar）
        
        Returns:
            生成的项目目录路径
        """
        # 如果项目目录已存在，清理旧的源码目录避免残留文件冲突
        src_dir = os.path.join(self.project_dir, "src")
        if os.path.isdir(src_dir):
            shutil.rmtree(src_dir)

        # 创建项目目录结构
        self._create_directory_structure()

        # 生成 Gradle 构建文件
        self._generate_build_files(generated_code)

        # 写入 Java 源码
        self._write_java_sources(generated_code)

        # 生成资源文件
        self._generate_resources(generated_code)

        # 复制依赖 jar 到 libs/
        if source_mods_path and generated_code.get("dependencies"):
            self._copy_dependencies(source_mods_path, generated_code["dependencies"])

        return self.project_dir

    def _create_directory_structure(self):
        """创建项目目录结构"""
        dirs = [
            self.project_dir,
            os.path.join(self.project_dir, "src", "main", "java"),
            os.path.join(self.project_dir, "src", "main", "resources", "META-INF"),
            os.path.join(self.project_dir, "libs"),
            os.path.join(self.project_dir, "gradle", "wrapper"),
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    def _generate_build_files(self, generated_code: Dict):
        """生成 Gradle 构建文件"""
        # settings.gradle
        settings_template = self._read_template("settings.gradle")
        settings_content = settings_template.replace("${project_name}", self.mod_id)
        self._write_file("settings.gradle", settings_content)

        # gradle.properties
        props_template = self._read_template("gradle.properties")
        props_content = props_template.replace("${minecraft_version}", self.mc_version)
        props_content = props_content.replace("${forge_version}", self.forge_version)
        props_content = props_content.replace("${mod_id}", self.mod_id)
        props_content = props_content.replace("${mod_version}", "1.0.0")
        self._write_file("gradle.properties", props_content)

        # build.gradle
        build_template = self._read_template("build.gradle")
        main_class = generated_code.get("main_class", {})
        mod_group = main_class.get("package", f"com.fix.{self.mod_id}")

        # 构建 libs 依赖
        libs_deps = ""
        deps = generated_code.get("dependencies", [])
        if deps:
            for dep in deps:
                libs_deps += f"    compileOnly files('libs/{dep}')\n"
        else:
            libs_deps = "    // 无额外编译依赖"

        build_content = build_template.replace("${mod_group}", mod_group)
        build_content = build_content.replace("${mod_id}", self.mod_id)
        build_content = build_content.replace("${libs_dependencies}", libs_deps)
        self._write_file("build.gradle", build_content)

        # 内置 Gradle Wrapper
        self._install_gradle_wrapper()

    def _write_java_sources(self, generated_code: Dict):
        """写入 Java 源码文件"""
        # 主类
        main_class = generated_code.get("main_class")
        if main_class:
            self._write_java_file(
                main_class["package"],
                main_class["class_name"],
                main_class["code"],
            )

        # 事件处理类
        for handler in generated_code.get("event_handlers", []):
            self._write_java_file(
                handler["package"],
                handler["class_name"],
                handler["code"],
            )

        # Mixin 类
        for mixin in generated_code.get("mixins", []):
            self._write_java_file(
                mixin["package"],
                mixin["class_name"],
                mixin["code"],
            )

    def _generate_resources(self, generated_code: Dict):
        """生成资源文件"""
        main_class = generated_code.get("main_class", {})
        description = generated_code.get("description", "服务器优化修复模组")

        # META-INF/mods.toml
        mods_toml_template = self._read_template("mods.toml")
        display_name = f"{self.mod_id.replace('_', ' ').title()} Fix"

        # 构建额外依赖
        extra_deps = ""
        deps_mods = generated_code.get("dependencies", [])
        # 从依赖文件名推断 mod ID
        for dep in deps_mods:
            dep_mod_id = dep.replace(".jar", "").split("-")[0].lower().replace(" ", "")
            extra_deps += f"""
[[dependencies.{self.mod_id}]]
modId="{dep_mod_id}"
mandatory=false
versionRange="*"
ordering="AFTER"
side="BOTH"
"""

        mods_toml = mods_toml_template.replace("${mod_id}", self.mod_id)
        mods_toml = mods_toml_template.replace("${mod_id}", self.mod_id)
        mods_toml = mods_toml.replace("${display_name}", display_name)
        mods_toml = mods_toml.replace("${description}", description)
        mods_toml = mods_toml.replace("${minecraft_version}", self.mc_version)
        mods_toml = mods_toml.replace("${extra_dependencies}", extra_deps)
        mods_toml = mods_toml.replace("${file.jarVersion}", "${file.jarVersion}")

        self._write_file(
            os.path.join("src", "main", "resources", "META-INF", "mods.toml"),
            mods_toml,
        )

        # pack.mcmeta
        pack_template = self._read_template("pack.mcmeta")
        pack_content = pack_template.replace("${display_name}", display_name)
        self._write_file(
            os.path.join("src", "main", "resources", "pack.mcmeta"),
            pack_content,
        )

        # mixins.json (如果有 Mixin)
        mixins = generated_code.get("mixins", [])
        if mixins:
            mixin_package = mixins[0]["package"]
            mixin_classes = ",\n".join(
                f'    "{m["class_name"]}"' for m in mixins
            )

            mixins_json_template = self._read_template("mixins.json")
            mixins_json = mixins_json_template.replace("${mixin_package}", mixin_package)
            mixins_json = mixins_json.replace("${mod_id}", self.mod_id)
            mixins_json = mixins_json.replace("${mixin_classes}", mixin_classes)

            self._write_file(
                os.path.join("src", "main", "resources", f"{self.mod_id}.mixins.json"),
                mixins_json,
            )

    def _copy_dependencies(self, mods_path: str, dependencies: List[str]):
        """复制依赖 jar 到 libs 目录"""
        libs_dir = os.path.join(self.project_dir, "libs")
        for dep_name in dependencies:
            src = os.path.join(mods_path, dep_name)
            if os.path.exists(src):
                dst = os.path.join(libs_dir, dep_name)
                shutil.copy2(src, dst)

    def _write_java_file(self, package: str, class_name: str, code: str):
        """写入 Java 源文件"""
        # 将包名转换为目录路径
        package_path = package.replace(".", os.sep)
        dir_path = os.path.join(
            self.project_dir, "src", "main", "java", package_path
        )
        os.makedirs(dir_path, exist_ok=True)

        file_path = os.path.join(dir_path, f"{class_name}.java")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

    def _write_file(self, relative_path: str, content: str):
        """写入文件到项目目录"""
        file_path = os.path.join(self.project_dir, relative_path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _read_template(self, template_name: str) -> str:
        """读取模板文件"""
        template_path = os.path.join(TEMPLATES_DIR, template_name)
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except IOError:
            return ""

    def _install_gradle_wrapper(self):
        """将内置的 Gradle Wrapper 写入项目目录"""
        # 复制 gradle-wrapper.jar
        wrapper_jar_src = os.path.join(TEMPLATES_DIR, "gradle", "wrapper", "gradle-wrapper.jar")
        wrapper_jar_dst = os.path.join(self.project_dir, "gradle", "wrapper", "gradle-wrapper.jar")
        os.makedirs(os.path.dirname(wrapper_jar_dst), exist_ok=True)
        if os.path.isfile(wrapper_jar_src):
            shutil.copy2(wrapper_jar_src, wrapper_jar_dst)

        # 复制 gradle-wrapper.properties
        wrapper_props_src = os.path.join(TEMPLATES_DIR, "gradle", "wrapper", "gradle-wrapper.properties")
        wrapper_props_dst = os.path.join(self.project_dir, "gradle", "wrapper", "gradle-wrapper.properties")
        if os.path.isfile(wrapper_props_src):
            shutil.copy2(wrapper_props_src, wrapper_props_dst)

        # 复制 gradlew (Unix)
        gradlew_src = os.path.join(TEMPLATES_DIR, "gradlew")
        gradlew_dst = os.path.join(self.project_dir, "gradlew")
        if os.path.isfile(gradlew_src):
            shutil.copy2(gradlew_src, gradlew_dst)

        # 复制 gradlew.bat (Windows)
        gradlew_bat_src = os.path.join(TEMPLATES_DIR, "gradlew.bat")
        gradlew_bat_dst = os.path.join(self.project_dir, "gradlew.bat")
        if os.path.isfile(gradlew_bat_src):
            shutil.copy2(gradlew_bat_src, gradlew_bat_dst)



def auto_build_project(project_dir: str, progress_callback: Callable[[str], None] = None) -> Optional[str]:
    """
    自动构建 Forge mod 项目，生成 jar 文件。
    
    需要系统已安装 JDK 17+ 和 Gradle，或项目中有 Gradle Wrapper。
    
    Args:
        project_dir: 项目目录路径
        progress_callback: 进度回调函数
    
    Returns:
        构建成功时返回生成的 jar 文件路径，失败返回 None
    """
    log = progress_callback or (lambda msg: None)

    # 检查 Java 环境
    java_home = _find_java()
    if not java_home:
        log("错误: 未找到 JDK 17+，请安装 JDK 并确保 JAVA_HOME 已设置或 java 在 PATH 中")
        log("下载地址: https://adoptium.net/")
        return None

    log(f"找到 Java: {java_home}")

    # 查找 Gradle
    gradle_cmd = _find_gradle(project_dir)
    if not gradle_cmd:
        log("未找到 Gradle，正在尝试使用 Gradle Wrapper...")
        # 尝试生成 wrapper
        if not _setup_gradle_wrapper(project_dir, log):
            log("错误: 未找到 Gradle。请安装 Gradle 并添加到 PATH")
            log("下载地址: https://gradle.org/releases/")
            log("或手动在项目目录运行: gradle wrapper")
            return None
        gradle_cmd = _find_gradle(project_dir)
        if not gradle_cmd:
            log("错误: Gradle Wrapper 设置失败")
            return None

    log(f"使用 Gradle: {gradle_cmd}")
    log("开始构建项目（首次构建可能需要几分钟下载依赖）...")

    # 执行构建
    try:
        env = os.environ.copy()
        if java_home and java_home != "system":
            env["JAVA_HOME"] = java_home

        # 构建命令
        if isinstance(gradle_cmd, list):
            cmd = gradle_cmd + ["build", "--no-daemon", "-x", "test"]
        else:
            cmd = [gradle_cmd, "build", "--no-daemon", "-x", "test"]

        process = subprocess.Popen(
            cmd,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        # 实时输出构建日志
        build_output = []
        for line in process.stdout:
            line = line.rstrip()
            if line:
                log(f"  [gradle] {line}")
                build_output.append(line)

        process.wait()

        if process.returncode == 0:
            # 查找生成的 jar
            jar_path = _find_built_jar(project_dir)
            if jar_path:
                log(f"\n构建成功!")
                log(f"生成的 jar: {jar_path}")
                return jar_path
            else:
                log("构建完成但未找到输出 jar 文件")
                return None
        else:
            log(f"\n构建失败 (退出码: {process.returncode})")
            # 返回错误信息字符串（以 "BUILD_ERROR:" 前缀标识）
            # 收集所有可能包含错误信息的行（编译错误、符号找不到、类型不匹配等）
            error_lines = [l for l in build_output if any(kw in l for kw in [
                "error", "Error", "FAILED", "cannot", "symbol",
                "private", "public", "access", "找不到", "错误",
                "incompatible", "unreported", "package", "does not exist",
                ".java:", "^",
            ])]
            # 限制长度避免 token 过多
            error_text = "\n".join(error_lines[:30])
            return f"BUILD_ERROR:{error_text}" if error_text else "BUILD_ERROR:Unknown compilation error"

    except FileNotFoundError:
        log(f"错误: 无法执行 Gradle 命令: {gradle_cmd}")
        return None
    except Exception as e:
        log(f"构建出错: {type(e).__name__}: {str(e)}")
        return None


def _find_java() -> Optional[str]:
    """查找 Java 安装路径"""
    # 检查 JAVA_HOME
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home and os.path.isdir(java_home):
        java_exe = os.path.join(java_home, "bin", "java.exe")
        if os.path.isfile(java_exe):
            # 验证版本
            try:
                result = subprocess.run(
                    [java_exe, "-version"],
                    capture_output=True, text=True, timeout=10
                )
                output = result.stderr + result.stdout
                if "version" in output:
                    return java_home
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

    # 检查 PATH 中的 java
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return "system"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # 检查常见安装路径
    common_paths = [
        r"C:\Program Files\Java",
        r"C:\Program Files\Eclipse Adoptium",
        r"C:\Program Files\Microsoft\jdk-17*",
    ]
    import glob
    for pattern in common_paths:
        for path in glob.glob(pattern):
            if os.path.isdir(path):
                # 查找 jdk-17 或更高版本
                for item in os.listdir(path):
                    jdk_path = os.path.join(path, item)
                    java_exe = os.path.join(jdk_path, "bin", "java.exe")
                    if os.path.isfile(java_exe):
                        return jdk_path

    return None


def _find_gradle(project_dir: str) -> Optional[any]:
    """查找可用的 Gradle 命令"""
    # 优先使用项目中的 Gradle Wrapper
    if os.name == "nt":
        gradlew = os.path.join(project_dir, "gradlew.bat")
    else:
        gradlew = os.path.join(project_dir, "gradlew")

    # 检查 wrapper jar 是否存在
    wrapper_jar = os.path.join(project_dir, "gradle", "wrapper", "gradle-wrapper.jar")
    if os.path.isfile(wrapper_jar):
        if os.name == "nt":
            return [gradlew]
        else:
            return ["sh", gradlew]

    # 检查系统 Gradle
    try:
        result = subprocess.run(
            ["gradle", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return "gradle"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _setup_gradle_wrapper(project_dir: str, log: Callable) -> bool:
    """尝试使用系统 Gradle 生成 Wrapper"""
    try:
        result = subprocess.run(
            ["gradle", "wrapper", "--gradle-version", "8.12"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            log("Gradle Wrapper 生成成功")
            return True
        else:
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _find_built_jar(project_dir: str) -> Optional[str]:
    """查找构建生成的 jar 文件"""
    libs_dir = os.path.join(project_dir, "build", "libs")
    if not os.path.isdir(libs_dir):
        return None

    # 查找非 sources/javadoc 的 jar
    for fname in os.listdir(libs_dir):
        if fname.endswith(".jar") and "-sources" not in fname and "-javadoc" not in fname:
            return os.path.join(libs_dir, fname)

    return None
