# 真机第一次走到"交给内核"这一步（2026-11-27 照片）

## 照片说明了什么

手机屏幕上是我们这套链自己的输出：

```
UniXNU 0.1.0        config: \EFI\UniXNU\unixnu.toml        入口 1: iOS 16.7.16 (xnu)
DARWINBOOT: payload from another volume 0 of 0
DARWINBOOT: ARM64 va=0xFFFFFFF004004000 pa=0x27004000 args=0x2BAE0000 entry=0x2B...
DEC488 owned=0x20000000
DARWINBOOT: video base=0x400000 display=1 row=4320 width=1080 height=1920 depth=32
DARWINBOOT: inputs validated; exiting boot services
DARWINBOOT: hand-off to the kernel
```

以及交接页：

```
kernel  va 0xFFFFFFF004004000  pa 0x27004000
entry   pa 0x2BEC488
args    pa 0x2BAE0000  window 0x20000000 bytes
video   base 0x400000  1080x1920  row 4320 bytes  32 bpp
entry words 140006F5 00000000 00000000 00000000
CurrentEL 1  SCTLR_EL1 0xC01B0D  TCR_EL1 0x280003518
ID_AA64MMFR0_EL1 0x1122  (PARange 2, 4 KiB granule supported)
ID_AA64PFR0_EL1  0x2222
```

顶部有加载器绿条。

## 可以确认的

- **链在真机上走到了"交给内核"这一步**：加载器读到了自己的配置、选中 `xnu`、打印交接页、退出 boot services 并报告 hand-off。
- **真机的视频参数被实测确认**：`base 0x400000`、`1080x1920`、`row 4320 bytes`、`32 bpp`。
- **真机的 EL1 状态被记录下来**：`SCTLR_EL1 0xC01B0D`、`TCR_EL1 0x280003518`、`ID_AA64PFR0_EL1 0x2222`（AArch64-only）。
  这些与模拟器不同（模拟器是 `0x30D0198D` / `0x280803518` / `0x22`），因此内核的早期假设必须以真机为准。

## 不能确认的

- **内核是否执行**：照片里**没有**内核的控制台输出，**也没有**底部 16 行绿条。
- 拍到这一页之后屏幕**是否变化**、设备**是否重启**，照片没有记录。

## 所以下一步只有一件事

同一台手机、同一次开机，**等 30~60 秒后再拍一张屏幕最底部**（带物理边框）：

| 第二张照片看到 | 结论 |
|---|---|
| 底部 16 行绿（或出现白色控制台文字） | 内核在真机执行并到 `bsd_init` |
| 仍然是这一页、纹丝不动 | 内核没跑到画色块的位置（jump 之后立即挂死或复位循环） |
| 屏幕黑了 / 设备重启 | 内核执行了但很快失败，需要关掉埋点做二分 |

## 第二张照片（已按机主更正）：是**同一次开机**，启动日志叠在菜单画面上

机主指出：手机**没有回菜单**。所以这张照片要这样读——

- 菜单（`Booting iOS 16.7.16 in 1 s`、`drivers 2 loaded / 0 failed`、按键提示）是**同一屏先画好的**；
- DARWINBOOT 的日志与交接页**叠印在它上面**（印刷式覆盖，菜单不清屏）；
- 之后**没有新东西**出现，屏幕就停在这一页。

也就是说：这不是"第二次开机"，而是**同一次开机**的两个时刻。设备既没有重启，也没有走到内核输出。

### 故障形态因此是"停住"，不是"复位循环"

- 内核若在早期同步异常里打转，它没法打印（见下面"早期无法输出"），画面正是这样；
- 内核若在早期挂起（等中断/死循环），画面也完全一样。

两种都符合照片，暂时无法区分；区别要靠"能不能打出 `arm_vm_init returned` 这一行"。

## 一个实测的坏消息：内核在 `arm_vm_init` 之前**无法输出**

我试着把 earliest marker 提前，两处都失败：

