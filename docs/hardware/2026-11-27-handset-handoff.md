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

## 第二张照片：交接之后手机**又回到了菜单**

照片里是 UniXNU 菜单（`Booting iOS 16.7.16 in 1 s`、`drivers 2 loaded / 0 failed`），
而**上一轮的 DARWINBOOT 交接页还留在屏幕上**——因为菜单是在旧像素上重画，不擦屏。

两条合起来读：

- 链**每次都能跑到 hand-off**（第一张照片、第二张照片的残留文字都是它）；
- **内核没有在屏幕上留下任何东西**，设备回到了加载器；
- 照片没有记录"是自己重启的，还是被人按了电源"。

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
若打不出，说明死在 VM 之前。

这行还没有上机（构建中）。它是目前能拿到的最强早期信号。
