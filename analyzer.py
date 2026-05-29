"""
日志分析引擎 - 检测 Minecraft 服务器/客户端日志中的内存泄漏和性能问题
"""
import os
import re
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class LeakIssue:
    """检测到的内存泄漏问题"""
    issue_type: str          # 问题类型
    severity: str            # critical / high / medium / low
    description: str         # 问题描述
    involved_mods: List[str] # 涉及的 mod
    evidence: List[str]      # 相关日志片段
    suggestion: str          # 修复建议

    def to_dict(self) -> Dict:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "involved_mods": self.involved_mods,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }


# 内存泄漏检测规则
LEAK_PATTERNS = [
    {
        "name": "OutOfMemoryError",
        "pattern": r"java\.lang\.OutOfMemoryError",
        "severity": "critical",
        "description": "服务器发生内存溢出错误",
        "suggestion": "存在严重内存泄漏，需要检查实体引用和静态集合",
    },
    {
        "name": "GC_overhead",
        "pattern": r"GC overhead limit exceeded",
        "severity": "critical",
        "description": "GC 开销超出限制，堆内存几乎耗尽",
        "suggestion": "大量对象无法被回收，可能存在实体或玩家对象泄漏",
    },
    {
        "name": "entity_leak_high_count",
        "pattern": r"Loaded\s+(\d{4,})\s+entities",
        "severity": "high",
        "description": "实体数量异常偏高",
        "suggestion": "可能存在实体未正确移除或引用未释放的问题",
    },
    {
        "name": "player_reference_leak",
        "pattern": r"(?:ServerPlayer|EntityPlayerMP).*(?:removed|disconnected).*(?:still|leak|reference)",
        "severity": "high",
        "description": "玩家对象在断开连接后仍被引用",
        "suggestion": "需要在玩家退出/重生时清理所有对该玩家的引用",
    },
    {
        "name": "tps_degradation",
        "pattern": r"Can't keep up! Is the server overloaded\?.*(?:Running|skipping)\s+(\d+)ms",
        "severity": "medium",
        "description": "服务器 TPS 持续下降，可能由内存压力导致",
        "suggestion": "内存压力导致 GC 频繁触发，影响 TPS",
    },
    {
        "name": "chunk_leak",
        "pattern": r"(?:Chunk|ChunkHolder).*(?:leak|unload.*fail|still loaded)",
        "severity": "high",
        "description": "区块未正确卸载，可能被实体引用持有",
        "suggestion": "实体持有对已卸载区块的引用，阻止 GC 回收",
    },
    {
        "name": "static_map_growth",
        "pattern": r"(?:HashMap|ConcurrentHashMap|Map).*(?:size|entries)\s*[:=]\s*(\d{5,})",
        "severity": "high",
        "description": "静态 Map 无限增长",
        "suggestion": "需要定期清理静态集合中的过期条目",
    },
    {
        "name": "capability_leak",
        "pattern": r"(?:capability|Cap).*(?:invalidate|dispose|leak)",
        "severity": "medium",
        "description": "Forge Capability 未正确失效",
        "suggestion": "在实体/玩家移除时需要调用 invalidateCaps()",
    },
    {
        "name": "summoned_entity_leak",
        "pattern": r"(?:Summoned|Minion|Servant|Ally).*(?:target|owner|master).*(?:null|removed|invalid)",
        "severity": "high",
        "description": "召唤物实体持有已失效的目标/主人引用",
        "suggestion": "需要在主人退出/死亡时清理召唤物的引用字段",
    },
    {
        "name": "event_handler_leak",
        "pattern": r"(?:EventBus|EVENT_BUS).*(?:register|handler).*(?:leak|duplicate|multiple)",
        "severity": "medium",
        "description": "事件处理器重复注册或未注销",
        "suggestion": "确保事件处理器在适当时机注销",
    },
    {
        "name": "dimension_change_leak",
        "pattern": r"(?:dimension|level).*(?:change|transfer|teleport).*(?:old|previous).*(?:player|entity)",
        "severity": "medium",
        "description": "维度切换时旧实体引用未清理",
        "suggestion": "在维度切换事件中更新所有引用到新实体实例",
    },
]

