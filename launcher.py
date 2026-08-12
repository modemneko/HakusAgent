#!/usr/bin/env python3
"""
HakusAI Chat 启动器
提供一键启动、依赖检测、配置管理等功能
"""
import os
import sys
import subprocess
import platform
import argparse
from pathlib import Path
from typing import Optional, List, Tuple

try:
    import importlib.metadata
except ImportError:
    importlib = None

COLORS = {
    'GREEN': '\033[92m',
    'RED': '\033[91m',
    'YELLOW': '\033[93m',
    'BLUE': '\033[94m',
    'CYAN': '\033[96m',
    'PURPLE': '\033[35m',
    'RESET': '\033[0m',
    'BOLD': '\033[1m',
}

def color(text: str, color_name: str) -> str:
    return f"{COLORS.get(color_name, '')}{text}{COLORS['RESET']}"

def print_banner():
    banner = f"""
{color('╔════════════════════════════════════════════════════════════╗', 'CYAN')}
{color('║', 'CYAN')}                                                            {color('║', 'CYAN')}
{color('║', 'CYAN')}   {color('██╗  ██╗ █████╗ ██╗  ██╗██╗   ██╗███████╗', 'PURPLE')}                {color('║', 'CYAN')}
{color('║', 'CYAN')}   {color('██║  ██║██╔══██╗██║ ██╔╝██║   ██║██╔════╝', 'PURPLE')}                {color('║', 'CYAN')}
{color('║', 'CYAN')}   {color('███████║███████║█████╔╝ ██║   ██║█████╗  ', 'PURPLE')}                {color('║', 'CYAN')}
{color('║', 'CYAN')}   {color('██╔══██║██╔══██║██╔═██╗ ██║   ██║██╔══╝  ', 'PURPLE')}                {color('║', 'CYAN')}
{color('║', 'CYAN')}   {color('██║  ██║██║  ██║██║  ██╗╚██████╔╝███████╗', 'PURPLE')}                {color('║', 'CYAN')}
{color('║', 'CYAN')}   {color('╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝', 'PURPLE')}                {color('║', 'CYAN')}
{color('║', 'CYAN')}                                                            {color('║', 'CYAN')}
{color('║', 'CYAN')}   {color('HakusAI Multi Platform  v1.0.0', 'YELLOW')}                           {color('║', 'CYAN')}
{color('║', 'CYAN')}                                                            {color('║', 'CYAN')}
{color('╚════════════════════════════════════════════════════════════╝', 'CYAN')}
"""
    print(banner)

def get_python_version() -> Tuple[int, int, int]:
    return sys.version_info[:3]

def check_python_version() -> bool:
    version = get_python_version()
    print(color(f"[*] Python 版本: {version[0]}.{version[1]}.{version[2]}", 'BLUE'))
    
    if version < (3, 10, 0):
        print(color("[✗] Python 版本过低，需要 3.10 或更高版本", 'RED'))
        return False
    
    print(color("[✓] Python 版本符合要求", 'GREEN'))
    return True

def check_venv() -> bool:
    in_venv = hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )
    
    venv_exists = Path("venv").exists()
    
    if in_venv:
        print(color(f"[✓] 当前在虚拟环境中: {sys.prefix}", 'GREEN'))
        return True
    elif venv_exists:
        print(color("[!] 检测到虚拟环境但未激活", 'YELLOW'))
        return False
    else:
        print(color("[!] 未检测到虚拟环境", 'YELLOW'))
        return False

def create_venv() -> bool:
    print(color("[*] 创建虚拟环境...", 'BLUE'))
    try:
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)
        print(color("[✓] 虚拟环境创建完成", 'GREEN'))
        return True
    except subprocess.CalledProcessError as e:
        print(color(f"[✗] 创建虚拟环境失败: {e}", 'RED'))
        return False

def relaunch_with_venv():
    """使用虚拟环境中的 Python 重新运行启动器"""
    venv_python = Path("venv") / ("Scripts" if platform.system() == "Windows" else "bin") / ("python.exe" if platform.system() == "Windows" else "python")
    
    if venv_python.exists():
        print(color("[*] 正在切换到虚拟环境...", 'BLUE'))
        print()
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)
    else:
        print(color("[✗] 虚拟环境 Python 不存在", 'RED'))

def get_pip_command() -> List[str]:
    if Path("venv").exists():
        if platform.system() == "Windows":
            return ["venv\\Scripts\\python.exe", "-m", "pip"]
        else:
            return ["venv/bin/python", "-m", "pip"]
    return [sys.executable, "-m", "pip"]

