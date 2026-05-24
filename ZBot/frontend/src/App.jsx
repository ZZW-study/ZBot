// ============================================
// App.jsx —— 根组件（应用的主页面）
// ============================================
// 这是整个应用的"主组件"，所有页面内容都从这里开始

// 从 react 库中导入 useState 钩子（Hook）
// useState 用于在函数组件中创建和管理"状态"（可以变化的数据）
import React, { useState } from 'react';

// 导入 App 组件专用的 CSS 样式
import './App.css';

// 导入子组件：TodoList（待办列表）和 AddTodo（添加待办的表单）
// 这两个组件在 ./components/ 文件夹中定义
import TodoList from './components/TodoList';
import AddTodo from './components/AddTodo';

// 导入 react-router-dom 提供的路由组件
// BrowserRouter：整个应用的路由容器，提供路由的上下文环境
// Routes：路由规则的容器，用来包裹所有 Route
// Route：定义一条路由规则（当用户访问某个路径时，显示哪个组件）
// Link：类似 <a> 标签的导航链接，但不会刷新页面（单页应用导航）
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';

// 导入"关于"页面组件（我们稍后会创建它）
import About from './pages/About';

// ============================================
// App 组件定义
// ============================================
// function App() 表示定义一个名为 App 的函数组件
// 函数组件就是一个返回 JSX（HTML 模板）的函数
function App() {

  // ---- 状态定义 ----

  // useState([]) 创建一个状态变量：
  //   - todos：当前状态值（一个数组，存放所有待办事项）
  //   - setTodos：修改状态的函数（调用它来更新 todos）
  //   - []：初始值，表示一开始没有待办事项，是个空数组
  const [todos, setTodos] = useState([]);

  // ---- 函数定义 ----

  // addTodo 函数：添加一个新的待办事项
  // 参数 text：新待办的文字内容（由 AddTodo 组件传入）
  const addTodo = (text) => {
    // 创建一个新的待办对象
    const newTodo = {
      id: Date.now(), // 用当前时间戳作为唯一 id（毫秒级，不会重复）
      text: text,     // 待办的文字内容
      completed: false // 是否已完成，新创建的默认是 false（未完成）
    };

    // 更新 todos 状态
    // [...todos, newTodo] 的意思是：
    //   - ...todos：展开运算符，把原来数组里的每一项都拿出来
    //   - , newTodo：把新待办追加到末尾
    // 结果是一个全新的数组（React 要求状态是不可变的，不能直接修改原数组）
    setTodos([...todos, newTodo]);
  };

  // deleteTodo 函数：删除一个待办事项
  // 参数 id：要删除的待办的 id
  const deleteTodo = (id) => {
    // filter() 方法会遍历数组，只保留满足条件的元素
    // todo.id !== id 的意思是：只保留 id 不等于要删除的那个 id 的待办
    // 等于把目标待办从数组中"过滤掉"了
    setTodos(todos.filter(todo => todo.id !== id));
  };

  // ---- 渲染 JSX ----

  return (
    // BrowserRouter 包裹整个应用，启用路由功能
    // 这样应用中的 Link 和 Routes 才能正常工作
    <BrowserRouter>

      {/* 导航栏 */}
      <nav className="navbar">
        {/* Link 组件类似 <a> 标签，但点击后不会刷新页面 */}
        {/* to 属性指定要跳转的路径 */}
        <Link to="/" className="nav-link">首页（待办事项）</Link>
        <Link to="/about" className="nav-link">关于</Link>
      </nav>

      {/* Routes 定义路由规则集合 */}
      {/* React 会根据当前浏览器地址栏的路径，匹配并显示对应的组件 */}
      <Routes>
        {/* Route 定义一条路由规则 */}
        {/* path="/" 表示当用户访问根路径时 */}
        {/* element={...} 表示要显示的组件内容 */}
        <Route path="/" element={
          <div className="app">
            {/* 标题 */}
            <h1>我的待办事项</h1>
            {/* 渲染 AddTodo 组件，把 addTodo 函数作为 onProp 传给它 */}
            {/* 子组件通过调用 onAdd(props名) 来通知父组件"我要添加待办" */}
            <AddTodo onAdd={addTodo} />
            {/* 渲染 TodoList 组件，把 todos 数组和 deleteTodo 函数传给它 */}
            <TodoList todos={todos} onDelete={deleteTodo} />
          </div>
        } />

        {/* 当用户访问 /about 路径时，显示 About 组件 */}
        <Route path="/about" element={<About />} />
      </Routes>

    </BrowserRouter>
  );
}

// export default 表示导出这个组件
// 其他文件（比如 main.jsx）可以通过 import App from './App' 来使用它
export default App;
