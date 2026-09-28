# cockpit_mini —— 仿数字座舱测试项目

[![tests](https://github.com/Xzt6666/cockpit_mini/actions/workflows/test.yml/badge.svg)](https://github.com/Xzt6666/cockpit_mini/actions/workflows/test.yml)

用 pytest 给一个**假的车机系统**写自动化测试。

不需要真车、台架或 HIL 设备：车速、挡位这些车辆信号，以及语音助手、
蓝牙模块，全部是内存里的模拟实现。所以整个测试套件在任何一台电脑上
都能确定性地跑完，两秒钟出结果。

## 这个项目做了什么

- **写了 75 条自动化测试用例**，覆盖 7 个功能模块，全部通过
- **用 fixture 分层管理测试环境**：session 级共享"贵"的资源，函数级保证
  每条用例都从干净状态开始，从根上消除"用例互相影响导致的偶发失败"
- **用参数化表格逐条钉死边界值**，例如视频锁定的 4.9 / 5 / 120 km/h
- **自己实现了 DBC 文件解析器和 CAN 报文编解码器**——汽车总线上跑的
  就是 8 个字节的裸数据，这个模块负责把"车速 50 km/h"和字节互相翻译
- **用内存 Mock 替代真实硬件**：域控制器、中控屏、语音助手、蓝牙模块，
  每个都带显式状态机和只追加的事件日志
- **接了 GitHub Actions**：每次提交自动在 Python 3.10 / 3.11 / 3.12 / 3.13
  上各跑一遍完整测试，并把结构化报告存档

## 快速开始

```bash
pip install -r requirements.txt
pytest -v
```

唯一的运行时依赖是 `pytest`，其余全是标准库。

## 项目结构

```
cockpit_mini/
├── pytest.ini                    # marker 注册表 + 默认选项
├── conftest.py                   # 分层 fixture + 结构化报告钩子
├── rules.py                      # 业务规则（纯函数，不依赖任何 Mock）
├── cockpit_mock.py               # 假硬件：域控制器 / 中控屏 / 语音 / 蓝牙
├── dbc_parser.py                 # 解析 .dbc 文件（总线的"数据字典"）
├── can_bus.py                    # CAN 报文编解码 + 模拟总线
├── dbc/
│   └── cockpit.dbc               # 报文与信号定义
└── tests/
    ├── test_hmi.py               # 行车时锁视频、首页小组件
    ├── test_voice.py             # 唤醒词边界、指令门控
    ├── test_navigation.py        # ETA 计算、非法输入
    ├── test_speedgearwarning.py  # 超速提醒、挡位互锁、倒车影像
    ├── test_bluetooth.py         # 配对 / 连接状态机、异常断开
    ├── test_dbc_parser.py        # DBC 语法、位布局、缩放、取值表
    └── test_can_bus.py           # 位打包、字节序、端到端链路
```

## 分层设计

代码按"改动原因"分成四层，改一处不会牵连别处：

| 层 | 文件 | 职责 | 为什么这样分 |
|---|---|---|---|
| 规则层 | `rules.py` | 纯输入 → 输出 | 不碰 Mock、不做 I/O，所以可以被极简单地测试 |
| 机制层 | `cockpit_mock.py` | 假硬件 | 状态机 + 只追加的事件日志 |
| 数据层 | `dbc_parser.py` / `can_bus.py` | 总线的编解码 | 位级可验证，和业务逻辑完全解耦 |
| 验证层 | `tests/` | 断言 | 参数化表格精确探测阈值边界 |

```bash
pytest -v                     # 全量
pytest -m smoke -v            # 只跑冒烟用例（19 条）
pytest -m speedgearwarning    # 单个业务模块
pytest -m "voice and smoke"   # marker 组合切片
pytest -m can -v              # CAN 编解码（20 条）
pytest -m dbc -v              # DBC 解析（12 条）
pytest --collect-only -q      # 干跑：只列出用例不执行
```

## 测试覆盖了什么

| 模块 | 用例数 | 测的东西 | 举一条具体用例 |
|---|---|---|---|
| HMI | 7 | 行车时视频锁定、首页小组件可见性、页面关闭 | 车速正好 5 km/h 时必须锁定视频 |
| 语音 | 9 | 唤醒词大小写 / 空格 / 中文 / 标点边界 | `"Hi Nomi!"` 多了个感叹号就**不该**唤醒 |
| 导航 | 6 | ETA 计算 + 非法输入（0 速度、负距离） | 速度为 0 必须报错，不能返回无穷大 |
| 动力告警 | 14 | 超速阈值、挡位互锁、倒车影像、拒绝事件 | 车还在动时挂 P 必须被拒绝**并留下证据** |
| 蓝牙 | 7 | 配对 → 连接 → 断开、异常断开 | 手机走出范围后配对关系要保留 |
| DBC 解析 | 12 | 语法、位布局、缩放、取值表、坏输入 | 遇到不支持的大端信号必须报错而非算错 |
| CAN 编解码 | 20 | 位打包、字节序、取值表、端到端 | 断言具体的十六进制字节，而不只是往返一致 |

### 为什么边界值要单独测

需求写的是"车速达到 **5 km/h** 就锁视频"，对应到代码是 `<` 还是 `<=`
很容易写错。只测 0 和 100 这两种情况，两种写法都能通过。
所以测试表里是这么写的：

```
0     → 允许        （停着）
4.9   → 允许        （差一点点）
5     → 锁定        ← 阈值本身，专门测它
120   → 锁定        （高速）
```

`4.9` 和 `5` 这两行才是真正有价值的用例。

## DBC 和 CAN 是什么

**CAN** 是汽车里的总线协议，车上几十个控制器就靠它互相通信。
一条 CAN 报文长这样：一个编号（表示"这是什么消息"）+ 最多 8 个字节。

**问题是**：光看 8 个字节的裸数据，谁也读不懂。

```
f4 01 03 00 00 00 00 00     ← 这 8 个字节是什么意思？
```

**DBC 就是这份数据字典**。它用纯文本描述每个字节里的哪几位是什么信号：

```
BO_ 256 VehicleDynamics: 8 DCU                 报文 ID 256，8 字节，由 DCU 发出
 SG_ VehicleSpeed : 0|16@1+ (0.1,0) [0|250]    第 0 位起占 16 位，系数 0.1
 SG_ GearPosition : 16|4@1+ (1,0) [0|7]        第 16 位起占 4 位
```

`(0.1, 0)` 是**缩放**：原始值 × 0.1 + 0 = 物理值。于是有了 DBC 之后：

```
原始值 500  →  500 × 0.1  =  50.0  →  就是 50 km/h
```

**本项目做的事情**，就是把这两个方向都实现出来：

```
        encode                                    decode
{"VehicleSpeed": 50.0}  ────────→  f401030000000000  ────────→  {"VehicleSpeed": 50.0}
                        ←────────                     ←────────
```

具体拆开看 `f40103...` 是怎么来的：

```
50 km/h ÷ 0.1 = 500      ← 按 DBC 的系数反算，得到"原始值"
500 = 0x01F4             ← 写成十六进制
小端 = 低位字节在前       ← 所以是 f4 01，不是 01 f4
D 挡的原始值 = 3          ← 查 DBC 里的取值表，3 就叫 "D"
```

最终字节：`f4 01 03 00 00 00 00 00`

这些字节不是凭空造的，参考数据库 `dbc/cockpit.dbc` 就是真实工具导出的格式。

## 建议的阅读顺序

1. `rules.py` —— 最短，全是纯函数，先建立"业务规则"的直觉
2. `tests/test_hmi.py` —— 最简单的测试长什么样
3. `conftest.py` —— fixture 为什么要分层（这是面试高频问题）
4. `cockpit_mock.py` —— 假硬件是怎么搭起来的
5. `dbc/cockpit.dbc` → `dbc_parser.py` → `can_bus.py` —— 总线这条链路
6. `tests/test_can_bus.py` —— 看位打包是怎么被验证的

## 持续集成

`.github/workflows/test.yml` 在每次 push 到 `main` 和每个 PR 上自动执行：

* **版本矩阵**：Python 3.10 / 3.11 / 3.12 / 3.13 各跑一遍完整测试集，
  任一版本失败不影响其余版本出结果（`fail-fast: false`），
  这样版本相关的回归会精确暴露在具体版本上
* **报告回流**：`conftest.py` 产出的结构化报告会写进该次运行的 Job Summary，
  并作为 artifact 保留。上传步骤用的是 `if: always()`——测试失败时报告
  才最该被看到，不能因为失败就丢掉
* 页面顶部那个徽章，代表的是 `main` 分支在**一台全新 Linux 机器**上的
  真实结果，不是本地环境

## 结构化报告

`conftest.py` 里的钩子会逐条收集用例结果，运行结束时往 `reports/` 写两份文件：

* `reports/test_report.md` —— 人看的汇总表（用例、结果、耗时、失败原因）
* `reports/test_report.json` —— 机器可读，可接看板或 Allure 这类下游工具

## 三个值得深聊的设计取舍

这一节不是功能说明，而是三个"**为什么这么做**"的问题。每一条在代码里都有
对应位置，可以直接打开对照着讲。

### 一、fixture 为什么分两层

一句话：**贵的资源用宽作用域，脏的状态用窄作用域。**

`cockpit_env` 是 session 级的——整个测试运行只创建一次座舱控制器，因为创建它
成本高，没必要每条用例都重建。而 `vehicle_state` 是函数级的，每条用例都拿到一份
重新 `reset()` 过的车辆状态：

```python
@pytest.fixture(scope="session")      # session 级：整个运行共用一个
def cockpit_env():
    cockpit = MockCockpit()
    cockpit.power_on()
    yield cockpit

@pytest.fixture                          # 函数级：每条用例一份干净的
def vehicle_state(cockpit_env):
    cockpit_env.reset()
    cockpit_env.set_signal("vehicle_speed", 0)
    cockpit_env.set_signal("gear", "P")
    return cockpit_env
```

这样分的好处是**用例之间不可能互相污染**。反过来，如果所有状态都靠 session 级
共享，上一个用例把车速设成 100，下一个用例就会莫名其妙地失败——"单独跑能过、
一起跑就挂"这类偶发失败最难查，而分层之后它从根上不会发生。

### 二、为什么"编码再解码"的往返测试不算数

一个很自然的想法是：把数据编码成字节，再解码回来，看结果是否和输入一样。
问题是——**如果编码和解码错得一模一样，往返测试照样会通过。**

举个具体的例子：小端和大端写反了，编码时按大端写、解码时也按大端读，
一来一回结果完全一致，但在真车上就是错的。所以 `test_can_bus.py` 断言的是
**具体的字节**：

```python
data = encode_message(message, {"VehicleSpeed": 50.0, "GearPosition": "D"})
assert data == bytes.fromhex("f401030000000000")   # 手工按 DBC 推算出来的答案
```

`f4 01` 是这么来的：50 ÷ 0.1 = 500 = `0x01F4`，小端所以低位字节在前。
同时还会反过来测一次——**手写这串字节**，完全不借助 encoder 去解码：

```python
decoded = decode_message(database.message(256), bytes.fromhex("f401030000000000"))
assert decoded["VehicleSpeed"] == pytest.approx(50.0)
```

两个方向都对着同一个"标准答案"，编码器和解码器就不可能一起错。

### 三、为什么拒绝一个操作之后，还要检查事件日志

挡位互锁的规则是"车还在动就不能挂 P 挡"，所以测试里当然要断言返回值是 `False`。
但只断言这个是不够的——**"明确拒绝"和"静默失败"在返回值上长得一模一样**。

所以每次换挡都会往只追加的事件日志里记一笔：

```python
allowed, reason = can_shift_gear(target_gear, self.speed_kmh())
if allowed:
    self.set_signal("gear", target_gear)
self.log_event(f"gear_shift:{target_gear}:{'ok' if allowed else 'rejected'}")
```

测试于是可以进一步断言"日志里确实留下了一条被拒绝的记录"：

```python
assert vehicle_state.set_gear("P") is False                     # 返回值说"没成功"
assert vehicle_state.gear() == "D"                              # 挡位确实没变
assert vehicle_state.event_count("gear_shift:P:rejected") == 1  # 而且是被拒绝的
```

最后那条断言才真正证明"系统识别出了非法操作并明确拒绝"，而不只是"它没执行"。
如果哪天代码被改成直接把这段逻辑删掉，返回值仍然是 `False`，但日志断言会立刻失败。

## 注意

* 只支持**小端（Intel）字节序**。大端（Motorola）信号的位布局是"锯齿轮廓"，
  跨字节时要跳到下一个字节的最高位，理解成本高且本项目用不到，
  因此遇到 `@0` 直接报错——而不是悄悄算错。
* 不支持 CAN 多路复用信号（`M` / `m0`），不支持解析 `CM_` 注释和属性语句。
* 各阈值（5 km/h 锁视频、120 km/h 超速）是"系统需求规格"的替身。
* 同一时刻只支持一路蓝牙连接（简化的车机模型）。
* 唤醒词匹配忽略大小写和空格，但对标点敏感——相近短语绝不能唤醒助手。

## Roadmap

* [√] 用 DBC 定义的 CAN 报文驱动信号，替代直接传字典
* [√] GitHub Actions：pytest + 多版本矩阵 + 报告产物上传
* [ ] 在相同接口背后，把 `MockCockpit` 换成 socket / 串口适配器
* [ ] 集成 Allure / JUnit XML，用于 CI 看板
