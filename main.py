"""
MC 优化模组生成器 - 主程序 (GUI)
分析 Minecraft 服务器/客户端日志和 mods 目录，调用 AI 生成针对性的优化模组。
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from config import load_config, save_config, get_default_output_dir, APP_DATA_DIR
from mod_scanner import scan_mods_directory, detect_server_version
from analyzer import LogAnalyzer, find_log_files
from ai_generator import AIGenerator
from project_builder import ProjectBuilder, auto_build_project


class Application(tk.Tk):
    """主应用窗口"""

    def __init__(self):
        super().__init__()
        self.title("MC 优化模组生成器")
        self.geometry("900x700")
        self.minsize(800, 600)

        self.config_data = load_config()
        self.issues = []
        self.installed_mods = []
        self.is_running = False

        self._create_ui()
        self._load_saved_paths()

        # 窗口关闭时自动保存配置
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_ui(self):
        """创建 UI 布局"""
        # 主容器
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === 输入区域 ===
        input_frame = ttk.LabelFrame(main_frame, text="输入", padding=8)
        input_frame.pack(fill=tk.X, pady=(0, 8))

        # 模式选择（服务端/客户端）
        mode_frame = ttk.Frame(input_frame)
        mode_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(mode_frame, text="优化模式:", width=10).pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value=self.config_data.get("optimize_mode", "server"))
        ttk.Radiobutton(mode_frame, text="服务端优化（内存泄漏修复）", variable=self.mode_var,
                        value="server", command=self._on_mode_change).pack(side=tk.LEFT, padx=8)
        ttk.Radiobutton(mode_frame, text="客户端优化（帧率/渲染优化）", variable=self.mode_var,
                        value="client", command=self._on_mode_change).pack(side=tk.LEFT, padx=8)

        # 日志路径
        log_frame = ttk.Frame(input_frame)
        log_frame.pack(fill=tk.X, pady=2)
        ttk.Label(log_frame, text="日志路径:", width=10).pack(side=tk.LEFT)
        self.log_path_var = tk.StringVar()
        ttk.Entry(log_frame, textvariable=self.log_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(log_frame, text="选择目录", command=self._browse_log_dir).pack(side=tk.LEFT, padx=2)
        ttk.Button(log_frame, text="选择文件", command=self._browse_log_file).pack(side=tk.LEFT)

        # Mods 目录
        mods_frame = ttk.Frame(input_frame)
        mods_frame.pack(fill=tk.X, pady=2)
        ttk.Label(mods_frame, text="Mods目录:", width=10).pack(side=tk.LEFT)
        self.mods_path_var = tk.StringVar()
        ttk.Entry(mods_frame, textvariable=self.mods_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(mods_frame, text="浏览...", command=self._browse_mods_dir).pack(side=tk.LEFT)

        # 输出目录
        output_frame = ttk.Frame(input_frame)
        output_frame.pack(fill=tk.X, pady=2)
        ttk.Label(output_frame, text="输出目录:", width=10).pack(side=tk.LEFT)
        self.output_path_var = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.output_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(output_frame, text="浏览...", command=self._browse_output_dir).pack(side=tk.LEFT)

        # === AI 配置区域 ===
        ai_frame = ttk.LabelFrame(main_frame, text="AI 配置", padding=8)
        ai_frame.pack(fill=tk.X, pady=(0, 8))

        # 后端选择
        backend_frame = ttk.Frame(ai_frame)
        backend_frame.pack(fill=tk.X, pady=2)
        ttk.Label(backend_frame, text="AI 后端:").pack(side=tk.LEFT)
        self.backend_var = tk.StringVar(value=self.config_data.get("ai_backend", "openai"))
        ttk.Radiobutton(backend_frame, text="OpenAI 兼容", variable=self.backend_var,
                        value="openai", command=self._on_backend_change).pack(side=tk.LEFT, padx=8)
        ttk.Radiobutton(backend_frame, text="Claude", variable=self.backend_var,
                        value="claude", command=self._on_backend_change).pack(side=tk.LEFT, padx=8)

        # OpenAI 配置
        self.openai_frame = ttk.Frame(ai_frame)
        self.openai_frame.pack(fill=tk.X, pady=2)

        row1 = ttk.Frame(self.openai_frame)
        row1.pack(fill=tk.X, pady=1)
        ttk.Label(row1, text="Base URL:", width=10).pack(side=tk.LEFT)
        self.openai_url_var = tk.StringVar(value=self.config_data.get("openai_base_url", ""))
        ttk.Entry(row1, textvariable=self.openai_url_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        row2 = ttk.Frame(self.openai_frame)
        row2.pack(fill=tk.X, pady=1)
        ttk.Label(row2, text="API Key:", width=10).pack(side=tk.LEFT)
        self.openai_key_var = tk.StringVar(value=self.config_data.get("openai_api_key", ""))
        self.openai_key_entry = ttk.Entry(row2, textvariable=self.openai_key_var, show="*")
        self.openai_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.openai_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="显示", variable=self.openai_show_var,
                        command=lambda: self.openai_key_entry.config(
                            show="" if self.openai_show_var.get() else "*"
                        )).pack(side=tk.LEFT)

        row3 = ttk.Frame(self.openai_frame)
        row3.pack(fill=tk.X, pady=1)
        ttk.Label(row3, text="模型:", width=10).pack(side=tk.LEFT)
        self.openai_model_var = tk.StringVar(value=self.config_data.get("openai_model", "gpt-4o"))
        ttk.Entry(row3, textvariable=self.openai_model_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        # Claude 配置
        self.claude_frame = ttk.Frame(ai_frame)

        crow1 = ttk.Frame(self.claude_frame)
        crow1.pack(fill=tk.X, pady=1)
        ttk.Label(crow1, text="API Key:", width=10).pack(side=tk.LEFT)
        self.claude_key_var = tk.StringVar(value=self.config_data.get("claude_api_key", ""))
        self.claude_key_entry = ttk.Entry(crow1, textvariable=self.claude_key_var, show="*")
        self.claude_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.claude_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(crow1, text="显示", variable=self.claude_show_var,
                        command=lambda: self.claude_key_entry.config(
                            show="" if self.claude_show_var.get() else "*"
                        )).pack(side=tk.LEFT)

        crow2 = ttk.Frame(self.claude_frame)
        crow2.pack(fill=tk.X, pady=1)
        ttk.Label(crow2, text="模型:", width=10).pack(side=tk.LEFT)
        self.claude_model_var = tk.StringVar(value=self.config_data.get("claude_model", "claude-sonnet-4-20250514"))
        ttk.Entry(crow2, textvariable=self.claude_model_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self._on_backend_change()

        # Mod ID 配置
        modid_frame = ttk.Frame(ai_frame)
        modid_frame.pack(fill=tk.X, pady=2)
        ttk.Label(modid_frame, text="Mod ID:", width=10).pack(side=tk.LEFT)
        self.mod_id_var = tk.StringVar(value=self.config_data.get("mod_id", "serverfix"))
        ttk.Entry(modid_frame, textvariable=self.mod_id_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Label(modid_frame, text="(生成的修复模组 ID，小写字母+下划线)").pack(side=tk.LEFT)

        # 自动构建选项
        build_frame = ttk.Frame(ai_frame)
        build_frame.pack(fill=tk.X, pady=2)
        self.auto_build_var = tk.BooleanVar(value=self.config_data.get("auto_build", False))
        ttk.Checkbutton(build_frame, text="自动构建（生成后自动编译为 jar，需要 JDK 17+ 和 Gradle）",
                        variable=self.auto_build_var).pack(side=tk.LEFT)

        # === 操作按钮 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=4)

        self.analyze_btn = ttk.Button(btn_frame, text="1. 分析日志", command=self._start_analyze)
        self.analyze_btn.pack(side=tk.LEFT, padx=4)

        self.generate_btn = ttk.Button(btn_frame, text="2. 生成优化模组", command=self._start_generate, state=tk.DISABLED)
        self.generate_btn.pack(side=tk.LEFT, padx=4)

        self.open_btn = ttk.Button(btn_frame, text="打开输出目录", command=self._open_output, state=tk.DISABLED)
        self.open_btn.pack(side=tk.RIGHT, padx=4)

        # 进度条
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, mode="indeterminate")
        self.progress_bar.pack(fill=tk.X, pady=4)

        # === 输出区域 ===
        output_notebook = ttk.Notebook(main_frame)
        output_notebook.pack(fill=tk.BOTH, expand=True)

        # 日志标签页
        log_tab = ttk.Frame(output_notebook)
        output_notebook.add(log_tab, text="运行日志")
        self.log_text = scrolledtext.ScrolledText(log_tab, height=12, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 问题列表标签页
        issues_tab = ttk.Frame(output_notebook)
        output_notebook.add(issues_tab, text="检测到的问题")
        self.issues_text = scrolledtext.ScrolledText(issues_tab, height=12, font=("Consolas", 9))
        self.issues_text.pack(fill=tk.BOTH, expand=True)

        # Mods 列表标签页
        mods_tab = ttk.Frame(output_notebook)
        output_notebook.add(mods_tab, text="已安装 Mods")
        self.mods_text = scrolledtext.ScrolledText(mods_tab, height=12, font=("Consolas", 9))
        self.mods_text.pack(fill=tk.BOTH, expand=True)

        # === 底部制作者信息 ===
        credit_frame = ttk.Frame(main_frame)
        credit_frame.pack(fill=tk.X, side=tk.BOTTOM)
        credit_text = "制作者: yuuka0desu | GitHub: https://github.com/yuuka0desu | QQ: 3458164587"
        ttk.Label(credit_frame, text=credit_text, foreground="gray",
                  font=("", 8)).pack(side=tk.RIGHT, pady=2)

    def _on_backend_change(self):
        """切换 AI 后端时更新 UI"""
        if self.backend_var.get() == "openai":
            self.claude_frame.pack_forget()
            self.openai_frame.pack(fill=tk.X, pady=2)
        else:
            self.openai_frame.pack_forget()
            self.claude_frame.pack(fill=tk.X, pady=2)

    def _on_mode_change(self):
        """切换优化模式时更新 UI 提示"""
        mode = self.mode_var.get()
        if mode == "client":
            self.mod_id_var.set("clientfix")
        else:
            self.mod_id_var.set("serverfix")

    def _browse_log_dir(self):
        mode = self.mode_var.get()
        if mode == "client":
            title = "选择客户端日志目录（.minecraft/logs 或 .minecraft 根目录）"
        else:
            title = "选择服务器日志目录（logs 或服务器根目录）"
        path = filedialog.askdirectory(title=title)
        if path:
            self.log_path_var.set(path)

    def _browse_log_file(self):
        path = filedialog.askopenfilename(
            title="选择日志文件",
            filetypes=[("日志文件", "*.log *.txt"), ("所有文件", "*.*")]
        )
        if path:
            self.log_path_var.set(path)

    def _browse_mods_dir(self):
        path = filedialog.askdirectory(title="选择 mods 目录")
        if path:
            self.mods_path_var.set(path)

    def _browse_output_dir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_path_var.set(path)

    def _open_output(self):
        output_path = self.output_path_var.get()
        mod_id = self.mod_id_var.get().strip() or "serverfix"
        project_dir = os.path.join(output_path, mod_id)
        if os.path.isdir(project_dir):
            os.startfile(project_dir)
        elif os.path.isdir(output_path):
            os.startfile(output_path)

    def _load_saved_paths(self):
        """加载上次使用的路径"""
        if self.config_data.get("last_log_path"):
            self.log_path_var.set(self.config_data["last_log_path"])
        if self.config_data.get("last_mods_path"):
            self.mods_path_var.set(self.config_data["last_mods_path"])
        if self.config_data.get("last_output_path"):
            self.output_path_var.set(self.config_data["last_output_path"])
        else:
            # 默认输出到应用数据目录下的 output 文件夹
            self.output_path_var.set(get_default_output_dir())

    def _on_close(self):
        """窗口关闭时保存配置"""
        self._save_current_config()
        self.destroy()

    def _save_current_config(self):
        """保存当前配置"""
        self.config_data["ai_backend"] = self.backend_var.get()
        self.config_data["openai_base_url"] = self.openai_url_var.get()
        self.config_data["openai_api_key"] = self.openai_key_var.get()
        self.config_data["openai_model"] = self.openai_model_var.get()
        self.config_data["claude_api_key"] = self.claude_key_var.get()
        self.config_data["claude_model"] = self.claude_model_var.get()
        self.config_data["last_log_path"] = self.log_path_var.get()
        self.config_data["last_mods_path"] = self.mods_path_var.get()
        self.config_data["last_output_path"] = self.output_path_var.get()
        self.config_data["optimize_mode"] = self.mode_var.get()
        self.config_data["mod_id"] = self.mod_id_var.get()
        self.config_data["auto_build"] = self.auto_build_var.get()
        save_config(self.config_data)

    def _log(self, message: str):
        """输出日志到 UI（线程安全）"""
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.after(0, _append)

    def _set_running(self, running: bool):
        """设置运行状态"""
        self.is_running = running
        def _update():
            if running:
                self.progress_bar.start(10)
                self.analyze_btn.config(state=tk.DISABLED)
                self.generate_btn.config(state=tk.DISABLED)
            else:
                self.progress_bar.stop()
                self.progress_var.set(0)
                self.analyze_btn.config(state=tk.NORMAL)
                if self.issues:
                    self.generate_btn.config(state=tk.NORMAL)
        self.after(0, _update)

    # === 分析流程 ===

    def _start_analyze(self):
        """开始分析（在后台线程执行）"""
        log_path = self.log_path_var.get().strip()
        mods_path = self.mods_path_var.get().strip()

        if not log_path:
            messagebox.showwarning("提示", "请选择日志文件或目录")
            return

        if not mods_path:
            messagebox.showwarning("提示", "请选择 mods 目录")
            return

        self._save_current_config()
        self._set_running(True)

        thread = threading.Thread(target=self._do_analyze, args=(log_path, mods_path), daemon=True)
        thread.start()

    def _do_analyze(self, log_path: str, mods_path: str):
        """执行分析（后台线程）"""
        try:
            mode = self.mode_var.get()
            mode_name = "客户端" if mode == "client" else "服务端"

            # 扫描 mods
            self._log(f"[{mode_name}模式] 正在扫描 mods 目录...")
            self.installed_mods = scan_mods_directory(mods_path)
            self._log(f"发现 {len(self.installed_mods)} 个 mod")

            # 显示 mods 列表
            self._display_mods()

            # 查找日志文件
            self._log("正在查找日志文件...")
            if os.path.isfile(log_path):
                log_files = [log_path]
            else:
                log_files = find_log_files(log_path)

            if not log_files:
                self._log("警告: 未找到日志文件，将仅基于已安装 mod 进行分析")
                log_files = []
            else:
                self._log(f"找到 {len(log_files)} 个日志文件")

            # 分析日志
            self._log(f"正在进行{mode_name}性能分析...")
            analyzer = LogAnalyzer(mode=mode)
            self.issues = analyzer.analyze(log_files, self.installed_mods)

            # 显示结果
            self._display_issues()

            if self.issues:
                self._log(f"\n分析完成! 检测到 {len(self.issues)} 个问题。")
                self._log("请点击 '2. 生成优化模组' 来生成优化代码。")
            else:
                self._log("\n分析完成，未检测到明显的性能问题。")
                if self.installed_mods:
                    self._log("你仍然可以基于已安装的 mod 生成通用优化模组。")
                    if mode == "client":
                        self.issues = [{
                            "issue_type": "general_client_optimization",
                            "severity": "medium",
                            "description": "通用客户端性能优化",
                            "involved_mods": [m["mod_id"] for m in self.installed_mods[:5]],
                            "evidence": ["基于已安装 mod 列表生成通用客户端优化"],
                            "suggestion": "优化渲染管线、减少内存分配、缓存模型和纹理",
                        }]
                    else:
                        self.issues = [{
                            "issue_type": "general_optimization",
                            "severity": "medium",
                            "description": "通用服务器内存优化",
                            "involved_mods": [m["mod_id"] for m in self.installed_mods[:5]],
                            "evidence": ["基于已安装 mod 列表生成通用优化"],
                            "suggestion": "定期清理实体引用和静态集合",
                        }]

        except Exception as e:
            self._log(f"分析出错: {str(e)}")
            import traceback
            self._log(traceback.format_exc())
        finally:
            self._set_running(False)

    def _display_mods(self):
        """显示 mods 列表"""
        def _update():
            self.mods_text.delete("1.0", tk.END)
            for mod in self.installed_mods:
                line = f"[{mod['loader']}] {mod['display_name']} ({mod['mod_id']}) v{mod['version']}"
                if mod.get("dependencies"):
                    line += f"  依赖: {', '.join(mod['dependencies'][:3])}"
                self.mods_text.insert(tk.END, line + "\n")
        self.after(0, _update)

    def _display_issues(self):
        """显示检测到的问题"""
        def _update():
            self.issues_text.delete("1.0", tk.END)
            for i, issue in enumerate(self.issues, 1):
                if isinstance(issue, dict):
                    issue_dict = issue
                else:
                    issue_dict = issue.to_dict()

                severity_icon = {"critical": "[!!!]", "high": "[!!]", "medium": "[!]", "low": "[.]"}
                icon = severity_icon.get(issue_dict["severity"], "[?]")

                self.issues_text.insert(tk.END, f"\n{'='*60}\n")
                self.issues_text.insert(tk.END, f"{icon} 问题 {i}: {issue_dict['description']}\n")
                self.issues_text.insert(tk.END, f"    严重程度: {issue_dict['severity']}\n")
                self.issues_text.insert(tk.END, f"    涉及 mod: {', '.join(issue_dict['involved_mods']) or '未知'}\n")
                self.issues_text.insert(tk.END, f"    建议: {issue_dict['suggestion']}\n")
                if issue_dict.get("evidence"):
                    self.issues_text.insert(tk.END, f"    证据:\n")
                    for ev in issue_dict["evidence"][:3]:
                        self.issues_text.insert(tk.END, f"      > {ev}\n")
        self.after(0, _update)

    # === 生成流程 ===

    def _start_generate(self):
        """开始生成修复模组"""
        output_path = self.output_path_var.get().strip()
        if not output_path:
            messagebox.showwarning("提示", "请选择输出目录")
            return

        mod_id = self.mod_id_var.get().strip()
        if not mod_id:
            messagebox.showwarning("提示", "请填写 Mod ID")
            return

        # 验证 API 配置
        backend = self.backend_var.get()
        if backend == "openai" and not self.openai_key_var.get().strip():
            messagebox.showwarning("提示", "请填写 OpenAI API Key")
            return
        if backend == "claude" and not self.claude_key_var.get().strip():
            messagebox.showwarning("提示", "请填写 Claude API Key")
            return

        self._save_current_config()
        self._set_running(True)

        thread = threading.Thread(target=self._do_generate, daemon=True)
        thread.start()

    def _do_generate(self):
        """执行生成（后台线程）"""
        try:
            mod_id = self.mod_id_var.get().strip()
            output_path = self.output_path_var.get().strip()
            mods_path = self.mods_path_var.get().strip()
            mode = self.mode_var.get()
            mode_name = "客户端" if mode == "client" else "服务端"

            # 准备问题数据
            issues_data = []
            for issue in self.issues:
                if isinstance(issue, dict):
                    issues_data.append(issue)
                else:
                    issues_data.append(issue.to_dict())

            # 调用 AI 生成代码
            self._log(f"\n开始生成{mode_name}优化模组...")
            generator = AIGenerator(self.config_data, progress_callback=self._log)
            result = generator.generate_fix_mod(
                issues=issues_data,
                installed_mods=self.installed_mods,
                mod_id=mod_id,
                mc_version=self.config_data.get("minecraft_version", "1.20.1"),
                mode=mode,
            )

            if not result:
                self._log("错误: AI 代码生成失败")
                return

            self._log("AI 代码生成成功，正在组装项目...")

            # 构建项目
            builder = ProjectBuilder(
                output_dir=output_path,
                mod_id=mod_id,
                mc_version=self.config_data.get("minecraft_version", "1.20.1"),
                forge_version=self.config_data.get("forge_version", "47.2.0"),
            )

            project_dir = builder.build(result, source_mods_path=mods_path)

            self._log(f"\n项目生成成功!")
            self._log(f"输出目录: {project_dir}")

            # 自动构建
            if self.auto_build_var.get():
                self._log(f"\n{'='*50}")
                self._log("开始自动构建...")
                jar_path = auto_build_project(project_dir, progress_callback=self._log)
                if jar_path:
                    self._log(f"\n构建完成! jar 文件:")
                    self._log(f"  {jar_path}")
                    if mode == "client":
                        self._log(f"\n将此 jar 复制到客户端 .minecraft/mods/ 目录即可使用")
                    else:
                        self._log(f"\n将此 jar 复制到服务器 mods/ 目录即可使用")
                else:
                    self._log("\n自动构建失败，你可以手动构建：")
                    self._log(f"  cd {project_dir}")
                    self._log(f"  gradle build")
            else:
                self._log(f"\n使用方法:")
                self._log(f"  1. 安装 JDK 17+ 和 Gradle")
                self._log(f"  2. 在项目目录运行: gradle build")
                if mode == "client":
                    self._log(f"  3. 将 build/libs/ 下的 jar 放入客户端 mods 目录")
                else:
                    self._log(f"  3. 将 build/libs/ 下的 jar 放入服务器 mods 目录")

            # 启用打开目录按钮
            self.after(0, lambda: self.open_btn.config(state=tk.NORMAL))

        except Exception as e:
            self._log(f"生成出错: {str(e)}")
            import traceback
            self._log(traceback.format_exc())
        finally:
            self._set_running(False)


def main():
    app = Application()
    app.mainloop()


if __name__ == "__main__":
    main()
