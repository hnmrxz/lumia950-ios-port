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

## 8. 实测：框架自己也会改 `start.s`，所以我们的映射补丁不能先打

第一次尝试按第 3 节直接改 `start.s`，runner 的回答是：

```
error: patch failed: osfmk/arm/pmap/pmap.h:115
error: osfmk/arm64/start.s:426: patch does not apply
error: osfmk/arm64/genassym.c:270: patch does not apply
```

原因是框架在归档之后会跑 `scripts/build-xnu-4k-baseline.sh`，它要应用一套**同时改 `pmap.h`、`start.s`、`genassym.c`** 的补丁；
我们在 workflow 里先改了 `start.s`，这套补丁整体失败（一个 hunk 失败会让整份补丁拒绝应用），内核构建随之中止。

### 结论

1. 路线 A 的 C 侧标记（`lumia-early-map`）可以留在树里，但**没有 start.s 的映射它不会生效**，也不会改变普通启动（token 不在参数里）；
2. `start.s` 的映射必须**追加到框架那套补丁里**（或在补丁应用之后、编译之前插入），不能在我们的 workflow 步骤里抢跑；
3. 这条约束也说明为什么"先写代码再看能不能过"在这里代价高：框架的补丁顺序本身是一道门禁。

### 下一步（下一轮）

先取回框架那份 patch 文件（`unixnu/patches/...` 里被 `build-xnu-4k-baseline.sh` 引用的那一份），确认它的格式与文件列表，然后把我们的
hunk **追加**为最后一段，再用 `git apply` 复验：应用后 `start.s` 同时包含框架的 4K 基线与我们的映射。这样只有一次构建，也不与框架争顺序。

## 10. 阶段一审计：早期观测路径逐项核对（2026-11-27）

### 10.1 三个地址必须分开（源码核对）

| 名称 | 来源 | 用途 | 何时可用 |
|---|---|---|---|
| `boot_args.Video.v_baseAddr` | DarwinBoot 传入的**物理**地址（真机 `0x00400000`，QEMU `0xEC7A0000`） | 只用于计算要映射的物理块 | 全程可读，但**不能直接当指针** |
| bootstrap 页表映射 `0xFFFFFFF0E0000000` | `arm_init` 里新建的一条 L1 表项 + 一个 L2 块表项 | 早期标记的唯一合法写入口 | 从 `arm_init` 开始 |
| `vinfo.v_baseaddr` | `PE_create_console()` 之后由 XNU video console 发布 | 第二阶段色块（`STAGE_2`） | `arm_vm_init` 之后 |

**已证实的问题（P0）**：`STAGE_0`（`native_boot_progress_remember`/`stage`）在 `PE_init_platform()` **之前**就把
`args->Video.v_baseAddr`（物理地址）传给驱动并当指针使用。这一步在 `arm_vm_init` 之前必然 fault——早期实测正是
`_sleh_synchronous_sp1`。这不是"驱动写错了"，而是**物理地址在 MMU 建立映射前被当成虚拟地址**。
修复方向：`STAGE_0` 只能记录参数（不写 framebuffer），第一次写屏必须走 `lumia-early-map` 建立的映射；
`lumia-bars`/`lumia-bars2` 走 `vinfo`（后 MMU）。

### 10.2 开关组合（生成代码核对）

| 参数 | 行为 |
|---|---|
| 无 | 不写屏；`STAGE_0` 仍会记录参数（**待修**：记录本身不写 framebuffer 才安全） |
| `lumia-early-map` | 建立映射并在 `arm_vm_init` 前画 16 行；**当前 QEMU 失败** |
| `lumia-bars` | 在 `PE_init_platform()` 之后用 `vinfo` 画（`vinfo` 此时全零 ⇒ 不画） |
| `lumia-bars2` | 阶段 2 色块（后 MMU） |

### 10.3 页表计算核对（源码 + 常量）

`bootstrap_pagetables + 0` = V=P L1，`+ ARM_PGBYTES` = KVA L1（start.s 第 596–598 行），L2 页由空闲指针分配；
`BOOTSTRAP_TABLE_SIZE = 34 页`，所以多用一个 BSS 页不越界。索引与掩码全部取自 `osfmk/arm64/proc_reg.h` 的
`ARM_TT_L1/L2_INDEX_MASK`、`_SHIFT`，表项模板取 `ARM_TTE_BOOT_TABLE` / `ARM_TTE_BOOT_BLOCK`。
BSS 页的物理地址用 `args->virtBase/physBase` 换算，与 start.s 建立 V=P 映射的关系一致。

**仍是假设**：框架的 4K 基线补丁是否改变了 KVA 根表的层级（4K 粒度为 L0/L1/L2/L3 四级），以及 `bootstrap_pagetables`
在该补丁后是否仍以 `+PGBYTES` 为 KVA L1。**这一条没有被验证**，见 10.5。

### 10.4 `apply_bsd()` 重复定义（已证实，待修）

`ci/boot-progress.py` 中 `def apply_bsd(` 出现 **2 次**，后一个覆盖前一个。当前两者内容一致，所以行为未受影响，
但这是"改了看不出来"的隐患，必须合并为一个。

### 10.5 QEMU 实测（两次，均已归档）

| 用例 | 结果 | 证据 |
|---|---|---|
| 无 `lumia-early-map` | `root-wait`（与改动前一致） | `docs/hardware/measurements/m1-early-map/report.json` |
| 有 `lumia-early-map` | `_sleh_synchronous_sp1`；ESR `0x96000005`、FAR `0x158`、ELR=`el1_sp0_synchronous_vector_long+0x34` | 同上 |

**读法**：ELR 落在**异常向量本身**，说明这是**嵌套异常**——向量在保存现场时访问 `0x158` 失败，即被打断的上下文栈/映射
已经坏了。寄存器显示绘图循环**已经跑过**（x8=stride、x9=width、x10=映射基址、x15=颜色），且 x20 变成了 `0x158`。
所以症状指向**寄存器/栈被破坏**，而不是帧缓冲地址算错。

加入"只写入空表项 + 索引边界检查"后症状**未变**，因此"覆盖了已用表项"这个假设**未被证实**。

### 10.6 结论与下一步

1. 早期映射**未通过验收**，**不得上真机**；默认路径（无该参数）行为不变，普通启动无回归。
2. 下一步不再靠猜：用 fixture 在 `arm_init` 下断点，单步走过建表的三条 store，读回 `l1_index`、`l1[l1_index]`、
   `table_pa`、`TTBR1_EL1`，确认写的是不是 MMU 真正使用的那张表；若表层级不同，改为读取 `TTBR1_EL1` 得到根表地址，
   再从根表按真实层级走到 L1，而不是假定 `bootstrap_pagetables + ARM_PGBYTES`。
3. 同时修 `STAGE_0`：把"记录参数"和"写屏"彻底分开，任何物理地址都不得在建立映射前被解引用。
4. 在此之前，M1 的观测仍只有 `docs/hardware/measurements/vinfo-early` 的零值结论与真机"无输出"的事实。
