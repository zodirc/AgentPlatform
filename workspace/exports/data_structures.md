# C/C++ 数据结构完全指南

> **版本**: C89 / C99 / C++11 / C++14 / C++17 / C++20
> **适用平台**: Linux / macOS / Windows

---

## 目录

1. [概述](#1-概述)
2. [数组（Array）](#2-数组array)
3. [链表（Linked List）](#3-链表linked-list)
4. [栈（Stack）](#4-栈stack)
5. [队列（Queue）](#5-队列queue)
6. [树（Tree）](#6-树tree)
7. [二叉搜索树（BST）](#7-二叉搜索树bst)
8. [平衡二叉树（AVL）](#8-平衡二叉树avl)
9. [堆（Heap）](#9-堆heap)
10. [哈希表（Hash Table）](#10-哈希表hash-table)
11. [图（Graph）](#11-图graph)
12. [C++ STL 容器速查](#12-c-stl-容器速查)
13. [时间复杂度对比](#13-时间复杂度对比)
14. [最佳实践与常见陷阱](#14-最佳实践与常见陷阱)
15. [参考资源](#15-参考资源)

---

## 1. 概述

**数据结构**（Data Structure）是计算机中组织和存储数据的方式，它定义了数据之间的关系以及可对其执行的操作。选择合适的数据结构可以显著影响算法的效率和程序的性能。

### 1.1 数据结构的分类

```
                    ┌─────────────────────────────────────┐
                    │           数据结构                  │
                    └─────────────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
       线性结构                             非线性结构
    ┌────┼────┐                        ┌──────┼──────┐
    │    │    │                        │      │      │
  数组 链表  栈/队列                 树     图     堆
```

| 分类 | 特点 | 典型结构 |
|------|------|----------|
| **线性结构** | 元素之间存在一对一关系 | 数组、链表、栈、队列 |
| **树形结构** | 元素之间存在一对多关系 | 二叉树、BST、AVL、堆 |
| **图形结构** | 元素之间存在多对多关系 | 有向图、无向图 |

### 1.2 逻辑结构与物理结构

- **逻辑结构**：数据元素之间的逻辑关系（集合、线性、树形、图形）
- **物理结构**：数据在计算机内存中的存储方式（顺序存储、链式存储）

---

## 2. 数组（Array）

### 2.1 C 语言数组

数组是最基础的数据结构，元素在内存中**连续存储**，支持 **O(1)** 随机访问。

```c
// 声明与初始化
int arr[5] = {1, 2, 3, 4, 5};
int arr2[]  = {1, 2, 3};       // 自动推断大小

// 多维数组
int matrix[3][4] = {
    {1, 2, 3, 4},
    {5, 6, 7, 8},
    {9, 10, 11, 12}
};

// 动态数组（堆分配）
int* dyn_arr = (int*)malloc(10 * sizeof(int));
free(dyn_arr);                  // 必须手动释放

// 变长数组（C99 起）
void func(int n) {
    int vla[n];                 // 运行时确定大小
}
```

### 2.2 C++ 数组

```cpp
// 静态数组
int arr[5] = {1, 2, 3, 4, 5};

// std::array（C++11，定长，栈分配）
#include <array>
std::array<int, 5> a = {1, 2, 3, 4, 5};
a.size();                       // 5
a.front();                      // 1
a.back();                       // 5

// std::vector（动态数组，堆分配）
#include <vector>
std::vector<int> v = {1, 2, 3, 4, 5};
v.push_back(6);                 // 追加
v.pop_back();                   // 删除末尾
v.size();                       // 当前元素个数
v.capacity();                   // 当前容量
```

### 2.3 数组性能

| 操作 | 时间复杂度 | 说明 |
|------|-----------|------|
| 随机访问 | **O(1)** | 通过索引直接访问 |
| 插入（末尾） | **O(1)** | 需容量充足（vector 均摊 O(1)） |
| 插入（开头/中间） | **O(n)** | 需要移动元素 |
| 删除（末尾） | **O(1)** | |
| 删除（开头/中间） | **O(n)** | 需要移动元素 |
| 搜索（无序） | **O(n)** | 线性扫描 |
| 搜索（有序，二分） | **O(log n)** | 前提是已排序 |

---

## 3. 链表（Linked List）

### 3.1 单向链表（Singly Linked List）

每个节点包含数据和指向下一个节点的指针。

```c
typedef struct Node {
    int data;
    struct Node* next;
} Node;

// 创建节点
Node* create_node(int data) {
    Node* node = (Node*)malloc(sizeof(Node));
    node->data = data;
    node->next = NULL;
    return node;
}

// 头部插入
void push_front(Node** head, int data) {
    Node* new_node = create_node(data);
    new_node->next = *head;
    *head = new_node;
}

// 遍历
void print_list(Node* head) {
    for (Node* cur = head; cur; cur = cur->next) {
        printf("%d -> ", cur->data);
    }
    printf("NULL\n");
}

// 释放
void free_list(Node* head) {
    Node* cur = head;
    while (cur) {
        Node* temp = cur;
        cur = cur->next;
        free(temp);
    }
}
```

### 3.2 双向链表（Doubly Linked List）

```c
typedef struct DNode {
    int data;
    struct DNode* prev;
    struct DNode* next;
} DNode;

// 头部插入（双向）
void push_front(DNode** head, int data) {
    DNode* node = (DNode*)malloc(sizeof(DNode));
    node->data = data;
    node->prev = NULL;
    node->next = *head;
    if (*head) (*head)->prev = node;
    *head = node;
}
```

### 3.3 C++ 标准链表

```cpp
#include <forward_list>  // 单向链表（C++11）
#include <list>          // 双向链表

std::forward_list<int> fl = {1, 2, 3};
fl.push_front(0);

std::list<int> lst = {1, 2, 3, 4, 5};
lst.push_front(0);
lst.push_back(6);
lst.pop_front();
lst.pop_back();
```

### 3.4 链表性能

| 操作 | 单向链表 | 双向链表 | 说明 |
|------|---------|---------|------|
| 头部插入 | **O(1)** | **O(1)** | |
| 尾部插入 | O(n) | **O(1)**（持有尾指针） | |
| 头部删除 | **O(1)** | **O(1)** | |
| 尾部删除 | O(n) | **O(1)** | |
| 按值查找 | O(n) | O(n) | 需遍历 |
| 按索引访问 | O(n) | O(n) | 不支持随机访问 |
| 在给定节点后插入 | **O(1)** | **O(1)** | 需先持有节点指针 |

---

## 4. 栈（Stack）

### 4.1 栈的定义

**栈**（Stack）是 **LIFO**（Last In, First Out，后进先出）的线性结构。只允许在栈顶进行插入（push）和删除（pop）操作。

```
    栈顶 ← push(3) →  [3]
    栈顶 ← push(5) →  [3, 5]
    栈顶 ← pop()   →  [3]      返回 5
    栈顶 ← top()   →  [3]      返回 3（不删除）
```

### 4.2 C 语言实现（基于数组）

```c
typedef struct {
    int* data;
    int top;
    int capacity;
} Stack;

Stack* create_stack(int capacity) {
    Stack* s = (Stack*)malloc(sizeof(Stack));
    s->data = (int*)malloc(capacity * sizeof(int));
    s->top = -1;
    s->capacity = capacity;
    return s;
}

void push(Stack* s, int val) {
    if (s->top < s->capacity - 1)
        s->data[++(s->top)] = val;
}

int pop(Stack* s) {
    if (s->top >= 0)
        return s->data[(s->top)--];
    return -1;  // 栈空
}

int top(Stack* s) {
    return (s->top >= 0) ? s->data[s->top] : -1;
}

int is_empty(Stack* s) {
    return s->top == -1;
}

void free_stack(Stack* s) {
    free(s->data);
    free(s);
}
```

### 4.3 C++ 实现

```cpp
#include <stack>

std::stack<int> s;
s.push(1);
s.push(2);
s.push(3);
int x = s.top();    // 3
s.pop();            // 删除栈顶
bool empty = s.empty();  // false
size_t size = s.size();  // 2
```

### 4.4 栈的典型应用

- **函数调用栈**：管理函数调用和返回地址
- **表达式求值**：中缀转后缀（逆波兰）、括号匹配
- **深度优先搜索**（DFS）
- **撤销操作**（Undo / Redo）
- **语法分析**（编译器）

---

## 5. 队列（Queue）

### 5.1 队列的定义

**队列**（Queue）是 **FIFO**（First In, First Out，先进先出）的线性结构。从队尾入队（enqueue），从队头出队（dequeue）。

```
  出队方向 →    入队方向 →
  [1, 2, 3, 4, 5]
   ↑            ↑
  front        back
```

### 5.2 循环队列（C 语言）

```c
typedef struct {
    int* data;
    int front, rear;
    int capacity;
} Queue;

Queue* create_queue(int capacity) {
    Queue* q = (Queue*)malloc(sizeof(Queue));
    q->data = (int*)malloc(capacity * sizeof(int));
    q->front = 0;
    q->rear = 0;
    q->capacity = capacity;
    return q;
}

int is_empty(Queue* q) {
    return q->front == q->rear;
}

int is_full(Queue* q) {
    return (q->rear + 1) % q->capacity == q->front;
}

void enqueue(Queue* q, int val) {
    if (!is_full(q)) {
        q->data[q->rear] = val;
        q->rear = (q->rear + 1) % q->capacity;
    }
}

int dequeue(Queue* q) {
    if (is_empty(q)) return -1;
    int val = q->data[q->front];
    q->front = (q->front + 1) % q->capacity;
    return val;
}
```

### 5.3 C++ 实现

```cpp
#include <queue>

std::queue<int> q;
q.push(1);
q.push(2);
q.push(3);
int x = q.front();     // 1
int y = q.back();      // 3
q.pop();               // 删除队头（1）
```

### 5.4 优先队列（Priority Queue）

```cpp
#include <queue>

// 最大堆（默认）
std::priority_queue<int> pq;
pq.push(10);
pq.push(30);
pq.push(20);
pq.top();               // 30

// 最小堆
std::priority_queue<int, std::vector<int>, std::greater<int>> min_pq;
```

### 5.5 队列的典型应用

- **广度优先搜索**（BFS）
- **任务调度**（CPU 调度、线程池）
- **消息队列**（进程间通信）
- **缓冲区**（I/O 缓冲、生产者-消费者）

---

## 6. 树（Tree）

### 6.1 二叉树（Binary Tree）

每个节点最多有两个子节点（左子节点、右子节点）。

```c
typedef struct TreeNode {
    int data;
    struct TreeNode* left;
    struct TreeNode* right;
} TreeNode;

TreeNode* create_node(int data) {
    TreeNode* node = (TreeNode*)malloc(sizeof(TreeNode));
    node->data = data;
    node->left = NULL;
    node->right = NULL;
    return node;
}
```

### 6.2 二叉树的遍历

```c
// 前序遍历（根 → 左 → 右）
void preorder(TreeNode* root) {
    if (!root) return;
    printf("%d ", root->data);
    preorder(root->left);
    preorder(root->right);
}

// 中序遍历（左 → 根 → 右）
void inorder(TreeNode* root) {
    if (!root) return;
    inorder(root->left);
    printf("%d ", root->data);
    inorder(root->right);
}

// 后序遍历（左 → 右 → 根）
void postorder(TreeNode* root) {
    if (!root) return;
    postorder(root->left);
    postorder(root->right);
    printf("%d ", root->data);
}

// 层序遍历（BFS）
void level_order(TreeNode* root) {
    if (!root) return;
    // 使用队列实现
    TreeNode* queue[100];
    int front = 0, rear = 0;
    queue[rear++] = root;
    while (front < rear) {
        TreeNode* cur = queue[front++];
        printf("%d ", cur->data);
        if (cur->left)  queue[rear++] = cur->left;
        if (cur->right) queue[rear++] = cur->right;
    }
}
```

```
        1
       / \
      2   3
     / \   \
    4   5   6

前序: 1 2 4 5 3 6
中序: 4 2 5 1 3 6
后序: 4 5 2 6 3 1
层序: 1 2 3 4 5 6
```

### 6.3 树的应用

- **文件系统目录**
- **HTML / XML DOM 树**
- **编译器 AST（抽象语法树）**
- **数据库索引（B 树、B+ 树）**
- **路由协议**

---

## 7. 二叉搜索树（BST）

### 7.1 定义与性质

**二叉搜索树**（Binary Search Tree, BST）是满足以下性质的二叉树：

1. 左子树所有节点的值 **小于** 根节点
2. 右子树所有节点的值 **大于** 根节点
3. 左右子树也分别是二叉搜索树

```
        8
       / \
      3   10
     / \    \
    1   6    14
       / \   /
      4   7 13
```

### 7.2 基本操作

```c
// 搜索
TreeNode* search(TreeNode* root, int key) {
    if (!root || root->data == key)
        return root;
    if (key < root->data)
        return search(root->left, key);
    return search(root->right, key);
}

// 插入
TreeNode* insert(TreeNode* root, int key) {
    if (!root) return create_node(key);
    if (key < root->data)
        root->left = insert(root->left, key);
    else if (key > root->data)
        root->right = insert(root->right, key);
    return root;  // 相等则不插入
}

// 查找最小值（最左节点）
TreeNode* find_min(TreeNode* root) {
    while (root && root->left)
        root = root->left;
    return root;
}

// 删除
TreeNode* delete_node(TreeNode* root, int key) {
    if (!root) return NULL;
    if (key < root->data)
        root->left = delete_node(root->left, key);
    else if (key > root->data)
        root->right = delete_node(root->right, key);
    else {
        // 情况 1: 叶子节点
        if (!root->left && !root->right) {
            free(root);
            return NULL;
        }
        // 情况 2: 一个子节点
        if (!root->left) {
            TreeNode* temp = root->right;
            free(root);
            return temp;
        }
        if (!root->right) {
            TreeNode* temp = root->left;
            free(root);
            return temp;
        }
        // 情况 3: 两个子节点 → 用右子树最小值替换
        TreeNode* min = find_min(root->right);
        root->data = min->data;
        root->right = delete_node(root->right, min->data);
    }
    return root;
}
```

### 7.3 BST 性能

| 操作 | 平均 | 最坏 |
|------|------|------|
| 搜索 | O(log n) | O(n) |
| 插入 | O(log n) | O(n) |
| 删除 | O(log n) | O(n) |

> **注意**：最坏情况发生在树退化为链表时（如插入有序序列）。平衡树（AVL、红黑树）可保证 O(log n) 的最坏复杂度。

---

## 8. 平衡二叉树（AVL）

### 8.1 定义

**AVL 树**是自平衡的二叉搜索树，每个节点的左右子树高度差不超过 **1**。

- 平衡因子 = 左子树高度 - 右子树高度（取值范围: -1, 0, 1）

### 8.2 旋转操作

```c
typedef struct AVLNode {
    int data;
    struct AVLNode* left;
    struct AVLNode* right;
    int height;     // 以该节点为根的子树高度
} AVLNode;

int height(AVLNode* n) {
    return n ? n->height : 0;
}

int max(int a, int b) { return a > b ? a : b; }

int balance_factor(AVLNode* n) {
    return n ? height(n->left) - height(n->right) : 0;
}

// 右旋（LL 情况）
AVLNode* rotate_right(AVLNode* y) {
    AVLNode* x = y->left;
    AVLNode* T2 = x->right;

    x->right = y;
    y->left = T2;

    y->height = max(height(y->left), height(y->right)) + 1;
    x->height = max(height(x->left), height(x->right)) + 1;

    return x;  // 新根
}

// 左旋（RR 情况）
AVLNode* rotate_left(AVLNode* x) {
    AVLNode* y = x->right;
    AVLNode* T2 = y->left;

    y->left = x;
    x->right = T2;

    x->height = max(height(x->left), height(x->right)) + 1;
    y->height = max(height(y->left), height(y->right)) + 1;

    return y;  // 新根
}

// 插入（带平衡）
AVLNode* avl_insert(AVLNode* root, int key) {
    if (!root) {
        AVLNode* node = (AVLNode*)malloc(sizeof(AVLNode));
        node->data = key;
        node->left = node->right = NULL;
        node->height = 1;
        return node;
    }

    if (key < root->data)
        root->left = avl_insert(root->left, key);
    else if (key > root->data)
        root->right = avl_insert(root->right, key);
    else
        return root;  // 不重复插入

    root->height = max(height(root->left), height(root->right)) + 1;

    int bf = balance_factor(root);

    // LL
    if (bf > 1 && key < root->left->data)
        return rotate_right(root);
    // RR
    if (bf < -1 && key > root->right->data)
        return rotate_left(root);
    // LR
    if (bf > 1 && key > root->left->data) {
        root->left = rotate_left(root->left);
        return rotate_right(root);
    }
    // RL
    if (bf < -1 && key < root->right->data) {
        root->right = rotate_right(root->right);
        return rotate_left(root);
    }

    return root;
}
```

```
四种失衡情况:

1. LL (左左): 在左子树的左子节点插入 → 右旋
       z              y
      / \           / \
     y   T4   →    x   z
    / \           / \ / \
   x  T3         T1 T2 T3 T4
  / \
 T1 T2

2. RR (右右): 在右子树的右子节点插入 → 左旋
   z                y
  / \             / \
 T1  y     →     z   x
    / \         / \ / \
   T2  x       T1 T2 T3 T4
      / \
     T3 T4

3. LR (左右): 在左子树的右子节点插入 → 先左旋再右旋
4. RL (右左): 在右子树的左子节点插入 → 先右旋再左旋
```

### 8.3 AVL vs 红黑树

| 特性 | AVL 树 | 红黑树 |
|------|--------|--------|
| 平衡条件 | 高度差 ≤ 1 | 最长路径 ≤ 2×最短路径 |
| 查找 | **更快**（更严格平衡） | 稍慢 |
| 插入/删除 | 更慢（更多旋转） | **更快**（旋转更少） |
| 应用 | 查找密集型场景（数据库） | 插入/删除密集型（std::map） |

---

## 9. 堆（Heap）

### 9.1 定义

**堆**（Heap）是一种特殊的完全二叉树，用数组实现：

- **最大堆**：每个节点的值 ≥ 其子节点的值（根最大）
- **最小堆**：每个节点的值 ≤ 其子节点的值（根最小）

```
最大堆:          存储（数组）:
    100          [100, 19, 36, 17, 3, 25, 1, 2, 7]
   /   \
  19    36
 / \   / \
17  3 25  1
/ \
2  7
```

### 9.2 C 语言实现（最小堆）

```c
typedef struct {
    int* data;
    int size;
    int capacity;
} MinHeap;

MinHeap* create_heap(int capacity) {
    MinHeap* h = (MinHeap*)malloc(sizeof(MinHeap));
    h->data = (int*)malloc(capacity * sizeof(int));
    h->size = 0;
    h->capacity = capacity;
    return h;
}

int parent(int i) { return (i - 1) / 2; }
int left(int i)   { return 2 * i + 1; }
int right(int i)  { return 2 * i + 2; }

void swap(int* a, int* b) { int t = *a; *a = *b; *b = t; }

// 插入：向上调整
void push(MinHeap* h, int val) {
    if (h->size >= h->capacity) return;
    int i = h->size++;
    h->data[i] = val;
    while (i > 0 && h->data[i] < h->data[parent(i)]) {
        swap(&h->data[i], &h->data[parent(i)]);
        i = parent(i);
    }
}

// 向下调整
void heapify(MinHeap* h, int i) {
    int smallest = i;
    int l = left(i), r = right(i);
    if (l < h->size && h->data[l] < h->data[smallest])
        smallest = l;
    if (r < h->size && h->data[r] < h->data[smallest])
        smallest = r;
    if (smallest != i) {
        swap(&h->data[i], &h->data[smallest]);
        heapify(h, smallest);
    }
}

// 删除最小值
int pop(MinHeap* h) {
    if (h->size == 0) return -1;
    int min_val = h->data[0];
    h->data[0] = h->data[--(h->size)];
    heapify(h, 0);
    return min_val;
}
```

### 9.3 C++ 实现

```cpp
#include <algorithm>  // std::make_heap, push_heap, pop_heap
#include <vector>

std::vector<int> v = {3, 1, 4, 1, 5, 9};
std::make_heap(v.begin(), v.end());       // 建堆（默认最大堆）
std::push_heap(v.begin(), v.end());       // 插入后调整
std::pop_heap(v.begin(), v.end());        // 将堆顶移到末尾
v.pop_back();                             // 真正删除

// 最小堆
std::make_heap(v.begin(), v.end(), std::greater<int>{});
```

### 9.4 堆的应用

- **优先队列**
- **堆排序**（O(n log n)）
- **Top K 问题**
- **中位数维护**（双堆技巧）
- **Dijkstra 最短路径算法**

---

## 10. 哈希表（Hash Table）

### 10.1 定义

**哈希表**（Hash Table / Hash Map）通过**哈希函数**将键映射到数组索引，实现平均 **O(1)** 的查找、插入和删除。

```
键 → 哈希函数 → 哈希值 → 索引（模运算）
                     ↓
              ┌──────────────┐
              │  [0]  [k1, v1]│
              │  [1]  NULL   │
              │  [2]  [k2, v2]│
              │  ...         │
              └──────────────┘
```

### 10.2 冲突解决：链地址法

```c
#define TABLE_SIZE 128

typedef struct Entry {
    char* key;
    int value;
    struct Entry* next;
} Entry;

typedef struct {
    Entry** buckets;
    int size;
} HashMap;

unsigned int hash(const char* key) {
    unsigned int h = 0;
    while (*key)
        h = h * 31 + (unsigned char)(*key++);
    return h;
}

HashMap* create_map() {
    HashMap* map = (HashMap*)malloc(sizeof(HashMap));
    map->buckets = (Entry**)calloc(TABLE_SIZE, sizeof(Entry*));
    map->size = 0;
    return map;
}

void put(HashMap* map, const char* key, int value) {
    int idx = hash(key) % TABLE_SIZE;
    Entry* cur = map->buckets[idx];
    while (cur) {
        if (strcmp(cur->key, key) == 0) {
            cur->value = value;  // 更新
            return;
        }
        cur = cur->next;
    }
    Entry* new_entry = (Entry*)malloc(sizeof(Entry));
    new_entry->key = strdup(key);  // 注意: 需要释放
    new_entry->value = value;
    new_entry->next = map->buckets[idx];
    map->buckets[idx] = new_entry;
    map->size++;
}

int* get(HashMap* map, const char* key) {
    int idx = hash(key) % TABLE_SIZE;
    Entry* cur = map->buckets[idx];
    while (cur) {
        if (strcmp(cur->key, key) == 0)
            return &cur->value;
        cur = cur->next;
    }
    return NULL;  // 未找到
}
```

### 10.3 C++ 哈希表

```cpp
#include <unordered_map>
#include <unordered_set>

// 键值对
std::unordered_map<std::string, int> umap;
umap["apple"] = 5;
umap["banana"] = 3;
int x = umap["apple"];      // 5
auto it = umap.find("pear");
if (it != umap.end()) { /* 找到 */ }

// 集合
std::unordered_set<int> uset = {1, 2, 3, 4, 5};
uset.insert(6);
uset.erase(3);
```

### 10.4 哈希表性能

| 操作 | 平均 | 最坏 |
|------|------|------|
| 查找 | **O(1)** | O(n) |
| 插入 | **O(1)** | O(n) |
| 删除 | **O(1)** | O(n) |

> **最坏情况**：哈希冲突严重（所有键映射到同一桶）。可通过选择好的哈希函数、扩容（rehash）来避免。

---

## 11. 图（Graph）

### 11.1 图的表示

```
图 G = (V, E)
  V: 顶点集合
  E: 边集合

无向图:          有向图:
  1 ─── 2        1 ──→ 2
  │     │        │     ↓
  3 ─── 4        3 ←── 4
```

### 11.2 邻接矩阵

```c
typedef struct {
    int** matrix;   // n × n
    int n;          // 顶点数
} GraphMatrix;

GraphMatrix* create_graph(int n) {
    GraphMatrix* g = (GraphMatrix*)malloc(sizeof(GraphMatrix));
    g->n = n;
    g->matrix = (int**)calloc(n, sizeof(int*));
    for (int i = 0; i < n; i++)
        g->matrix[i] = (int*)calloc(n, sizeof(int));
    return g;
}

void add_edge(GraphMatrix* g, int u, int v) {
    g->matrix[u][v] = 1;
    g->matrix[v][u] = 1;  // 无向图
}

// 检查边: O(1)
// 空间: O(V²)
```

### 11.3 邻接表

```c
typedef struct AdjNode {
    int vertex;
    struct AdjNode* next;
} AdjNode;

typedef struct {
    AdjNode** heads;  // 每个顶点一个链表头
    int n;
} GraphList;

GraphList* create_graph_list(int n) {
    GraphList* g = (GraphList*)malloc(sizeof(GraphList));
    g->n = n;
    g->heads = (AdjNode**)calloc(n, sizeof(AdjNode*));
    return g;
}

void add_edge_list(GraphList* g, int u, int v) {
    AdjNode* node = (AdjNode*)malloc(sizeof(AdjNode));
    node->vertex = v;
    node->next = g->heads[u];
    g->heads[u] = node;
    // 无向图还需添加 v → u
    node = (AdjNode*)malloc(sizeof(AdjNode));
    node->vertex = u;
    node->next = g->heads[v];
    g->heads[v] = node;
}

// 遍历邻居: O(degree(v))
// 空间: O(V + E)
```

### 11.4 图的遍历

```c
// DFS（递归）
void dfs(GraphList* g, int v, int visited[]) {
    visited[v] = 1;
    printf("%d ", v);
    AdjNode* cur = g->heads[v];
    while (cur) {
        if (!visited[cur->vertex])
            dfs(g, cur->vertex, visited);
        cur = cur->next;
    }
}

// BFS（队列）
void bfs(GraphList* g, int start) {
    int visited[100] = {0};
    int queue[100], front = 0, rear = 0;
    visited[start] = 1;
    queue[rear++] = start;
    while (front < rear) {
        int v = queue[front++];
        printf("%d ", v);
        AdjNode* cur = g->heads[v];
        while (cur) {
            if (!visited[cur->vertex]) {
                visited[cur->vertex] = 1;
                queue[rear++] = cur->vertex;
            }
            cur = cur->next;
        }
    }
}
```

### 11.5 图的性能

| 操作 | 邻接矩阵 | 邻接表 |
|------|---------|--------|
| 检查(u,v)是否有边 | **O(1)** | O(degree(u)) |
| 遍历所有邻居 | O(V) | **O(degree(v))** |
| 空间 | O(V²) | **O(V + E)** |
| 适用场景 | 稠密图 | 稀疏图 |

---

## 12. C++ STL 容器速查

| 容器 | 头文件 | 底层结构 | 关键特性 |
|------|--------|---------|---------|
| `std::array` | `<array>` | 静态数组 | 定长，栈分配，C++11 |
| `std::vector` | `<vector>` | 动态数组 | 随机访问，均摊 O(1) 尾部插入 |
| `std::deque` | `<deque>` | 双端队列 | 头部和尾部 O(1) 插入/删除 |
| `std::list` | `<list>` | 双向链表 | 双向遍历，任意位置 O(1) 插入（已知迭代器） |
| `std::forward_list` | `<forward_list>` | 单向链表 | 最小开销，C++11 |
| `std::stack` | `<stack>` | 容器适配器 | LIFO（默认 deque 适配） |
| `std::queue` | `<queue>` | 容器适配器 | FIFO（默认 deque 适配） |
| `std::priority_queue` | `<queue>` | 容器适配器 | 最大堆（默认 vector 适配） |
| `std::set` | `<set>` | 红黑树 | 有序，唯一键 |
| `std::multiset` | `<set>` | 红黑树 | 有序，允许多个相同键 |
| `std::map` | `<map>` | 红黑树 | 有序键值对，O(log n) |
| `std::multimap` | `<map>` | 红黑树 | 有序，允许多个相同键 |
| `std::unordered_set` | `<unordered_set>` | 哈希表 | 无序，O(1) 均摊，C++11 |
| `std::unordered_map` | `<unordered_map>` | 哈希表 | 无序键值对，O(1) 均摊，C++11 |
| `std::bitset` | `<bitset>` | 位数组 | 定长位操作 |
| `std::span` | `<span>` | 视图 | 不拥有所有权的连续序列视图，C++20 |

### 12.1 容器选择指南

```
需要随机访问？
  ├─ 是 → 定长？ std::array    /   变长？ std::vector
  └─ 否 → 需要双向？ std::list  /   单向？ std::forward_list

需要键值存储？
  ├─ 需要有序？
  │    ├─ 唯一键 → std::map / std::set
  │    └─ 允许重复 → std::multimap / std::multiset
  └─ 需要快速（无序）？
       ├─ 唯一键 → std::unordered_map / std::unordered_set
       └─ 允许重复 → std::unordered_multimap / std::unordered_multiset

需要适配器？
  ├─ LIFO → std::stack
  ├─ FIFO → std::queue
  └─ 按优先级 → std::priority_queue
```

---

## 13. 时间复杂度对比

| 数据结构 | 查找 | 插入 | 删除 | 随机访问 | 说明 |
|----------|------|------|------|---------|------|
| 数组（无序） | O(n) | O(n) | O(n) | **O(1)** | |
| 数组（有序） | O(log n) | O(n) | O(n) | **O(1)** | 二分查找 |
| 动态数组（末尾） | O(n) | O(1)* | O(1)* | **O(1)** | *均摊 |
| 单向链表 | O(n) | O(1) | O(1) | O(n) | 给定节点指针 |
| 双向链表 | O(n) | O(1) | O(1) | O(n) | 给定节点指针 |
| 栈 | O(n) | **O(1)** | **O(1)** | - | 仅操作栈顶 |
| 队列 | O(n) | **O(1)** | **O(1)** | - | FIFO |
| BST（平衡） | O(log n) | O(log n) | O(log n) | - | |
| 哈希表 | **O(1)*** | **O(1)*** | **O(1)*** | - | *均摊 |
| 堆 | O(n) | O(log n) | O(log n) | - | 仅移除堆顶 |
| 图（邻接表） | O(V+E) | O(1) | O(E) | - | 取决于具体操作 |

---

## 14. 最佳实践与常见陷阱

### 14.1 通用原则

1. **选择合适的数据结构**
   - 频繁随机访问？→ 数组 / vector
   - 频繁中间插入/删除？→ 链表
   - 键值对快速查找？→ 哈希表
   - 需要有序迭代？→ 平衡树（map / set）

2. **注意空间换时间**
   - 哈希表用额外空间换取 O(1) 查找
   - 缓存计算结果（Memoization）减少重复计算

3. **警惕最坏情况**
   - 哈希表：糟糕的哈希函数导致 O(n)
   - BST：插入有序数据退化到 O(n)

### 14.2 C 语言陷阱

```c
// 1. 忘记释放内存 → 内存泄漏
int* arr = (int*)malloc(N * sizeof(int));
// ... 使用 ...
// 忘记 free(arr);

// 2. 悬空指针
int* p = (int*)malloc(sizeof(int));
free(p);
*p = 42;  // 未定义行为！

// 3. 缓冲区溢出
int buf[5];
for (int i = 0; i <= 5; i++)  // 越界！
    buf[i] = i;

// 4. 结构体自引用忘记 typedef
typedef struct Node {
    int data;
    struct Node* next;  // 必须写 struct Node*
} Node;
```

### 14.3 C++ 陷阱

```cpp
// 1. 迭代器失效
std::vector<int> v = {1, 2, 3, 4, 5};
for (auto it = v.begin(); it != v.end(); ++it) {
    if (*it % 2 == 0)
        v.erase(it);  // 迭代器失效！应该用 erase 返回值
}

// 正确写法:
auto it = v.begin();
while (it != v.end()) {
    if (*it % 2 == 0)
        it = v.erase(it);
    else
        ++it;
}

// 2. map 的 [] 操作会插入默认值
std::map<std::string, int> m;
if (m["nonexistent"] == 0) { ... }  // 注意: 会插入键 "nonexistent"！
// 正确: 使用 m.find("nonexistent")

// 3. unordered_map 需要自定义哈希函数（对自定义类型）
struct Point {
    int x, y;
    bool operator==(const Point&) const = default;
};
struct PointHash {
    size_t operator()(const Point& p) const {
        return std::hash<int>()(p.x) ^ (std::hash<int>()(p.y) << 1);
    }
};
std::unordered_map<Point, int, PointHash> point_map;

// 4. vector<bool> 特化（不是真正的 bool 数组）
std::vector<bool> vb;  // 特化版本，不满足容器要求
// 替代品: std::vector<char> 或 std::bitset
```

### 14.4 性能建议

| 场景 | 建议 |
|------|------|
| 在循环中使用 `reserve` 预分配 vector 空间 | 减少重新分配次数 |
| 小对象用 `std::array` 而非 vector | 避免堆分配 |
| 频繁插入/删除用 list/deque 而非 vector | 避免元素移动 |
| 使用 `emplace_back` 而非 `push_back`（C++11） | 减少临时对象 |
| 优先使用 `std::unique_ptr` 管理动态内存 | RAII 保证安全 |
| 在需要稳定迭代器时选择 list 或 map | vector 的插入/删除会使迭代器失效 |

---

## 15. 参考资源

### 书籍

| 书名 | 作者 | 推荐理由 |
|------|------|----------|
| 《算法导论》（CLRS） | Cormen 等 | 数据结构和算法的权威教材 |
| 《数据结构与算法分析》 | Mark Allen Weiss | C 语言实现，经典教材 |
| 《C++ Primer》（第5版） | Lippman 等 | C++ STL 容器详解 |
| 《Effective C++》 | Scott Meyers | C++ 最佳实践 |

### 在线资源

- **cppreference.com** — C/C++ 标准库参考
- **LeetCode / HackerRank** — 数据结构算法练习
- **Visualgo.net** — 数据结构可视化
- **GeeksforGeeks** — 数据结构教程与代码示例

### C++ 标准演进

| 标准 | 相关容器特性 |
|------|-------------|
| C++98 | `vector`, `list`, `deque`, `map`, `set`, `stack`, `queue` |
| C++11 | `array`, `forward_list`, `unordered_map`, `unordered_set` |
| C++17 | `string_view`, 并行算法 |
| C++20 | `span`, `flat_map` (TS), `flat_set` (TS) |

---

> **总结**：数据结构是程序设计的基石。选择正确的数据结构，往往比优化算法本身更能提升程序性能。理解每种结构的优缺点、时间/空间复杂度以及适用场景，是编写高效、可维护代码的关键。在实际开发中，优先使用 C++ 标准库提供的容器，它们经过了充分的测试和性能优化。
