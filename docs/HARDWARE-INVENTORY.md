# Lumia 950 hardware inventory

本表仅记录当前 Lumia 950（MSM8992）仓库已有证据。未完成实测的资源必须标为 unknown / TODO，不得套用 950 XL 的数据。

## 已有真机测量

| 项目 | 测量值 | 来源 / 日期 | 限制 |
|---|---|---|---|
| 设备 | Microsoft Lumia 950 / MSM8992 / Snapdragon 808 | `TwisstedToast/UniXNU-lumia950` | 非 950 XL（MSM8994） |
| 当前异常级 | EL1 | LumiaProbe EFI report，2026-10-26 | 证明 EFI 环境级别，不证明 DarwinBoot/XNU handoff |
| CPU boot core | Cortex-A53，MIDR `0x410fd033`，MPIDR `0x80000000` | 同上 | 只代表 boot CPU |
| 计数器频率 | 19.2 MHz | 同上 | 应用于 ADT/timebase 前仍需和 XNU 时钟实现核对 |
| GOP | 1080×1920，stride 1080，BGR，base `0x00400000`，8,294,400 bytes | 同上 | 固件 framebuffer；退出 boot services 后的 XNU 驱动接管尚未证明 |
| 可用内存描述符 | 47 个 memory descriptors；约 2806 MiB conventional memory | 同上 | 不是单一连续可用区 |
| 最大空闲连续区 | 1536 MiB，base `0x80000000` | 同上 | 需在 DarwinBoot/XNU handoff 时重新核验；不要 claim 全部 3 GiB 连续可用 |
| EFI handles | 7 filesystem handles、42 block-I/O handles、2 absolute-pointer handles | 同上 | 需记录具体协议/分区映射 |
| CPU 拓扑 | 4×A53 + 2×A57，affinity `0,1,2,3,0x100,0x101` | `docs/hardware/2026-10-26-probe-v1.json` 与设备记录 | XNU SMP 仍未真机验证 |

## 尚缺的关键测量

| 子系统 | 必须补齐的输入 | 建议证据 |
|---|---|---|
| DRAM / reservations | 完整物理内存区间、固件 carve-outs、EFI memory map 与实际所有权交接 | EFI probe 原始报告；DarwinBoot handoff dump；XNU pmap 日志 |
| CPU / GICv2 | GICD/GICC 地址、IRQ map、PPI/SPI、timer、每核启动顺序、PSCI HVC 返回码 | WOA ACPI/DTS 与真机 EFI 探测；逐核 XNU checkpoint |
| eMMC / GPT | SDCC1 MMIO、时钟/电源、总线宽度/频率、卡状态、真实 GPT geometry | WOA `Lumia950XLPkg` 源码、只读探测、PIO 与 ADMA2 对比日志 |
| 显示 | MDP/MDSS/DSI/PHY 寄存器、PLL、lane、panel init 序列、GOP handoff 格式 | 原厂 UEFI/ACPI 源、Linux 驱动、设备探针；不得复制 950 XL 数值 |
| 触摸/按键 | 控制器型号、I2C 总线/地址、reset/power GPIO、IRQ 与扫描协议 | 设备硬件资料、Linux/WOA 驱动、原始事件日志 |
| GPU | Adreno 418 的 GPU ID、power domain、clock、SMMU/IOMMU、firmware、ring/fence contract | Qualcomm/Linux 开源驱动与真机逐级探测；禁止直接用 Adreno 430 参数 |
| 电池/充电 | PMIC 型号、fuel gauge、charger、SPMI/I2C 路径和中断 | WOA/Windows 固件实现、只读 probe |
| rootfs | 分区方案、空间、OS/SystemOS/Data windows、UUID、文件系统与只读/读写策略 | 只读 GPT dump + 明确备份记录；先不改分区 |

## 资料来源

- [Lumia 950 device repository — hardware probe](https://github.com/TwisstedToast/UniXNU-lumia950/blob/main/docs/hardware/2026-10-26-probe-v1.json)
- [Lumia 950 board README](https://github.com/TwisstedToast/UniXNU-lumia950)
- [WOA-Project Lumia950XLPkg](https://github.com/WOA-Project/Lumia950XLPkg)
- [WOA-Project Linux (v5.8-rc3-lumia)](https://github.com/WOA-Project/linux/tree/v5.8-rc3-lumia)

所有测量需标注设备型号、固件版本、工具版本、日期、原始日志/照片及哈希。照片、截图或文档中的宣传性描述不能替代原始读数。

这条规则从 2026-10-27 的记录起逐条执行。两份更早的转录没有照片哈希，已显式标成
`photo_sha256: null` 并写明原因（`2026-10-26-probe-v1.json`、`2026-10-26-handoff-v1.json`）——
留白比补一个编出来的哈希诚实。新的证据文件必须带哈希，否则不要加入 `docs/hardware/`。