# 已知 mod 的特定泄漏模式
KNOWN_MOD_LEAKS = [
    {
        "mod_pattern": r"(?i)goety|goetyawaken",
        "log_pattern": r"(?:Summoned|Apostle|Servant).*(?:commandPos|priorityTarget|lastMoney|enhancedEntit)",
        "severity": "high",
        "description": "Goety/GoetyAwaken 的 Summoned 实体持有过期 ServerPlayer 引用导致内存泄漏",
        "involved_mod": "goety",
        "suggestion": "需要 Mixin 注入清理 Summoned.commandPosEntity 和 priorityTarget 字段",
    },
    {
        "mod_pattern": r"(?i)ice_and_fire|iceandfire",
        "log_pattern": r"(?:Dragon|Hippogryph|Pixie).*(?:target|owner).*(?:null|removed)",
        "severity": "medium",
        "description": "Ice and Fire 的龙/生物持有已移除玩家的引用",
        "involved_mod": "iceandfire",
        "suggestion": "清理 IaF 生物的 owner/target 引用",
    },
    {
        "mod_pattern": r"(?i)minecolonies",
        "log_pattern": r"(?:Citizen|Colony|Building).*(?:leak|memory|reference)",
        "severity": "medium",
        "description": "MineColonies 的殖民者实体引用泄漏",
        "involved_mod": "minecolonies",
        "suggestion": "清理殖民者对已离线玩家的引用",
    },
    {
        "mod_pattern": r"(?i)create",
        "log_pattern": r"(?:Contraption|SchematicWorld|BlockEntity).*(?:leak|unload|orphan)",
        "severity": "medium",
        "description": "Create 的机械装置可能持有已卸载区块的引用",
        "involved_mod": "create",
        "suggestion": "在区块卸载时清理 Contraption 的 BlockEntity 引用",
    },
]


# ============================================================
# 客户端优化检测规则
# ============================================================

