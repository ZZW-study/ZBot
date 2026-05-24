// ============================================
// TodoList.jsx —— 待办列表组件
// ============================================
// 这个组件负责：
//   1. 接收父组件传来的 todos 数组
//   2. 遍历数组，为每个待办渲染一个 TodoItem 组件

// 导入 React 核心库
import React from 'react';

// 导入 TodoItem 组件（单个待办项）
import TodoItem from './TodoItem';

// ============================================
// TodoList 组件定义
// ============================================
// { todos, onDelete } 从 props 中解构出两个属性：
//   - todos：待办事项数组（从父组件 App 传入）
//   - onDelete：删除待办的函数（从父组件 App 传入）
function TodoList({ todos, onDelete }) {

  // 渲染一个无序列表 <ul>，里面包含所有待办项
  return (
    <ul className="todo-list">

      {/* {} 花括号在 JSX 中表示"这里要写 JavaScript 表达式" */}
      {/* todos.map() 遍历数组，把每个 todo 对象转换成一个 TodoItem 组件 */}
      {/* map() 会返回一个新数组，数组的每个元素都是一个 JSX 组件 */}
      {/* 类似于 Python 的列表推导式：[f(todo) for todo in todos] */}
      {todos.map(todo => (
        // key 是 React 要求的特殊属性，用于高效更新列表
        // 每个 key 必须是唯一的，我们用 todo.id
        // todo 是把整个 todo 对象传给 TodoItem
        // onDelete 是把删除函数也传给 TodoItem，让它能触发删除
        <TodoItem
          key={todo.id}
          todo={todo}
          onDelete={onDelete}
        />
      ))}

    </ul>
  );
}

// 导出组件
export default TodoList;