| 尝试 | 结果 |
|---|---|
| `PE_init_platform()` 之后 `kprintf` | `_sleh_synchronous_sp1`（EL1 同步异常，VM 之前） |
| 打开 stage 0/1 色块（`lumia-bars` 而不是 `lumia-bars2`） | **同样 fault**：`el1_sp0_synchronous_vector_long+0x34` |

也就是说：在本移植里，**任何**在 `arm_vm_init` 之前碰帧缓冲（无论 kprintf 还是直接写像素）都会同步异常——因为那时
帧缓冲还没有被内核映射。这解释了为什么真机上"内核死在早期"与"内核根本没跑"在屏幕上**完全无法区分**。

## 因此下一步要靠"能落在屏幕上的最早一点"

边界很清楚：`arm_vm_init` 之后的第一处输出才是可用的。我在 `arm_vm_init(xmaxmem, args);` **之后**加一行
`kprintf("LUMIA: arm_vm_init returned…")`，它比 `bsd_init` 那行早得多——若真机能打出这一行，说明 VM 工作完成；
若打不出，说明停在 VM 之前。

这行还没有上机（构建中）。它是目前能拿到的最强早期信号。


## 现在手机上装的是"带 post-VM 标记"的内核

本机验证（`scripts/verify-after-vm-marker.py`）：这行**确实会打出来**，而且内核照常走到 `root-wait`：

```
[    7.204918]: LUMIA: arm_vm_init returned, entering the rest of arm_init
past_bsd: root-wait    milestones: … arm_vm_init_return … bsd_init_entry
```

已装到手机（`H:\EFI\UniXNU\Payloads\kernel.macho`，sha256 `f8ea5f23…`，旧内核留在 `kernel.macho.prev`）。

### 下一次开机怎么判读

| 屏幕底部 / 屏幕上出现 | 结论 | 下一步 |
|---|---|---|
| `LUMIA: arm_vm_init returned…` | VM 工作**完成**，停在这行之后 | 往 `PE_init_iokit` / `bsd_init` 之间找（可在更后面再加标记） |
| 只有 DARWINBOOT 那页，**没有**这行 | 停在 `arm_vm_init` **之前或之中** | 查 early boot：EL1 环境、缓存、`wfe_timeout_*`、ADT 解析 |
| 出现这行后又出现别的字样 | 打印的内容告诉我停在哪 | 按打印内容继续 |


## 备用仪器已就绪：`regprobe.efi`（读真机的 CNTFRQ / MIDR / SCTLR / TCR / TTBR）

如果下次开机屏幕上**没有** `arm_vm_init returned`，说明停在 VM 之前，而内核那时**无法输出**。这时唯一的办法是从 EL1
读真机的关键寄存器——那是 EFI 应用能做的事，我们的 `LumiaControlMark` 就是现成的载体，本轮给它加了一段：

```
CNTFRQ  MIDR  MPIDR  CURRL  SCTLR  TCR  TTBR0  TTBR1     （逐个以 16 进制画在面板上）
```

为什么要看这几个：

| 寄存器 | 为什么重要 |
|---|---|
| `CNTFRQ_EL0` | 若固件留成 0 或不对，内核早期定时器/超时会挂；这个值在本项目里**从未在真机上记录过** |
| `MIDR_EL1` | 决定 XNU 走哪条 CPU 特性分支（真机 vs QEMU 的 cortex-a53 可能不同） |
| `SCTLR_EL1` / `TCR_EL1` | 交接时的 MMU/缓存/页表配置；真机与 QEMU 已知不同 |
| `TTBR0/TTBR1_EL1` | 固件留下的页表基址，内核切换时要覆盖 |

### 本地构建链（新增）

`scripts/build-control-mark.py`：用工作区自带的 Zig 直接编出 EFI 应用（`aarch64-windows-msvc` + `-nostdlib` + EDK2 头 +
lld 的 `--subsystem,efi_application`）。本轮实跑：

