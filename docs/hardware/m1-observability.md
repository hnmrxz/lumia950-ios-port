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

## 11. 现状（2026-11-27，本轮收尾）

### 11.1 已完成且保留

| 项 | 状态 |
|---|---|
| 从 `TTBR1_EL1` 读根表、按真实层级取 L1 | **已实现**（不再假定 `bootstrap_pagetables + PGBYTES`） |
| `STAGE_0` / `STAGE_2` 用物理地址写屏 | **已移除**（审计确认的 P0） |
| `apply_bsd()` 重复定义 | **已合并** |
| 映射结果自报 | **已实现**（post-VM `kprintf` 打印 `lumia_early_map_state`） |
| 面板参数边界 | 已实现（非零、`height > 136`、`width ≤ 16384`、`stride ≤ 65536`） |
| 任意空 L1 槽扫描 | **已撤回**（见 11.3，会让内核在 `arm_vm_init` 之前彻底失联） |

### 11.2 本轮 QEMU 验收（artifact `d57f6eea…`，commit `d51be80`，build 45972181135）

| 配置 | 结果 | ESR | 状态码 |
|---|---|---|---|
| 无 `lumia-early-map` | **root-wait** | `0x0` | **4**（参数缺失） |
| 有 `lumia-early-map` | **root-wait** | `0x0` | **7**（固定 L1 槽已被占用） |

**两条路径都没有新增异常**；默认路径与改动前一致。**映射仍未装入**，因此早期标记仍未画出。

### 11.3 为什么不再尝试别的槽位

build 45969556167（扫描最高空槽）的结果是**内核在 `arm_vm_init` 之前彻底失联**——没有串口输出、没有 dmesg、没有状态码。
这说明 bootstrap 表不是"随便找个空槽塞进去"就能用的：`arm_vm_init` 要消费这些表来建立 kernel pmap，塞进去的表项它无法解释。
所以扫描已撤回，回到"拒绝并自报状态 7"的**不崩**形态。

**下一步不是换槽位，而是读源码**：看 `arm_vm_init` 如何遍历/消费 `bootstrap_pagetables`，据此决定这条映射应该放在哪一层、哪一个范围，
或者换成不碰页表的观测方式（路线 B：把标记写进内核镜像内已映射的变量，另找读取途径）。

### 11.4 阻塞已解除（本轮）

上一轮 kernel 构建全部失败的根因是框架 `drivers/NativeMetal` 钉的提交 `c6d29caa` 被远端 force-push 掉（GitHub API 返回 422）。
现在 `scripts/repair-framework-submodules.sh` 会先核对该提交是否仍可服务，**只在确实不可用时**把该子模块改指到远端 head，并在 job summary 里写明替换。
本轮构建因此恢复：`drivers/NativeMetal` 由 `c6d29caa` 改为 `78c4abf99e36`。

### 11.5 证据等级（禁止互相替代）

| 等级 | 现在 |
|---|---|
| QEMU 到 root-wait | **是** |
| QEMU 映射装入 | **否**（状态 7） |
| QEMU 到 BSD init | 否 |
| 真机 hand-off | 是（此前建立） |
| 真机 XNU entry | 否 |
| 真机 BSD init | 否 |

### 11.6 是否进入真机 M1 测试准入评审

**不进入**。完成条件要求"状态 0 且默认路径无回归"；现在是"默认路径无回归 + 状态 7"。映射装入这一步尚未成立。

## 12. 改用 identity map（TTBR0）：不崩，但还差一级表（2026-11-27）

读源码确定了一件事：`arm_vm_init.c` 的 `arm_replace_identity_map()` **整页清零 V=P 的 L1 表**，只重建“打开 MMU 需要的那一页”——
说明 identity map 在 XNU 自己的设计里就是**临时**的；而 `pmap_bootstrap` 继续使用的是**内核 VA（TTBR1）**那些表。
上一轮把表项塞进 TTBR1 表，正是“改它不该改的表”，所以 45969556167 连 console 都没有。

因此本轮把映射改到 **TTBR0（identity map）**：按 `boot_args.Video.v_baseAddr` 找到它所在的块，在 identity 表里补上块表项，
然后**用物理地址直接写**（identity map 里物理地址就是虚拟地址）。

**QEMU 结果（artifact `311a9460…`，build 45975269374）**：两条路径都 **root-wait、ESR `0x0`**，状态码 off=**4**、on=**5**。

- 不崩、不回归——这是相对 TTBR1 版本的关键改善；
- 状态 5 = “identity map 里该块所在 L1 表项不是表”：在 QEMU 上 start.s 只映射了内核自己的物理范围，
  帧缓冲的物理地址（`0xEC7A0000`）根本不在其中；
- 还有一个**层级**问题必须下一版解决：4 KB 粒度下 TTBR 指向 root（L0），1 GB 级在 L1，
  所以“用 L1 掩码直接索引 TTBR0”只在 16 KB 粒度成立。下一版要先走 `ARM_TT_ROOT_*`、再走 `ARM_TT_L1_*`，
  这正是 TTBR1 版本从状态 2 走到 7 时用过的形状。

**下一步**：identity map 里先 root、再 L1、最后填块表项；越界或槽位已被别的块占用时继续拒绝并自报状态。

## 13. root→L1 补层实测：又一次把启动弄死，所以回到"拒绝"版本（2026-11-27）

上一节的状态 5 说明 identity map 根本到不了帧缓冲所在的 GB。这一轮按"先 root、再 L1"的走法**补上缺失的那一层**（指向本标记自己的 L2 页），
然后按 identity 地址写屏。