CLIENT_PERF_PATTERNS = [
    {
        "name": "client_oom",
        "pattern": r"java\.lang\.OutOfMemoryError",
        "severity": "critical",
        "description": "客户端内存溢出",
        "suggestion": "需要优化纹理加载、模型缓存或减少同时加载的资源",
    },
    {
        "name": "client_gc_overhead",
        "pattern": r"GC overhead limit exceeded",
        "severity": "critical",
        "description": "客户端 GC 开销过大，导致卡顿",
        "suggestion": "存在大量短生命周期对象分配，需要对象池化或减少分配",
    },
    {
        "name": "fps_drop",
        "pattern": r"(?:fps|framerate|frame rate).*?(\d+)\s*(?:fps)?.*?(?:drop|low|lag|spike)",
        "severity": "high",
        "description": "FPS 下降/卡顿",
        "suggestion": "需要优化渲染管线、减少不必要的渲染调用",
    },
    {
        "name": "texture_leak",
        "pattern": r"(?:texture|Texture).*(?:leak|not released|failed to free|overflow)",
        "severity": "high",
        "description": "纹理资源未正确释放，导致显存泄漏",
        "suggestion": "需要在资源卸载时正确释放 GL 纹理对象",
    },
    {
        "name": "shader_error",
        "pattern": r"(?:shader|Shader).*(?:error|fail|compile|link).*(?:program|vertex|fragment)",
        "severity": "medium",
        "description": "着色器编译/链接错误导致渲染回退",
        "suggestion": "修复着色器兼容性问题或提供回退方案",
    },
    {
        "name": "render_thread_lag",
        "pattern": r"(?:Render|Client) thread.*(?:behind|lag|slow|block|stall)",
        "severity": "high",
        "description": "渲染线程阻塞或延迟",
        "suggestion": "将耗时操作移出渲染线程，使用异步加载",
    },
    {
        "name": "model_loading_slow",
        "pattern": r"(?:model|Model|bake|Bake).*(?:slow|timeout|took \d{4,}ms|loading)",
        "severity": "medium",
        "description": "模型加载/烘焙耗时过长",
        "suggestion": "缓存已烘焙的模型，避免重复计算",
    },
    {
        "name": "chunk_render_lag",
        "pattern": r"(?:chunk|Chunk).*(?:render|rebuild|compile).*(?:slow|lag|took \d{3,}ms)",
        "severity": "medium",
        "description": "区块渲染重建耗时过长",
        "suggestion": "优化区块渲染批处理，减少不必要的重建",
    },
    {
        "name": "particle_overflow",
        "pattern": r"(?:particle|Particle).*(?:overflow|too many|limit|exceed|\d{4,})",
        "severity": "medium",
        "description": "粒子数量过多导致性能下降",
        "suggestion": "限制粒子生成数量或优化粒子渲染批处理",
    },
    {
        "name": "entity_render_lag",
        "pattern": r"(?:entity|Entity).*(?:render|tick).*(?:slow|lag|skip|took \d{2,}ms)",
        "severity": "medium",
        "description": "实体渲染/tick 耗时过长",
        "suggestion": "优化实体渲染距离裁剪和 LOD",
    },
    {
        "name": "resource_reload_slow",
        "pattern": r"(?:resource|Resource).*(?:reload|pack|load).*(?:slow|took \d{4,}ms|timeout)",
        "severity": "low",
        "description": "资源包重载耗时过长",
        "suggestion": "优化资源加载流程，使用懒加载",
    },
    {
        "name": "mixin_conflict",
        "pattern": r"(?:mixin|Mixin).*(?:conflict|fail|error|inject|overwrite).*(?:render|client|screen)",
        "severity": "high",
        "description": "Mixin 注入冲突影响客户端渲染",
        "suggestion": "解决 Mixin 冲突，调整注入优先级",
    },
    {
        "name": "opengl_error",
        "pattern": r"(?:OpenGL|GL|LWJGL).*(?:error|Error|invalid|1281|1282|1280)",
        "severity": "medium",
        "description": "OpenGL 错误，可能导致渲染异常",
        "suggestion": "修复 GL 状态管理，确保正确的 push/pop 调用",
    },
    {
        "name": "audio_lag",
        "pattern": r"(?:sound|Sound|audio|Audio).*(?:lag|buffer|overflow|skip|delay)",
        "severity": "low",
        "description": "音频系统延迟或缓冲区溢出",
        "suggestion": "优化音频资源管理，限制同时播放的音效数量",
    },
    {
        "name": "network_lag_client",
        "pattern": r"(?:Netty|network|Network|packet|Packet).*(?:slow|timeout|queue|overflow|behind)",
        "severity": "medium",
        "description": "网络数据包处理延迟",
        "suggestion": "优化客户端数据包处理，避免主线程阻塞",
    },
    {
        "name": "client_player_clone_leak",
        "pattern": r"(?:ClientPlayerEntity|LocalPlayer|AbstractClientPlayer).*(?:clone|respawn|dimension|old|previous|stale)",
        "severity": "high",
        "description": "客户端玩家重生/维度切换时旧 LocalPlayer 引用未清理",
        "suggestion": "需要在 ClientPlayerNetworkHandler 重建时清理所有对旧 LocalPlayer 的引用，防止内存泄漏",
    },
    {
        "name": "client_player_reference_leak",
        "pattern": r"(?:player|Player|LocalPlayer).*(?:removed|disconnect|respawn).*(?:still|leak|reference|held|retain)",
        "severity": "high",
        "description": "客户端玩家对象在重生/断线后仍被其他对象持有",
        "suggestion": "Mod 的客户端缓存（如渲染器、动画控制器）需要在玩家重建时更新引用",
    },
    {
        "name": "client_entity_memory_leak",
        "pattern": r"(?:entity|Entity).*(?:memory|Memory|leak|Leak|accumulate|retain|not.*(?:free|release|remove|gc))",
        "severity": "high",
        "description": "客户端实体对象未被正确释放导致内存泄漏",
        "suggestion": "实体从客户端世界移除时需要清理渲染缓存、动画状态和事件监听器",
    },
    {
        "name": "client_level_change_leak",
        "pattern": r"(?:level|Level|world|World|dimension|Dimension).*(?:change|switch|unload|leave).*(?:leak|memory|retain|old|previous)",
        "severity": "high",
        "description": "客户端维度切换时旧世界资源未释放",
        "suggestion": "维度切换时需要清理旧 ClientLevel 的实体缓存、区块渲染数据和音频资源",
    },
    {
        "name": "client_capability_leak",
        "pattern": r"(?:capability|Capability|Cap).*(?:client|Client).*(?:invalidate|dispose|leak|stale)",
        "severity": "medium",
        "description": "客户端 Capability 在玩家重建后未正确失效",
        "suggestion": "在 LocalPlayer 重建时调用 invalidateCaps() 释放旧的 Capability 引用",
    },
    {
        "name": "client_static_cache_growth",
        "pattern": r"(?:cache|Cache|map|Map|HashMap|ConcurrentHashMap).*(?:client|Client|render|Render).*(?:size|grow|large|exceed|\d{4,})",
        "severity": "medium",
        "description": "客户端静态缓存无限增长",
        "suggestion": "客户端 mod 的静态缓存（模型、纹理、动画）需要设置上限或定期清理",
    },
]

