from __future__ import annotations
import sys
from collections import deque


class TreeNode:
    def __init__(self, val: int = 0, left: TreeNode | None = None, right: TreeNode | None =None):
        self.val = val
        self.left = left
        self.right = right


def build_tree(tree_arr: list[str]):
    # 空树
    if not tree_arr or tree_arr[0] == "null":
        return None

    root = TreeNode(int(tree_arr[0]))
    q = deque([root])
    index = 1

    while q and index < len(tree_arr):
        node = q.popleft()

        if index < len(tree_arr) and tree_arr[index] != "null":
            node.left = TreeNode(val = int(tree_arr[index]))
            q.append(node.left)
        index += 1
        
        if index < len(tree_arr) and tree_arr[index] != "null":
            node.right = TreeNode(val = int(tree_arr[index]))
            q.append(node.right)
        index += 1
        
    return root

class Solution:
    @staticmethod
    def max_deep(root: TreeNode | None) ->int:
        if not root:
            return 0
        
        left_max: int = Solution.max_deep(root.left)
        right_max: int = Solution.max_deep(root.right)

        return max(left_max,right_max) + 1

def main():
    input_list: list[str] = sys.stdin.readline().strip().split()
    tree_root_node: TreeNode | None = build_tree(input_list)

    result = Solution().max_deep(tree_root_node)
    
    if not result:
        print(0)
    else:
        print(result)

if __name__ == "__main__":
    main()
