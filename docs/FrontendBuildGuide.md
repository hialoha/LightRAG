# Frontend Build Guide

> 以下安装与打包命令用于独立开发环境或发布构建环境，不是每次改代码的必做步骤。日常维护遵守 [AGENTS.md](../AGENTS.md)：复用可用依赖；服务正在使用 `lightrag/api/webui/` 时，在 `lightrag_webui/` 执行 `bun run build -- --outDir <暂存绝对目录>`，验证后再发布，避免构建直接覆盖在线资源。

## Overview

The LightRAG project includes a React-based WebUI frontend. This guide explains how frontend building works in different scenarios.

## Key Principle

- **Git Repository**: Frontend build results are **NOT** included (kept clean)
- **PyPI Package**: Frontend build results **ARE** included (ready to use)
- **Build Tool**: Uses **Bun** (not npm/yarn)

## Installation Scenarios

### 1. End Users (From PyPI) ✨

**Command:**
```bash
pip install lightrag-hku[api]
```

**What happens:**
- Frontend is already built and included in the package
- No additional steps needed
- Web interface works immediately

---

### 2. Development Mode (Recommended for Contributors) 🔧

**Command:**
```bash
# Clone the repository
git clone https://github.com/HKUDS/LightRAG.git
cd LightRAG

# Install in editable mode (no frontend build required yet)
pip install -e ".[api]"

# Build frontend when needed (can be done anytime)
cd lightrag_webui
bun install --frozen-lockfile
bun run build
cd ..
```

**Advantages:**
- Install first, build later (flexible workflow)
- Changes take effect immediately (symlink mode)
- Frontend can be rebuilt anytime without reinstalling

**How it works:**
- Creates symlinks to source directory
- Frontend build output goes to `lightrag/api/webui/`
- Changes are immediately visible in installed package

---

### 3. Normal Installation (Testing Package Build) 📦

**Command:**
```bash
# Clone the repository
git clone https://github.com/HKUDS/LightRAG.git
cd LightRAG

# ⚠️ MUST build frontend FIRST
cd lightrag_webui
bun install --frozen-lockfile
bun run build
cd ..

# Now install
pip install ".[api]"
```

**What happens:**
- Frontend files are **copied** to site-packages
- Post-build modifications won't affect installed package
- Requires rebuild + reinstall to update

**When to use:**
- Testing complete installation process
- Verifying package configuration
- Simulating PyPI user experience

---

### 4. Creating Distribution Package 🚀

**Command:**
```bash
# Build frontend first
cd lightrag_webui
bun install --frozen-lockfile --production
bun run build
cd ..

# Create distribution packages
python -m build

# Output: dist/lightrag_hku-*.whl and dist/lightrag_hku-*.tar.gz
```

**What happens:**
- `setup.py` checks if frontend is built
- If missing, installation fails with helpful error message
- Generated package includes all frontend files

---

## GitHub Actions (Automated Release)

When creating a release on GitHub:

1. **Automatically builds frontend** using Bun
2. **Verifies** build completed successfully
3. **Creates Python package** with frontend included
4. **Publishes to PyPI** using existing trusted publisher setup

**No manual intervention required!**

---

## Quick Reference

| Scenario | Command | Frontend Required | Can Build After |
|----------|---------|-------------------|-----------------|
| From PyPI | `pip install lightrag-hku[api]` | Included | No (already installed) |
| Development | `pip install -e ".[api]"` | No | ✅ Yes (anytime) |
| Normal Install | `pip install ".[api]"` | ✅ Yes (before) | No (must reinstall) |
| Create Package | `python -m build` | ✅ Yes (before) | N/A |

---

## Bun Installation

If you don't have Bun installed:

```bash
# macOS/Linux
curl -fsSL https://bun.sh/install | bash

# Windows
powershell -c "irm bun.sh/install.ps1 | iex"
```

Official documentation: https://bun.sh

---

## File Structure

```
LightRAG/
├── lightrag_webui/          # Frontend source code
│   ├── src/                 # React components
│   ├── package.json         # Dependencies
│   └── vite.config.ts       # Build configuration
│       └── outDir: ../lightrag/api/webui  # Build output
│
├── lightrag/
│   └── api/
│       └── webui/           # Frontend build output (gitignored)
│           ├── index.html   # Built files (after running bun run build)
│           └── assets/      # Built assets
│
├── setup.py                 # Build checks
├── pyproject.toml           # Package configuration
└── .gitignore               # Excludes lightrag/api/webui/* (except .gitkeep)
```

---

## Troubleshooting

### Q: I installed in development mode but the web interface doesn't work

**A:** Build the frontend:
```bash
cd lightrag_webui && bun run build
```

### Q: I built the frontend but it's not in my installed package

**A:** You probably used `pip install .` after building. Either:
- Use `pip install -e ".[api]"` for development
- Or reinstall: `pip uninstall lightrag-hku && pip install ".[api]"`

### Q: Where are the built frontend files?

**A:** In `lightrag/api/webui/` after running `bun run build`

### Q: Can I use npm or yarn instead of Bun?

**A:** The project is configured for Bun. While npm/yarn might work, Bun is recommended per project standards.

---

## Summary

✅ **PyPI users**: No action needed, frontend included
✅ **Developers**: Use `pip install -e ".[api]"`, build frontend when needed
✅ **CI/CD**: Automatic build in GitHub Actions
✅ **Git**: Frontend build output never committed

For questions or issues, please open a GitHub issue.