**结果（artifact `155d628b…`，build 45978469173，commit `8ab49e6`）**

| 配置 | 结果 | ESR | 状态 |
|---|---|---|---|
| 关 | root-wait | `0x0` | 4 |
| 开 | **stopped**，**无 console** | `0x96000005`（data abort，translation fault） | 无 |

**读法**：一旦这个标记真的去补层并写屏，内核在 console 建立之前就翻译异常。两次安装尝试（TTBR1 塞表项、TTBR0 补层）都以同样方式结束：
**标记无法自证的表修改会毁掉启动**。只有"拒绝"形态（2 / 5 / 7）能把内核保到 root-wait。

**决定**：恢复 `db0bb9c` 的拒绝版（identity map，状态 5，root-wait，无异常）。**该仪器不带去真机。**

**下一步不是再换一种形状，而是把这次 fault 读出来**：在 fixture 里断在 `arm_init`，单步跨过建表的几条 store，
回读 `TTBR0_EL1` 与刚写的表项，确认"标记装的映射"和"CPU 真正用的映射"是不是同一个——这是调试器任务，不是启动参数能回答的。

## 14. 两页分离也没救回来：fault 签名与第一次完全相同（2026-11-27）

上一轮补层 fault，怀疑是“补的那层和块表项共用同一页”。本轮给每一层**各一页**（`lumia_l1` / `lumia_l2`），重新构建验证。

**结果（artifact `409a1a39…`，build 45981395798，commit `9fc225c`）**

| 配置 | 结果 | ESR | FAR | 状态 |
|---|---|---|---|---|
| 关 | root-wait | `0x0` | — | 4 |
| 开 | **stopped，无 console** | `0x96000005` | **`0x158`** | 无 |

寄存器显示标记**已经把地址算完**：x8=`0xEC7A0000`（video pa）、x9=stride、x10=width、x15=`0xEC800000`（块基址）。
然后内核在 **VA `0x158`** 上发生 data abort，且 ELR 落在**异常向量内部**（向量自己的 store 也失败的嵌套异常）——
**与最初 TTBR1 版本完全相同的签名**。

**读法**：`0x158` 不是帧缓冲地址，所以这不是“新映射写屏”的 fault，而是建表之后的某次 NULL+0x158 访问；x20=`0x158` 也说明本该放指针的寄存器被改坏了。
三种形态（TTBR1 塞表项、TTBR0 补层共页、TTBR0 补层分页）**同一签名**，因此问题在**改这些 bootstrap 表这件事本身**（或它之后立刻被使用的结构），
而不是地址算术。

**决定**：再次恢复“拒绝”版（状态 5、root-wait、ESR 0），两次安装尝试都保留在记录里。

**下一步必须是调试器**：断在标记之后，回读 `TTBR0_EL1` 与写入的表项，单步看是哪条指令访问到 `0x158`。再换一种表形状就是第四次猜。

## 15. 第一次真正读到页表布局（2026-11-27，调试器，不靠猜）

用 fixture 在 `_arm_vm_init`（`0xfffffff0073fca68`）下断点，读出系统寄存器：

| 寄存器 | 值 |
|---|---|
| `TTBR0_EL1` | `0x4818d000` |
| `TTBR1_EL1` | `0x4818e000` |
| `TCR_EL1` | `0x22a51a251a` |
| `SCTLR_EL1` | `0x3454593d` |

**TTBR0 与 TTBR1 指向 `bootstrap_pagetables` 的两个相邻页**：页 0 是 identity 根表，页 1 是内核 VA 根表。
这正是之前**假定**的关系，现在是**测到**的关系。

### 15.1 三次 fault 的原因因此清楚了

`start.s` 从 `physBase` 起映射 identity 范围，所以**落在 RAM 里的帧缓冲本来就被一个 block 表项覆盖**。
之前三个版本在中间层把"已有的 block 表项"替换成"指向自己页的表项"，于是**丢掉了整整 1 GB 的 identity 映射**——
这与"第一次写屏就 fault、签名一模一样"完全对得上。

### 15.2 新版本：绝不替换 block 表项

- 根表项或 L1 表项若是 **block**：能覆盖目标就**直接用**（状态 1），覆盖不了就**拒绝**（状态 9），**绝不拆分**；
- 只有**真正空的叶子槽**才写入 block 表项，且若该槽已属别的块则拒绝（状态 7）。

### 15.3 本轮 QEMU 结果（artifact `4b92701c…`，build 45984406868，commit `d13f651`）

| 配置 | 结果 | ESR | 状态 |
|---|---|---|---|
| 关 | **root-wait** | `0x0` | 4 |
| 开 | **root-wait** | `0x0` | **5** |

**不崩了**——这本身就验证了"fault 来自替换 block 表项"的判断。

### 15.4 现在的问题变成"读到的是哪一层"

状态 5 = 用 `ARM_TT_ROOT_*` 索引 TTBR0 指向的表时，读到的表项既不是表也不是块。
`TCR_EL1 = 0x22a51a251a` 的 T0SZ 字段提示：**翻译从 XNU 称作 L1 的那一层开始**，所以"宏名字"和"CPU 实际起始层级"需要
用**表里的真实内容**对齐，而不是继续推断。

**下一步（仍然是读，不是构建）**：在同一断点读取 `TTBR0` 指向页的头四个表项（地址 = `ttbr0 + virtBase - physBase`），
看 `start.s` 把帧缓冲所在范围填进了哪一个槽，再据此定索引。
