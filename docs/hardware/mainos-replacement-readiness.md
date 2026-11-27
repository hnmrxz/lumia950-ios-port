# MainOS 替换就绪度：载荷读取路径与 APFS 根卷

只读审计，2026-11-27。回答两个问题：**换掉 MainOS 之前必须先证明什么**，以及 **APFS root 现在到底能不能做**。

## 1. 当前载荷读取路径（已成立的部分）

```
EFI\UniXNU\Drivers\ntfs.efi        给 UEFI 提供 NTFS 读能力
EFI\UniXNU\Drivers\DarwinBoot.efi  打开 MainOS 上的 \EFI\UniXNU\Payloads\
                                   kernel.macho + kernel.macho.adt，读入内存，hand-off
```

真机证据：hand-off 页打印 `DARWINBOOT: payload from another volume 0 of 0`、`pent` 与内核 VA/PA、`entry words 140006F5`
（`docs/hardware/measurements/handoff-hardware/report.json`）。

**这条路径依赖 MainOS 是 NTFS 且存在该目录。** 若 MainOS 改文件系统（APFS/ext4/…），`ntfs.efi` 即失效。

## 2. 换 MainOS 前必须逐项证明（本机/真机各算一半）

| # | 要证明的事 | 现在能否证明 | 证明方式（不动 MainOS） |
|---|---|---|---|
| 1 | UEFI 能枚举目标卷 | 部分（能枚举 NTFS 卷） | microSD/FAT32 卷上放同样载荷，看菜单是否列出 |
| 2 | UniXNU 能访问该卷 | 是（NTFS 已工作） | 上条通过后，菜单能读该卷的 `unixnu.toml`/载荷 |
| 3 | DarwinBoot 能找到 `kernel.macho` | 是（NTFS 已工作） | 同上，只是换卷 |
| 4 | DarwinBoot 能读 ADT | 是（同上） | 同上 |
| 5 | 真机能完成 hand-off | **是**（照片 + 页内数值） | 已有证据 |

也就是说：**换卷的关键未知只有"非 NTFS 卷"这一项**，而它可以用 microSD/FAT32 **完全不动 MainOS** 地验证。

## 3. APFS 根卷：现状与缺口

| 项 | 状态 | 证据/说明 |
|---|---|---|
| XNU 源码里有 HFS+ | **没有**（pin 内无 `bsd/hfs`） | 早前审计；因此 `Apple_HFS` root-wait 在源码内核上永远等不到 |
| 合并镜像里的文件系统 | `com.apple.filesystems.apfs` 已 prelink | `scripts/inspect-prelink.py` 输出（16 个 kext 中含 apfs） |
| IOStorageFamily | 已 prelink | 同上 |
| 块设备驱动 | **没有** | 16 个 kext 里没有任何 eMMC/SD 块设备驱动 |
| `NativeSdhci` | ABI 编译 + 95,462 B mkext 嵌入内核，**未在真机加载** | `docs/architecture/ADR-0003-storage-delivery.md` |
| kext 投递 | 受 private API 限制；prelink 注入已验证"内核会读我们插入的条目" | 同上 + 测量记录 |
| 根卷匹配 | QEMU 期望 `Apple_HFS`；iOS 16 真实根是 APFS | 二者**不一致**，必须先确定 root matching 的真实条件 |
| root UUID / boot-args | 未确定 | 需要 iOS 16.7.16 真实卷布局 |

**结论：APFS root 目前不可行，缺口不在"APFS kext"而在三处——块设备驱动未进内核、kext 投递未打通、root matching 条件未核实。**

## 4. 分阶段迁移方案（每阶段都可回滚，且都不动 EFIESP/BCD）

### 阶段 0：只读基线（现在就能做，不需要改任何东西）

- `phone-snapshot.py save`（EFIESP 文件级）
- `phone-image.py dump --volume R:`（EFIESP 原始镜像）与 MainOS 原始镜像（若容量允许）
- 记录 `scripts/phone-tools.py` 的工具体哈希

**回滚**：无写入，无需回滚。

### 阶段 1：microSD/FAT32 载荷（不动 MainOS、不动 EFIESP）

- 把 `kernel.macho(+.adt)` 放到 microSD 的 `\EFI\UniXNU\Payloads\`
- 让菜单指向该卷（`unixnu.toml` 的条目路径），保留原 NTFS 条目作为回退

**完成标志**：真机从 microSD 完成 hand-off（照片 + 页内数值）。
**回滚**：把菜单条目改回 MainOS 路径即可（文件级，可逆）。

### 阶段 2：块设备驱动进内核（仍不动分区）

- 解决 `NativeSdhci` 的投递（prelink 注入或公开 loader）
- 目标：真机至少一次 `CMD17` 读到某扇区

**回滚**：内核镜像换回 `kernel.macho.prev`（已具备）。

### 阶段 3：root matching 与根卷

- 先确定 XNU 在该 pin 上"认什么 root"（`Apple_HFS` 是 QEMU 夹具的期望，不代表真机必须）
- 再决定 APFS 卷的生成方式与 UUID/`boot-args`

**回滚**：不改分区，仅内核/配置回退。

### 阶段 4（仅在 0–3 全部通过且解锁补丁清单明确后）：分区级改动

- 仍优先"缩小 MainOS 尾部新建分区"，而不是格式化 MainOS
- 任何分区写入前，先完成一次**成对分区镜像恢复**的实机验证

**回滚**：`phone-image.py restore`（成对），最后手段 FFU。

## 5. 当前的硬性禁止项

1. 不格式化 MainOS（解锁补丁落点未确认）。
2. 不替换 `bootarm.efi`、`\UEFI.elf`、BCD（已有失败记录）。
3. 不在真机上把 `Apple_HFS` 当作目标根卷设计（源码内核没有 HFS+）。
4. 不把"kext ABI 编译通过 / QEMU 能插入 prelink 条目"当作"真机能读盘"。
