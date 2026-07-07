"""
CosyVoice v3.5 TTS 测试脚本
测试声音复刻、声音设计和语音合成功能
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts.cosyvoice_tts import CosyVoiceTTS
from utils.logger import get_logger

logger = get_logger(__name__)

async def test_basic_tts():
    """测试基本TTS功能"""
    print("\n" + "="*60)
    print("测试1: 基本TTS功能")
    print("="*60)
    
    tts = CosyVoiceTTS()
    
    if not tts.is_initialized():
        print("❌ TTS未初始化，请检查DASHSCOPE_API_KEY配置")
        return False
    
    print(f"✓ TTS已初始化")
    print(f"  模型: {tts.model}")
    print(f"  当前音色: {tts.voice_id}")
    print(f"  支持语种: {', '.join(tts.get_supported_languages())}")
    
    return True

async def test_audio_generation():
    """测试音频生成"""
    print("\n" + "="*60)
    print("测试2: 音频生成")
    print("="*60)
    
    tts = CosyVoiceTTS()
    
    if not tts.is_initialized():
        print("❌ TTS未初始化")
        return
    
    test_text = "你好，我是小雪，很高兴认识你！今天天气真不错。"
    print(f"测试文本: {test_text}")
    print(f"使用音色: {tts.voice_id}")
    
    print("正在生成音频...")
    audio_data = tts.generate_audio(test_text)
    
    if audio_data:
        output_path = "test_output_cosyvoice.wav"
        tts.save_to_file(audio_data, output_path)
        print(f"✓ 音频生成成功，已保存到: {output_path}")
        print(f"  音频大小: {len(audio_data)} 字节")
    else:
        print("❌ 音频生成失败")

async def test_streaming_generation():
    """测试流式音频生成"""
    print("\n" + "="*60)
    print("测试3: 流式音频生成")
    print("="*60)
    
    tts = CosyVoiceTTS()
    
    if not tts.is_initialized():
        print("❌ TTS未初始化")
        return
    
    test_text = "这是一段测试流式输出的文本，希望能够正常工作。"
    print(f"测试文本: {test_text}")
    
    print("正在流式生成音频...")
    
    chunks = []
    chunk_count = 0
    
    for chunk in tts.generate_audio_stream(test_text):
        if chunk:
            chunks.append(chunk)
            chunk_count += 1
            if chunk_count <= 5:
                print(f"  接收到第 {chunk_count} 个音频块，大小: {len(chunk)} 字节")
    
    if chunks:
        output_path = "test_output_streaming.wav"
        with open(output_path, "wb") as f:
            for chunk in chunks:
                f.write(chunk)
        print(f"✓ 流式音频生成成功，共 {chunk_count} 个块")
        print(f"  已保存到: {output_path}")
    else:
        print("❌ 流式音频生成失败")

async def test_list_voices():
    """测试查询音色列表"""
    print("\n" + "="*60)
    print("测试4: 查询已创建的音色")
    print("="*60)
    
    tts = CosyVoiceTTS()
    
    if not tts.is_initialized():
        print("❌ TTS未初始化")
        return
    
    voices = tts.list_voices()
    
    if voices:
        print(f"✓ 找到 {len(voices)} 个已创建的音色:")
        for v in voices:
            voice_id = v.get('voice_id', '')
            status = v.get('status', '')
            target_model = v.get('target_model', '')
            print(f"  - {voice_id}")
            print(f"    状态: {status}, 模型: {target_model}")
    else:
        print("暂无已创建的音色")

async def test_voice_design():
    """测试声音设计功能"""
    print("\n" + "="*60)
    print("测试5: 声音设计（从文本描述生成音色）")
    print("="*60)
    
    tts = CosyVoiceTTS()
    
    if not tts.is_initialized():
        print("❌ TTS未初始化")
        return
    
    voice_prompt = "活泼可爱的少女声音，音色清脆甜美，语速轻快，充满朝气"
    preview_text = "大家好，我是小雪，很高兴认识你们！"
    
    print(f"声音描述: {voice_prompt}")
    print(f"试听文本: {preview_text}")
    print("\n正在设计音色...")
    
    voice_id, audio_data = tts.design_voice(
        voice_prompt=voice_prompt,
        preview_text=preview_text,
        language_hints="zh"
    )
    
    if voice_id and audio_data:
        print(f"✓ 音色设计成功: {voice_id}")
        output_path = "test_output_designed_voice.wav"
        with open(output_path, "wb") as f:
            f.write(audio_data)
        print(f"  预览音频已保存到: {output_path}")
        print(f"  音频大小: {len(audio_data)} 字节")
        
        print("\n使用设计的音色进行语音合成...")
        test_audio = tts.generate_audio("测试一下设计的声音效果。")
        if test_audio:
            print("✓ 使用设计音色合成成功")
    else:
        print("❌ 音色设计失败")

async def test_voice_cloning():
    """测试声音复刻（需要公网URL）"""
    print("\n" + "="*60)
    print("测试6: 声音复刻（需要公网可访问的音频URL）")
    print("="*60)
    
    tts = CosyVoiceTTS()
    
    if not tts.is_initialized():
        print("❌ TTS未初始化")
        return
    
    print("声音复刻需要公网可访问的音频URL")
    print("请将音频上传到阿里云OSS或其他云存储服务")
    print("\n示例用法:")
    print('  voice_id = tts.create_voice_from_url(')
    print('      audio_url="https://your-bucket.oss-cn-beijing.aliyuncs.com/audio.wav",')
    print('      prefix="kirara",')
    print('      language_hints="ja"  # 日语')
    print('  )')
    
    print("\n音频要求:")
    print("  - 时长: 10-20秒")
    print("  - 格式: WAV(16bit), MP3, M4A")
    print("  - 采样率: >= 16kHz")
    print("  - 内容: 清晰无杂音，连续语音")

async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("CosyVoice v3.5 TTS 功能测试")
    print("="*60)
    
    if not await test_basic_tts():
        print("\n⚠ 请确保已配置 DASHSCOPE_API_KEY")
        return
    
    await test_audio_generation()
    await test_streaming_generation()
    await test_list_voices()
    
    print("\n" + "-"*60)
    print("是否测试声音设计功能？(输入 y 测试)")
    try:
        choice = input().strip().lower()
        if choice == 'y':
            await test_voice_design()
    except:
        pass
    
    await test_voice_cloning()
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)
    
    print("\n配置说明:")
    print("  模型版本:")
    print("    - cosyvoice-v3-flash: 快速版，支持多语种")
    print("    - cosyvoice-v3-plus: 高质量版")
    print("    - cosyvoice-v3.5-flash: 最新快速版（仅北京地域）")
    print("    - cosyvoice-v3.5-plus: 最新高质量版（仅北京地域）")
    print("\n  声音复刻流程:")
    print("    1. 上传音频到公网URL（如阿里云OSS）")
    print("    2. 调用 create_voice_from_url() 创建音色")
    print("    3. 使用返回的 voice_id 进行语音合成")
    print("\n  声音设计流程:")
    print("    1. 调用 design_voice() 并提供声音描述")
    print("    2. 获取预览音频试听效果")
    print("    3. 使用返回的 voice_id 进行语音合成")

if __name__ == "__main__":
    asyncio.run(main())