# 已知客户端 mod 的性能问题
KNOWN_CLIENT_MOD_ISSUES = [
    {
        "mod_pattern": r"(?i)optifine|OptiFine",
        "log_pattern": r"(?:OptiFine|optifine).*(?:conflict|incompatible|error|crash)",
        "severity": "high",
        "description": "OptiFine 与其他渲染 mod 冲突",
        "involved_mod": "optifine",
        "suggestion": "OptiFine 与 Sodium/Iris 等 mod 不兼容，需要选择其一或用 Mixin 解决冲突",
    },
    {
        "mod_pattern": r"(?i)rubidium|embeddium|sodium",
        "log_pattern": r"(?:Rubidium|Embeddium|Sodium).*(?:error|crash|incompatible|conflict)",
        "severity": "medium",
        "description": "渲染优化 mod 与其他 mod 的兼容性问题",
        "involved_mod": "embeddium",
        "suggestion": "需要兼容性补丁来解决渲染管线冲突",
    },
    {
        "mod_pattern": r"(?i)iris|oculus",
        "log_pattern": r"(?:Iris|Oculus|shader).*(?:error|fail|incompatible|crash)",
        "severity": "medium",
        "description": "光影 mod 与其他渲染 mod 冲突",
        "involved_mod": "oculus",
        "suggestion": "需要修复光影管线与自定义渲染的兼容性",
    },
    {
        "mod_pattern": r"(?i)jei|JEI|just.*enough.*items",
        "log_pattern": r"(?:JEI|jei).*(?:slow|lag|memory|heap|reload)",
        "severity": "medium",
        "description": "JEI 物品索引占用大量内存",
        "involved_mod": "jei",
        "suggestion": "优化 JEI 的物品缓存策略，延迟加载配方",
    },
    {
        "mod_pattern": r"(?i)create",
        "log_pattern": r"(?:Create|create).*(?:render|contraption|flywheel).*(?:slow|lag|error)",
        "severity": "medium",
        "description": "Create 机械装置渲染性能问题",
        "involved_mod": "create",
        "suggestion": "优化 Contraption 渲染，减少动态模型重建频率",
    },
    {
        "mod_pattern": r"(?i)ysm|yes.*steve.*model",
        "log_pattern": r"(?:YSM|ysm|YesSteve).*(?:model|render|texture|load).*(?:slow|error|lag|memory)",
        "severity": "medium",
        "description": "YSM 自定义模型加载/渲染性能问题",
        "involved_mod": "ysm",
        "suggestion": "缓存已加载的玩家模型，限制同时渲染的自定义模型数量",
    },
    {
        "mod_pattern": r"(?i)ice_and_fire|iceandfire",
        "log_pattern": r"(?:Dragon|iceandfire|IceAndFire).*(?:render|model|texture).*(?:slow|lag|error)",
        "severity": "medium",
        "description": "Ice and Fire 龙模型渲染性能问题",
        "involved_mod": "iceandfire",
        "suggestion": "优化龙实体的 LOD 渲染和动画计算",
    },
    {
        "mod_pattern": r"(?i)supplementaries",
        "log_pattern": r"(?:supplementaries|Supplementaries).*(?:render|particle|block).*(?:slow|lag)",
        "severity": "low",
        "description": "Supplementaries 装饰方块渲染开销",
        "involved_mod": "supplementaries",
        "suggestion": "优化装饰方块的渲染批处理",
    },
]


