// ============================================
// AddTodo.jsx —— 添加待办的表单组件
// ============================================
// 这个组件负责：
//   1. 显示一个输入框和一个"添加"按钮
//   2. 用户输入文字后，点击按钮提交
//   3. 通知父组件"有新待办要添加"

// 从 react 库中导入 useState 钩子
// 因为这个组件需要管理输入框的内容（一个会变化的数据）
import React, { useState } from 'react';

// ============================================
// AddTodo 组件定义
// ============================================
// { onAdd } 是"解构赋值"，从 props 对象中取出 onAdd 属性
// onAdd 是父组件（App）传过来的一个函数，用于添加待办
function AddTodo({ onAdd }) {

  // ---- 状态定义 ----

  // 创建输入框的状态：
  //   - inputValue：输入框当前的文字内容
  //   - setInputValue：修改输入框内容的函数
  //   - ''：初始值是空字符串（输入框一开始是空的）
  const [inputValue, setInputValue] = useState('');

  // ---- 事件处理函数 ----

  // handleInputChange：当用户在输入框中打字时触发
  // 参数 e 是"事件对象"，包含了触发事件的所有信息
  const handleInputChange = (e) => {
    // e.target 指向触发事件的 DOM 元素（就是那个 <input>）
    // e.target.value 是输入框当前的内容
    // setInputValue() 更新状态，让 inputValue 等于输入框的内容
    // 这样 React 就知道要重新渲染组件，显示最新的输入内容
    setInputValue(e.target.value);
  };

  // handleSubmit：当用户点击"添加"按钮或按回车键时触发
  const handleSubmit = (e) => {
    // preventDefault() 阻止表单的默认行为
    // 表单默认行为是提交后刷新页面，但我们不想刷新（单页应用）
    e.preventDefault();

    // trim() 去除字符串前后的空格
    // 比如 "  买牛奶  " 会变成 "买牛奶"
    const trimmedValue = inputValue.trim();

    // 只有输入内容不为空时才添加
    // 空字符串在 JavaScript 中是"假值"（falsy），if('') 会跳过
    if (trimmedValue) {
      // 调用父组件传过来的 onAdd 函数
      // 把用户输入的文字作为参数传给父组件
      // 父组件的 addTodo 函数会被执行，从而添加新待办
      onAdd(trimmedValue);

      // 清空输入框，让用户可以继续添加下一个待办
      setInputValue('');
    }
  };

  // ---- 渲染 JSX ----

  // form 是 HTML 表单标签，onSubmit 是表单提交事件
  // 当用户点击按钮或按回车时，会触发 handleSubmit 函数
  return (
    <form className="add-todo-form" onSubmit={handleSubmit}>

      {/* input 是输入框 */}
      {/* type="text" 表示这是一个文本输入框 */}
      {/* value={inputValue} 让输入框显示的内容等于状态变量 inputValue */}
      {/* （这是"受控组件"模式：React 控制输入框的值） */}
      {/* onChange={handleInputChange} 当输入框内容变化时，调用 handleInputChange */}
      {/* placeholder 是输入框为空时显示的提示文字 */}
      {/* className 是 CSS 类名，用于样式控制 */}
      <input
        type="text"
        value={inputValue}
        onChange={handleInputChange}
        placeholder="输入新待办..."
        className="todo-input"
      />

      {/* 提交按钮 */}
      {/* type="submit" 表示点击它会触发表单的 onSubmit 事件 */}
      <button type="submit" className="add-button">
        添加
      </button>

    </form>
  );
}

// 导出组件，让其他文件可以导入使用
export default AddTodo;
