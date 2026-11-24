/**
 * 模型侧工具名必须保持 ASCII（OpenAI 函数名约束、官方 JSONGenerativeUI
 * 的 present / promptUser 键）。对话面用中文展示，不改调用标识。
 */
export const TOOL_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  present: "呈现",
  promptUser: "征求用户",
  presentArtifact: "展示产物",
  host_result_card: "结果卡片",
  assistant_plan_ready: "发布方案",
  write_todos: "更新待办",
  ls: "列出文件",
  read_file: "读取文件",
  write_file: "写入文件",
  edit_file: "编辑文件",
  glob: "查找文件",
  grep: "搜索内容",
  execute: "执行命令",
  task: "子任务",
  delete: "删除文件",
};

export function toolDisplayName(toolName: string): string | undefined {
  return TOOL_DISPLAY_NAMES[toolName];
}

export function toolGroupCountLabel(count: number): string {
  return `${count} 次工具调用`;
}