# ============================================================
# 客户端优化检测规则
# ============================================================

CLIENT_LEAK_PATTERNS = [
    {
        "name": "client_oom",
        "pattern": r"java\.lang\.OutOfMemoryError",
        "severity": "critical",
        "description": "客户端发生内存溢出错误",
        "suggestion": "存在严重内存泄漏，需要检查纹理缓存、模型缓存或实体渲染器",
    },
    {
        "name": "client_gc_overhead",
        "pattern": r"GC overhead limit exceeded",
        "severity": "critical",
        "description": "客户端 GC 开销超出限制",
        "suggestion": "大量对象无法被回收，可能是纹理/模型未释放或渲染缓冲区泄漏",
    },
    {
        "name": "texture_leak",
        "pattern": r"(?:texture|Texture|TextureManager).*(?:leak|failed to (?:release|free|unload)|overflow|exceed)",
        "severity": "high",
        "description": "纹理资源未正确释放，导致显存/内存泄漏",
        "suggestion": "需要在资源重载或维度切换时释放未使用的纹理缓存",
    },
    {
        "name": "model_cache_bloat",
        "pattern": r"(?:ModelBakery|BakedModel|ModelManager).*(?:cache|size|memory|overflow|large)",
        "severity": "high",
        "description": "模型缓存无限增长",
        "suggestion": "需要限制模型缓存大小或在适当时机清理过期模型",
    },
    {
        "name": "render_buffer_leak",
        "pattern": r"(?:BufferBuilder|VertexBuffer|RenderType|RenderBuffer).*(?:leak|overflow|not released|orphan)",
        "severity": "high",
        "description": "渲染缓冲区未正确释放",
        "suggestion": "需要确保 BufferBuilder/VertexBuffer 在使用后正确释放",
    },
    {
        "name": "fps_drop_stutter",
        "pattern": r"(?:Slow|Running behind|Skipping|lag spike).*(?:\d{3,}ms|frame|tick)",
        "severity": "medium",
        "description": "客户端出现严重卡顿/帧率下降",
        "suggestion": "可能由 GC 暂停、渲染管线阻塞或主线程阻塞导致",
    },
    {
        "name": "shader_compilation_stall",
        "pattern": r"(?:shader|Shader|Program).*(?:compil|link|error|fail|stall|slow)",
        "severity": "medium",
        "description": "着色器编译导致卡顿",
        "suggestion": "需要预编译着色器或缓存编译结果避免运行时卡顿",
    },
    {
        "name": "chunk_render_leak",
        "pattern": r"(?:ChunkRender|RenderChunk|SectionRender).*(?:leak|orphan|not freed|accumulate)",
        "severity": "high",
        "description": "区块渲染数据未正确释放",
        "suggestion": "区块卸载时需要释放对应的渲染缓冲区和 VBO",
    },
    {
        "name": "entity_renderer_leak",
        "pattern": r"(?:EntityRenderer|MobRenderer|LivingEntityRenderer).*(?:leak|cache|accumulate|not cleared)",
        "severity": "medium",
        "description": "实体渲染器缓存泄漏",
        "suggestion": "实体渲染器的临时缓存需要定期清理",
    },
    {
        "name": "sound_leak",
        "pattern": r"(?:SoundEngine|SoundManager|SoundSystem|OpenAL).*(?:leak|overflow|too many|channel|source|error)",
        "severity": "medium",
        "description": "音频资源泄漏或音频通道耗尽",
        "suggestion": "需要限制同时播放的音频数量或正确释放音频资源",
    },
    {
        "name": "particle_overflow",
        "pattern": r"(?:Particle|ParticleEngine|ParticleManager).*(?:overflow|too many|limit|exceed|\d{5,})",
        "severity": "medium",
        "description": "粒子数量过多导致性能下降",
        "suggestion": "需要限制粒子生成数量或加速粒子消亡",
    },
    {
        "name": "resource_reload_leak",
        "pattern": r"(?:ResourceManager|ReloadableResourceManager|ResourcePack).*(?:leak|not closed|fail|error)",
        "severity": "medium",
        "description": "资源重载时旧资源未正确释放",
        "suggestion": "资源包切换/重载时需要释放旧的资源引用",
    },
    {
        "name": "gui_screen_leak",
        "pattern": r"(?:Screen|GuiScreen|ContainerScreen).*(?:leak|not closed|orphan|reference)",
        "severity": "low",
        "description": "GUI 界面关闭后仍持有引用",
        "suggestion": "关闭 Screen 时需要清理所有回调和引用",
    },
]

