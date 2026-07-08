# C++ 智能指针完全指南

> **版本**: C++11 / C++14 / C++17 / C++20
> **头文件**: `<memory>`

---

## 目录

1. [概述](#1-概述)
2. [为什么需要智能指针](#2-为什么需要智能指针)
3. [`std::unique_ptr`](#3-stdunique_ptr)
4. [`std::shared_ptr`](#4-stdshared_ptr)
5. [`std::weak_ptr`](#5-stdweak_ptr)
6. [工厂函数：`std::make_unique` 与 `std::make_shared`](#6-工厂函数stdmake_unique-与-stdmake_shared)
7. [自定义删除器](#7-自定义删除器)
8. [已弃用的 `std::auto_ptr`](#8-已弃用的-stdauto_ptr)
9. [智能指针的比较](#9-智能指针的比较)
10. [最佳实践与常见陷阱](#10-最佳实践与常见陷阱)
11. [性能考量](#11-性能考量)
12. [参考资源](#12-参考资源)

---

## 1. 概述

**智能指针**（Smart Pointer）是 C++ 标准库中提供的 RAII（资源获取即初始化）类模板，用于自动管理动态分配的内存。它们包装原始指针，在适当的时机自动释放所管理的对象，从而**避免内存泄漏**、**悬空指针**和**重复释放**等问题。

| 智能指针 | 所有权模型 | 引用计数 | 引入标准 |
|----------|-----------|---------|---------|
| `std::unique_ptr` | 独占所有权 | 无 | C++11 |
| `std::shared_ptr` | 共享所有权 | 有（原子操作） | C++11 |
| `std::weak_ptr` | 弱引用（不控制生命周期） | 有（不增加计数） | C++11 |
| `std::auto_ptr`（已弃用） | 伪独占所有权 | 无 | C++98（C++17 移除） |

---

## 2. 为什么需要智能指针

### 2.1 原始指针的问题

```cpp
void foo() {
    int* p = new int(42);
    // ... 如果在到达 delete 之前抛出异常
    if (some_condition) {
        throw std::runtime_error("oops");
        // p 永远不会被释放 → 内存泄漏！
    }
    delete p;  // 可能永远不会执行
}
```

### 2.2 智能指针的解决方案

```cpp
#include <memory>

void foo() {
    std::unique_ptr<int> p = std::make_unique<int>(42);
    // ... 如果抛出异常
    if (some_condition) {
        throw std::runtime_error("oops");
        // p 的析构函数会自动调用 → 安全释放！
    }
    // 离开作用域时自动释放
}
```

### 2.3 核心优势

- **自动内存管理**：离开作用域时自动释放资源
- **异常安全**：即使抛出异常也能正确释放
- **明确的所有权语义**：代码意图更清晰
- **零开销抽象**：相比原始指针，`unique_ptr` 几乎没有额外开销

---

## 3. `std::unique_ptr`

### 3.1 基本概念

`std::unique_ptr` 表示对动态分配对象的**独占所有权**。它**不可复制**，但可以**移动**。当 `unique_ptr` 被销毁时，它所拥有的对象也会被销毁。

### 3.2 基本用法

```cpp
#include <memory>
#include <iostream>

// 创建 unique_ptr
std::unique_ptr<int> p1 = std::make_unique<int>(42);
std::unique_ptr<int> p2(new int(100));  // 不推荐，但合法

// 访问管理的对象
*p1 = 10;
std::cout << *p1 << std::endl;  // 10

// 获取原始指针（不转移所有权）
int* raw = p1.get();

// 释放所有权（返回原始指针，unique_ptr 变为空）
int* released = p1.release();  // p1 变为 nullptr
delete released;

// 重置（销毁当前对象，并可选择接管新对象）
p2.reset(new int(200));  // 销毁原对象，管理新对象
p2.reset();              // 销毁对象，变为空
```

### 3.3 独占所有权（不可复制，只能移动）

```cpp
std::unique_ptr<int> p1 = std::make_unique<int>(1);

// ❌ 错误：unique_ptr 不可复制
// std::unique_ptr<int> p2 = p1;

// ✅ 正确：所有权转移（移动语义）
std::unique_ptr<int> p2 = std::move(p1);
// 此时 p1 为 nullptr，p2 拥有对象

// ✅ 从函数返回 unique_ptr（移动语义自动应用）
auto createPtr() -> std::unique_ptr<int> {
    return std::make_unique<int>(42);
}

auto p3 = createPtr();  // 所有权从函数转移到 p3
```

### 3.4 自定义删除器

```cpp
// 删除器可以是函数指针、lambda 或函数对象
auto file_deleter = [](FILE* f) {
    if (f) {
        fclose(f);
        std::cout << "File closed.\n";
    }
};

std::unique_ptr<FILE, decltype(file_deleter)> file_ptr(
    fopen("test.txt", "w"), file_deleter);

// 使用 lambda 作为删除器（推荐）
std::unique_ptr<int, void(*)(int*)> p(
    new int(42), [](int* p) {
        std::cout << "Custom delete\n";
        delete p;
    });
```

### 3.5 数组特化

```cpp
// unique_ptr 支持数组管理
std::unique_ptr<int[]> arr = std::make_unique<int[]>(10);
arr[0] = 1;
arr[1] = 2;
// 自动调用 delete[]
```

> **注意**：`shared_ptr` 也支持数组（C++17），但需要使用自定义删除器。

### 3.6 在容器中使用

```cpp
std::vector<std::unique_ptr<Widget>> widgets;
widgets.push_back(std::make_unique<Widget>());
widgets.push_back(std::make_unique<Widget>());

// 遍历
for (const auto& wp : widgets) {
    wp->doSomething();
}

// 转移所有权的常用模式
std::unique_ptr<Widget> createAndTransfer() {
    auto w = std::make_unique<Widget>();
    w->initialize();
    return w;  // 移动返回
}
```

---

## 4. `std::shared_ptr`

### 4.1 基本概念

`std::shared_ptr` 实现**共享所有权**模型。多个 `shared_ptr` 可以指向同一个对象，对象在**最后一个** `shared_ptr` 销毁时被释放。它使用**引用计数**来追踪所有者数量。

### 4.2 基本用法

```cpp
#include <memory>
#include <iostream>

// 创建 shared_ptr - 推荐使用 make_shared
auto p1 = std::make_shared<int>(42);
{
    auto p2 = p1;  // ✅ 可以复制，引用计数 +1
    auto p3 = p1;  // 引用计数 +1
    std::cout << p1.use_count();  // 输出 3
    // p2, p3 离开作用域，引用计数 -2
}
// 此时引用计数为 1
// p1 离开作用域，引用计数变为 0，对象被销毁
```

### 4.3 引用计数细节

```cpp
auto p1 = std::make_shared<int>(10);

std::cout << p1.use_count();  // 1
std::cout << p1.unique();     // C++17 前判断是否独占，C++17 已弃用

{
    auto p2 = p1;
    std::cout << p1.use_count();  // 2
    std::cout << p2.use_count();  // 2
}

std::cout << p1.use_count();  // 1
```

### 4.4 控制块

`shared_ptr` 的管理结构包含两个关键部分：

1. **指向对象的指针**
2. **控制块**（Control Block），包含：
   - 引用计数（对象被多少个 `shared_ptr` 引用）
   - 弱引用计数（多少个 `weak_ptr` 引用此对象）
   - 删除器（Deleter）
   - 分配器（Allocator）

```
┌──────────────┐       ┌──────────────────────┐
│  shared_ptr   │──────→│     Control Block    │
├──────────────┤       ├──────────────────────┤
│  T* ptr      │       │  Reference Count: 2  │
│  Control* cb │       │  Weak Count: 1       │
└──────────────┘       │  Deleter / Alloc     │
                       └──────────┬───────────┘
                                  │
                          ┌───────▼───────┐
                          │   T Object    │
                          └───────────────┘
```

### 4.5 循环引用问题

`shared_ptr` 最经典的陷阱是**循环引用**，导致内存泄漏：

```cpp
struct Node {
    std::shared_ptr<Node> next;
    ~Node() { std::cout << "Node destroyed\n"; }
};

void leak() {
    auto a = std::make_shared<Node>();
    auto b = std::make_shared<Node>();
    a->next = b;
    b->next = a;  // 循环引用！a 和 b 永远不会被释放
    // 离开作用域时两个 Node 都不会被销毁！
}
```

**解决方案**：在可能形成环的情况下，使用 `weak_ptr` 打破循环。

---

## 5. `std::weak_ptr`

### 5.1 基本概念

`std::weak_ptr` 是一种**不控制对象生命周期**的智能指针。它指向一个由 `shared_ptr` 管理的对象，但**不增加引用计数**。`weak_ptr` 主要用于**打破循环引用**和**观察者模式**。

### 5.2 基本用法

```cpp
auto sp = std::make_shared<int>(42);
std::weak_ptr<int> wp = sp;  // 从 shared_ptr 创建 weak_ptr

// use_count() 与原 shared_ptr 相同（不会增加计数）
std::cout << wp.use_count();  // 1

// 访问对象前必须先锁（lock）为 shared_ptr
if (auto locked = wp.lock()) {
    std::cout << *locked;  // 42
} else {
    std::cout << "对象已被释放";
}

// 检查对象是否已被销毁
if (wp.expired()) {
    std::cout << "对象已不存在";
}
```

### 5.3 打破循环引用

```cpp
struct Node {
    std::shared_ptr<Node> next;
    // 使用 weak_ptr 避免循环引用
    std::weak_ptr<Node> prev;
    
    ~Node() { std::cout << "Node destroyed\n"; }
};

void noLeak() {
    auto a = std::make_shared<Node>();
    auto b = std::make_shared<Node>();
    a->next = b;
    b->prev = a;  // weak_ptr，不影响引用计数
    
    // 离开作用域时两个 Node 都能正确释放
    // 输出：
    // Node destroyed
    // Node destroyed
}
```

### 5.4 常见应用场景

**缓存系统**：

```cpp
class Cache {
    std::map<std::string, std::weak_ptr<ExpensiveResource>> cache_;
    
public:
    std::shared_ptr<ExpensiveResource> get(const std::string& key) {
        auto it = cache_.find(key);
        if (it != cache_.end()) {
            if (auto resource = it->second.lock()) {
                return resource;  // 缓存命中
            } else {
                cache_.erase(it);  // 清除已失效的条目
            }
        }
        auto resource = std::make_shared<ExpensiveResource>(key);
        cache_[key] = resource;
        return resource;
    }
};
```

**观察者模式**：

```cpp
class Observer {
public:
    virtual ~Observer() = default;
    virtual void update() = 0;
};

class Subject {
    std::vector<std::weak_ptr<Observer>> observers_;
    
public:
    void attach(std::shared_ptr<Observer> obs) {
        observers_.push_back(obs);
    }
    
    void notify() {
        for (auto& wptr : observers_) {
            if (auto obs = wptr.lock()) {
                obs->update();
            }
        }
    }
};
```

---

## 6. 工厂函数：`std::make_unique` 与 `std::make_shared`

### 6.1 `std::make_unique`（C++14）

C++11 中没有 `std::make_unique`，只有 `std::make_shared`。`std::make_unique` 在 C++14 中加入标准库。

```cpp
// C++11 中需要自己实现
template<typename T, typename... Args>
std::unique_ptr<T> make_unique(Args&&... args) {
    return std::unique_ptr<T>(new T(std::forward<Args>(args)...));
}

// C++14 及以后
auto ptr = std::make_unique<Widget>(arg1, arg2);
```

### 6.2 `std::make_shared`（C++11）

```cpp
// 一次分配对象和控制块，更高效
auto ptr = std::make_shared<Widget>(arg1, arg2);
```

### 6.3 为什么优先使用 make 函数

| 原因 | 说明 |
|------|------|
| **异常安全** | 避免因参数求值顺序导致的潜在泄漏 |
| **效率更高** | `make_shared` 一次分配对象+控制块 |
| **代码简洁** | 避免显式 `new`，减少冗余 |
| **无重复类型名** | 类型名只写一次 |

```cpp
// ❌ 不推荐：异常不安全
process(std::shared_ptr<Widget>(new Widget), get_priority());

// ✅ 推荐：异常安全
process(std::make_shared<Widget>(), get_priority());

// ❌ 不推荐：类型名重复
std::unique_ptr<Widget> p(new Widget);

// ✅ 推荐：类型名只写一次
auto p = std::make_unique<Widget>();
```

### 6.4 何时不使用 make 函数

- **需要自定义删除器时**
- **使用 `std::shared_ptr` 但想单独控制对象和控制块时**
- **使用 `std::shared_ptr` 且对象非常大，但可能只有 `weak_ptr` 存活时**

```cpp
// make_shared 的缺点：对象和控制块在同一块内存中
// 当所有 shared_ptr 销毁但仍有 weak_ptr 存活时，
// 对象和控制块都不能释放

// 改用直接构造 shared_ptr：
std::shared_ptr<HugeObject> sp(new HugeObject());
// 此时即使仍有 weak_ptr，对象本身也可以释放
```

---

## 7. 自定义删除器

### 7.1 基本用法

```cpp
// unique_ptr 自定义删除器（删除器类型是模板参数的一部分）
auto deleter = [](int* p) {
    std::cout << "删除 int\n";
    delete p;
};

std::unique_ptr<int, decltype(deleter)> ptr(new int(42), deleter);

// shared_ptr 自定义删除器（删除器类型不是模板参数）
std::shared_ptr<int> ptr(new int(42), [](int* p) {
    std::cout << "删除 int\n";
    delete p;
});
```

### 7.2 实际应用：管理非内存资源

```cpp
// 管理文件描述符
struct FileCloser {
    void operator()(FILE* f) const {
        if (f) {
            fclose(f);
            std::cout << "文件已关闭\n";
        }
    }
};
using FilePtr = std::unique_ptr<FILE, FileCloser>;

FilePtr openFile(const char* name, const char* mode) {
    return FilePtr(fopen(name, mode));
}

// 管理 socket
struct SocketCloser {
    void operator()(int* sock) const {
        if (sock) {
            close(*sock);
            delete sock;
        }
    }
};
using SocketPtr = std::unique_ptr<int, SocketCloser>;
```

### 7.3 删除器与类型擦除

```cpp
// shared_ptr 的删除器是类型擦除的（std::function 类型擦除）
// 这意味着不同的删除器不会影响 shared_ptr 的类型

std::shared_ptr<int> sp1(new int(1), [](int* p) { delete p; });
std::shared_ptr<int> sp2(new int(2), std::default_delete<int>());
// sp1 和 sp2 类型相同，可以放入同一个容器

// 而 unique_ptr 的删除器是类型的一部分
std::unique_ptr<int, decltype([](int* p) { delete p; })> up1;
std::unique_ptr<int> up2;  // 默认删除器
// 两个类型不同
```

---

## 8. 已弃用的 `std::auto_ptr`

### 8.1 为什么被弃用

`std::auto_ptr`（C++98）是智能指针的早期尝试，由于其设计缺陷，在 C++11 中被弃用，在 C++17 中被正式移除。

**主要问题**：

1. **隐式的所有权转移**：复制 `auto_ptr` 会静默地转移所有权
2. **无法用于容器**：复制操作会破坏原始指针
3. **数组支持不佳**：使用 `delete` 而非 `delete[]`

```cpp
std::auto_ptr<int> ap1(new int(42));
std::auto_ptr<int> ap2 = ap1;      // 所有权转移！ap1 变为 nullptr
// 这种隐式行为非常危险

// 不能用于标准容器
std::vector<std::auto_ptr<int>> vec;  // ❌ 编译错误或运行时错误

// 解决方法：在 C++11 及以上使用 std::unique_ptr 替代
std::unique_ptr<int> up1(new int(42));
std::unique_ptr<int> up2 = std::move(up1);  // 显式移动，语义清晰
```

### 8.2 迁移指南

| C++98/03 代码 | C++11/14/17 替代 |
|---------------|------------------|
| `std::auto_ptr<T>` | `std::unique_ptr<T>` |
| `ap.release()` | `up.release()`（保持） |
| `ap.reset(p)` | `up.reset(p)`（保持） |
| `auto_ptr` 传参 | `unique_ptr` 传参（按值/按右值引用） |
| `auto_ptr` 返回值 | `unique_ptr` 返回值（推荐） |

---

## 9. 智能指针的比较

### 9.1 特性对比表

| 特性 | `unique_ptr` | `shared_ptr` | `weak_ptr` |
|------|:------------:|:------------:|:----------:|
| 所有权模型 | 独占 | 共享 | 不拥有 |
| 大小 | 1 个指针 | 2 个指针 | 2 个指针 |
| 引用计数 | 无 | 有（原子操作） | 弱引用计数 |
| 复制操作 | ❌ | ✅（引用计数 +1） | ✅（弱引用计数 +1） |
| 移动操作 | ✅（所有权转移） | ✅（引用计数不变） | ✅ |
| 线程安全（引用计数） | N/A | ✅（原子操作） | ✅ |
| 自定义删除器 | 是（类型的一部分） | 是（类型擦除） | N/A |
| 数组支持 | ✅（`unique_ptr<T[]>`） | ⚠️（C++17 需要自定义删除器） | ❌ |
| 性能开销 | 几乎为零 | 分配控制块 + 原子操作 | 同 shared_ptr 控制块 |

### 9.2 开销对比

```cpp
// unique_ptr（约等于原始指针的开销）
// 大小：8 字节（64 位系统）
std::unique_ptr<int> up;

// shared_ptr（额外控制块）
// 大小：16 字节（64 位系统）
// 内存分配：一次（make_shared）或两次（直接构造）
std::shared_ptr<int> sp;

// weak_ptr（依赖 shared_ptr 的控制块）
// 大小：16 字节（64 位系统）
std::weak_ptr<int> wp;
```

### 9.3 类型转换

```cpp
std::unique_ptr<Base> up = std::make_unique<Derived>();

// unique_ptr 类型转换
std::unique_ptr<Derived> up_derived = std::make_unique<Derived>();
std::unique_ptr<Base> up_base = std::move(up_derived);  // 隐式转换

// shared_ptr 类型转换
auto sp = std::make_shared<Derived>();
std::shared_ptr<Base> sp_base = sp;  // 隐式转换（指向子类）

// static_pointer_cast, dynamic_pointer_cast, const_pointer_cast
auto sp_base2 = std::static_pointer_cast<Base>(sp);
auto sp_derived2 = std::dynamic_pointer_cast<Derived>(sp_base2);
```

---

## 10. 最佳实践与常见陷阱

### 10.1 黄金法则

| 场景 | 推荐做法 |
|------|---------|
| 独占对象所有权 | 使用 `std::unique_ptr` |
| 共享对象所有权 | 使用 `std::shared_ptr` |
| 观察者/打破循环引用 | 使用 `std::weak_ptr` |
| 创建智能指针 | 优先使用 `std::make_unique` / `std::make_shared` |
| 传递所有权 | 按值传递 `unique_ptr` |
| 共享所有权但不修改 | 传 `const shared_ptr&` 或原始引用/指针 |

### 10.2 常见陷阱

#### 陷阱 1：get() 返回的原始指针

```cpp
auto sp = std::make_shared<int>(42);
int* raw = sp.get();

// ❌ 危险：raw 可能在 sp 销毁后继续使用
delete raw;  // ❌ 双重释放！

// ❌ 不要从 get() 创建新的智能指针
std::shared_ptr<int> sp2(raw);  // 双重释放！
```

#### 陷阱 2：将 shared_ptr 传递给 this

```cpp
struct Widget {
    void process() {
        // ❌ 危险：如果外部没有 shared_ptr 管理 this
        // auto sp = std::shared_ptr<Widget>(this);  // 可能导致双重释放
    }
};

// ✅ 正确做法：继承 std::enable_shared_from_this
struct Widget : std::enable_shared_from_this<Widget> {
    void process() {
        auto sp = shared_from_this();  // 安全获取 shared_ptr
    }
};

// 使用 shared_from_this 的前提：对象必须被 shared_ptr 管理
auto widget = std::make_shared<Widget>();
widget->process();  // ✅
```

#### 陷阱 3：shared_ptr 的循环引用

已在 §5.3 中详细讨论，使用 `weak_ptr` 解决。

#### 陷阱 4：在容器中使用 shared_ptr 的代价

```cpp
// 频繁访问容器的 shared_ptr 元素有原子操作开销
class Container {
    std::vector<std::shared_ptr<LargeObject>> items_;
    
    int getTotal() const {
        int sum = 0;
        for (auto& sp : items_) {
            sum += sp->getValue();  // 每次访问都有原子操作开销
            // ✅ 如果只是读取，考虑解引用后缓存
        }
        return sum;
    }
};
```

#### 陷阱 5：unique_ptr 的删除器类型

```cpp
// ❌ 不同的 lambda 有不同的类型
auto d1 = [](int* p) { delete p; };
auto d2 = [](int* p) { delete p; };

std::unique_ptr<int, decltype(d1)> up1(new int(1), d1);
std::unique_ptr<int, decltype(d2)> up2(new int(2), d2);

// up1 和 up2 类型不同，不能放在同一容器中
// ✅ 如果类型擦除是必要的，使用 shared_ptr 或 std::function
std::function<void(int*)> deleter = [](int* p) { delete p; };
```

### 10.3 线程安全性

```cpp
// shared_ptr 的引用计数操作是原子级的，所以是线程安全的
// 但指向的对象本身不是线程安全的（需要外部同步）

auto sp = std::make_shared<int>(0);

// 线程 A：
sp = std::make_shared<int>(1);  // 引用计数原子操作，安全

// 线程 B：
auto sp2 = sp;  // 引用计数原子操作，安全

// ❌ 但同时访问对象需要同步
// 线程 A：
*sp = 42;  // 不加锁的话，与线程 B 的 *sp 冲突

// ✅ 使用 mutex 保护
std::mutex mtx;
// 线程 A：
{
    std::lock_guard<std::mutex> lock(mtx);
    *sp = 42;
}
```

### 10.4 所有权传递指南

```cpp
// 1. 传递所有权（按值传递 unique_ptr）
void takeOwnership(std::unique_ptr<Widget> w) {
    w->doWork();
    // 离开时自动销毁
}

auto w = std::make_unique<Widget>();
takeOwnership(std::move(w));  // 显式转移所有权

// 2. 借用/观察（传递原始指针或引用）
void observe(Widget* w) {
    if (w) w->doWork();
}

void observeRef(const Widget& w) {
    w.doWork();
}

// 3. 共享所有权（按值传递 shared_ptr）
void shareOwnership(std::shared_ptr<Widget> w) {
    // 引用计数 +1
    w->doWork();
    // 离开时引用计数 -1
}

// 4. 如果不需要共享所有权，传递 const shared_ptr&
void maybeShare(const std::shared_ptr<Widget>& w) {
    // 不增加引用计数，仅读取
    w->doWork();
}
```

---

## 11. 性能考量

### 11.1 内存开销

```cpp
// 64 位系统下的典型大小：

sizeof(std::unique_ptr<int>);       // 8 字节（等同于原始指针）
sizeof(std::shared_ptr<int>);       // 16 字节（两个指针）
sizeof(std::weak_ptr<int>);         // 16 字节（两个指针）

// shared_ptr 控制块额外开销（每个对象一次）
// - 引用计数：8 字节
// - 弱引用计数：8 字节
// - 删除器/分配器：取决于类型擦除情况
```

### 11.2 性能对比

| 操作 | `unique_ptr` | `shared_ptr` | `weak_ptr` |
|------|:------------:|:------------:|:----------:|
| 构造（make） | 一次分配 | 一次分配 | 无分配 |
| 构造（从指针） | 无额外分配 | 分配控制块 | 无分配 |
| 复制 | ❌ | 原子递增 | 原子递增 |
| 移动 | 交换指针 | 交换指针 | 交换指针 |
| 析构 | 删除对象 | 原子递减+可能删除 | 原子递减 |
| 解引用 | 与原始指针相同 | 与原始指针相同 | lock() 有原子开销 |

### 11.3 何时避免智能指针

- **性能关键的代码路径**，例如每秒调用数百万次的热点函数
- **嵌入式系统**，内存极度受限
- **与 C 接口互操作**，需要传递原始指针的场景
- **实现低层数据结构**（如自定义内存池）

在这些场景下，仍然可以手动管理资源，但要确保正确性。

---

## 12. 参考资源

### 12.1 标准库参考

- [std::unique_ptr - cppreference.com](https://en.cppreference.com/w/cpp/memory/unique_ptr)
- [std::shared_ptr - cppreference.com](https://en.cppreference.com/w/cpp/memory/shared_ptr)
- [std::weak_ptr - cppreference.com](https://en.cppreference.com/w/cpp/memory/weak_ptr)
- [std::make_unique - cppreference.com](https://en.cppreference.com/w/cpp/memory/unique_ptr/make_unique)
- [std::make_shared - cppreference.com](https://en.cppreference.com/w/cpp/memory/shared_ptr/make_shared)
- [std::enable_shared_from_this](https://en.cppreference.com/w/cpp/memory/enable_shared_from_this)

### 12.2 推荐阅读

- **《Effective Modern C++》** - Scott Meyers，第 4 章（智能指针）
- **《C++ Primer》（第 5 版）** - 第 12 章（动态内存）
- **《C++ 标准库》（第 2 版）** - Nicolai M. Josuttis
- **CppCon 演讲**: "Smart Pointers: What, Why, How?" - Arthur O'Dwyer

### 12.3 代码示例汇总

完整的可运行示例可在 [Compiler Explorer](https://godbolt.org/) 中测试。

---

> **总结**：在现代 C++ 中，应**默认使用 `std::unique_ptr`**，当需要共享所有权时使用 `std::shared_ptr`，当需要打破循环引用或观察但不拥有对象时使用 `std::weak_ptr`。**避免使用原始指针**来拥有动态内存资源。优先使用 `std::make_unique` 和 `std::make_shared` 而不是直接 `new`。

---

*最后更新：2025 年 | 适用于 C++11 及更高版本*
