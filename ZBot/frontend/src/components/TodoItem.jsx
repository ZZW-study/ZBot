// ============================================
// TodoItem.jsx —— 单个待办项组件
// ============================================
// 这个组件负责：
//   1. 显示单个待办的文字
//   2. 显示一个"删除"按钮
//   3. 根据待办是否完成，显示不同的样式

// 导入 React 核心库
import React from 'react';

// ============================================
// TodoItem 组件定义
// ============================================
// { todo, onDelete } 从 props 中解构出两个属性：
//   - todo：单个待办对象，包含 { id, text, completed }
//   - onDelete：删除待办的函数
function TodoItem({ todo, onDelete }) {

  // 渲染一个列表项 <li>
  return (
    // className 使用了模板字符串（反引号 ``）来动态拼接 CSS 类名
    // 语法：`固定文字 ${JavaScript表达式} 固定文字`
    // todo.completed ? 'completed' : '' 是三元表达式：
    //   - 如果 todo.completed 为 true，返回 'completed'
    //   - 如果 todo.completed 为 false，返回 ''（空字符串）
    // 所以如果待办已完成，会加上 'completed' 类名，显示删除线样式
    <li className={`todo-item ${todo.completed ? 'completed' : ''}`}>

      {/* 显示待办的文字内容 */}
      {/* {todo.text} 把 todo 对象的 text 属性显示在页面上 */}
      <span className="todo-text">{todo.text}</span>

      {/* 删除按钮 */}
      {/* onClick 是点击事件，点击时执行一个箭头函数 */}
      {/* () => onDelete(todo.id) 的意思是：调用 onDelete 函数，并传入当前待办的 id */}
      {/* 父组件（App）的 deleteTodo 函数会被执行，从状态中移除这个待办 */}
      <button
        className="delete-button"
        onClick={() => onDelete(todo.id)}
      >
        删除
      </button>

    </li>
  );
}

// 导出组件
export default TodoItem;