def get_python_command() -> List[str]:
    if Path("venv").exists():
        if platform.system() == "Windows":
            return ["venv\\Scripts\\python.exe"]
        else:
            return ["venv/bin/python"]
    return [sys.executable]

def check_dependencies() -> bool:
    print(color("[*] 检查核心依赖...", 'BLUE'))
    
    required = ['fastapi', 'uvicorn', 'pyyaml', 'aiohttp']
    missing = []
    
    for pkg in required:
        try:
            __import__(pkg.replace('-', '_'))
        except ImportError:
            missing.append(pkg)
    
    if missing:
        print(color(f"[!] 缺少核心依赖: {', '.join(missing)}", 'YELLOW'))
        return False
    
    print(color("[✓] 核心依赖已安装", 'GREEN'))
    return True

def smart_install_dependencies() -> bool:
    """根据配置智能安装依赖"""
    print(color("[*] 分析配置并安装所需依赖...", 'BLUE'))
    
    pip_cmd = get_pip_command()
    
    DEPENDENCY_MAP = {
        "core": [
            "pyyaml>=6.0", "aiohttp>=3.8.0", "fastapi>=0.100.0",
            "uvicorn>=0.23.0", "websockets>=11.0", "pydantic>=2.0.0",
        ],
        "models": {
            "deepseek": ["openai>=1.0.0"],
            "gemini": ["google-generativeai>=0.3.0", "langchain-google-genai>=1.0.0"],
            "qwen": ["openai>=1.0.0"],
            "glm": ["openai>=1.0.0"],
        },
        "memory": [
            "langchain>=0.1.0", "langchain-chroma>=0.1.0", "chromadb>=0.4.0",
            "faiss-cpu>=1.7.0", "numpy>=1.24.0", "scikit-learn>=1.3.0", "jieba>=0.42.0",
        ],
        "desktop_pet": {
            "basic": ["PyQt5>=5.15.0"],
            "3d": ["PyOpenGL>=3.1.0", "PyOpenGL-accelerate>=3.1.0", "pyglm>=2.7.0", "numpy>=1.20.0"],
            "gltf": ["pygltflib>=1.16.0"],
        },
    }
    
    dependencies = set(DEPENDENCY_MAP["core"])
    
    try:
        import yaml
        config_path = Path("config.yaml")
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if config:
                default_model = config.get("models", {}).get("default_model", "deepseek")
                if default_model in DEPENDENCY_MAP["models"]:
                    dependencies.update(DEPENDENCY_MAP["models"][default_model])
                    print(color(f"    - 模型 [{default_model}] 依赖", 'CYAN'))
                
                if config.get("memory", {}).get("short_term_max_length", 50) > 0:
                    dependencies.update(DEPENDENCY_MAP["memory"])
                    print(color(f"    - 记忆系统依赖", 'CYAN'))
    except Exception as e:
        print(color(f"[!] 读取配置失败，安装全部依赖: {e}", 'YELLOW'))
        for model_deps in DEPENDENCY_MAP["models"].values():
            dependencies.update(model_deps)
        dependencies.update(DEPENDENCY_MAP["memory"])
    
    missing = []
    for dep in dependencies:
        pkg_name = dep.split(">=")[0].split("==")[0].replace("-", "_")
        try:
            __import__(pkg_name)
        except ImportError:
            missing.append(dep)
    
    if not missing:
        print(color("[✓] 所有依赖已安装", 'GREEN'))
        return True
    
    print(color(f"[*] 安装 {len(missing)} 个依赖包...", 'BLUE'))
    
    try:
        subprocess.run(pip_cmd + ["install"] + missing + ["-q"], check=True)
        print(color("[✓] 依赖安装完成", 'GREEN'))
        return True
    except subprocess.CalledProcessError as e:
        print(color(f"[✗] 依赖安装失败: {e}", 'RED'))
        return False

def install_dependencies() -> bool:
    """安装全部依赖（兼容旧方式）"""
    return smart_install_dependencies()

def check_config() -> bool:
    config_path = Path("config.yaml")
    
    if not config_path.exists():
        print(color("[!] 配置文件不存在", 'YELLOW'))
        
        example_path = Path("config.yaml.example")
        if example_path.exists():
            print(color("[*] 从示例创建配置文件...", 'BLUE'))
            import shutil
            shutil.copy(example_path, config_path)
            print(color("[✓] 默认配置已创建", 'GREEN'))
            return True
        return False
    
    print(color("[✓] 配置文件存在", 'GREEN'))
    return True

