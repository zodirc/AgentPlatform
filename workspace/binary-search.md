# 二分查找（Binary Search）理解文档

## 1. 什么是二分查找

**二分查找**（Binary Search）是一种在**有序数组**中查找特定元素的高效算法。它的核心思想是 **"分而治之"** —— 每次将搜索范围缩小一半，从而以对数级别的时间复杂度完成查找。

> 生活中的类比：猜数字游戏。如果让你在 1~100 中猜一个数，每次告诉你"大了"或"小了"，你会先猜 50，然后根据反馈不断折半，而不是从 1 开始逐个猜。

---

## 2. 算法原理

### 2.1 前提条件

- 数据结构必须是**数组**（支持随机访问）
- 数组必须是**有序的**（升序或降序）

### 2.2 执行流程

1. 确定搜索区间 `[left, right]`（初始为整个数组）
2. 计算中间位置 `mid = left + (right - left) / 2`
3. 比较 `arr[mid]` 与目标值 `target`：
   - **相等** → 找到目标，返回下标
   - **目标值更大** → 目标在右半区间，`left = mid + 1`
   - **目标值更小** → 目标在左半区间，`right = mid - 1`
4. 重复步骤 2~3，直到 `left > right`（未找到）

### 2.3 动画示意

```
数组: [1, 3, 5, 7, 9, 11, 13, 15]  查找 target = 7

第 1 步: left=0, right=7, mid=3
  [1, 3, 5, 7, 9, 11, 13, 15]
            ↑mid
  arr[3]=7 == target ✅ → 返回 3
```

```
数组: [1, 3, 5, 7, 9, 11, 13, 15]  查找 target = 6

第 1 步: left=0, right=7, mid=3
  [1, 3, 5, 7, 9, 11, 13, 15]
            ↑mid
  arr[3]=7 > target → right=2

第 2 步: left=0, right=2, mid=1
  [1, 3, 5, 7, 9, 11, 13, 15]
       ↑mid
  arr[1]=3 < target → left=2

第 3 步: left=2, right=2, mid=2
  [1, 3, 5, 7, 9, 11, 13, 15]
          ↑mid
  arr[2]=5 < target → left=3

第 4 步: left=3 > right=2 → 退出，返回 -1
```

---

## 3. 代码实现

### 3.1 标准版（闭区间 `[left, right]`）

```python
def binary_search(arr: list[int], target: int) -> int:
    left, right = 0, len(arr) - 1

    while left <= right:
        mid = left + (right - left) // 2  # 防止溢出

        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1

    return -1
```

### 3.2 左闭右开版 `[left, right)`

```python
def binary_search_left_open(arr: list[int], target: int) -> int:
    left, right = 0, len(arr)  # right 初始为 len(arr)

    while left < right:        # 左闭右开时 left < right
        mid = left + (right - left) // 2

        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid        # 右开区间，right = mid

    return -1
```

### 3.3 递归版

```python
def binary_search_recursive(arr: list[int], target: int,
                            left: int, right: int) -> int:
    if left > right:
        return -1

    mid = left + (right - left) // 2

    if arr[mid] == target:
        return mid
    elif arr[mid] < target:
        return binary_search_recursive(arr, target, mid + 1, right)
    else:
        return binary_search_recursive(arr, target, left, mid - 1)
```

---

## 4. 复杂度分析

| 维度 | 复杂度 | 说明 |
|------|--------|------|
| **时间复杂度** | **O(log n)** | 每次将搜索范围缩小一半，log₂(n) 次即可完成 |
| **空间复杂度（迭代）** | **O(1)** | 只使用了常数个变量 |
| **空间复杂度（递归）** | **O(log n)** | 递归调用栈的深度 |

### 为什么是 O(log n)？

- 长度为 n 的数组
- 第 1 次比较后，搜索范围缩小到 n/2
- 第 2 次比较后，n/4
- 第 k 次比较后，n/2ᵏ
- 当 n/2ᵏ = 1 时，k = log₂(n)

---

## 5. 常见变体

### 5.1 查找第一个等于 target 的位置（下界）

```python
def find_first(arr: list[int], target: int) -> int:
    left, right = 0, len(arr) - 1
    result = -1

    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] == target:
            result = mid
            right = mid - 1   # 继续在左半区间找第一个
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1

    return result
```

### 5.2 查找最后一个等于 target 的位置（上界）

```python
def find_last(arr: list[int], target: int) -> int:
    left, right = 0, len(arr) - 1
    result = -1

    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] == target:
            result = mid
            left = mid + 1    # 继续在右半区间找最后一个
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1

    return result
```

### 5.3 查找第一个大于等于 target 的位置

```python
def find_first_ge(arr: list[int], target: int) -> int:
    left, right = 0, len(arr) - 1

    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] >= target:
            if mid == 0 or arr[mid - 1] < target:
                return mid
            right = mid - 1
        else:
            left = mid + 1

    return -1  # 所有元素都小于 target
```

### 5.4 查找最后一个小于等于 target 的位置

