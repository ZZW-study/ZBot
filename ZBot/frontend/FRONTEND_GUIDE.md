# React 前端脚手架文件详解

> 本文档面向后端开发者，解释 `npm create vite` 生成的 React 脚手架中每个文件的作用。
> 你用的命令应该是 `npm create vite@latest . -- --template react`，这会基于 **Vite + React** 生成项目。

---

## 1. 总览：文件树

```
frontend/
├── .gitignore              # Git 忽略规则
├── README.md               # Vite 自动生成的说明文档
├── eslint.config.js        # 代码风格检查配置
├── index.html              # 应用入口 HTML（唯一的 HTML 文件）
├── node_modules/           # 依赖包目录（86MB，101个包）
├── package-lock.json       # 依赖版本锁定文件
├── package.json            # 项目元信息 + 依赖声明 + 脚本命令
├── public/                 # 静态资源目录（原样复制到构建产物）
│   ├── favicon.svg         # 浏览器标签页图标
│   └── icons.svg           # 页面用的 SVG 图标集
├── src/                    # 源代码目录（你写代码的地方）
│   ├── App.css             # App 组件的样式
│   ├── App.jsx             # 主组件（页面内容）
│   ├── assets/             # 需要打包处理的静态资源
│   │   ├── hero.png
│   │   ├── react.svg
│   │   └── vite.svg
│   ├── index.css           # 全局样式
│   └── main.jsx            # JavaScript 入口文件
└── vite.config.js          # Vite 构建工具配置
```

---

## 2. 逐文件详解

### 2.1 `package.json` — 项目的"身份证"

```json
{
  "name": "frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",          // 启动开发服务器
    "build": "vite build",  // 打包生产版本
    "lint": "eslint .",     // 代码风格检查
    "preview": "vite preview"  // 预览打包结果
  },
  "dependencies": {
    "react": "^19.2.6",      // React 核心库
    "react-dom": "^19.2.6"   // React 的 DOM 渲染器
  },
  "devDependencies": {
    "vite": "^8.0.12",              // 构建工具
    "@vitejs/plugin-react": "^6.0.1", // Vite 的 React 插件
    "eslint": "^10.3.0",            // 代码检查工具
    // ...其他 eslint 相关插件
  }
}
```

**后端类比：** 相当于 Python 的 `pyproject.toml` 或 `requirements.txt`。

- `dependencies` = 运行时依赖（类似 `pip install flask`）
- `devDependencies` = 开发时依赖（类似 `pip install pytest`，生产环境不需要）
- `scripts` = 可运行的命令（类似 Makefile 或 `justfile`）

**常用命令：**

```bash
npm run dev      # 启动开发服务器，类似 python main.py
npm run build    # 打包，类似 pyinstaller 打包
npm run lint     # 检查代码风格，类似 flake8 / ruff
```

---

### 2.2 `package-lock.json` — 精确版本锁定

**后端类比：** 相当于 Python 的 `uv.lock` 或 `poetry.lock`。

它锁定了每个依赖的**精确版本**和**下载地址**，确保团队成员和 CI 环境安装完全相同的依赖版本。

**你不需要手动修改它。** 每次 `npm install` 时自动生成/更新。

---

### 2.3 `node_modules/` — 依赖包实际安装位置

**后端类比：** 相当于 Python 的 `site-packages/` 或虚拟环境目录。

- 86MB、101 个包 —— 这是因为前端依赖树很深（一个包依赖十几个包）
- **绝对不要手动编辑或提交到 Git**
- `.gitignore` 已经排除了它
- 丢失后运行 `npm install` 即可恢复（从 `package-lock.json` 读取）

---

### 2.4 `index.html` — 唯一的 HTML 文件

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>frontend</title>
  </head>
  <body>
    <div id="root"></div>                    <!-- React 挂载点 -->
    <script type="module" src="/src/main.jsx"></script>  <!-- JS 入口 -->
  </body>
</html>
```

**后端类比：** 相当于 Flask/Django 模板中的 `base.html`。

**关键点：**

- 这是浏览器加载的**第一个也是唯一一个** HTML 文件
- `<div id="root"></div>` 是 React 的挂载点，所有 React 组件都渲染到这里
- Vite 开发时会自动注入热更新（HMR）脚本
- 和后端不同：前端是**单页面应用（SPA）**，只有一个 HTML，页面切换靠 JS 动态渲染

---

### 2.5 `vite.config.js` — 构建工具配置

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
```

**后端类比：** 相当于 `webpack.config.js` 或 Django 的 `settings.py` 中关于静态文件的部分。

Vite 是新一代前端构建工具，作用：

- **开发时：** 启动本地服务器，提供热模块替换（HMR）—— 改代码自动刷新浏览器
- **构建时：** 把 JSX/CSS/图片打包成浏览器能直接运行的静态文件

目前配置很简单，后续如果需要代理后端 API，会加 `server.proxy` 配置。

---

### 2.6 `eslint.config.js` — 代码风格检查

**后端类比：** 相当于 Python 的 `ruff.toml` 或 `.flake8`。

ESLint 检查代码中的问题：

- 使用了未声明的变量
- React Hooks 使用不规范
- 常见的代码错误

运行 `npm run lint` 即可检查。IDE（VSCode）也会实时显示警告。

---

### 2.7 `.gitignore` — Git 忽略规则

**后端类比：** 和 Python 项目的 `.gitignore` 一样。

排除了：

- `node_modules/` — 依赖目录（太大，通过 `npm install` 恢复）
- `dist/` — 打包产物（通过 `npm run build` 重新生成）
- 日志文件、编辑器配置等

