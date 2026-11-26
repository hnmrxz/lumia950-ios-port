# 观测阶梯：从"有没有色块"到"内核跑到哪一步"

一页纸，说明每一种仪器能回答什么、依赖什么、以及失败时怎么解读。所有仪器都在 framebuffer 上画，
因为这台机器没有可用 UART；顺序按"依赖的映射从弱到强"排列。

## 阶梯

| # | 仪器 | 依赖 | 触发 | 回答的问题 | 状态 |
|---|---|---|---|---|---|
| 1 | 第 1 条色块（红） | bootstrap 恒等映射（`start.s` 建立） | `arm_init` 内、`PE_init_platform` 前 | 内核入口 C 代码是否执行 | 已实现，受 `lumia-bars` 控制 |
| 2 | 第 2 条色块（黄） | 同上 | `arm_vm_init` 调用前 | 是否走到建立 VM 的最后一步 | 已实现 |
| 3 | 第 3 条色块（绿） | **pexpert 已装视频控制台**，`PE_state.video.v_baseAddr` 为映射过的地址 | `bsd_init` 入口 | 是否越过 VM 建立、进入 BSD 初始化 | 已实现（run 45781718126 起的镜像） |
| 4 | 第 4 条色块（青） | 自己在 `bsd_init` 里 `ml_io_map()` 面板物理地址 | 同第 3 条 + `lumia-bars4` 开关 | 面板是否可被显式映射并写入（不依赖 pexpert 的映射） | 已实现，待构建验证 |
| 5 | 复位检查点 | PSCI `SYSTEM_RESET` **不可用**（`board.toml` 记录了 8992 的 PSCI 没有该调用） | — | （改用 PMIC/PSHOLD 需另行验证） | 未采用 |

## 为什么第 1、2 条在模拟器里必然崩

本机 QEMU 复现（9 秒一轮）后读寄存器：`x9 = 0xe03030`（色块颜色）、`x11 = 0x6c7fdc00`（写入地址）、
`ESR_EL1 = 0x96000005` → EC `0x25`（同 EL 数据中止）、FSC `0b000101`（**translation fault, level 1**）。

`start.s` 在进入 C 之前建立了 bootstrap 恒等映射，只覆盖 RAM；模拟器的面板在 `0x6C7A0000`（RAM 之上）→ 未映射。
真机面板在 `0x400000`，落在 ADT 声明的 DRAM 窗口 `0x0 + 0xaf600000` 内 → 应当可写。第 3、4 条不依赖这个假设。

## 如何用本地 QEMU 迭代（不花 CI）

```powershell
# 1) 组一个"带开关"的 ESP（stage-kernel 会把 args 写进 unixnu.toml）
python scripts\stage-kernel.py --kernel <kernel.macho> --unique-chip-id 0 `
    --menu-tree out\payload --out out\qemu-x --ntfs-driver out\ntfs_aa64.efi `
    --args "-v cpus=1 lumia-bars lumia-bars4 skmem_seg_size=16384 skmem_md_seg_size=16384 skmem_drv_buf_seg_size=65536 skmem_usr_buf_seg_size=16384 skmem_sysctl_skip=1"

# 2) fixture 要求菜单是"显式非自动启动"：toml 里 default = "exit"、timeout = 300
#    （它自己会改成 default="xnu"、timeout=1 再启动）

# 3) 跑（主机有 QEMU 11.1.0 与 edk2-aarch64-code.fd）
python scripts\test-native-xnu-entry.py --kernel out\qemu-x\EFI\UniXNU\Payloads\kernel.macho `
    --esp out\qemu-x --firmware 'C:\Program Files\qemu\share\edk2-aarch64-code.fd' `
    --output out\qemu-x-run --qemu 'C:\Program Files\qemu\qemu-system-aarch64.exe' `
    --allow-prelinked --past-bsd --dump-dmesg --dump-framebuffer --adt-profile qemu --smt 2 `
    --timeout 240 --gdb-transport tcp
```

注：`--allow-prelinked` 会跳过 strip 校验与 source-crypto 契约（本地实验用）；`--smp 2` 是正确拼写。

## 解读矩阵（真机）

| 屏幕 | 结论 | 下一步 |
|---|---|---|
| 0 条色块 | 内核没到 `arm_init` | 检查 DarwinBoot 跳转到 EL1 之后的路径；考虑把第 1 条改成"在 `start.s` 之后由异常向量写入"或用 panic 屏 |
| 1 条 | 入口 C 代码执行，卡在 `arm_init` 里 | 用第 3/4 条判断是否卡在 VM 建立 |
| 2 条 | 卡在 `arm_vm_init` 内或其后 | 对照 ADT 的 DRAM/窗口参数 |
| 3 条 | 越过 VM 建立，进入 `bsd_init` | 继续往 `vfs_mountroot` 做仪器 |
| 4 条 | 显式映射面板成功 | 说明可以把任意物理地址映射后绘制 → 可做更细的日志页 |

## 与官方文档的对应

- 官方把入口探针画成"蓝/品红"两条，并明确 **MMU 打开后不再画条、改用复位**；我们的第 1、2 条对应蓝/品红。
- 官方的第 3 阶段用 `entry_probe_reset_delay` 触发 PSCI 复位；本机 PSCI 无 `SYSTEM_RESET`，所以改用
  "在 `bsd_init` 用已映射地址画第 3 条"这一等价观测点（见 `docs/hardware/2026-11-26-official-boot-chain-notes.md`）。
