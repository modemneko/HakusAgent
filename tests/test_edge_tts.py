"""
测试 Edge TTS 引擎
"""

import asyncio
import sys
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hakusai_core.voice import tts_registry
from hakusai_core.voice.tts import EdgeTTS  # 确保注册


async def test_edge_tts():
    """测试 Edge TTS"""
    print("=" * 50)
    print("测试 Edge TTS 引擎")
    print("=" * 50)
    
    try:
        # 创建TTS引擎
        print("\n1. 创建TTS引擎...")
        tts = tts_registry.create_engine("edge", {
            "voice": "xiaoxiao",  # 晓晓
            "speed": 1.0,
            "volume": 1.0,
            "cache_enabled": True,
            "cache_dir": "data/cache/tts"
        })
        print(f"   ✓ 引擎创建成功: {tts.provider_name}")
        
        # 初始化
        print("\n2. 初始化引擎...")
        await tts.initialize()
        print("   ✓ 初始化成功")
        
        # 合成语音
        print("\n3. 合成语音...")
        test_text = "你好，我是小雪，很高兴认识你！"
        print(f"   文本: {test_text}")
        
        result = await tts.synthesize(test_text)
        print(f"   ✓ 合成成功")
        print(f"   - 音频大小: {len(result.audio_data)} bytes")
        print(f"   - 采样率: {result.sample_rate} Hz")
        print(f"   - 格式: {result.format}")
        print(f"   - 来自缓存: {result.cached}")
        
        # 保存到文件
        print("\n4. 保存音频文件...")
        output_path = "test_output.mp3"
        await tts.synthesize_to_file(test_text, output_path)
        print(f"   ✓ 已保存到: {output_path}")
        
        # 测试缓存
        print("\n5. 测试缓存...")
        result2 = await tts.synthesize(test_text)
        print(f"   ✓ 第二次合成: 来自缓存 = {result2.cached}")
        
        # 关闭
        print("\n6. 关闭引擎...")
        await tts.close()
        print("   ✓ 关闭成功")
        
        print("\n" + "=" * 50)
        print("✅ Edge TTS 测试通过！")
        print("=" * 50)
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_edge_tts())
    sys.exit(0 if result else 1)
