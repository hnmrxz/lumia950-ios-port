# 让 prelink 带上我们的 kext：可行性笔记

合并镜像现在能跑到 `bsd_init`（run 45858986402，证据 `docs/hardware/measurements/merged-bsd-init/`），所以
"prelink 携带第三方 kext"从"不确定能不能用"变成"只差把 kext 放进 prelink 信息"。这份笔记记录投入之前应该知道的、
已经读出来的事实。

## 事实一：prelink 工具做的是真正的重定位，不是简单拼接

框架的 `emit_prelink.py`（pin：`UniXNU/NativePrelink@2b6ffb50`，20,136 字符）内部有：

| 环节 | 函数/位置 | 作用 |
|---|---|---|
| 取模块 | `modules`（由原始内核缓存解析） | 每个 Apple kext 的 segments、vmaddr、filesize |
| PC 相对修复 | `pc_relative_target` / `instruction_inventory` | 把模块里的 PC 相对指令改写到新地址 |
| 追加段 | `append_segment(name, va, blob, size, protection)` | 生成新的 `__PRELINK_TEXT`/`__PRELINK_DATA` |
| 元数据 | 写 `_PrelinkInfoDictionary`、`_PrelinkLinkKASLROffsets`、`_PrelinkKCID` | 让内核按 prelink 语义加载 |
| 每模块键 | `_PrelinkExecutableLoadAddr`、`_PrelinkExecutableSize`、`_PrelinkKmodInfo`、`_PrelinkExecutableSourceAddr` | 内核据此映射与启动 |

结论：**把我们自己的 kext 塞进去，等于自己实现一个 prelinker**（放置地址、段合并、指令修复、kmod 指针）。
这不是"序列化一个容器"，工程量在数周级。

## 事实二：即使有了块设备，还缺文件系统

pin 的 XNU 源码里没有 `bsd/hfs`，也没有 `md`（内存盘）。合并镜像能提供的是**内核缓存里的 kext**：`IOStorageFamily`、
`com.apple.filesystems.apfs` 等。也就是说：

- 块设备 + 根卷这条路，文件系统侧只能寄希望于 **APFS kext**（需要在 prelink roots 里，且需要一个 APFS 卷）；
- 设备上现在**没有 Apple 格式的卷**（MainOS=NTFS、EFIESP=FAT），创建它要重新分区或生成 FFU（见 ADR-0005）。

## 事实三：还有一条更便宜的路没试

`OSKext::loadKextWithIdentifier()` 是**公开**的，它按 bundle id 在 kext 目录里查找。它需要文件系统——但**合并镜像已经
有 IOStorageFamily**（Apple 的 kext）。如果将来出现任何一个块设备（哪怕是一个 RAM 介质），先挂一个最小文件系统、
把我们的 kext 放进去，再让它按 id 加载，可能比写 prelinker 便宜。

## 建议的决策顺序

1. **先在真机上确认内核执行**（等一张底部绿条的照片）——它决定这一切是否值得做；
2. 若真机也到 `bsd_init`，则评估：写 prelinker（贵但通用） vs 先用 RAM 介质 + 公开 loader（便宜但依赖文件系统）；
3. 两条都不做之前，不要声称"存储已通"——现在成立的是：kext 产物、容器、嵌入与调用诊断，**不是介质**。

## 已经能读它了：`scripts/inspect-prelink.py`

写入之前先证明能读。这个工具解析镜像的段表、取出 `__PRELINK_INFO` 的内容、把发射器那种"没有 plist 外壳、整数写成
`<integer size="64">0x...`"的片段规范化后用标准解析器读出来，并列出每个 kext 的 `_PrelinkExecutableLoadAddr` 与大小。
对真实的合并镜像（54 MB，run 45832509015）实跑：

```
16 prelinked kexts, prelink info segment 110592 bytes
  com.apple.kpi.bsd                              load=0xfffffff004004000 size=0x7c78
  com.apple.iokit.IOStorageFamily                load=0xfffffff00400b280 size=0x1fc0
  com.apple.filesystems.apfs                     load=0xfffffff004337000 size=0x3ca15
  ...
```

这一步本身有价值：任何"把我们的 kext 加进去"的尝试，都要先能读懂这张表；现在它可读、可断言（6 个主机测试）。

## 字典这一半也能写了

`scripts/add-prelink-entry.py` 往 `_PrelinkInfoDictionary` 的数组末尾插入一条新条目，其余字节原样保留。两件事值得记：

- **段里有富余空间**：真实合并镜像的文本是 108,416 字节，段是 110,592 字节，插一条 300 多字节的条目后用了 108,749，
  仍然放得下。所以改字典不需要挪动段表。
- **不能简单找第一个 `</array>`**：kext 条目内部自带数组（personality 之类），第一个 `</array>` 往往是内层的。
  工具改成按标签配平找 `_PrelinkInfoDictionary` 的那个收尾——第一版就栽在这里，插进去以后读不回来。

对真实镜像实跑：

```
inserted org.unixnu.NativeSdhci at offset 39581, 108749 of 110592 bytes used; 17 entries parse back
```

**仍然缺的一半**：条目里的 `_PrelinkExecutableLoadAddr` 必须指向镜像内被映射的模块文本，而把我们的 kext 放进去意味着
选地址、追加段、修复 PC 相对指令——即 ADR-0003 里评估为"数周级"的那部分。这条工具的价值是让字典这一半先可测。

## 内核真的读到了我们插入的条目

把上一步编辑过的合并镜像（`add-prelink-entry.py` 插入 `org.unixnu.NativeSdhci`）直接在本机 QEMU 里启动，dmesg 出现：

```
[    7.666566]: Kext org.unixnu.NativeSdhci error - CFBundleVersion missing/invalid type.
```

这一行同时说明三件事：

1. **prelink 字典的编辑确实被内核消费**——不是写进文件就算完，加载器读到了它；
2. 加载器**会校验条目字段**（这里抱怨 `CFBundleVersion` 缺失/类型不对）；
3. 随后它仍然 panic，因为条目里的 `_PrelinkExecutableLoadAddr` 指向的是内核自己的文本，而不是一个真实的模块。

这条结果把"注入路线是否可行"从推断变成了观测：**路是通的，缺的是条目字段与可执行文件的放置**。后者才是数周级的部分。
