# cockpit_mini — 仿真数字座舱测试框架

一个基于 pytest 的测试框架，针对**内存中的数字座舱域控制器 Mock** 构建，
用于汽车软件测试的学习与作品集展示。无需实车、台架或 HIL 设备：
车速、挡位等车辆信号、语音输入、蓝牙外设全部为 Mock 实现，
因此所有测试均为确定性、可重复执行的。

> 项目定位：展示座舱软件的**测试工程**能力——分层 fixture、参数化、
> marker 切片、Mock 状态机、结构化报告——而非 HIL/CANoe 方向。

## 架构

```
cockpit_mini/
├── pytest.ini                  # marker 注册表 + 默认选项
├── conftest.py                 # 分层 fixture + 报告钩子
├── cockpit_mock.py             # MockCockpit / HmiPage / 语音 / 蓝牙 Mock
├── rules.py                    # 纯业务规则（策略层）
└── tests/
    ├── test_hmi.py             # 行车视频锁定、桌面小组件
    ├── test_voice.py           # NOMI 唤醒词、指令门控
    ├── test_navigation.py      # ETA 计算、非法输入
    ├── test_speedgearwarning.py# 超速提醒、挡位互锁、倒车影像
    └── test_bluetooth.py       # 配对 / 连接状态机、异常断连
```

### 分层设计

| 层 | 职责 | 核心思想 |
|---|---|---|
| `rules.py` | 纯输入→输出策略 | 无 Mock、无 I/O——可极简单地做单元测试 |
| `cockpit_mock.py` | 机制层 / "硬件"层 | 状态机 + 只追加（append-only）事件日志 |
| `tests/` | 验证层 | 参数化用例表，精确探测阈值边界 |

### Fixture 分层（面试谈资）

* **昂贵的资源用宽作用域**——`cockpit_env`（session 级）每次运行只
  初始化一次 Mock 域控制器。
* **脏状态用窄作用域**——每条测试都拿到全新重置的车辆快照
  （`vehicle_state`、`hmi_home`、`voice_assistant`、`bluetooth_module`），
  彻底消除测试间的状态污染。

### Mock 能力

* 带校验的车辆信号（`vehicle_speed` ≥ 0，挡位 ∈ P/R/N/D）
* `HmiPage` 小组件的可见性**由实时信号推导**
  （车速触发视频锁定，倒车影像仅在 R 挡可用）
* 超速提示音，通过可观察的事件日志验证
* 挡位互锁并记录拒绝事件（`gear_shift:P:rejected`）
* NOMI 语音助手（中英双语唤醒词、非法输入日志）
* 蓝牙模块（`off → pairing → connected → disconnected`，
  另有 `connection_lost` 表征异常断连）

## 环境

* Python ≥ 3.10（基于 3.13 开发）
* `pytest`——唯一的运行时依赖（其余均为标准库）

```bash
pip install -r requirements.txt
```

## 运行

```bash
pytest -v                     # 全量运行，详细模式
pytest -m smoke -v            # 只跑所有模块的冒烟用例
pytest -m "voice and smoke"   # 精确的 marker 组合切片
pytest -m speedgearwarning    # 单个业务模块
pytest --collect-only -q      # 干跑：只列出用例不执行
pytest -s                     # 显示 fixture 生命周期打印
```

当前测试集：**48 条用例，全部通过。**

## 结构化报告（测试设计 → 执行 → 分析）

`conftest.py` 中的钩子会逐条收集测试记录，并在每次运行结束时
向 `reports/` 目录写入两个文件：

* `reports/test_report.md`——人类可读的汇总表
  （用例、结果、耗时、失败原因）
* `reports/test_report.json`——机器可读的记录，可用于看板、
  CI 产物或 Allure 类下游工具

## 设计取舍与已知简化

* 各阈值（`5 km/h 视频锁定`、`120 km/h 超速`）是真实系统需求
  规格的替身。
* 唤醒词匹配做了归一化（忽略大小写和空格），但对标点敏感——
  相近短语绝不能唤醒助手。
* 同一时刻只支持一路蓝牙连接（简化的车机模型）。
* 事件日志即可观察的"总线 trace"——测试断言的是*证据*，
  而不仅仅是返回值。

## Roadmap（迈向 HIL 的现实路径）

* [ ] 用基于 DBC 定义的 CAN 报文解码器驱动信号，替代字典
* [ ] 在相同接口背后，将 `MockCockpit` 替换为 socket/串口适配器
* [ ] GitHub Actions 工作流：pytest + 报告产物上传
* [ ] 集成 Allure / JUnit XML，用于 CI 看板
