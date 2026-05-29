# MC 优化模组生成器

分析 Minecraft 服务器/客户端日志和 mods 目录，调用 AI 自动生成针对性的优化修复模组。

## 功能

- **服务端优化模式**：检测内存泄漏（实体引用泄漏、静态集合增长、Capability 未释放等），生成修复 mod
- **客户端优化模式**：检测渲染性能问题（FPS 下降、纹理泄漏、LocalPlayer 引用泄漏等），生成优化 mod
- **AI 代码生成**：支持 OpenAI 兼容 API 和 Claude API，可接入本地模型
- **自动构建**：内置 Gradle Wrapper，勾选后自动编译为可用的 jar 文件
- **完整项目输出**：生成包含 build.gradle、Mixin 配置、Java 源码的完整 Forge mod 项目

## 使用方法

1. 运行 `MC优化模组生成器.exe`（或 `python main.py`）
2. 选择优化模式（服务端/客户端）
3. 导入日志文件和 mods 目录
4. 配置 AI API（OpenAI 兼容或 Claude）
5. 点击"分析日志"查看检测到的问题
6. 点击"生成优化模组"生成修复代码

## 环境要求

- Python 3.8+（开发环境）
- requests 库
- JDK 17+（自动构建时需要）

## 项目结构

```
mc-optimizer/
├── main.py              # GUI 主程序
├── config.py            # 配置管理
├── mod_scanner.py       # Mods 目录扫描器
├── analyzer.py          # 日志分析引擎
├── ai_generator.py      # AI 代码生成器
├── project_builder.py   # Forge 项目生成器
├── requirements.txt     # Python 依赖
└── templates/           # Forge 项目模板 + Gradle Wrapper
```

## 开源协议

MIT License
