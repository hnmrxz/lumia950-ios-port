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
