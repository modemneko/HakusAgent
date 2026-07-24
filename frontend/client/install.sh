#!/bin/bash
# HakusAI Frontend Installation Script
# This script handles all dependency installation and setup

set -e  # Exit on error

echo "🚀 HakusAI 前端安装脚本"
echo "========================"

# Check Node.js version
echo "📋 检查 Node.js 环境..."
if ! command -v node &> /dev/null; then
    echo "❌ 错误: 未找到 Node.js"
    echo "   请先安装 Node.js >= 18: https://nodejs.org/"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ 错误: Node.js 版本过低 (当前: $(node -v), 需要 >= 18)"
    exit 1
fi
echo "✅ Node.js 版本: $(node -v)"

# Check npm
if ! command -v npm &> /dev/null; then
    echo "❌ 错误: 未找到 npm"
    exit 1
fi
echo "✅ npm 版本: $(npm -v)"

# Clean install
echo ""
echo "🧹 清理旧的依赖..."
rm -rf node_modules package-lock.json dist dist-electron

# Install dependencies
echo ""
echo "📦 安装依赖 (这可能需要几分钟)..."
npm install --legacy-peer-deps

# Verify installation
echo ""
echo "🔍 验证安装..."
if [ -d "node_modules" ]; then
    echo "✅ node_modules 目录存在"
else
    echo "❌ 错误: node_modules 目录未创建"
    exit 1
fi

# Type check
echo ""
echo "🔧 运行 TypeScript 类型检查..."
./node_modules/.bin/tsc --noEmit || {
    echo "⚠️  警告: TypeScript 类型检查有错误 (非致命)"
}

# Build test
echo ""
echo "🏗️  测试构建..."
npm run build || {
    echo "❌ 错误: 构建失败"
    exit 1
}

echo ""
echo "================================"
echo "✅ 安装完成!"
echo ""
echo "可用命令:"
echo "  npm run dev          # 启动开发服务器"
echo "  npm run dev:electron # 启动 Electron 桌面应用"
echo "  npm run build        # 构建生产版本"
echo "  npm run test:e2e     # 运行 E2E 测试"
echo ""
echo "如果遇到问题，请尝试:"
echo "  rm -rf node_modules package-lock.json"
echo "  npm install --legacy-peer-deps"
echo "================================"