```python
def find_last_le(arr: list[int], target: int) -> int:
    left, right = 0, len(arr) - 1

    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] <= target:
            if mid == len(arr) - 1 or arr[mid + 1] > target:
                return mid
            left = mid + 1
        else:
            right = mid - 1

    return -1  # 所有元素都大于 target
```

---

## 6. 二分查找的典型应用场景

### 6.1 在有序数组中查找元素
最基本的应用，标准二分直接解决。

### 6.2 求平方根 / 数值近似
```python
def my_sqrt(x: int) -> int:
    """计算 x 的平方根的整数部分"""
    if x == 0 or x == 1:
        return x
    left, right = 1, x
    while left <= right:
        mid = left + (right - left) // 2
        if mid * mid == x:
            return mid
        elif mid * mid < x:
            left = mid + 1
        else:
            right = mid - 1
    return right  # 返回向下取整的结果
```

### 6.3 寻找旋转排序数组的最小值
```python
def find_min_in_rotated(nums: list[int]) -> int:
    """在旋转排序数组中找最小值，如 [4,5,6,7,0,1,2] → 0"""
    left, right = 0, len(nums) - 1
    while left < right:
        mid = left + (right - left) // 2
        if nums[mid] > nums[right]:
            left = mid + 1
        else:
            right = mid
    return nums[left]
```

### 6.4 答案二分（值域二分）
当问题的答案具有**单调性**时，可以在答案的值域上做二分搜索。

例题：给定一个数组，求最大值最小化问题（如"分割数组的最大值"）。

### 6.5 峰值查找（局部有序）
```python
def find_peak(arr: list[int]) -> int:
    """在数组中找到一个峰值（比两边大）"""
    left, right = 0, len(arr) - 1
    while left < right:
        mid = left + (right - left) // 2
        if arr[mid] > arr[mid + 1]:
            right = mid      # 峰值在左侧
        else:
            left = mid + 1   # 峰值在右侧
    return left
```

---

## 7. 易错点与注意事项

### 7.1 区间边界处理（最常见的坑）

| 写法 | 循环条件 | `left` 更新 | `right` 更新 | 适用场景 |
|------|----------|-------------|--------------|----------|
| 闭区间 `[l, r]` | `l <= r` | `l = m + 1` | `r = m - 1` | 标准查找 |
| 左闭右开 `[l, r)` | `l < r` | `l = m + 1` | `r = m` | 变体查找 |

> **口诀**："闭区间进到等于，开区间进到等于"。意思是在闭区间中，循环要到 `<=`；左闭右开时，更新右边界直接用 `r = m`。

### 7.2 中点计算溢出问题

❌ 错误写法：
```python
mid = (left + right) // 2
```
当 `left` 和 `right` 都很大时（接近 `2³¹-1`），`left + right` 可能**整数溢出**。

✅ 正确写法：
```python
mid = left + (right - left) // 2
```

在 Python 中不会溢出，但这是良好的工程习惯。

### 7.3 死循环陷阱

当区间长度为 2 时，`(left + right) // 2` 取的是靠左的中点。如果更新逻辑是 `left = mid`（而非 `left = mid + 1`），可能陷入死循环。

**自检方法**：测试数组长度为 2 时，算法是否能正确退出。

### 7.4 数组为空或长度为 1

始终在代码开头处理边界情况：
```python
if not arr:
    return -1
```

---

## 8. 算法理解要点总结

| 要点 | 说明 |
|------|------|
| **单调性** | 二分查找的本质是利用**单调性**（有序）来快速缩小范围 |
| **分治思想** | 每次丢弃一半不可能的解，只需处理另一半 |
| **时间复杂度** | O(log n) 是指数级效率——1000 个元素只需 10 次比较 |
| **适用性局限** | 只适用于**随机访问**结构（数组），不适用于链表 |
| **变体核心** | 变体的关键在于**区间收缩策略**（`mid ± 1` 还是 `mid`） |
| **直觉理解** | 翻字典：你不从第一页开始翻，而是翻到中间，根据字母前后决定翻左还是翻右 |

### 一句话总结

> **二分查找 = 有序 + 折半 + O(log n)。它是一个优雅的"猜数字"过程，每次排除一半的错误答案。**

---

## 9. LeetCode 经典练习推荐

| 题号 | 题目 | 难度 | 核心考点 |
|------|------|------|----------|
| 704 | 二分查找 | ⭐ | 标准二分模板 |
| 34 | 在排序数组中查找元素的第一个和最后一个位置 | ⭐⭐ | 上下界变体 |
| 35 | 搜索插入位置 | ⭐ | 第一个大于等于的位置 |
| 153 | 寻找旋转排序数组中的最小值 | ⭐⭐ | 旋转数组二分 |
| 33 | 搜索旋转排序数组 | ⭐⭐⭐ | 带条件判断的二分 |
| 69 | x 的平方根 | ⭐ | 值域二分 |
| 162 | 寻找峰值 | ⭐⭐ | 局部有序二分 |
| 875 | 爱吃香蕉的珂珂 | ⭐⭐⭐ | 答案二分（最小值问题） |
| 410 | 分割数组的最大值 | ⭐⭐⭐⭐ | 答案二分 + 贪心 |

---

*文档版本：v1.0*
*最后更新：2025年*
