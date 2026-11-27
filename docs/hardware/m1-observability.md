# M1 观测路线 A 的实现设计：从 bootstrap 页表映射帧缓冲

2026-11-27。**本文件是设计，不是已完成的改动**；代码尚未落地，原因写在最后一节。所有常量都从 pin 的源码读出，并标注出处。

## 1. 为什么需要它

| 事实 | 出处 |
|---|---|
| `PE_init_platform()` 返回时 `vinfo` **全零**（`v_baseaddr=0`） | QEMU 断点实测：`docs/hardware/measurements/vinfo-early/report.json` |
| 控制台由 `PE_create_console()` 创建，它在 `arm_init` 第 571 行、`arm_vm_init()`（第 516 行）**之后** | `osfmk/arm/arm_init.c` |
| 因此 VM 之前任何 `kprintf` 或帧缓冲写入都会 fault | 两次实测：`_sleh_synchronous_sp1`（run 45918861169 与本机 `verify-pre-vm-bar.py`） |

结论：要观测 `arm_vm_init` 之前的停点，必须在**内核自己的 bootstrap 页表**里先建立一条帧缓冲映射。

## 2. 机制（读源码得到，不是猜测）

`osfmk/arm64/start.s` 用宏 `create_bootstrap_mapping` 建表：

```
/*  arg0 - virtual start address
 *  arg1 - physical start address
 *  arg2 - number of entries to map
 *  arg3 - L1 table address
 *  arg4 - free space pointer
 *  arg5..arg9 - scratch
 */
```

- 调用点（start.s 第 606/610 行）：
  - V=P：`create_bootstrap_mapping x0, x4, x5, x1, x2, x6, x10, x11, x12, x13`
  - KVA：`create_bootstrap_mapping x14, x15, x5, x3, x2, x9, x10, x11, x12, x13`
- `x2` 是**空闲页指针**，宏内部会 `add $4, $4, PGBYTES` 并把用到的页分配给新 L2 表；两次调用共用同一个 `x2`，因此页是连续分配的。
- 表页预算：`BOOTSTRAP_TABLE_SIZE`（start.s 注释：2G/4K 设备最坏需 8 页）。
- 块大小：`ARM_TT_L2_SIZE`。16K 页内核是 `0x02000000`（32 MB），4K 页内核是 `0x00200000`（2 MB）（`osfmk/arm64/proc_reg.h`）。
- 块表项模板 `ARM_TTE_BOOT_BLOCK`（proc_reg.h 第 1526–1533 行）= 块 | 有效 | `SH_OUTER_MEMORY` | `ATTRINDX(CACHE_ATTRINDX_WRITEBACK)` | AF
  ⇒ **普通 write-back 可缓存内存**，不是 device 内存。

## 3. 于是设计只能是这个形状

1. 在 `start.s` 的 `dsb ish` 之前再加一次 `create_bootstrap_mapping`：
   - `pbase = video_base & ~(ARM_TT_L2_SIZE - 1)`，**运行时从 boot args 读**（`Boot_Video.v_baseAddr` 在 `boot_args` 偏移 24，见 `pexpert/pexpert/arm/boot.h`）；
   - `vbase = 0xFFFFFFF0E0000000`（32 MB 对齐、远离内核镜像的 KVA 槽）；
   - `entries = 1`（一个块就覆盖 32 MB 内的帧缓冲）。
   - 这样同一份内核在真机（video base `0x400000` → 块基址 `0`）与 QEMU（video base `0xEC7A0000` → 块基址 `0xEC000000`）都能映射到。
2. 在 `arm_init` 极早处（`PE_init_platform` 之前）写标记：地址 = `0xFFFFFFF0E0000000 + (video_pa & (ARM_TT_L2_SIZE-1)) + 偏移`。
3. **必须显式清缓存**：块模板是 write-back，写完用 `dc civac` 逐行 clean+invalidate，否则面板可能看不到。
   （Arm64 内联：`__asm__ volatile("dc civac, %0" :: "r"(addr) : "memory")`。）
4. 开关：仍用 boot argument（如 `lumia-early-map`），默认不启用，保证普通启动行为不变。

## 4. 已知风险（写代码前必须承认）

| 风险 | 说明 |
|---|---|
| **内存属性别名** | 块模板是 WB；若同一 PA 在别处被映射为 device，会产生属性冲突（ARM ARM 定义为不可预测）。真机上低 32 MB 含固件/TZ 保留区，内核通常不映射它们（内核镜像在 `0x27004000`），所以冲突概率低但非零。 |
| **KVA 槽选择** | `0xFFFFFFF0E0000000` 落在 KVA 区。`arm_vm_init` 之后可能覆盖该表项；标记只用于 VM 之前，之后失效可接受，但不能让 pmap 在初始化时读到它而困惑——这一条必须先看 `arm_vm_init` 如何消费 bootstrap 表。 |
| **QEMU 与真机的块基址不同** | 运行时读 video_pa 能同时适配，但 QEMU 的帧缓冲是 PCI 内存（`0xEC7A0000`），映射它需要 WB 访问 device 区，QEMU 允许，真机不是这种布局。 |
| **构建周期** | 每次验证 30 分钟；`start.s` 改动会影响所有启动路径，必须先用现有门禁（`past_bsd=root-wait`、底部色块、`check-evidence`）确认没有回归。 |

## 5. 验收标准（QEMU 侧，真机之前）

1. 不启用开关：`past_bsd=root-wait`、底部 16 行 12,800 像素、`check-evidence` 通过 —— 与改动前完全一致；
2. 启用开关：在 `arm_vm_init` 之前出现一条**可回读**的色块（帧缓冲 dump 中 y=120 行有非零像素），且内核仍到 root-wait；
3. 两者都通过，才允许装到手机做一次真机测试。

## 6. 为什么本轮没有直接写代码

写这段汇编需要一次编译—真机/仿真往返才能验证；在没有本地汇编器与 SDK 的前提下，盲改 `start.s` 会把"仪器 bug"引入内核
（上一轮的 `lumia-skip-wfe` 就是活生生的例子：结构正确、语义正确，但一上电就把内核打死）。

因此本轮交付的是：**读源码确认的机制、精确常量、寄存器契约、风险清单与 QEMU 验收标准**。下一步写代码时按第 5 节验证，
不再靠"看起来对"。

## 7. 备选路线 B（保持有效）

RAM mailbox + 热复位：把阶段标记写进内核镜像内（V=P 已映射）的变量，热复位后由加载器读出并显示。
优点是不触碰 MMU；缺点是需要加载器改动，且"热复位后 DRAM 仍可读"尚未验证。若路线 A 的 QEMU 原型回归太多，就转 B。