def check_frontend() -> bool:
    dist_path = Path("webui/dist")
    
    if dist_path.exists() and (dist_path / "index.html").exists():
        print(color("[✓] 前端已构建", 'GREEN'))
        return True
    
    print(color("[!] 前端未构建", 'YELLOW'))
    return False

def build_frontend() -> bool:
    print(color("[*] 检查 Node.js...", 'BLUE'))
    
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(color("[✗] 未找到 Node.js", 'RED'))
            print("    下载地址: https://nodejs.org/")
            return False
        
        print(color(f"[✓] Node.js 版本: {result.stdout.strip()}", 'GREEN'))
    except FileNotFoundError:
        print(color("[✗] 未找到 Node.js", 'RED'))
        return False
    
    webui_path = Path("webui")
    if not webui_path.exists():
        print(color("[✗] 前端目录不存在", 'RED'))
        return False
    
    print(color("[*] 安装前端依赖...", 'BLUE'))
    npm_cmd = "npm.cmd" if platform.system() == "Windows" else "npm"
    
    subprocess.run([npm_cmd, "install"], cwd=webui_path, check=True)
    
    print(color("[*] 构建前端...", 'BLUE'))
    subprocess.run([npm_cmd, "run", "build"], cwd=webui_path, check=True)
    
    print(color("[✓] 前端构建完成", 'GREEN'))
    return True

def start_web(port: int = 8000):
    print(color(f"[*] 启动 Web 模式...", 'GREEN'))
    print(color(f"[*] 访问地址: http://localhost:{port}", 'BLUE'))
    print(color(f"[*] API 文档: http://localhost:{port}/docs", 'BLUE'))
    print()
    
    python_cmd = get_python_command()
    subprocess.run(python_cmd + [
        "main.py", "api",
        "--host", "0.0.0.0",
        "--port", str(port)
    ])

def start_cli():
    print(color("[*] 启动 CLI 模式...", 'GREEN'))
    print()
    
    python_cmd = get_python_command()
    subprocess.run(python_cmd + ["main.py", "cli"])

def start_api(port: int = 8000):
    print(color(f"[*] 启动 API 服务 (端口: {port})...", 'GREEN'))
    print()
    
    python_cmd = get_python_command()
    subprocess.run(python_cmd + [
        "main.py", "api",
        "--host", "0.0.0.0",
        "--port", str(port)
    ])

def start_virtual_avatar(port: int = 8000):
    print(color("[*] 启动虚拟主播模式...", 'GREEN'))
    print()
    print(color("  虚拟主播功能已集成到 Web 管理界面", 'CYAN'))
    print(color("  请在浏览器中访问 http://localhost:" + str(port) + "/live2d", 'CYAN'))
    print()
    
    start_web(port)

def show_menu() -> str:
    print()
    print(color("════════════════════════════════════════════════════════════", 'CYAN'))
    print(color("  请选择启动模式", 'CYAN'))
    print(color("════════════════════════════════════════════════════════════", 'CYAN'))
    print()
    print("  [1] Web 模式     - 启动 Web 管理界面 (推荐)")
    print("  [2] CLI 模式     - 命令行交互模式")
    print("  [3] API 模式     - 仅启动 API 服务")
    print("  [4] 虚拟主播     - Live2D 虚拟主播模式")
    print("  [5] 安装前端     - 安装/更新 WebUI 前端")
    print("  [6] 更新依赖     - 更新 Python 依赖")
    print("  [7] 编辑配置     - 编辑配置文件")
    print("  [8] 系统诊断     - 检查系统环境")
    print("  [0] 退出")
    print()
    
    return input("请输入选项 [0-8]: ").strip()

