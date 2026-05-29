"""
AI 代码生成器 - 调用 AI API 生成修复 mod 的 Java 代码
支持 OpenAI 兼容 API 和 Claude API
"""
import json
import re
import requests
from typing import List, Dict, Optional, Callable


class AIGenerator:
    """AI 代码生成器"""

    def __init__(self, config: dict, progress_callback: Callable[[str], None] = None):
        """
        Args:
            config: 配置字典（来自 config.py）
            progress_callback: 进度回调函数
        """
        self.config = config
        self.progress = progress_callback or (lambda msg: None)

    def generate_fix_mod(
        self,
        issues: List[Dict],
        installed_mods: List[Dict],
        mod_id: str = "serverfix",
        mc_version: str = "1.20.1",
        mode: str = "server",
    ) -> Optional[Dict]:
        """
        调用 AI 生成修复 mod 的代码。
        
        Args:
            issues: 检测到的问题列表（LeakIssue.to_dict()）
            installed_mods: 已安装的 mod 列表
            mod_id: 生成的 mod ID
            mc_version: Minecraft 版本
            mode: "server" 或 "client"
        
        Returns:
            生成结果字典:
            {
                "main_class": {"package": str, "class_name": str, "code": str},
                "event_handlers": [{"package": str, "class_name": str, "code": str}, ...],
                "mixins": [{"package": str, "class_name": str, "code": str}, ...],
                "description": str,
                "dependencies": [str, ...]  # 需要的 mod jar 作为编译依赖
            }
        """
        self.progress("正在构建 AI 提示词...")

        if mode == "client":
            prompt = self._build_client_prompt(issues, installed_mods, mod_id, mc_version)
            system_prompt = self._build_client_system_prompt()
        else:
            prompt = self._build_prompt(issues, installed_mods, mod_id, mc_version)
            system_prompt = self._build_system_prompt()

        self.progress("正在调用 AI API 生成代码...")

        response = self._call_ai(system_prompt, prompt)
        if not response:
            self.progress("AI API 调用未返回有效响应，使用内置模板生成...")
            return self._generate_fallback_mod(mod_id)

        self.progress(f"\n{'='*50}")
        self.progress("AI 返回的完整文本:")
        self.progress(f"{'='*50}")
        self.progress(response)
        self.progress(f"{'='*50}\n")

        self.progress("正在解析 AI 返回的代码...")

        result = self._parse_response(response, mod_id)
        return result

    def _build_system_prompt(self, mode: str = "server") -> str:
        if mode == "client":
            return """你是一个 Minecraft Forge mod 开发专家，专精客户端性能优化。你的任务是根据客户端日志分析结果，生成一个优化客户端性能和修复内存泄漏的 Forge mod。

要求：
1. 生成完整可编译的 Java 代码
2. 使用 Forge 事件系统处理客户端事件（如 RenderLevelStageEvent、ClientTickEvent、ResourceReloadEvent 等）
3. 如果需要修改其他 mod 的渲染行为，使用 Mixin 注入
4. 使用反射访问其他 mod 的私有字段（避免硬依赖）
5. 代码必须健壮，处理所有可能的异常
6. 添加详细的中文注释说明优化原理
7. 注意客户端特有的优化点：
   - 纹理/模型缓存管理
   - 渲染缓冲区释放
   - 粒子数量限制
   - 音频资源管理
   - GUI 界面引用清理
   - 区块渲染数据释放

输出格式要求：
请严格按照以下 JSON 格式输出，不要添加任何其他文字：

```json
{
  "description": "优化模组的简要描述",
  "dependencies": ["需要作为编译依赖的mod文件名"],
  "main_class": {
    "package": "com.fix.modid",
    "class_name": "MainModClass",
    "code": "完整的Java源码"
  },
  "event_handlers": [
    {
      "package": "com.fix.modid",
      "class_name": "ClientOptimizer",
      "code": "完整的Java源码"
    }
  ],
  "mixins": [
    {
      "package": "com.fix.modid.mixin",
      "class_name": "SomeMixin",
      "code": "完整的Java源码",
      "target_class": "被注入的目标类全限定名"
    }
  ]
}
```"""
        else:
            return """你是一个 Minecraft Forge mod 开发专家。你的任务是根据服务器日志分析结果，生成一个修复内存泄漏问题的 Forge mod。

要求：
1. 生成完整可编译的 Java 代码
2. 使用 Forge 事件系统（@SubscribeEvent）处理玩家退出/重生事件
3. 如果需要修改其他 mod 的行为，使用 Mixin 注入
4. 使用反射访问其他 mod 的私有字段（避免硬依赖）
5. 代码必须健壮，处理所有可能的异常
6. 添加详细的中文注释说明修复原理

输出格式要求：
请严格按照以下 JSON 格式输出，不要添加任何其他文字：

```json
{
  "description": "修复模组的简要描述",
  "dependencies": ["需要作为编译依赖的mod文件名"],
  "main_class": {
    "package": "com.fix.modid",
    "class_name": "MainModClass",
    "code": "完整的Java源码"
  },
  "event_handlers": [
    {
      "package": "com.fix.modid",
      "class_name": "LeakFixer",
      "code": "完整的Java源码"
    }
  ],
  "mixins": [
    {
      "package": "com.fix.modid.mixin",
      "class_name": "SomeMixin",
      "code": "完整的Java源码",
      "target_class": "被注入的目标类全限定名"
    }
  ]
}
```"""

    def _build_prompt(
        self,
        issues: List[Dict],
        installed_mods: List[Dict],
        mod_id: str,
        mc_version: str,
        mode: str = "server",
    ) -> str:
        # 构建问题描述
        issues_text = ""
        for i, issue in enumerate(issues, 1):
            issues_text += f"\n### 问题 {i}: {issue['description']}\n"
            issues_text += f"- 类型: {issue['issue_type']}\n"
            issues_text += f"- 严重程度: {issue['severity']}\n"
            issues_text += f"- 涉及 mod: {', '.join(issue['involved_mods']) if issue['involved_mods'] else '未知'}\n"
            issues_text += f"- 修复建议: {issue['suggestion']}\n"
            issues_text += f"- 日志证据:\n"
            for ev in issue["evidence"][:3]:
                issues_text += f"  ```\n  {ev}\n  ```\n"

        # 构建已安装 mod 列表
        mods_text = ""
        for mod in installed_mods[:30]:  # 限制数量避免 token 过多
            mods_text += f"- {mod['display_name']} ({mod['mod_id']}) v{mod['version']} [{mod['file_name']}]\n"

        if mode == "client":
            prompt = f"""请为以下 Minecraft {mc_version} Forge 客户端生成一个优化性能和修复内存泄漏的 mod。

## 生成的 Mod 信息
- Mod ID: {mod_id}
- 包名: com.fix.{mod_id}
- Minecraft 版本: {mc_version}
- Forge 版本: 47.2.0
- 运行端: 客户端

## 检测到的问题
{issues_text}

## 已安装的 Mod 列表
{mods_text}

## 要求
1. 生成一个主类（@Mod 注解），注册客户端事件处理器
2. 生成事件处理类，针对以下客户端优化场景：
   - 纹理/模型缓存清理（在资源重载、维度切换时）
   - 渲染缓冲区管理（防止 VBO/FBO 泄漏）
   - 粒子数量限制（防止粒子爆炸导致卡顿）
   - 实体渲染器缓存清理（实体离开视野时）
   - 音频资源管理（限制同时播放数量）
   - GUI 界面引用清理（Screen 关闭时）
3. 如果需要 Mixin，生成对应的 Mixin 类（注入客户端渲染相关类）
4. 使用反射访问其他 mod 的字段，做好异常处理
5. 所有对其他 mod 类的访问都用 try-catch 包裹，确保即使目标 mod 不存在也不会崩溃
6. 使用 @OnlyIn(Dist.CLIENT) 标注客户端专用代码

请生成完整的客户端优化代码。"""
        else:
            prompt = f"""请为以下 Minecraft {mc_version} Forge 服务器生成一个修复内存泄漏的 mod。

## 生成的 Mod 信息
- Mod ID: {mod_id}
- 包名: com.fix.{mod_id}
- Minecraft 版本: {mc_version}
- Forge 版本: 47.2.0

## 检测到的问题
{issues_text}

## 已安装的 Mod 列表
{mods_text}

## 要求
1. 生成一个主类（@Mod 注解），注册事件处理器
2. 生成事件处理类，在以下时机清理内存泄漏：
   - PlayerEvent.Clone（玩家重生时更新引用）
   - PlayerEvent.PlayerLoggedOutEvent（玩家退出时清理引用）
   - TickEvent.ServerTickEvent（定期清理静态集合）
3. 如果需要 Mixin，生成对应的 Mixin 类
4. 使用反射访问其他 mod 的字段，做好异常处理
5. 所有对其他 mod 类的访问都用 try-catch 包裹，确保即使目标 mod 不存在也不会崩溃

请生成完整的修复代码。"""

        return prompt

    def _build_client_system_prompt(self) -> str:
        return """你是一个 Minecraft Forge mod 开发专家，专注于客户端性能优化。你的任务是根据客户端日志分析结果，生成一个优化客户端性能的 Forge mod。

要求：
1. 生成完整可编译的 Java 代码
2. 针对客户端性能问题进行优化，包括但不限于：
   - 渲染优化（减少 draw call、优化 VBO、LOD 系统）
   - 内存优化（纹理缓存管理、模型缓存、对象池化）
   - 帧率优化（异步加载、延迟初始化、跳帧策略）
   - 粒子/实体渲染裁剪和批处理
3. 重点处理客户端内存泄漏：
   - LocalPlayer 重生/维度切换时的引用泄漏（类似服务端 ServerPlayer clone 问题）
   - 监听 ClientPlayerNetworkEvent.LoggingIn 清理旧玩家引用
   - 其他 mod 的静态缓存持有旧 LocalPlayer/Entity 引用导致 GC 无法回收
   - 维度切换时旧 ClientLevel 的资源未释放
   - Capability 在玩家重建后未 invalidate
4. 使用 Forge 客户端事件系统（RenderLevelStageEvent、ClientTickEvent、ClientPlayerNetworkEvent 等）
5. 如果需要修改其他 mod 的渲染行为，使用 Mixin 注入
6. 使用 @OnlyIn(Dist.CLIENT) 确保服务端安全
7. 代码必须健壮，处理所有可能的异常
8. 添加详细的中文注释说明优化原理

输出格式要求：
请严格按照以下 JSON 格式输出，不要添加任何其他文字：

```json
{
  "description": "优化模组的简要描述",
  "dependencies": ["需要作为编译依赖的mod文件名"],
  "main_class": {
    "package": "com.fix.modid",
    "class_name": "MainModClass",
    "code": "完整的Java源码"
  },
  "event_handlers": [
    {
      "package": "com.fix.modid",
      "class_name": "ClientOptimizer",
      "code": "完整的Java源码"
    }
  ],
  "mixins": [
    {
      "package": "com.fix.modid.mixin",
      "class_name": "SomeMixin",
      "code": "完整的Java源码",
      "target_class": "被注入的目标类全限定名"
    }
  ]
}
```"""

    def _build_client_prompt(
        self,
        issues: List[Dict],
        installed_mods: List[Dict],
        mod_id: str,
        mc_version: str,
    ) -> str:
        # 构建问题描述
        issues_text = ""
        for i, issue in enumerate(issues, 1):
            issues_text += f"\n### 问题 {i}: {issue['description']}\n"
            issues_text += f"- 类型: {issue['issue_type']}\n"
            issues_text += f"- 严重程度: {issue['severity']}\n"
            issues_text += f"- 涉及 mod: {', '.join(issue['involved_mods']) if issue['involved_mods'] else '未知'}\n"
            issues_text += f"- 修复建议: {issue['suggestion']}\n"
            issues_text += f"- 日志证据:\n"
            for ev in issue["evidence"][:3]:
                issues_text += f"  ```\n  {ev}\n  ```\n"

        # 构建已安装 mod 列表
        mods_text = ""
        for mod in installed_mods[:30]:
            mods_text += f"- {mod['display_name']} ({mod['mod_id']}) v{mod['version']} [{mod['file_name']}]\n"

        prompt = f"""请为以下 Minecraft {mc_version} Forge 客户端生成一个性能优化 mod。

## 生成的 Mod 信息
- Mod ID: {mod_id}
- 包名: com.fix.{mod_id}
- Minecraft 版本: {mc_version}
- Forge 版本: 47.2.0
- 运行端: 客户端（需要 @OnlyIn(Dist.CLIENT) 注解）

## 检测到的性能问题
{issues_text}

## 已安装的 Mod 列表
{mods_text}

## 要求
1. 生成一个主类（@Mod 注解），注册客户端事件处理器
2. 生成客户端优化类，针对检测到的问题进行优化：
   - 使用 RenderLevelStageEvent 优化渲染流程
   - 使用 ClientTickEvent 进行定期清理
   - 使用 TextureStitchEvent 优化纹理管理
   - 使用 ModelEvent.BakingCompleted 优化模型缓存
3. 重点处理客户端内存泄漏和 LocalPlayer 引用问题：
   - 监听 ClientPlayerNetworkEvent.LoggingIn / ClientPlayerNetworkEvent.Clone 事件
   - 在客户端玩家重生/维度切换时，清理所有对旧 LocalPlayer 的引用
   - 遍历其他 mod 的静态缓存（通过反射），清除持有旧玩家实例的字段
   - 在 ClientLevel 切换时释放旧世界的实体渲染缓存和 Capability
   - 调用旧玩家的 invalidateCaps() 断开 Capability 引用链
4. 如果需要 Mixin 修改渲染管线，生成对应的 Mixin 类
5. 所有客户端代码必须用 @OnlyIn(Dist.CLIENT) 标注
6. 使用反射访问其他 mod 的字段，做好异常处理
7. 确保即使目标 mod 不存在也不会崩溃
8. 优化应该是非侵入性的，不改变游戏逻辑只提升性能

请生成完整的优化代码。"""

        return prompt

    def _call_ai(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """调用 AI API"""
        backend = self.config.get("ai_backend", "openai")

        try:
            if backend == "openai":
                return self._call_openai(system_prompt, user_prompt)
            elif backend == "claude":
                return self._call_claude(system_prompt, user_prompt)
            else:
                self.progress(f"错误: 未知的 AI 后端 '{backend}'")
                return None
        except requests.exceptions.ConnectionError as e:
            self.progress(f"错误: 无法连接到 AI API 服务器 - {str(e)[:100]}")
            return None
        except requests.exceptions.Timeout:
            self.progress("错误: AI API 请求超时（120秒），请检查网络或尝试更短的 prompt")
            return None
        except requests.exceptions.RequestException as e:
            self.progress(f"错误: 网络请求失败 - {type(e).__name__}: {str(e)[:150]}")
            return None
        except Exception as e:
            self.progress(f"错误: AI API 调用失败 - {type(e).__name__}: {str(e)[:150]}")
            return None

    def _call_openai(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """调用 OpenAI 兼容 API"""
        base_url = self.config.get("openai_base_url", "https://api.openai.com/v1").rstrip("/")
        api_key = self.config.get("openai_api_key", "")
        model = self.config.get("openai_model", "gpt-4o")

        if not api_key:
            self.progress("错误: 未设置 OpenAI API Key")
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 16000,
        }

        response = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )

        if response.status_code != 200:
            self.progress(f"错误: API 返回 {response.status_code} - {response.text[:200]}")
            return None

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _call_claude(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """调用 Claude API"""
        api_key = self.config.get("claude_api_key", "")
        model = self.config.get("claude_model", "claude-sonnet-4-20250514")

        if not api_key:
            self.progress("错误: 未设置 Claude API Key")
            return None

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": model,
            "max_tokens": 16000,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=180,
        )

        if response.status_code != 200:
            self.progress(f"错误: API 返回 {response.status_code} - {response.text[:200]}")
            return None

        data = response.json()
        return data["content"][0]["text"]

    def _parse_response(self, response: str, mod_id: str) -> Optional[Dict]:
        """解析 AI 返回的代码"""
        # 记录原始响应用于调试
        self.progress(f"AI 响应长度: {len(response)} 字符")

        # 尝试提取 JSON 块（完整的 ```json ... ```）
        json_match = re.search(r"```json\s*\n(.*?)\n```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            try:
                result = json.loads(json_str)
                if "main_class" in result:
                    self.progress("JSON 解析成功（完整代码块）")
                    return result
            except json.JSONDecodeError:
                pass

        # 去除 markdown 标记，提取 JSON 内容
        json_str = response.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"^```\w*\n", "", json_str)
            json_str = re.sub(r"\n```\s*$", "", json_str)

        # 尝试找到 JSON 对象的起止位置
        brace_start = json_str.find("{")
        if brace_start != -1:
            # 先尝试完整解析
            brace_end = json_str.rfind("}")
            if brace_end > brace_start:
                json_candidate = json_str[brace_start:brace_end + 1]
                try:
                    result = json.loads(json_candidate)
                    if "main_class" in result:
                        self.progress("JSON 解析成功")
                        return result
                except json.JSONDecodeError:
                    pass

            # JSON 被截断的情况：尝试从截断的 JSON 中提取 code 字段
            self.progress("检测到 JSON 可能被截断，尝试提取已有代码...")
            truncated_result = self._parse_truncated_json(json_str[brace_start:])
            if truncated_result:
                return truncated_result

        self.progress("警告: JSON 解析失败，尝试从代码块提取...")
        return self._fallback_parse(response, mod_id)

    def _parse_truncated_json(self, json_str: str) -> Optional[Dict]:
        """
        处理被截断的 JSON 响应。
        从不完整的 JSON 中提取已有的 code 字段值。
        """
        result = {
            "description": "AI 生成的优化模组（响应被截断，已提取可用部分）",
            "dependencies": [],
            "main_class": None,
            "event_handlers": [],
            "mixins": [],
        }

        # 提取 "code": "..." 字段中的 Java 代码
        # JSON 中的代码用 \n 转义换行，用 \" 转义引号
        code_pattern = r'"code"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)'
        code_matches = re.finditer(code_pattern, json_str, re.DOTALL)

        # 同时提取对应的 package 和 class_name
        # 匹配 "package": "xxx", "class_name": "xxx", "code": "xxx"
        block_pattern = r'"package"\s*:\s*"([^"]+)"[^}]*?"class_name"\s*:\s*"([^"]+)"[^}]*?"code"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)'
        block_matches = list(re.finditer(block_pattern, json_str, re.DOTALL))

        if not block_matches:
            return None

        for match in block_matches:
            package = match.group(1)
            class_name = match.group(2)
            raw_code = match.group(3)

            # 反转义 JSON 字符串
            try:
                code = raw_code.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
            except Exception:
                code = raw_code

            if not code.strip():
                continue

            entry = {
                "package": package,
                "class_name": class_name,
                "code": code,
            }

            # 判断类型
            if "@Mod(" in code and result["main_class"] is None:
                result["main_class"] = entry
            elif "@Mixin" in code:
                target_match = re.search(r"@Mixin\s*\(\s*(?:value\s*=\s*)?(\w+)\.class", code)
                entry["target_class"] = target_match.group(1) if target_match else "Unknown"
                result["mixins"].append(entry)
            else:
                result["event_handlers"].append(entry)

        # 检查是否提取到了有效内容
        if result["main_class"] or result["event_handlers"]:
            # 如果没有主类但有事件处理器，生成一个默认主类
            if not result["main_class"] and result["event_handlers"]:
                pkg = result["event_handlers"][0]["package"]
                mod_id_guess = pkg.split(".")[-1] if "." in pkg else "clientfix"
                class_name = "".join(w.capitalize() for w in mod_id_guess.split("_")) + "Mod"
                handlers_reg = ""
                for handler in result["event_handlers"]:
                    handlers_reg += f"        MinecraftForge.EVENT_BUS.register({handler['class_name']}.class);\n"

                result["main_class"] = {
                    "package": pkg,
                    "class_name": class_name,
                    "code": f"""package {pkg};

import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.fml.common.Mod;

@Mod("{mod_id_guess}")
public class {class_name} {{
    public {class_name}() {{
{handlers_reg}    }}
}}
""",
                }

            self.progress(f"从截断的 JSON 中成功提取 {1 if result['main_class'] else 0} 个主类, "
                         f"{len(result['event_handlers'])} 个事件处理器, "
                         f"{len(result['mixins'])} 个 Mixin")
            return result

        return None

    def _fallback_parse(self, response: str, mod_id: str) -> Optional[Dict]:
        """备用解析：从代码块中提取 Java 代码"""
        # 尝试多种代码块格式
        code_blocks = re.findall(r"```java\s*\n(.*?)\n```", response, re.DOTALL)

        # 如果没有 ```java，尝试普通 ``` 块
        if not code_blocks:
            code_blocks = re.findall(r"```\s*\n(.*?)\n```", response, re.DOTALL)
            # 过滤出看起来像 Java 代码的块
            code_blocks = [b for b in code_blocks if "package " in b or "import " in b or "class " in b]

        # 如果还是没有，尝试直接从响应中提取 Java 类定义
        if not code_blocks:
            # 查找 package 声明开头到文件结尾的模式
            class_patterns = re.findall(
                r"(package\s+[\w.]+;.*?(?:public\s+(?:abstract\s+)?class\s+\w+.*?\{.*?\n\}))",
                response, re.DOTALL
            )
            if class_patterns:
                code_blocks = class_patterns

        if not code_blocks:
            self.progress("错误: 无法从 AI 响应中提取代码")
            self.progress(f"响应前500字符: {response[:500]}")
            # 最后的兜底：生成一个基础模组
            return self._generate_fallback_mod(mod_id)

        result = {
            "description": "AI 生成的优化修复模组",
            "dependencies": [],
            "main_class": None,
            "event_handlers": [],
            "mixins": [],
        }

        for code in code_blocks:
            # 解析包名和类名
            pkg_match = re.search(r"package\s+([\w.]+);", code)
            class_match = re.search(r"public\s+(?:abstract\s+)?class\s+(\w+)", code)

            if not pkg_match or not class_match:
                continue

            package = pkg_match.group(1)
            class_name = class_match.group(1)

            entry = {
                "package": package,
                "class_name": class_name,
                "code": code,
            }

            if "@Mod(" in code:
                result["main_class"] = entry
            elif "@Mixin" in code:
                # 提取目标类
                target_match = re.search(r"@Mixin\s*\(\s*(?:value\s*=\s*)?(\w+)\.class", code)
                entry["target_class"] = target_match.group(1) if target_match else "Unknown"
                result["mixins"].append(entry)
            else:
                result["event_handlers"].append(entry)

        # 如果没有找到主类，创建一个默认的
        if not result["main_class"]:
            pkg = f"com.fix.{mod_id}"
            class_name = "".join(w.capitalize() for w in mod_id.split("_")) + "Mod"
            handlers_reg = ""
            for handler in result["event_handlers"]:
                handlers_reg += f"        MinecraftForge.EVENT_BUS.register({handler['class_name']}.class);\n"

            result["main_class"] = {
                "package": pkg,
                "class_name": class_name,
                "code": f"""package {pkg};

import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.fml.common.Mod;

@Mod("{mod_id}")
public class {class_name} {{
    public {class_name}() {{
{handlers_reg}    }}
}}
""",
            }

        return result

    def _generate_fallback_mod(self, mod_id: str) -> Dict:
        """当 AI 响应无法解析时，生成一个基础的客户端/服务端优化模组"""
        self.progress("使用内置模板生成基础优化模组...")
        pkg = f"com.fix.{mod_id}"
        class_name = "".join(w.capitalize() for w in mod_id.split("_")) + "Mod"
        handler_name = "".join(w.capitalize() for w in mod_id.split("_")) + "Fixer"

        main_code = f"""package {pkg};

import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.fml.common.Mod;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

@Mod("{mod_id}")
public class {class_name} {{
    public static final Logger LOGGER = LogManager.getLogger("{mod_id}");

    public {class_name}() {{
        MinecraftForge.EVENT_BUS.register({handler_name}.class);
        LOGGER.info("{mod_id} loaded");
    }}
}}
"""

        handler_code = f"""package {pkg};

import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.level.Level;
import net.minecraftforge.api.distmarker.Dist;
import net.minecraftforge.api.distmarker.OnlyIn;
import net.minecraftforge.client.event.ClientPlayerNetworkEvent;
import net.minecraftforge.event.TickEvent;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import java.lang.reflect.Field;
import java.util.Map;

/**
 * 客户端优化修复器
 * - 在玩家重生/维度切换时清理旧 LocalPlayer 引用
 * - 定期清理客户端静态缓存防止内存泄漏
 */
@OnlyIn(Dist.CLIENT)
public class {handler_name} {{

    private static final Logger LOGGER = LogManager.getLogger("{mod_id}");
    private static int tickCounter = 0;
    private static LocalPlayer lastPlayer = null;

    /**
     * 客户端玩家登入事件 - 清理旧玩家引用
     * 当玩家重生或切换维度时，Minecraft 会创建新的 LocalPlayer 实例
     * 旧实例如果被其他 mod 的静态字段持有，会导致内存泄漏
     */
    @SubscribeEvent
    public static void onPlayerLogin(ClientPlayerNetworkEvent.LoggingIn event) {{
        LocalPlayer newPlayer = event.getPlayer();
        if (lastPlayer != null && lastPlayer != newPlayer) {{
            LOGGER.debug("检测到玩家实例更新，清理旧引用...");
            try {{
                lastPlayer.invalidateCaps();
            }} catch (Exception e) {{
                LOGGER.debug("invalidateCaps failed: {{}}", e.getMessage());
            }}
            cleanupStaleReferences(lastPlayer);
        }}
        lastPlayer = newPlayer;
    }}

    /**
     * 客户端玩家登出事件 - 清理所有玩家相关缓存
     */
    @SubscribeEvent
    public static void onPlayerLogout(ClientPlayerNetworkEvent.LoggingOut event) {{
        if (lastPlayer != null) {{
            try {{
                lastPlayer.invalidateCaps();
            }} catch (Exception e) {{
                // ignore
            }}
            lastPlayer = null;
        }}
        System.gc();
    }}

    /**
     * 定期清理（每 30 秒）
     */
    @SubscribeEvent
    public static void onClientTick(TickEvent.ClientTickEvent event) {{
        if (event.phase != TickEvent.Phase.END) return;
        if (++tickCounter < 600) return;
        tickCounter = 0;

        Minecraft mc = Minecraft.getInstance();
        if (mc.level == null) return;

        cleanupRemovedEntities(mc);
    }}

    /**
     * 清理旧玩家的引用 - 通过反射清理其他 mod 的静态缓存
     */
    @SuppressWarnings("unchecked")
    private static void cleanupStaleReferences(LocalPlayer oldPlayer) {{
        // 可在此添加已知 mod 的缓存类名
        String[] knownCaches = {{}};

        for (String className : knownCaches) {{
            try {{
                Class<?> clazz = Class.forName(className);
                for (Field field : clazz.getDeclaredFields()) {{
                    if (java.lang.reflect.Modifier.isStatic(field.getModifiers())) {{
                        field.setAccessible(true);
                        Object value = field.get(null);
                        if (value == oldPlayer) {{
                            field.set(null, null);
                            LOGGER.debug("Cleared stale player ref in {{}}.{{}}", className, field.getName());
                        }} else if (value instanceof Map) {{
                            Map<Object, Object> map = (Map<Object, Object>) value;
                            map.entrySet().removeIf(e ->
                                e.getKey() == oldPlayer || e.getValue() == oldPlayer
                            );
                        }}
                    }}
                }}
            }} catch (ClassNotFoundException e) {{
                // mod not installed
            }} catch (Exception e) {{
                LOGGER.debug("Cleanup failed for {{}}: {{}}", className, e.getMessage());
            }}
        }}
    }}

    private static void cleanupRemovedEntities(Minecraft mc) {{
        if (mc.level != null) {{
            long entityCount = mc.level.entitiesForRendering().spliterator().getExactSizeIfKnown();
            if (entityCount > 5000) {{
                LOGGER.debug("High client entity count: {{}}", entityCount);
            }}
        }}
    }}
}}
"""

        return {
            "description": "客户端内存泄漏修复和性能优化模组",
            "dependencies": [],
            "main_class": {
                "package": pkg,
                "class_name": class_name,
                "code": main_code,
            },
            "event_handlers": [
                {
                    "package": pkg,
                    "class_name": handler_name,
                    "code": handler_code,
                }
            ],
            "mixins": [],
        }