# 客户端已知 mod 特定问题
KNOWN_CLIENT_MOD_ISSUES = [
    {
        "mod_pattern": r"(?i)optifine|OptiFine",
        "log_pattern": r"(?:OptiFine|optifine).*(?:error|conflict|incompatible|crash|exception)",
        "severity": "high",
        "description": "OptiFine 与其他渲染 mod 冲突导致内存泄漏或崩溃",
        "involved_mod": "optifine",
        "suggestion": "OptiFine 的自定义渲染管线可能与其他 mod 冲突，需要兼容性修复",
    },
    {
        "mod_pattern": r"(?i)sodium|rubidium",
        "log_pattern": r"(?:sodium|Sodium|rubidium|Rubidium).*(?:leak|buffer|memory|error|crash)",
        "severity": "medium",
        "description": "Sodium/Rubidium 渲染优化 mod 的缓冲区管理问题",
        "involved_mod": "sodium",
        "suggestion": "Sodium 的自定义渲染管线可能存在缓冲区未释放的问题",
    },
    {
        "mod_pattern": r"(?i)iris|oculus",
        "log_pattern": r"(?:iris|Iris|oculus|Oculus).*(?:shader|framebuffer|leak|error|memory)",
        "severity": "medium",
        "description": "Iris/Oculus 着色器 mod 的帧缓冲区泄漏",
        "involved_mod": "iris",
        "suggestion": "着色器切换时需要正确释放旧的帧缓冲区对象",
    },
    {
        "mod_pattern": r"(?i)embeddium|flywheel",
        "log_pattern": r"(?:embeddium|Embeddium|flywheel|Flywheel).*(?:buffer|render|leak|error|memory)",
        "severity": "medium",
        "description": "Embeddium/Flywheel 渲染引擎的缓冲区管理问题",
        "involved_mod": "embeddium",
        "suggestion": "自定义渲染引擎的 GPU 缓冲区需要在适当时机释放",
    },
    {
        "mod_pattern": r"(?i)ysm|yes.*steve.*model",
        "log_pattern": r"(?:ysm|YSM|YesSteve|CustomModel).*(?:texture|model|cache|memory|leak|load)",
        "severity": "high",
        "description": "YSM (Yes Steve Model) 自定义模型/纹理缓存泄漏",
        "involved_mod": "ysm",
        "suggestion": "自定义玩家模型的纹理和模型缓存需要在玩家离开视野时释放",
    },
    {
        "mod_pattern": r"(?i)geckolib|azurelib",
        "log_pattern": r"(?:geckolib|GeckoLib|azurelib|AzureLib).*(?:animation|cache|memory|leak|model)",
        "severity": "medium",
        "description": "GeckoLib/AzureLib 动画库的模型缓存泄漏",
        "involved_mod": "geckolib",
        "suggestion": "动画模型缓存需要在实体卸载时清理",
    },
    {
        "mod_pattern": r"(?i)create",
        "log_pattern": r"(?:Create|create).*(?:render|Contraption|flywheel|buffer|model).*(?:leak|error|memory)",
        "severity": "medium",
        "description": "Create mod 的机械装置渲染缓存泄漏",
        "involved_mod": "create",
        "suggestion": "Contraption 渲染器的模型缓存需要在装置卸载时释放",
    },
    {
        "mod_pattern": r"(?i)epic.?fight|epicfight",
        "log_pattern": r"(?:epicfight|EpicFight).*(?:animation|model|render|cache|memory|leak)",
        "severity": "medium",
        "description": "Epic Fight mod 的动画渲染缓存泄漏",
        "involved_mod": "epicfight",
        "suggestion": "战斗动画的模型和纹理缓存需要定期清理",
    },
]