---

### 2.8 `src/main.jsx` — JavaScript 入口文件

```jsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

**后端类比：** 相当于 Python 的 `main.py` 或 `__init__.py`。

执行流程：

1. 浏览器加载 `index.html`
2. 发现 `<script src="/src/main.jsx">`，加载并执行此文件
3. `createRoot(document.getElementById('root'))` 找到 HTML 中的 `<div id="root">`
4. `.render(<App />)` 把 `<App />` 组件渲染进去

**`StrictMode`** 是 React 的开发辅助模式，会在开发时额外检查潜在问题（生产构建自动移除）。

---

### 2.9 `src/App.jsx` — 主组件

```jsx
import { useState } from 'react'

function App() {
  const [count, setCount] = useState(0)

  return (
    <>
      <h1>Get started</h1>
      <button onClick={() => setCount(count + 1)}>
        Count is {count}
      </button>
    </>
  )
}

export default App
```

**后端类比：** 相当于 Flask 路由函数或 Django 视图函数返回的模板。

这是脚手架自带的示例页面，展示了一个计数器。**实际开发时你会把这里的内容全部替换成自己的页面。**

**核心概念：**

- `useState(0)` — React 的状态管理，类似后端的全局变量，但它是**响应式的**（值变了，页面自动更新）
- `JSX`（`<div>...</div>`）— 不是 HTML，是 JavaScript 的语法扩展，最终会被编译成 `React.createElement()` 调用
- `className` 而不是 `class` — 因为 `class` 是 JavaScript 的保留字

---

### 2.10 `src/index.css` — 全局样式

**后端类比：** 相当于所有模板共享的基础 CSS。

定义了：

- CSS 变量（颜色、字体）— 类似 Python 常量
- 基础排版样式（字号、行高）
- 暗色模式支持（`@media (prefers-color-scheme: dark)`）
- 响应式断点（`@media (max-width: 1024px)`）

---

### 2.11 `src/App.css` — App 组件专属样式

只作用于 `App.jsx` 中的元素。和 `index.css` 的区别：

- `index.css` — 全局，影响所有页面
- `App.css` — 局部，只影响导入它的组件（Vite 默认启用 CSS Modules 行为）

---

### 2.12 `public/` — 静态资源目录

```
public/
├── favicon.svg    # 浏览器标签页图标
└── icons.svg      # SVG 图标集合
```

**和 `src/assets/` 的区别：**

| 目录            | 处理方式                             | 使用场景                              |
| --------------- | ------------------------------------ | ------------------------------------- |
| `public/`     | 原样复制到构建产物，路径不变         | favicon、robots.txt、不需要处理的文件 |
| `src/assets/` | 被 Vite 处理（压缩、hash命名、优化） | 组件引用的图片、字体                  |

`public/` 中的文件通过 `/favicon.svg` 直接访问（绝对路径）。
`src/assets/` 中的文件通过 `import` 导入，Vite 会自动处理路径。

---

### 2.13 `src/assets/` — 需要构建处理的资源

```
assets/
├── hero.png      # 示例页面的装饰图片
├── react.svg     # React logo
└── vite.svg      # Vite logo
```

这些文件会被 Vite 打包处理（压缩、添加 hash 后缀），在 JS 中通过 `import` 使用：

```jsx
import reactLogo from './assets/react.svg'
// <img src={reactLogo} />
```

---

## 3. 后端 vs 前端：概念对照表

| 概念         | 后端 (Python)                   | 前端 (React + Vite)            |
| ------------ | ------------------------------- | ------------------------------ |
| 项目配置     | `pyproject.toml`              | `package.json`               |
| 依赖锁定     | `uv.lock`                     | `package-lock.json`          |
| 依赖安装位置 | `site-packages/` / `.venv/` | `node_modules/`              |
| 安装依赖     | `pip install` / `uv sync`   | `npm install`                |
| 运行项目     | `python main.py`              | `npm run dev`                |
| 打包部署     | `pyinstaller` / Docker        | `npm run build` → `dist/` |
| 代码检查     | `ruff` / `flake8`           | `eslint`                     |
| 入口文件     | `main.py`                     | `src/main.jsx`               |
| 配置文件     | `settings.py`                 | `vite.config.js`             |
| 模板文件     | `templates/*.html`            | 组件 `*.jsx`                 |
| 静态文件     | `static/`                     | `public/` + `src/assets/`  |

---

## 4. 前端为什么要这么多文件？

后端项目的"复杂度"在服务器上：数据库、API、中间件、部署。文件少但逻辑重。

前端项目的"复杂度"在工程化上：

- **浏览器兼容性** — 需要构建工具转译新语法
- **模块系统** — 浏览器原生不支持 `import`，需要打包
- **开发体验** — HMR（热更新）、Source Map、代理
- **性能优化** — 代码分割、Tree Shaking、资源压缩
- **代码质量** — ESLint、TypeScript、Prettier

这些"多出来的文件"就是这些工程化需求的配置。**你不需要一开始就理解所有文件**，随着开发深入逐步了解即可。

---

## 5. 快速上手

```bash
cd frontend
npm run dev        # 启动开发服务器，默认 http://localhost:5173
```

浏览器打开后你会看到 Vite + React 的欢迎页面。

**接下来你可以：**

1. 编辑 `src/App.jsx`，保存后浏览器自动刷新（HMR）
2. 删除 `src/App.jsx` 中的示例代码，写你自己的页面
3. 删除 `src/assets/` 中不需要的示例图片
4. 修改 `index.html` 中的 `<title>` 为你的项目名
