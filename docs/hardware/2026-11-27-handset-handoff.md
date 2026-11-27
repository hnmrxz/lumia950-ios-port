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