```
build\local\probe
egprobe.efi: 4096 bytes
QEMU 验证：面板绘出（640x480，文字像素 60760 + 116063）
```

### 什么时候用它

**只在"没有 `arm_vm_init returned` 那行"时才值得换**：把 `regprobe.efi` 装成 `R:\EFI\BOOT\BOOTAA64.EFI`，开机拍照，
再把真加载器换回来（`BOOTAA64.EFI.before-control-mark` 一直都在）。这样一次拍照就能拿到真机的定时器频率与 MMU 配置。


## 实测结论：`PE_init_platform()` 返回时 `vinfo` **全零**——VM 之前不存在可用的帧缓冲地址

按你的要求先核实语义再上机。方法是**在 QEMU 里把内核停在 `PE_init_platform()` 之后的第一个语句**并读出结构体：

```
断点：_wfe_timeout_configure = 0xfffffff00740a2c0     （arm_init 中紧接着 PE_init_platform 的调用）
读取：struct vinfo @ 0xfffffff007af17e8，128 字节
结果：v_height=0  v_width=0  v_depth=0  v_rowbytes=0  v_baseaddr=0x0   （前 32 字节全 0）
```

### 源码给出的原因（不是巧合）

| 位置 | 事实 |
|---|---|
| `pexpert/arm/pe_init.c` | 控制台由 **`PE_create_console()`** 创建；它才调用 `PE_initialize_console()` |
| `osfmk/console/video_console.c` `initialize_screen()` | 当 `kernel_map == VM_MAP_NULL` 时走 `ml_io_map_unmappable()` 建映射；VM 未起时该映射不存在，`v_baseaddr` 只能来自它的返回值 |
| `osfmk/arm/arm_init.c` | `PE_create_console()` 在 **第 571 行**，即 `arm_vm_init()`（第 516 行）**之后** |

**结论：在 `arm_vm_init` 之前，帧缓冲根本还没有被内核映射。** 这不是我们写错了地址，而是这条链的构造如此。

## `lumia-early-bar` 的正反对照（QEMU）

| 运行 | 参数 | rows 120–135 的色块像素 | 内核最终 |
|---|---|---|---|
| 正对照 | `… lumia-early-bar` | **0** | 仍到 `root-wait`（**未 fault**） |
| 负对照 | 无 | 0 | 仍到 `root-wait` |

- **正对照失败**：因为 `vinfo.v_baseaddr == 0`，守卫 `if (vinfo.v_baseaddr != 0 …)` 直接跳过绘制；
- **安全验证通过**：带参数时内核**没有**在仪器处 fault，与不带参数走完全一样的路径（都到 `root-wait`）；
- 因此这个仪器**无法**用来判断"真机是否到达 `PE_init_platform()`"——没有色块不代表没到。

## 三类结果的严格区分（回答你要求的判读标准）

| 结果 | 判定依据 | 能否用 `lumia-early-bar` 判定 |
|---|---|---|
| **执行未到达** | 无任何后续信号 | ❌ 与下一条不可区分 |
| **映射不可用** | `vinfo.v_baseaddr == 0`（VM 之前**恒为真**，已实测） | ❌ 恒发生，故无信息量 |
| **绘制失败** | `vinfo` 有效但 `drawable()` 拒绝或存储 fault | 只在 VM 之后才可能出现 |

**所以：`lumia-early-bar` 不作为真机判据，不为此再消耗一次开机。**

## 要在 `arm_vm_init` 之前获得观测，只剩两条路

1. **在内核 bootstrap 页表里为帧缓冲建一条映射**（改 `start.s` 的 L1/L2 填充），之后任何早期代码都能写屏；
2. **非视频通道**：把阶段标记写进一段内核镜像内（已映射）的变量，配合**热复位**（DRAM 保持）+ 加载器在下次启动时读出并显示。

第 1 条是纯内核改动、可在 QEMU 验证；第 2 条要加载器配合。两者都比继续"在错误的位置画色块"更接近你要求的 P1.1。