class LogAnalyzer:
    """Minecraft 服务器/客户端日志分析器"""

    def __init__(self, mode: str = "server"):
        """
        Args:
            mode: 分析模式，"server" 或 "client"
        """
        self.mode = mode
        self.issues: List[LeakIssue] = []
        self.log_lines: List[str] = []
        self.crash_reports: List[str] = []

    def analyze(self, log_paths: List[str], installed_mods: List[Dict] = None) -> List[LeakIssue]:
        """
        分析日志文件，检测性能问题。
        
        Args:
            log_paths: 日志文件路径列表
            installed_mods: 已安装的 mod 信息列表（来自 mod_scanner）
        
        Returns:
            检测到的问题列表
        """
        self.issues = []
        self.log_lines = []
        self.crash_reports = []

        # 读取所有日志
        for path in log_paths:
            self._read_log_file(path)

        # 根据模式选择检测规则
        self._run_pattern_detection()

        # 运行已知 mod 特定检测
        if installed_mods:
            self._run_mod_specific_detection(installed_mods)

        # 分析崩溃报告
        self._analyze_crash_context()

        # 去重并按严重程度排序
        self._deduplicate_and_sort()

        return self.issues

    def _read_log_file(self, path: str):
        """读取日志文件"""
        if not os.path.exists(path):
            return

        if os.path.isdir(path):
            # 如果是目录，扫描其中的日志文件
            for fname in os.listdir(path):
                if fname.endswith((".log", ".txt")):
                    fpath = os.path.join(path, fname)
                    self._read_single_file(fpath)
            # 扫描 crash-reports 子目录
            crash_dir = os.path.join(path, "crash-reports")
            if os.path.isdir(crash_dir):
                for fname in os.listdir(crash_dir):
                    if fname.endswith(".txt"):
                        fpath = os.path.join(crash_dir, fname)
                        self._read_single_file(fpath, is_crash=True)
        else:
            self._read_single_file(path)

    def _read_single_file(self, path: str, is_crash: bool = False):
        """读取单个文件"""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if is_crash:
                self.crash_reports.append("".join(lines))
            else:
                self.log_lines.extend(lines)
        except IOError:
            pass

    def _run_pattern_detection(self):
        """运行通用模式检测"""
        full_log = "".join(self.log_lines)

        # 根据模式选择规则集
        if self.mode == "client":
            patterns = CLIENT_PERF_PATTERNS
        else:
            patterns = LEAK_PATTERNS

        for rule in patterns:
            matches = re.finditer(rule["pattern"], full_log, re.IGNORECASE)
            evidence = []
            for match in matches:
                # 获取匹配行的上下文
                start = max(0, match.start() - 100)
                end = min(len(full_log), match.end() + 100)
                context = full_log[start:end].strip()
                # 截取到行边界
                lines = context.split("\n")
                for line in lines:
                    if re.search(rule["pattern"], line, re.IGNORECASE):
                        evidence.append(line.strip()[:200])

                if len(evidence) >= 5:
                    break

            if evidence:
                # 尝试从证据中识别涉及的 mod
                involved_mods = self._identify_mods_from_evidence(evidence)

                self.issues.append(LeakIssue(
                    issue_type=rule["name"],
                    severity=rule["severity"],
                    description=rule["description"],
                    involved_mods=involved_mods,
                    evidence=evidence[:5],
                    suggestion=rule["suggestion"],
                ))

    def _run_mod_specific_detection(self, installed_mods: List[Dict]):
        """运行已知 mod 特定的泄漏检测"""
        installed_mod_ids = {m["mod_id"].lower() for m in installed_mods}
        full_log = "".join(self.log_lines)

        # 根据模式选择已知问题列表
        if self.mode == "client":
            known_leaks = KNOWN_CLIENT_MOD_ISSUES
        else:
            known_leaks = KNOWN_MOD_LEAKS

        for known_leak in known_leaks:
            # 检查该 mod 是否已安装
            mod_installed = any(
                re.search(known_leak["mod_pattern"], mid)
                for mid in installed_mod_ids
            )
            # 也检查文件名
            if not mod_installed:
                mod_installed = any(
                    re.search(known_leak["mod_pattern"], m["file_name"])
                    for m in installed_mods
                )

            if not mod_installed:
                continue

            # 检查日志中是否有相关模式
            matches = re.finditer(known_leak["log_pattern"], full_log, re.IGNORECASE)
            evidence = []
            for match in matches:
                start = max(0, match.start() - 50)
                end = min(len(full_log), match.end() + 50)
                context = full_log[start:end].strip()
                lines = context.split("\n")
                for line in lines:
                    if line.strip():
                        evidence.append(line.strip()[:200])
                if len(evidence) >= 3:
                    break

            # 即使没有直接证据，如果 mod 已安装且是已知有泄漏的 mod，也报告
            if evidence or mod_installed:
                self.issues.append(LeakIssue(
                    issue_type=f"known_leak_{known_leak['involved_mod']}",
                    severity=known_leak["severity"],
                    description=known_leak["description"],
                    involved_mods=[known_leak["involved_mod"]],
                    evidence=evidence[:5] if evidence else ["(已知问题，该 mod 已安装)"],
                    suggestion=known_leak["suggestion"],
                ))

    def _analyze_crash_context(self):
        """分析崩溃报告中的内存相关信息"""
        for report in self.crash_reports:
            if re.search(r"OutOfMemoryError|heap space|GC overhead", report, re.IGNORECASE):
                # 提取堆栈中的 mod 相关类
                mod_classes = re.findall(
                    r"at\s+(com\.\w+\.\w+|net\.\w+\.\w+)\.[\w.]+\(",
                    report
                )
                involved = list(set(
                    cls for cls in mod_classes
                    if not cls.startswith(("net.minecraft", "java.", "sun.", "com.google"))
                ))[:5]

                # 提取关键堆栈行
                stack_lines = [
                    line.strip() for line in report.split("\n")
                    if line.strip().startswith("at ") and "minecraft" not in line.lower()
                ][:5]

                if involved or stack_lines:
                    self.issues.append(LeakIssue(
                        issue_type="crash_oom",
                        severity="critical",
                        description="崩溃报告显示内存溢出",
                        involved_mods=involved,
                        evidence=stack_lines[:5],
                        suggestion="崩溃堆栈指向特定 mod 的内存泄漏",
                    ))

    def _identify_mods_from_evidence(self, evidence: List[str]) -> List[str]:
        """从日志证据中识别涉及的 mod"""
        mods = set()
        for line in evidence:
            # 匹配包名模式: com.author.modname 或 net.author.modname
            packages = re.findall(r"(?:com|net|org)\.\w+\.(\w+)", line)
            for pkg in packages:
                if pkg.lower() not in ("minecraft", "forge", "java", "google", "mojang", "neoforge"):
                    mods.add(pkg.lower())
        return list(mods)[:5]

    def _deduplicate_and_sort(self):
        """去重并按严重程度排序"""
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        # 按 issue_type 去重，保留严重程度最高的
        seen = {}
        for issue in self.issues:
            key = issue.issue_type
            if key not in seen or severity_order.get(issue.severity, 3) < severity_order.get(seen[key].severity, 3):
                seen[key] = issue

        self.issues = sorted(
            seen.values(),
            key=lambda x: severity_order.get(x.severity, 3)
        )


def find_log_files(server_path: str) -> List[str]:
    """
    在服务器目录中查找日志文件。
    
    支持的位置:
    - logs/latest.log
    - logs/debug.log
    - crash-reports/*.txt
    - *.log (根目录)
    """
    log_files = []

    if os.path.isfile(server_path):
        # 直接指定了文件
        log_files.append(server_path)
        return log_files

    if not os.path.isdir(server_path):
        return log_files

    # logs 目录
    logs_dir = os.path.join(server_path, "logs")
    if os.path.isdir(logs_dir):
        for fname in os.listdir(logs_dir):
            if fname.endswith(".log"):
                log_files.append(os.path.join(logs_dir, fname))

    # crash-reports 目录
    crash_dir = os.path.join(server_path, "crash-reports")
    if os.path.isdir(crash_dir):
        for fname in os.listdir(crash_dir):
            if fname.endswith(".txt"):
                log_files.append(os.path.join(crash_dir, fname))

    # 根目录的 log 文件
    for fname in os.listdir(server_path):
        if fname.endswith(".log") and os.path.isfile(os.path.join(server_path, fname)):
            log_files.append(os.path.join(server_path, fname))

    return log_files