def run_diagnostics():
    print()
    print(color("════════════════════════════════════════════════════════════", 'CYAN'))
    print(color("  系统诊断", 'CYAN'))
    print(color("════════════════════════════════════════════════════════════", 'CYAN'))
    print()
    
    print(f"操作系统: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")
    print(f"Python 路径: {sys.executable}")
    print(f"工作目录: {os.getcwd()}")
    print()
    
    print(color("模型状态:", 'BLUE'))
    model_deps = {
        'deepseek': ['openai'],
        'gemini': ['google.generativeai'],
        'qwen': ['openai'],
        'glm': ['openai'],
    }
    for model, deps in model_deps.items():
        available = True
        for d in deps:
            try:
                __import__(d.split('.')[0])
            except ImportError:
                available = False
                break
        status = color('✓ 可用', 'GREEN') if available else color('✗ 依赖缺失', 'RED')
        print(f"  {model}: {status}")
    
    print()
    print(color("功能状态:", 'BLUE'))
    features = [
        ('记忆系统', ['langchain', 'chromadb']),
        ('TTS语音', ['sherpa_onnx']),
        ('搜索工具', ['langchain_google_community']),
        ('桌宠基础', ['PyQt5']),
        ('桌宠3D', ['OpenGL']),
    ]
    for name, deps in features:
        available = True
        for d in deps:
            try:
                __import__(d)
            except ImportError:
                available = False
                break
        status = color('✓ 可用', 'GREEN') if available else color('○ 未安装', 'YELLOW')
        print(f"  {name}: {status}")
    
    print()
    print(color("核心依赖:", 'BLUE'))
    packages = ['fastapi', 'uvicorn', 'pyyaml', 'aiohttp', 'openai', 'websockets']
    
    for pkg in packages:
        try:
            if importlib:
                version = importlib.metadata.version(pkg.replace('-', '_'))
                print(f"  {color('✓', 'GREEN')} {pkg}: {version}")
            else:
                __import__(pkg.replace('-', '_'))
                print(f"  {color('✓', 'GREEN')} {pkg}: 已安装")
        except:
            print(f"  {color('✗', 'RED')} {pkg}: 未安装")
    
    print()
    print(color("文件检查:", 'BLUE'))
    files = ['config.yaml', 'requirements.txt', 'main.py']
    for f in files:
        exists = Path(f).exists()
        status = color('✓', 'GREEN') if exists else color('✗', 'RED')
        print(f"  {status} {f}")
    
    print()
    print(color("前端检查:", 'BLUE'))
    frontend_ok = check_frontend()
    if frontend_ok:
        print(f"  {color('✓', 'GREEN')} 前端已构建")
    else:
        print(f"  {color('!', 'YELLOW')} 前端未构建")

def open_config():
    config_path = Path("config.yaml")
    if not config_path.exists():
        print(color("[✗] 配置文件不存在", 'RED'))
        return
    
    if platform.system() == "Windows":
        os.startfile(str(config_path))
    elif platform.system() == "Darwin":
        subprocess.run(["open", str(config_path)])
    else:
        editor = os.environ.get('EDITOR', 'nano')
        subprocess.run([editor, str(config_path)])

def main():
    parser = argparse.ArgumentParser(
        description="HakusAI Chat 启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'mode',
        nargs='?',
        choices=['web', 'cli', 'api', 'install', 'diagnose'],
        help='启动模式'
    )
    parser.add_argument('--port', '-p', type=int, default=8000, help='API端口')
    parser.add_argument('--no-venv', action='store_true', help='不使用虚拟环境')
    
    args = parser.parse_args()
    
    print_banner()
    
    if not check_python_version():
        sys.exit(1)
    
    if args.mode == 'install':
        if not args.no_venv and not check_venv():
            create_venv()
        install_dependencies()
        sys.exit(0)
    
    if args.mode == 'diagnose':
        run_diagnostics()
        sys.exit(0)
    
    if not args.no_venv and not check_venv():
        print(color("[*] 建议创建虚拟环境", 'YELLOW'))
        choice = input("是否创建? [Y/n]: ").strip().lower()
        if choice in ('', 'y', 'yes'):
            if create_venv():
                relaunch_with_venv()
            else:
                print(color("[!] 虚拟环境创建失败，继续使用系统 Python", 'YELLOW'))
    
    deps_ok = check_dependencies()
    if not deps_ok:
        print(color("[*] 需要安装依赖才能正常运行", 'YELLOW'))
        choice = input("是否安装? [Y/n]: ").strip().lower()
        if choice in ('', 'y', 'yes'):
            if not install_dependencies():
                print(color("[!] 依赖安装失败，部分功能可能不可用", 'YELLOW'))
        else:
            print(color("[!] 跳过依赖安装，部分功能可能不可用", 'YELLOW'))
    
    check_config()
    
    if args.mode == 'web':
        start_web(args.port)
    elif args.mode == 'cli':
        start_cli()
    elif args.mode == 'api':
        start_api(args.port)
    else:
        while True:
            choice = show_menu()
            
            if choice == '1':
                start_web(args.port)
            elif choice == '2':
                start_cli()
            elif choice == '3':
                start_api(args.port)
            elif choice == '4':
                start_virtual_avatar(args.port)
            elif choice == '5':
                build_frontend()
            elif choice == '6':
                install_dependencies()
            elif choice == '7':
                open_config()
            elif choice == '8':
                run_diagnostics()
            elif choice == '0':
                print()
                print(color("感谢使用 HakusAI Chat!", 'CYAN'))
                break
            else:
                print(color("[✗] 无效选项", 'RED'))

if __name__ == "__main__":
    main()
